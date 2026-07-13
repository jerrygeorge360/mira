"""Memory read routes for the MIRA API."""

from __future__ import annotations

from fastapi import APIRouter, Query

from api.auth import WorkspaceAuth
from api.schemas.memory import ItemsResponse, MemoryGraphResponse
from core.memory.read_models import (
    get_memory_graph_read_model,
    list_community_summaries_read_model,
    list_foresight_read_model,
    list_reflections_read_model,
)

router = APIRouter(tags=["memory"])


@router.get("/memory/graph", response_model=MemoryGraphResponse)
def get_memory_graph(
    auth: WorkspaceAuth,
    entity: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
) -> MemoryGraphResponse:
    """Return typed graph nodes and edges in a visualization-friendly shape."""
    graph = get_memory_graph_read_model(
        entity=entity, limit=limit, workspace_id=auth.context.workspace_id
    )
    return MemoryGraphResponse(nodes=graph["nodes"], edges=graph["edges"])


@router.get("/foresight", response_model=ItemsResponse)
def get_foresight(
    auth: WorkspaceAuth,
    session_id: str | None = None,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
) -> ItemsResponse:
    """Return foresight records."""
    return ItemsResponse(
        items=list_foresight_read_model(
            session_id, status, limit, workspace_id=auth.context.workspace_id
        )
    )


@router.get("/reflections", response_model=ItemsResponse)
def get_reflections(
    auth: WorkspaceAuth,
    limit: int = Query(default=50, ge=1, le=500),
) -> ItemsResponse:
    """Return reflection records."""
    return ItemsResponse(
        items=list_reflections_read_model(limit, workspace_id=auth.context.workspace_id)
    )


@router.get("/community-summaries", response_model=ItemsResponse)
def get_community_summaries(
    auth: WorkspaceAuth,
    limit: int = Query(default=50, ge=1, le=500),
) -> ItemsResponse:
    """Return graph-derived community summaries."""
    return ItemsResponse(
        items=list_community_summaries_read_model(limit, workspace_id=auth.context.workspace_id)
    )
