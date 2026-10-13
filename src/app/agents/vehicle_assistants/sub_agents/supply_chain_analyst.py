from google.adk.agents import Agent

from .. import prompts
from ..settings import MODEL
from ..tools.supply_chain_graph import run_graph_query

supply_chain_analyst = Agent(
    name="supply_chain_analyst",
    model=MODEL,
    description="Answers questions about suppliers, parts, plants and recalls by querying the supply-chain graph.",
    instruction=prompts.SUPPLY_CHAIN,
    tools=[run_graph_query],
    output_key="last_findings",
)
