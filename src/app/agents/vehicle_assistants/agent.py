"""The coordinator agent and its specialists.

    vehicle_assistant (coordinator, routes requests)
    ├── safety_insights       curated BigQuery reports
    ├── sql_analyst           free-form read-only SQL
    ├── supply_chain_analyst  graph queries (only when SUPPLY_CHAIN_GRAPH is set)
    └── report_writer         turns findings into a report

`app` wraps the agents with the Model Armor guardrail plugin. The FastAPI
server loads `app`, so the guardrails apply to every chat.
"""
from google.adk.agents import Agent
from google.adk.apps import App

from . import prompts
from .guardrails import build_plugins
from .settings import MODEL, SUPPLY_CHAIN_GRAPH
from .sub_agents import report_writer, safety_insights, sql_analyst, supply_chain_analyst

specialists = [safety_insights, sql_analyst]
if SUPPLY_CHAIN_GRAPH:
    specialists.append(supply_chain_analyst)
specialists.append(report_writer)

root_agent = Agent(
    name="vehicle_assistant",
    model=MODEL,
    description="Routes vehicle safety questions to the right specialist.",
    instruction=prompts.coordinator(with_supply_chain=bool(SUPPLY_CHAIN_GRAPH)),
    sub_agents=specialists,
)

app = App(name="vehicle_assistant", root_agent=root_agent, plugins=build_plugins())
