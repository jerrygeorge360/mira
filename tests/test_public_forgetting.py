"""Focused tests for authenticated public memory forgetting."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from api.auth import AuthenticatedWorkspace
from api.routes.memory import forget_memory_route
from api.schemas.memory import MemoryForgetRequest
from core.db.repositories import (
    WorkspaceContext,
    configure_database,
    create_session,
    create_workspace,
    repository_connection,
    save_observation,
)
from core.db.schema import LEGACY_WORKSPACE_ID
from core.memory.lifecycle import (
    ensure_memory_state,
    get_memory_state_by_id,
    lifecycle_for_retrieval,
    run_memory_sleep,
)
from integrations.mcp.server import build_mcp_server


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/memory/forget/forget",
            "headers": [],
        }
    )


def _memory(workspace_id: str = LEGACY_WORKSPACE_ID) -> tuple[str, str]:
    session_id = create_session("forgetting-user", workspace_id=workspace_id)
    observation_id = save_observation(
        session_id,
        "user",
        "The private project codename is MIRA.",
    )
    state = ensure_memory_state("observations", observation_id, workspace_id)
    return observation_id, str(state["id"])


def test_api_forgetting_is_workspace_scoped_and_preserves_history(tmp_path: Path) -> None:
    configure_database(tmp_path / "public-forgetting.sqlite3")
    observation_id, memory_id = _memory()
    auth = AuthenticatedWorkspace(WorkspaceContext(LEGACY_WORKSPACE_ID, auth_mode="development"))

    response = forget_memory_route(
        memory_id,
        _request(),
        MemoryForgetRequest(reason="user requested forgetting"),
        auth,
    )

    assert response.memory["id"] == memory_id
    assert response.memory["lifecycle_status"] == "forgotten"
    assert get_memory_state_by_id(memory_id, LEGACY_WORKSPACE_ID)["source_id"] == observation_id
    assert (
        lifecycle_for_retrieval("observations", observation_id, LEGACY_WORKSPACE_ID)["eligible"]
        is False
    )

    run_memory_sleep(LEGACY_WORKSPACE_ID, max_items=10, now="2030-01-01T00:00:00+00:00")
    assert get_memory_state_by_id(memory_id, LEGACY_WORKSPACE_ID)["lifecycle_status"] == "forgotten"
    with repository_connection() as connection:
        source = connection.execute(
            "SELECT id FROM observations WHERE id = ? AND workspace_id = ?",
            (observation_id, LEGACY_WORKSPACE_ID),
        ).fetchone()
        review = connection.execute(
            """
            SELECT event_type, evidence FROM memory_reviews
            WHERE memory_state_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (memory_id,),
        ).fetchone()
    assert source is not None
    assert review["event_type"] == "forgotten"
    assert json.loads(review["evidence"])["reason"] == "user requested forgetting"


def test_api_forgetting_is_idempotent_and_hides_unknown_or_foreign_ids(tmp_path: Path) -> None:
    configure_database(tmp_path / "public-forgetting-api-errors.sqlite3")
    _, memory_id = _memory()
    auth = AuthenticatedWorkspace(WorkspaceContext(LEGACY_WORKSPACE_ID, auth_mode="development"))
    payload = MemoryForgetRequest(reason="remove it")

    first = forget_memory_route(memory_id, _request(), payload, auth)
    second = forget_memory_route(memory_id, _request(), payload, auth)
    assert second.memory == first.memory

    with pytest.raises(HTTPException) as unknown:
        forget_memory_route("missing-memory-state", _request(), payload, auth)
    assert unknown.value.status_code == 404

    foreign_workspace = create_workspace("Foreign", "foreign-forgetting", "development")
    _, foreign_memory_id = _memory(foreign_workspace)
    with pytest.raises(HTTPException) as foreign:
        forget_memory_route(foreign_memory_id, _request(), payload, auth)
    assert foreign.value.status_code == 404


def test_mcp_forgetting_is_bound_to_workspace_and_handles_unknown_ids(tmp_path: Path) -> None:
    configure_database(tmp_path / "public-forgetting-mcp.sqlite3")
    _, memory_id = _memory()
    server = build_mcp_server(WorkspaceContext(LEGACY_WORKSPACE_ID, auth_mode="configured"))

    response = server.call_tool(
        "forget_memory",
        {"memory_id": memory_id, "reason": "MCP user request"},
    )

    assert response["ok"] is True
    assert response["result"]["memory"]["lifecycle_status"] == "forgotten"
    repeated = server.call_tool(
        "forget_memory",
        {"memory_id": memory_id, "reason": "MCP user request"},
    )
    assert repeated["ok"] is True
    assert repeated["result"]["memory"] == response["result"]["memory"]

    unknown = server.call_tool(
        "forget_memory",
        {"memory_id": "missing-memory-state", "reason": "not found"},
    )
    assert unknown["ok"] is False
    assert unknown["error"] == "memory_id not found"

    foreign_workspace = create_workspace("Foreign", "foreign-mcp-forgetting", "development")
    _, foreign_memory_id = _memory(foreign_workspace)
    foreign = server.call_tool(
        "forget_memory",
        {"memory_id": foreign_memory_id, "reason": "cross workspace attempt"},
    )
    assert foreign["ok"] is False
    assert foreign["error"] == "memory_id not found"
