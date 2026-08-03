"""Tests for the MIRA FastAPI chat endpoint."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from api.auth import AuthenticatedWorkspace
from api.routes.chat import _chat_event_stream, chat
from api.schemas.chat import ChatRequest
from core.db.repositories import WorkspaceContext, configure_database, repository_connection
from core.db.schema import LEGACY_WORKSPACE_ID


class _FakeAgent:
    calls: list[tuple[str, str, str]] = []

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id

    def respond(self, user_message: str, *, routing_strategy: str = "fast") -> dict[str, object]:
        self.calls.append((self.session_id, user_message, routing_strategy))
        return {
            "user_observation_id": "obs_user",
            "assistant_observation_id": "obs_assistant",
            "session_id": self.session_id,
            "answer": "Real agent path called.",
            "retrieval_mode": "quick",
            "routing_decision": {
                "context_scope": "durable_memory",
                "retrieval_mode": "quick",
            },
            "used_memory_items": ["fact_1"],
            "used_session_items": ["sws_1"],
            "trace_id": "trace_1",
        }


class _FailingAgent:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id

    def respond(self, user_message: str, *, routing_strategy: str = "fast") -> dict[str, object]:
        raise RuntimeError("Error executing plan: Internal error: Error finding id")


class _StreamingAgent:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id

    def respond(self, user_message: str, **kwargs: Any) -> dict[str, object]:
        progress_callback = kwargs.get("progress_callback")
        if callable(progress_callback):
            progress_callback(
                {
                    "type": "stage",
                    "stage": "retrieval",
                    "message": "Searching relevant memory.",
                }
            )
        return {
            "user_observation_id": "obs_user",
            "assistant_observation_id": "obs_assistant",
            "session_id": self.session_id,
            "answer": f"Answer for {user_message}",
            "retrieval_mode": "quick",
            "routing_decision": {
                "context_scope": "durable_memory",
                "retrieval_mode": "quick",
            },
            "used_memory_items": ["fact_1"],
            "used_session_items": ["sws_1"],
            "trace_id": "trace_1",
        }


def _request_and_auth() -> tuple[Request, AuthenticatedWorkspace]:
    request = Request({"type": "http", "method": "POST", "path": "/chat", "headers": []})
    auth = AuthenticatedWorkspace(WorkspaceContext(LEGACY_WORKSPACE_ID, auth_mode="development"))
    return request, auth


def test_chat_endpoint_calls_agent_path(monkeypatch: Any, tmp_path: Any) -> None:
    db_path = tmp_path / "api-chat.sqlite3"
    monkeypatch.setenv("MIRA_DB_PATH", str(db_path))
    configure_database(db_path)
    _FakeAgent.calls = []
    monkeypatch.setattr("api.routes.chat.Agent", _FakeAgent)

    request, auth = _request_and_auth()
    response = chat(
        request,
        ChatRequest(message="Use 2026.", retrieval_mode="auto"),
        auth,
    )

    assert response.answer == "Real agent path called."
    assert response.retrieval_mode == "quick"
    assert response.routing_decision == {
        "context_scope": "durable_memory",
        "retrieval_mode": "quick",
    }
    assert response.user_observation_id == "obs_user"
    assert response.assistant_observation_id == "obs_assistant"
    assert response.used_memory_items == ["fact_1"]
    assert response.used_session_items == ["sws_1"]
    assert _FakeAgent.calls and _FakeAgent.calls[0][1] == "Use 2026."
    assert _FakeAgent.calls[0][2] == "hybrid"
    with repository_connection() as connection:
        title = connection.execute(
            "SELECT title FROM sessions WHERE id = ?",
            (response.session_id,),
        ).fetchone()["title"]
    assert title == "Use 2026."


def test_chat_endpoint_passes_accurate_routing_strategy(monkeypatch: Any, tmp_path: Any) -> None:
    db_path = tmp_path / "api-chat-accurate.sqlite3"
    monkeypatch.setenv("MIRA_DB_PATH", str(db_path))
    configure_database(db_path)
    _FakeAgent.calls = []
    monkeypatch.setattr("api.routes.chat.Agent", _FakeAgent)

    request, auth = _request_and_auth()
    chat(
        request,
        ChatRequest(
            message="What is an apple?",
            routing_strategy="accurate",
        ),
        auth,
    )

    assert _FakeAgent.calls and _FakeAgent.calls[0][2] == "accurate"


def test_chat_request_accepts_hybrid_routing_strategy() -> None:
    request = ChatRequest(message="What is the project deadline?", routing_strategy="hybrid")

    assert request.routing_strategy == "hybrid"


def test_chat_endpoint_sanitizes_internal_runtime_errors(
    monkeypatch: Any,
    tmp_path: Any,
) -> None:
    db_path = tmp_path / "api-chat-failure.sqlite3"
    monkeypatch.setenv("MIRA_DB_PATH", str(db_path))
    configure_database(db_path)
    logged: list[dict[str, object]] = []
    monkeypatch.setattr("api.routes.chat.Agent", _FailingAgent)
    monkeypatch.setattr(
        "api.routes.chat.log_event",
        lambda event, message, **fields: logged.append(
            {"event": event, "message": message, **fields}
        ),
    )

    request, auth = _request_and_auth()
    with pytest.raises(HTTPException) as exc_info:
        chat(
            request,
            ChatRequest(message="I prefer Python."),
            auth,
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "chat runtime failed; check API logs for details"
    assert "Error finding id" not in str(exc_info.value.detail)
    assert logged
    assert logged[0]["event"] == "api_chat_error"
    assert logged[0]["error_type"] == "RuntimeError"


def test_chat_endpoint_validates_payload() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(message="")


def test_chat_request_only_accepts_agent_auto_retrieval_mode() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(message="Hello", retrieval_mode="quick")


def test_chat_request_validates_routing_strategy() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(message="Hello", routing_strategy="slow")


def test_chat_request_rejects_client_supplied_identity() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(user_id="guessed-user", message="Hello")


def test_chat_event_stream_emits_progress_answer_trace_and_completion(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr("api.routes.chat.Agent", _StreamingAgent)

    lines = list(
        _chat_event_stream(
            ChatRequest(message="What do I use?", retrieval_mode="auto"),
            "session-1",
        )
    )

    assert any('"type": "stage"' in line and '"stage": "retrieval"' in line for line in lines)
    assert any('"type": "answer"' in line and "Answer for What do I use?" in line for line in lines)
    assert any('"type": "trace"' in line and '"trace_id": "trace_1"' in line for line in lines)
    assert any(
        '"context_scope": "durable_memory"' in line and '"type": "trace"' in line for line in lines
    )
    assert any(
        '"type": "complete"' in line and '"session_id": "session-1"' in line for line in lines
    )
