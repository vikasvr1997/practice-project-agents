"""Where graph proposals are kept until a developer runs the Terraform.

"memory" (local runs and tests) or "firestore" (the deployed app), the same
choice as the chat sessions use.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field

from .spec import GraphSpec


class Proposal(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    spec: GraphSpec
    notes: list[str] = []
    status: str = "proposed"  # nothing is created until a developer applies the Terraform
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    updated_at: str = ""


class MemoryStore:
    def __init__(self):
        self._items: dict[str, Proposal] = {}

    def list(self) -> list[Proposal]:
        return sorted(self._items.values(), key=lambda p: p.created_at, reverse=True)

    def get(self, proposal_id: str) -> Proposal | None:
        return self._items.get(proposal_id)

    def save(self, proposal: Proposal) -> Proposal:
        self._items[proposal.id] = proposal
        return proposal

    def delete(self, proposal_id: str) -> bool:
        return self._items.pop(proposal_id, None) is not None


class FirestoreStore:
    COLLECTION = "graph_proposals"

    def __init__(self, client):
        self._col = client.collection(self.COLLECTION)

    def list(self) -> list[Proposal]:
        items = [Proposal.model_validate(d.to_dict()) for d in self._col.stream()]
        return sorted(items, key=lambda p: p.created_at, reverse=True)

    def get(self, proposal_id: str) -> Proposal | None:
        doc = self._col.document(proposal_id).get()
        return Proposal.model_validate(doc.to_dict()) if doc.exists else None

    def save(self, proposal: Proposal) -> Proposal:
        self._col.document(proposal.id).set(proposal.model_dump())
        return proposal

    def delete(self, proposal_id: str) -> bool:
        ref = self._col.document(proposal_id)
        if not ref.get().exists:
            return False
        ref.delete()
        return True


def build_store(settings):
    if settings.session_backend == "firestore":
        from google.cloud import firestore

        return FirestoreStore(firestore.Client(project=settings.google_cloud_project,
                                               database=settings.firestore_database))
    return MemoryStore()
