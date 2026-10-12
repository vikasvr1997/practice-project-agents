from functools import lru_cache
from typing import Optional

from google.cloud import bigquery

from ..settings import BQ_DATA_PROJECT,BQ_DATASET,BQ_MAX_BYTES_BILLED, GCP_PROJECT

AVAILABLE_YEARS = range(2015, 2021)

@lru_cache
def _client() -> bigquery.Client:
    return bigquery.Client(project=GCP_PROJECT)

def _table(year: int) -> str:

    if year not in AVAILABLE_YEARS:
        raise ValueError(f"year must be between 2015 and 2020, got {year}")

    return f"{BQ_DATA_PROJECT}.{BQ_DATASET}.accident_{year}"

def _run(sql: str, params: list) -> dict:
    job_config = bigquery.QueryJobConfig(
        query_parameters = params,
        maximum_bytes_billed=BQ_MAX_BYTES_BILLED,
    )

    rows = _client().query(sql, job_config=job_config).result()
    return {"status":"success", "rows": [dict(row) for row in rows]}

def fatalities_by_state(year:int, top_n: int = 10) -> dict:

    """Ranks US states by traffic fatalities for one year.

    Args:
        year: Year between 2015 and 2020.
        top_n: How many states to return (1-51).

    Returns:
        Rows of state_name, crashes and fatalities, highest fatalities first.
    """
    try:
        sql = f"""
            SELECT state_name,
                   COUNT(*) AS crashes,
                   SUM(number_of_fatalities) AS fatalities
            FROM {_table(year)}
            GROUP BY state_name
            ORDER BY fatalities DESC
            LIMIT @top_n
        """
        top_n = max(1, min(top_n, 51))
        return _run(sql, [bigquery.ScalarQueryParameter("top_n", "INT64",top_n)])
    except Exception as e:
        return {"status": "error", "error": str(e)}


def monthly_trend(year: int, state_name: Optional[str] = None) -> dict:
    """Shows fatal crashes and fatalities per month for one year.

    Args:
        year: Year between 2015 and 2020.
        state_name: Optional US state name, for example "Michigan".
            Leave empty for the whole country.

    Returns:
        Rows of month, crashes and fatalities, January first.
    """
    try:
        sql = f"""
            SELECT month_of_crash AS month,
                   COUNT(*) AS crashes,
                   SUM(number_of_fatalities) AS fatalities
            FROM {_table(year)}
            WHERE @state IS NULL OR LOWER(state_name) = LOWER(@state)
            GROUP BY month
            ORDER BY month
        """
        return _run(sql, [bigquery.ScalarQueryParameter("state", "STRING", state_name)])
    except Exception as e:
        return {"status": "error", "error": str(e)}




def crashes_by_hour(year: int, state_name: Optional[str] = None) -> dict:
    """Shows fatal crashes per hour of the day (0-23) for one year.

    Args:
        year: Year between 2015 and 2020.
        state_name: Optional US state name. Leave empty for the whole country.

    Returns:
        Rows of hour and crashes. Hour 99 means unknown.
    """
    try:
        sql = f"""
            SELECT hour_of_crash AS hour, COUNT(*) AS crashes
            FROM {_table(year)}
            WHERE @state IS NULL OR LOWER(state_name) = LOWER(@state)
            GROUP BY hour
            ORDER BY hour
        """
        return _run(sql, [bigquery.ScalarQueryParameter("state", "STRING", state_name)])
    except Exception as e:
        return {"status": "error", "error": str(e)}