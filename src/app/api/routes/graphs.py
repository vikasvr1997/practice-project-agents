"""Graph Creator API: list property graphs, and propose new ones.

Proposals are never applied here. Each one comes with the DDL and a
Terraform folder that a developer reviews and runs themselves.
"""
from datetime import datetime, timezone
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings
from app.core.security import require_api_key
from app.graphs import bigquery as bq
from app.graphs.infer import infer
from app.graphs.spec import DATASET, LABEL, PROJECT, GraphSpec
from app.graphs.store import Proposal

router = APIRouter(prefix="/graphs", tags=["graphs"], dependencies=[Depends(require_api_key)])

ProposalId = Annotated[str, Path(pattern=r"^[a-f0-9]{12}$")]


@lru_cache
def get_bigquery():
    from google.cloud import bigquery

    return bigquery.Client(project=get_settings().google_cloud_project)


def _project(project: str | None, settings: Settings) -> str:
    project = project or settings.google_cloud_project
    if not project:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pass a project or set GOOGLE_CLOUD_PROJECT.")
    return project


class ProposalOut(Proposal):
    ddl: str
    terraform: dict[str, str]
    problems: list[str]


def _out(p: Proposal) -> ProposalOut:
    return ProposalOut(**p.model_dump(), ddl=p.spec.ddl(), terraform=p.spec.terraform(), problems=p.spec.problems())


class NewProposal(BaseModel):
    dataset: str = Field(pattern=DATASET)
    name: str = Field(pattern=LABEL.pattern, max_length=128)
    project: str | None = Field(default=None, pattern=PROJECT)
    tables: list[str] | None = Field(default=None, max_length=100)  # None = every table in the dataset


class ProposalUpdate(BaseModel):
    spec: GraphSpec


@router.get("/datasets")
def datasets(
    project: Annotated[str | None, Query(pattern=PROJECT)] = None,
    settings: Settings = Depends(get_settings),
    client=Depends(get_bigquery),
) -> list[dict]:
    return bq.list_datasets(client, _project(project, settings))


@router.get("")
def list_graphs(
    request: Request,
    project: Annotated[str | None, Query(pattern=PROJECT)] = None,
    dataset: Annotated[str | None, Query(pattern=DATASET)] = None,
    settings: Settings = Depends(get_settings),
    client=Depends(get_bigquery),
) -> dict:
    """Graphs that exist in BigQuery, plus proposals waiting to be applied."""
    project = _project(project, settings)
    names = [dataset] if dataset else [d["dataset"] for d in bq.list_datasets(client, project)]
    existing, errors = bq.list_graphs(client, project, names)
    proposals = [
        _out(p) for p in request.app.state.graph_store.list()
        if p.spec.project == project and (not dataset or p.spec.dataset == dataset)
    ]
    return {"project": project, "existing": existing, "proposals": proposals, "errors": errors}


@router.post("/proposals", status_code=status.HTTP_201_CREATED)
def propose(body: NewProposal, request: Request, settings: Settings = Depends(get_settings),
            client=Depends(get_bigquery)) -> ProposalOut:
    """Scan the dataset's tables and propose a graph. Reads metadata and sample rows only."""
    project = _project(body.project, settings)
    try:
        tables = bq.scan_tables(client, project, body.dataset, body.tables)
        location = bq.dataset_location(client, project, body.dataset)
    except Exception as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Couldn't read {project}.{body.dataset}: {str(e)[:300]}")
    if not tables:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{project}.{body.dataset} has no tables.")
    spec, notes = infer(tables, name=body.name, project=project, dataset=body.dataset, location=location)
    return _out(request.app.state.graph_store.save(Proposal(spec=spec, notes=notes)))


@router.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: ProposalId, request: Request) -> ProposalOut:
    proposal = request.app.state.graph_store.get(proposal_id)
    if proposal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proposal not found")
    return _out(proposal)


@router.put("/proposals/{proposal_id}")
def update_proposal(proposal_id: ProposalId, body: ProposalUpdate, request: Request) -> ProposalOut:
    """Save the developer's edits (labels, directions, removed rows)."""
    store = request.app.state.graph_store
    proposal = store.get(proposal_id)
    if proposal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proposal not found")
    proposal.spec = body.spec
    proposal.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return _out(store.save(proposal))


@router.delete("/proposals/{proposal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_proposal(proposal_id: ProposalId, request: Request) -> None:
    if not request.app.state.graph_store.delete(proposal_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proposal not found")
