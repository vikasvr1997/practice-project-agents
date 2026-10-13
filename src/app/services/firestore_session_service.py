"""Firestore-backed ADK session service.

Persists sessions, their events, and app/user-scoped state in Firestore so
conversations survive process restarts (unlike ``InMemorySessionService``).

Layout, under a single root collection (default ``adk_sessions``):

    {root}/{app_name}                                 -- app-scoped state
    {root}/{app_name}/users/{user_id}                  -- user-scoped state
    {root}/{app_name}/users/{user_id}/sessions/{id}    -- session-scoped state
    .../sessions/{id}/events/{auto_id}                 -- ordered events

The app and user documents are always touched (even with an empty state
delta) so they exist for enumeration: ``list_sessions`` without a ``user_id``
walks the ``users`` subcollection to find every user who ever created a
session for the app.
"""

from __future__ import annotations

from typing import Any, Optional

from google.adk.errors.already_exists_error import AlreadyExistsError
from google.adk.errors.session_not_found_error import SessionNotFoundError
from google.adk.events.event import Event
from google.adk.platform import time as platform_time
from google.adk.platform import uuid as platform_uuid
from google.adk.sessions import BaseSessionService, Session, State
from google.adk.sessions.base_session_service import (
    GetSessionConfig,
    ListSessionsResponse,
)
from google.adk.sessions._session_util import (
    extract_json_safe_state_delta,
    make_json_safe_state,
)
from google.cloud import firestore
from google.cloud.firestore_v1.async_transaction import AsyncTransaction
from typing_extensions import override


class FirestoreSessionService(BaseSessionService):
    """A Firestore implementation of the session service."""

    def __init__(
        self,
        client: firestore.AsyncClient,
        *,
        root_collection: str = "adk_sessions",
    ) -> None:
        self._client = client
        self._root_collection = root_collection

    def _app_ref(self, app_name: str):
        return self._client.collection(self._root_collection).document(app_name)

    def _user_ref(self, app_name: str, user_id: str):
        return self._app_ref(app_name).collection("users").document(user_id)

    def _session_ref(self, app_name: str, user_id: str, session_id: str):
        return self._user_ref(app_name, user_id).collection("sessions").document(
            session_id
        )

    async def _merged_state(
        self, app_name: str, user_id: str, session_state: dict[str, Any]
    ) -> dict[str, Any]:
        """Combines raw session state with app/user state under their prefixes."""
        app_snap = await self._app_ref(app_name).get()
        user_snap = await self._user_ref(app_name, user_id).get()
        app_state = (app_snap.to_dict() or {}).get("state", {}) if app_snap.exists else {}
        user_state = (user_snap.to_dict() or {}).get("state", {}) if user_snap.exists else {}

        merged = dict(session_state)
        for key, value in app_state.items():
            merged[f"{State.APP_PREFIX}{key}"] = value
        for key, value in user_state.items():
            merged[f"{State.USER_PREFIX}{key}"] = value
        return merged

    @staticmethod
    def _decode_event(data: dict[str, Any]) -> Event:
        data = dict(data)
        data.pop("seq", None)
        return Event.model_validate(data)

    async def _load_events(
        self, session_ref, config: Optional[GetSessionConfig]
    ) -> list[Event]:
        if config and config.num_recent_events == 0:
            return []

        query = session_ref.collection("events").order_by("seq")
        events = [
            self._decode_event(doc.to_dict() or {})
            async for doc in query.stream()
        ]

        if config:
            if config.num_recent_events is not None:
                events = events[-config.num_recent_events :]
            if config.after_timestamp is not None:
                events = [e for e in events if e.timestamp >= config.after_timestamp]
        return events

    @override
    async def create_session(
        self,
        *,
        app_name: str,
        user_id: str,
        state: Optional[dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> Session:
        session_id = (session_id.strip() if session_id else None) or platform_uuid.new_uuid()
        state_deltas = extract_json_safe_state_delta(state or {})
        app_delta, user_delta, session_state = (
            state_deltas["app"],
            state_deltas["user"],
            state_deltas["session"],
        )
        now = platform_time.get_time()

        app_ref = self._app_ref(app_name)
        user_ref = self._user_ref(app_name, user_id)
        session_ref = self._session_ref(app_name, user_id, session_id)

        @firestore.async_transactional
        async def _create(transaction: AsyncTransaction) -> None:
            existing = await session_ref.get(transaction=transaction)
            if existing.exists:
                raise AlreadyExistsError(
                    f"Session with id {session_id} already exists."
                )
            # A marker field (rather than merging an empty "state": {}) keeps
            # the doc present for enumeration without the merge resolving to
            # an empty map that would wipe any state already stored there.
            transaction.set(app_ref, {"app_name": app_name}, merge=True)
            transaction.set(user_ref, {"user_id": user_id}, merge=True)
            if app_delta:
                transaction.set(app_ref, {"state": app_delta}, merge=True)
            if user_delta:
                transaction.set(user_ref, {"state": user_delta}, merge=True)
            transaction.set(
                session_ref,
                {
                    "app_name": app_name,
                    "user_id": user_id,
                    "id": session_id,
                    "state": session_state,
                    "event_seq": 0,
                    "last_update_time": now,
                },
            )

        await _create(self._client.transaction())

        merged_state = await self._merged_state(app_name, user_id, session_state)
        return Session(
            id=session_id,
            app_name=app_name,
            user_id=user_id,
            state=merged_state,
            last_update_time=now,
        )

    @override
    async def get_session(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        config: Optional[GetSessionConfig] = None,
    ) -> Optional[Session]:
        session_id = session_id.strip() if session_id else session_id
        session_ref = self._session_ref(app_name, user_id, session_id)
        snapshot = await session_ref.get()
        if not snapshot.exists:
            return None

        data = snapshot.to_dict() or {}
        events = await self._load_events(session_ref, config)
        merged_state = await self._merged_state(app_name, user_id, data.get("state", {}))

        return Session(
            id=session_id,
            app_name=app_name,
            user_id=user_id,
            state=merged_state,
            events=events,
            last_update_time=data.get("last_update_time", 0.0),
        )

    async def _list_user_sessions(self, app_name: str, user_id: str) -> list[Session]:
        sessions = []
        async for doc in self._user_ref(app_name, user_id).collection("sessions").stream():
            data = doc.to_dict() or {}
            merged_state = await self._merged_state(app_name, user_id, data.get("state", {}))
            sessions.append(
                Session(
                    id=doc.id,
                    app_name=app_name,
                    user_id=user_id,
                    state=merged_state,
                    last_update_time=data.get("last_update_time", 0.0),
                )
            )
        return sessions

    @override
    async def list_sessions(
        self, *, app_name: str, user_id: Optional[str] = None
    ) -> ListSessionsResponse:
        if user_id is not None:
            sessions = await self._list_user_sessions(app_name, user_id)
        else:
            sessions = []
            async for user_doc in self._app_ref(app_name).collection("users").stream():
                sessions.extend(await self._list_user_sessions(app_name, user_doc.id))

        sessions.sort(key=lambda s: (s.last_update_time, s.user_id, s.id))
        return ListSessionsResponse(sessions=sessions)

    @override
    async def delete_session(
        self, *, app_name: str, user_id: str, session_id: str
    ) -> None:
        session_ref = self._session_ref(app_name, user_id, session_id)
        async for doc in session_ref.collection("events").stream():
            await doc.reference.delete()
        await session_ref.delete()

    @override
    async def get_user_state(self, *, app_name: str, user_id: str) -> dict[str, Any]:
        snapshot = await self._user_ref(app_name, user_id).get()
        if not snapshot.exists:
            return {}
        return dict((snapshot.to_dict() or {}).get("state", {}))

    @override
    async def append_event(self, session: Session, event: Event) -> Event:
        if event.partial:
            return event

        self._apply_temp_state(session, event)
        event = self._trim_temp_delta_state(event)

        app_name, user_id, session_id = session.app_name, session.user_id, session.id
        app_ref = self._app_ref(app_name)
        user_ref = self._user_ref(app_name, user_id)
        session_ref = self._session_ref(app_name, user_id, session_id)

        delta = event.actions.state_delta if event.actions else {}
        state_deltas = extract_json_safe_state_delta(delta or {})
        app_delta, user_delta, session_delta = (
            state_deltas["app"],
            state_deltas["user"],
            state_deltas["session"],
        )
        event_data = make_json_safe_state(event.model_dump(mode="json"))

        @firestore.async_transactional
        async def _append(transaction: AsyncTransaction) -> None:
            snapshot = await session_ref.get(transaction=transaction)
            if not snapshot.exists:
                raise SessionNotFoundError(f"Session {session_id} not found.")

            event_seq = (snapshot.to_dict() or {}).get("event_seq", 0)
            event_ref = session_ref.collection("events").document()
            transaction.create(event_ref, {**event_data, "seq": event_seq})

            session_update: dict[str, Any] = {
                "event_seq": event_seq + 1,
                "last_update_time": event.timestamp,
            }
            if session_delta:
                session_update["state"] = session_delta
            transaction.set(session_ref, session_update, merge=True)

            if app_delta:
                transaction.set(app_ref, {"state": app_delta}, merge=True)
            if user_delta:
                transaction.set(user_ref, {"state": user_delta}, merge=True)

        await _append(self._client.transaction())

        self._update_session_state(session, event)
        session.events.append(event)
        session.last_update_time = event.timestamp
        return event
