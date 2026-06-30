"""Memory read routes for the MIRA API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

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
    session_id: str | None = None,
    user_id: str | None = None,
    entity: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
) -> MemoryGraphResponse:
    """Return typed graph nodes and edges in a visualization-friendly shape."""
    _reject_unsupported_filters(session_id=session_id, user_id=user_id)
    graph = get_memory_graph_read_model(entity=entity, limit=limit)
    return MemoryGraphResponse(nodes=graph["nodes"], edges=graph["edges"])


@router.get("/foresight", response_model=ItemsResponse)
def get_foresight(
    user_id: str | None = None,
    session_id: str | None = None,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
) -> ItemsResponse:
    """Return foresight records."""
    _reject_unsupported_filters(user_id=user_id)
    return ItemsResponse(items=list_foresight_read_model(session_id, status, limit))


@router.get("/reflections", response_model=ItemsResponse)
def get_reflections(
    user_id: str | None = None,
    session_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
) -> ItemsResponse:
    """Return reflection records."""
    _reject_unsupported_filters(user_id=user_id, session_id=session_id)
    return ItemsResponse(items=list_reflections_read_model(limit))


@router.get("/community-summaries", response_model=ItemsResponse)
def get_community_summaries(
    user_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
) -> ItemsResponse:
    """Return graph-derived community summaries."""
    _reject_unsupported_filters(user_id=user_id)
    return ItemsResponse(items=list_community_summaries_read_model(limit))


def _reject_unsupported_filters(**filters: str | None) -> None:
    unsupported = sorted(name for name, value in filters.items() if value is not None)
    if unsupported:
        joined = ", ".join(unsupported)
        raise HTTPException(
            status_code=400,
            detail=f"unsupported filter(s) for current read model: {joined}",
        )
