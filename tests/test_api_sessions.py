"""Tests for MIRA API session routes."""

from __future__ import annotations

from typing import Any

from starlette.requests import Request

from api.auth import AuthenticatedWorkspace
from api.routes.sessions import create_session_route, get_session_route, get_working_set_route
from api.schemas.sessions import CreateSessionRequest
from core.db.repositories import (
    WorkspaceContext,
    create_answer_trace,
    create_session_item,
    create_working_memory_item,
    save_observation,
)
from core.db.schema import LEGACY_WORKSPACE_ID

AUTH = AuthenticatedWorkspace(WorkspaceContext(LEGACY_WORKSPACE_ID, auth_mode="development"))
REQUEST = Request({"type": "http", "method": "POST", "path": "/sessions", "headers": []})


def test_session_endpoint_creates_and_returns_session(tmp_path: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv("MIRA_DB_PATH", str(tmp_path / "api-sessions.sqlite3"))

    created = create_session_route(REQUEST, CreateSessionRequest(title="API Test"), AUTH)

    assert created.user_id == "development"
    assert created.title == "API Test"

    fetched = get_session_route(created.session_id, AUTH)
    assert fetched.session_id == created.session_id


def test_working_set_endpoint_returns_grouped_shape(tmp_path: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv("MIRA_DB_PATH", str(tmp_path / "api-working-set.sqlite3"))
    session_id = create_session_route(REQUEST, CreateSessionRequest(), AUTH).session_id

    response = get_working_set_route(session_id, AUTH)

    assert response.session_id == session_id
    assert response.active_goals == []
    assert response.corrections == []
    assert response.constraints == []
    assert response.unresolved_questions == []
    assert response.provisional_decisions == []
    assert response.items == []


def test_working_set_endpoint_returns_enriched_inspection_fields(
    tmp_path: Any, monkeypatch: Any
) -> None:
    monkeypatch.setenv("MIRA_DB_PATH", str(tmp_path / "api-working-set-rich.sqlite3"))
    session_id = create_session_route(REQUEST, CreateSessionRequest(), AUTH).session_id
    old_id = create_session_item(
        {
            "session_id": session_id,
            "type": "active_constraint",
            "content": "Prefer concise responses.",
            "scope": "current_session",
            "status": "superseded",
            "priority": 0.4,
            "explicitness_label": "direct_instruction",
            "source_observations_json": [],
        }
    )
    source_observation_id = save_observation(
        session_id,
        "user",
        "Actually, give me detailed responses.",
    )
    assistant_observation_id = save_observation(session_id, "assistant", "Understood.")
    correction_id = create_session_item(
        {
            "session_id": session_id,
            "type": "correction",
            "content": "Give detailed responses.",
            "scope": "project",
            "status": "confirmed",
            "priority": 0.9,
            "explicitness_label": "direct_correction",
            "evidence_span": "Actually, give me detailed responses.",
            "source_observations_json": [source_observation_id],
            "supersedes_json": [old_id],
        }
    )
    create_answer_trace(
        {
            "session_id": session_id,
            "user_observation_id": source_observation_id,
            "assistant_observation_id": assistant_observation_id,
            "retrieval_mode": "quick",
            "session_item_ids_json": [correction_id],
        }
    )
    create_working_memory_item(
        {
            "content": "Give detailed responses.",
            "memory_type": "confirmed_correction",
            "scope": "project",
            "priority": 0.9,
            "status": "active",
            "source_record_type": "session_working_set",
            "source_record_id": correction_id,
        }
    )

    response = get_working_set_route(session_id, AUTH)
    item = next(row for row in response.items if row["id"] == correction_id)

    assert item["source_messages"][0]["message_index"] == 1
    assert item["usage_count"] == 1
    assert item["token_cost"] > 0
    assert item["promotion_status"] == "promoted"
    assert item["superseded_items"][0]["content"] == "Prefer concise responses."
