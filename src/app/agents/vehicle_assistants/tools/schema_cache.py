"""Caches the BigQuery schema (table + column list) for sql_analyst's dataset.

Fetched once per TTL window via one INFORMATION_SCHEMA query, then reused, so
most turns can skip the live list_table_ids / get_table_info round trips.
"""
import time
from functools import lru_cache

from google.cloud import bigquery

from ..settings import BQ_DATA_PROJECT, BQ_DATASET, GCP_PROJECT, SQL_SCHEMA_CACHE_TTL_SECONDS

MAX_COLUMNS_PER_TABLE = 25  # keeps the embedded schema text short

_cache: dict | None = None  # {"text": str, "fetched_at": float} or None


@lru_cache
def _client() -> bigquery.Client:
    return bigquery.Client(project=GCP_PROJECT or None)


def _fetch_schema_text() -> str:
    sql = f"""
        SELECT table_name, column_name, data_type
        FROM `{BQ_DATA_PROJECT}.{BQ_DATASET}`.INFORMATION_SCHEMA.COLUMNS
        ORDER BY table_name, ordinal_position
    """
    rows = list(_client().query(sql).result())

    by_table: dict[str, list[str]] = {}
    for row in rows:
        by_table.setdefault(row.table_name, []).append(f"{row.column_name} {row.data_type}")

    lines = []
    for table_name, columns in sorted(by_table.items()):
        shown = columns[:MAX_COLUMNS_PER_TABLE]
        extra = f", +{len(columns) - MAX_COLUMNS_PER_TABLE} more" if len(columns) > MAX_COLUMNS_PER_TABLE else ""
        # table_name is copied verbatim from BigQuery's own metadata, leading
        # space and all, if it has one -- never guessed.
        lines.append(f"`{BQ_DATA_PROJECT}.{BQ_DATASET}.{table_name}` ({', '.join(shown)}{extra})")
    return "\n".join(lines)


def get_schema_text(ttl: float = SQL_SCHEMA_CACHE_TTL_SECONDS) -> str:
    """Returns the dataset's table/column list as compact text.

    Cached in-process; refetches at most once every `ttl` seconds. On a
    BigQuery error, returns a short note instead of raising, and does NOT
    cache the failure, so the next call retries live.
    """
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache["fetched_at"] < ttl:
        return _cache["text"]
    try:
        text = _fetch_schema_text()
    except Exception as e:  # keep the agent working; just lose the shortcut
        return f"(schema lookup failed: {str(e)[:200]} -- call list_table_ids and get_table_info instead)"
    _cache = {"text": text, "fetched_at": now}
    return text


def clear_cache() -> None:
    """Test helper: forces the next get_schema_text() call to refetch."""
    global _cache
    _cache = None
