from google.adk.agents import Agent
from google.adk.integrations.bigquery import BigQueryToolset
from google.adk.integrations.bigquery.config import BigQueryToolConfig, WriteMode

from .. import prompts
from ..settings import BQ_MAX_BYTES_BILLED, GCP_PROJECT, MODEL

# No credentials_config: the tools use Application Default Credentials,
# which is your gcloud login locally and the service account on Cloud Run.
bigquery_tools = BigQueryToolset(
    tool_filter=["list_table_ids", "get_table_info", "execute_sql"],
    bigquery_tool_config=BigQueryToolConfig(
        write_mode=WriteMode.BLOCKED,  # SELECT only, no changes to data
        compute_project_id=GCP_PROJECT or None,
        default_project_id=GCP_PROJECT or None,
        maximum_bytes_billed=BQ_MAX_BYTES_BILLED,
        max_query_result_rows=50,
        application_name="vehicle-assistant",
    ),
)

sql_analyst = Agent(
    name="sql_analyst",
    model=MODEL,
    description="Writes and runs read-only BigQuery SQL for custom data questions.",
    instruction=prompts.sql_analyst_instruction,
    tools=[bigquery_tools],
    output_key="last_findings",
)
