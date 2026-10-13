"""Agent settings, read from environment variables.

Kept inside the agent package so `adk web` can load the agents on its own.
"""
import os

# Gemini model served through Vertex AI (GOOGLE_GENAI_USE_VERTEXAI=TRUE).
MODEL = os.getenv("MODEL", "gemini-2.5-flash")

# Project that runs (and pays for) BigQuery queries.
GCP_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "")

# Where the vehicle data lives. Defaults to NHTSA's public crash data.
BQ_DATA_PROJECT = os.getenv("BQ_DATA_PROJECT", "bigquery-public-data")
BQ_DATASET = os.getenv("BQ_DATASET", "nhtsa_traffic_fatalities")

# Safety limit: refuse any query that would scan more than this.
BQ_MAX_BYTES_BILLED = int(os.getenv("BQ_MAX_BYTES_BILLED", str(2 * 1024**3)))  # 2 GB

# Supply-chain property graph, as project.dataset.graph. Empty = the
# supply_chain_analyst agent is left out (create the graph first; see GUIDE.md).
SUPPLY_CHAIN_GRAPH = os.getenv("SUPPLY_CHAIN_GRAPH", "")

# Model Armor template that screens prompts and answers, as a full resource name:
# projects/<project>/locations/<region>/templates/<template-id>. Empty = off.
MODEL_ARMOR_TEMPLATE = os.getenv("MODEL_ARMOR_TEMPLATE", "")
