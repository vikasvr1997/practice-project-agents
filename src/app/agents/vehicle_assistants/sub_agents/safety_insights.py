from google.adk.agents import Agent

from .. import prompts
from ..settings import MODEL
from ..tools.safety_queries import crashes_by_hour, fatalities_by_state, monthly_trend

safety_insights = Agent(
    name="safety_insights",
    model=MODEL,
    description="Answers standard crash questions with curated, pre-approved reports.",
    instruction=prompts.SAFETY_INSIGHTS,
    tools=[fatalities_by_state, monthly_trend, crashes_by_hour],
    # Saved in session state (and so in Firestore) for the report writer.
    output_key="last_findings",
)
