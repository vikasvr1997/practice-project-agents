from google.adk.agents import Agent

from .. import prompts
from ..settings import MODEL

report_writer = Agent(
    name="report_writer",
    model=MODEL,
    description="Writes a short manager-ready report from findings already in the conversation.",
    instruction=prompts.REPORT_WRITER,
)