"""Read-only queries on the supply-chain property graph in BigQuery.

The graph comes from graphs/supply_chain/ (you create it with the Terraform
there, or design your own on the Graph Creator page). This tool only runs graph queries: GQL
starting with GRAPH, or SELECT ... FROM GRAPH_TABLE(...). Anything that
could change data is refused before it reaches BigQuery.
"""
import re
from functools import lru_cache

from google.cloud import bigquery

from ..settings import BQ_MAX_BYTES_BILLED, GCP_PROJECT

MAX_ROWS = 50
_WRITE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|CREATE|DROP|ALTER|TRUNCATE|GRANT|REVOKE|CALL|EXPORT|LOAD|EXECUTE)\b", re.I
)


@lru_cache
def _client() -> bigquery.Client:
    return bigquery.Client(project=GCP_PROJECT or None)


def is_read_only_graph_query(query: str) -> bool:
    body = re.sub(r"--[^\n]*|/\*.*?\*/", " ", query, flags=re.S).strip().rstrip(";").strip()
    if ";" in body or _WRITE.search(body):
        return False
    starts_graph = re.match(r"GRAPH\b", body, re.I)
    graph_table = re.match(r"(SELECT|WITH)\b", body, re.I) and "GRAPH_TABLE" in body.upper()
    return bool(starts_graph or graph_table)


def _run(query: str) -> list[dict]:
    job_config = bigquery.QueryJobConfig(maximum_bytes_billed=BQ_MAX_BYTES_BILLED)
    return [dict(row) for row in _client().query(query, job_config=job_config).result()]


def run_graph_query(query: str) -> dict:
    """Runs one read-only query on the supply-chain graph and returns up to 50 rows.

    Args:
        query: GQL starting with GRAPH, or SELECT ... FROM GRAPH_TABLE(...).

    Returns:
        status, rows and whether the rows were cut off; or status and error.
    """
    if not is_read_only_graph_query(query):
        return {"status": "error", "error": "Only one read-only graph query (GRAPH ... or GRAPH_TABLE) is allowed."}
    try:
        rows = _run(query)
    except Exception as e:  # the model reads the error and fixes its query
        return {"status": "error", "error": str(e)[:800]}
    return {"status": "success", "rows": rows[:MAX_ROWS], "truncated": len(rows) > MAX_ROWS}
