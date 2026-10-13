from google.adk.runners import Runner
from google.adk.sessions import BaseSessionService, InMemorySessionService

from app.agents.vehicle_assistants.agent import root_agent
from app.core.config import Settings


def build_session_service(settings: Settings) -> BaseSessionService:
    """Session storage for the agents.

    "memory" for local runs and unit tests: sessions live only as long as
    the process does. "firestore" persists sessions across restarts.
    """
    if settings.session_backend == "firestore":
        from google.cloud import firestore

        from app.services.firestore_session_service import FirestoreSessionService

        client = firestore.AsyncClient(
            project=settings.google_cloud_project,
            database=settings.firestore_database,
        )
        return FirestoreSessionService(client)
    return InMemorySessionService()


def build_runner(settings: Settings, session_service: BaseSessionService) -> Runner:
    return Runner(
        app_name=settings.app_name,
        agent=root_agent,
        session_service=session_service,
    )
