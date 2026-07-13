"""Tests for MIRA API session routes."""

from __future__ import annotations

from typing import Any

from starlette.requests import Request

from api.auth import AuthenticatedWorkspace
from api.routes.sessions import create_session_route, get_session_route, get_working_set_route
from api.schemas.sessions import CreateSessionRequest
from core.db.repositories import WorkspaceContext
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
