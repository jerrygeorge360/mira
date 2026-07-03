"""Tests for the MIRA FastAPI chat endpoint."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from api.routes.chat import chat
from api.schemas.chat import ChatRequest
from core.db.repositories import configure_database


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
            "used_memory_items": ["fact_1"],
            "used_session_items": ["sws_1"],
            "trace_id": "trace_1",
        }


def test_chat_endpoint_calls_agent_path(monkeypatch: Any, tmp_path: Any) -> None:
    db_path = tmp_path / "api-chat.sqlite3"
    monkeypatch.setenv("MIRA_DB_PATH", str(db_path))
    configure_database(db_path)
    _FakeAgent.calls = []
    monkeypatch.setattr("api.routes.chat.Agent", _FakeAgent)

    response = chat(ChatRequest(user_id="jerry", message="Use 2026.", retrieval_mode="auto"))

    assert response.answer == "Real agent path called."
    assert response.retrieval_mode == "quick"
    assert response.user_observation_id == "obs_user"
    assert response.assistant_observation_id == "obs_assistant"
    assert response.used_memory_items == ["fact_1"]
    assert response.used_session_items == ["sws_1"]
    assert _FakeAgent.calls and _FakeAgent.calls[0][1] == "Use 2026."
    assert _FakeAgent.calls[0][2] == "fast"


def test_chat_endpoint_passes_accurate_routing_strategy(monkeypatch: Any, tmp_path: Any) -> None:
    db_path = tmp_path / "api-chat-accurate.sqlite3"
    monkeypatch.setenv("MIRA_DB_PATH", str(db_path))
    configure_database(db_path)
    _FakeAgent.calls = []
    monkeypatch.setattr("api.routes.chat.Agent", _FakeAgent)

    chat(
        ChatRequest(
            user_id="jerry",
            message="What is an apple?",
            routing_strategy="accurate",
        )
    )

    assert _FakeAgent.calls and _FakeAgent.calls[0][2] == "accurate"


def test_chat_endpoint_validates_payload() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(user_id="jerry", message="")


def test_chat_request_only_accepts_agent_auto_retrieval_mode() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(user_id="jerry", message="Hello", retrieval_mode="quick")


def test_chat_request_validates_routing_strategy() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(user_id="jerry", message="Hello", routing_strategy="slow")
