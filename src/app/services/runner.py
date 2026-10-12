from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

from app.agents.vehicle_assistants.agent import root_agent
from app.core.config import Settings


def build_session_service(settings: Settings) -> InMemorySessionService:
    """Session storage for the agents.

    Only in-memory is supported for now: sessions live as long as the
    process does. Swap this for a Firestore-backed service once persistence
    across restarts is needed.
    """
    return InMemorySessionService()


def build_runner(settings: Settings, session_service: InMemorySessionService) -> Runner:
    return Runner(
        app_name=settings.app_name,
        agent=root_agent,
        session_service=session_service,
    )
