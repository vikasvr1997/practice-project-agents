"""Runs against the Firestore emulator. Skipped when it isn't running.

Start it with:  gcloud emulators firestore start --host-port=127.0.0.1:8085
Then:           export FIRESTORE_EMULATOR_HOST=127.0.0.1:8085
"""
import os
import uuid

import pytest
from google.adk.errors.already_exists_error import AlreadyExistsError
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.adk.sessions.base_session_service import GetSessionConfig
from google.genai import types

pytestmark = pytest.mark.skipif(
    not os.getenv("FIRESTORE_EMULATOR_HOST"), reason="Firestore emulator not running"
)


@pytest.fixture
def service():
    from google.cloud import firestore

    from app.services.firestore_session_service import FirestoreSessionService

    return FirestoreSessionService(firestore.AsyncClient(project="test-project"))


@pytest.fixture
def app_name():
    return f"app_{uuid.uuid4().hex[:8]}"  # fresh namespace per test


def make_event(author, message, delta=None):
    return Event(
        author=author,
        invocation_id="inv-1",
        content=types.Content(role="user" if author == "user" else "model", parts=[types.Part(text=message)]),
        actions=EventActions(state_delta=delta or {}),
    )


async def test_create_get_and_state_scopes(service, app_name):
    session = await service.create_session(
        app_name=app_name,
        user_id="u1",
        state={"topic": "crashes", "user:units": "miles", "app:version": 1, "temp:x": 1},
    )
    assert session.state == {"topic": "crashes", "user:units": "miles", "app:version": 1}

    # User state follows the user into a new session; session state does not.
    other = await service.create_session(app_name=app_name, user_id="u1")
    assert other.state == {"user:units": "miles", "app:version": 1}
    assert await service.get_user_state(app_name=app_name, user_id="u1") == {"units": "miles"}


async def test_append_event_persists_events_and_state(service, app_name):
    session = await service.create_session(app_name=app_name, user_id="u1", session_id="s1")
    await service.append_event(session, make_event("user", "hello"))
    await service.append_event(
        session,
        make_event("agent", "hi", {"last_findings": "Texas", "user:name": "Vikas", "temp:scratch": 1}),
    )

    loaded = await service.get_session(app_name=app_name, user_id="u1", session_id="s1")
    assert [e.content.parts[0].text for e in loaded.events] == ["hello", "hi"]
    assert loaded.state == {"last_findings": "Texas", "user:name": "Vikas"}
    assert loaded.events[1].actions.state_delta == {"last_findings": "Texas", "user:name": "Vikas"}

    recent = await service.get_session(
        app_name=app_name, user_id="u1", session_id="s1", config=GetSessionConfig(num_recent_events=1)
    )
    assert [e.content.parts[0].text for e in recent.events] == ["hi"]


async def test_duplicate_id_list_and_delete(service, app_name):
    await service.create_session(app_name=app_name, user_id="u1", session_id="a")
    with pytest.raises(AlreadyExistsError):
        await service.create_session(app_name=app_name, user_id="u1", session_id="a")
    await service.create_session(app_name=app_name, user_id="u2", session_id="b")

    mine = await service.list_sessions(app_name=app_name, user_id="u1")
    assert [s.id for s in mine.sessions] == ["a"]
    everyone = await service.list_sessions(app_name=app_name)
    assert sorted(s.id for s in everyone.sessions) == ["a", "b"]

    session = await service.get_session(app_name=app_name, user_id="u1", session_id="a")
    await service.append_event(session, make_event("user", "bye"))
    await service.delete_session(app_name=app_name, user_id="u1", session_id="a")
    assert await service.get_session(app_name=app_name, user_id="u1", session_id="a") is None
