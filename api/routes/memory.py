"""Memory read routes for the MIRA API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from api.auth import WorkspaceAuth, require_csrf
from api.schemas.memory import (
    ItemsResponse,
    MemoryForgetRequest,
    MemoryForgetResponse,
    MemoryGraphResponse,
    MemoryHealthResponse,
    MemoryLifecycleResponse,
    MemorySleepRequest,
    MemorySleepResponse,
)
from core.memory.lifecycle import forget_memory_by_id, list_memory_states
from core.memory.read_models import (
    get_memory_graph_read_model,
    get_memory_health_read_model,
    list_community_summaries_read_model,
    list_foresight_read_model,
    list_memory_lifecycle_read_model,
    list_reflections_read_model,
)
from core.memory.slow_path import run_memory_sleep_once

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


@router.get("/memory/lifecycle", response_model=MemoryLifecycleResponse)
def get_memory_lifecycle(
    auth: WorkspaceAuth,
    session_id: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> MemoryLifecycleResponse:
    """Return recent fast-path and slow-path lifecycle evidence."""
    return MemoryLifecycleResponse(
        items=list_memory_lifecycle_read_model(
            session_id=session_id,
            limit=limit,
            workspace_id=auth.context.workspace_id,
        )
    )


@router.get("/memory/health", response_model=MemoryHealthResponse)
def get_memory_health(auth: WorkspaceAuth) -> MemoryHealthResponse:
    """Return tier counts, status counts, and recent retention transitions."""
    return MemoryHealthResponse(
        health=get_memory_health_read_model(workspace_id=auth.context.workspace_id)
    )


@router.get("/memory/states", response_model=ItemsResponse)
def get_memory_states(
    auth: WorkspaceAuth,
    include_inactive: bool = True,
    limit: int = Query(default=100, ge=1, le=1000),
) -> ItemsResponse:
    """Return generic lifecycle state without replacing source read models."""
    return ItemsResponse(
        items=list_memory_states(
            auth.context.workspace_id,
            limit=limit,
            include_inactive=include_inactive,
        )
    )


@router.post("/memory/sleep", response_model=MemorySleepResponse)
def sleep_memory(
    request: Request,
    payload: MemorySleepRequest,
    auth: WorkspaceAuth,
) -> MemorySleepResponse:
    """Run one bounded retention/consolidation cycle for this workspace."""
    require_csrf(request, auth)
    try:
        result = run_memory_sleep_once(auth.context.workspace_id, max_items=payload.max_items)
    except ValueError as error:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(error)) from error
    return MemorySleepResponse(sleep=result)


@router.post("/memory/{memory_id}/forget", response_model=MemoryForgetResponse)
def forget_memory_route(
    memory_id: str,
    request: Request,
    payload: MemoryForgetRequest,
    auth: WorkspaceAuth,
) -> MemoryForgetResponse:
    """Forget one lifecycle memory without deleting its source or history."""
    require_csrf(request, auth)
    try:
        memory = forget_memory_by_id(
            memory_id,
            auth.context.workspace_id,
            reason=payload.reason,
        )
    except ValueError as error:
        if str(error) in {"memory_id not found", "memory_id must not be empty"}:
            raise HTTPException(status_code=404, detail="memory_id not found") from error
        raise HTTPException(status_code=400, detail=str(error)) from error
    return MemoryForgetResponse(memory=memory)


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
