"""Tests for MIRA API session routes."""

from __future__ import annotations

from typing import Any

from api.routes.sessions import create_session_route, get_session_route, get_working_set_route
from api.schemas.sessions import CreateSessionRequest


def test_session_endpoint_creates_and_returns_session(tmp_path: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv("MIRA_DB_PATH", str(tmp_path / "api-sessions.sqlite3"))

    created = create_session_route(CreateSessionRequest(user_id="jerry", title="API Test"))

    assert created.user_id == "jerry"
    assert created.title == "API Test"

    fetched = get_session_route(created.session_id)
    assert fetched.session_id == created.session_id


def test_working_set_endpoint_returns_grouped_shape(tmp_path: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv("MIRA_DB_PATH", str(tmp_path / "api-working-set.sqlite3"))
    session_id = create_session_route(CreateSessionRequest(user_id="jerry")).session_id

    response = get_working_set_route(session_id)

    assert response.session_id == session_id
    assert response.active_goals == []
    assert response.corrections == []
    assert response.constraints == []
    assert response.unresolved_questions == []
    assert response.provisional_decisions == []
    assert response.items == []
