""" The coordinator agent and its three specalists."""

from google.adk.agents import Agent

from . import prompts
from .settings import MODEL
from .sub_agents import report_writer, safety_insights, sql_analyst

root_agent = Agent(
    name = "vehicle_assistant",
    model = MODEL,
    description= "Routes vehicle safery questions to the right specialisst",
    instruction = prompts.COORDINATOR,
    sub_agents= [safety_insights, sql_analyst, report_writer]
)

