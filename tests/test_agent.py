"""Verify ISSUE-039 MIRA agent runtime loop.

Ownership: MIRA contributors.
Related issue: ISSUE-039.
Architecture area: agent runtime.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from core import agent
from core.agent import Agent, handle_user_message
from core.db.repositories import configure_database, create_session, list_observations


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    """Configure agent tests to use an isolated database."""
    path = tmp_path / "mira.sqlite3"
    configure_database(path)
    yield path


class _CapturingQwen:
    """Records the prompt passed to Qwen and returns a fixed structured answer."""

    def __init__(self, answer: str = "Acknowledged.") -> None:
        self.answer = answer
        self.prompts: list[str] = []

    def __call__(self, messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
        assert schema_name == "answer_generation"
        self.prompts.append(messages[0]["content"])
        return {"json": {"answer": self.answer, "used_memory_ids": []}}


@pytest.fixture
def fake_qwen(monkeypatch: pytest.MonkeyPatch) -> _CapturingQwen:
    """Mock the Qwen call so tests never hit the network."""
    fake = _CapturingQwen()
    monkeypatch.setattr(agent, "call_qwen_json", fake)
    return fake


def _roles(session_id: str) -> list[str]:
    return [str(row["role"]) for row in list_observations(session_id)]


def test_user_turn_is_saved(database_path: Path, fake_qwen: _CapturingQwen) -> None:
    """The user message is persisted as an observation."""
    session_id = create_session("jerry")

    response = handle_user_message(session_id, "What is my deadline?")

    assert response["user_observation_id"]
    contents = [str(row["content"]) for row in list_observations(session_id)]
    assert "What is my deadline?" in contents


def test_assistant_response_is_saved(database_path: Path, fake_qwen: _CapturingQwen) -> None:
    """The assistant answer is persisted and returned."""
    session_id = create_session("jerry")

    response = handle_user_message(session_id, "What is my deadline?")

    assert response["answer"] == "Acknowledged."
    assert response["assistant_observation_id"]
    assert _roles(session_id) == ["user", "assistant"]
    assistant_rows = [row for row in list_observations(session_id) if row["role"] == "assistant"]
    assert str(assistant_rows[0]["content"]) == "Acknowledged."


def test_qwen_call_is_mocked(database_path: Path, fake_qwen: _CapturingQwen) -> None:
    """The runtime calls Qwen exactly once for the answer."""
    session_id = create_session("jerry")

    handle_user_message(session_id, "What is my deadline?")

    assert len(fake_qwen.prompts) == 1


def test_session_correction_affects_response(
    database_path: Path, fake_qwen: _CapturingQwen
) -> None:
    """A correction in the turn enters the SWS and reaches the prompt."""
    session_id = create_session("jerry")

    response = handle_user_message(session_id, "Use 2026, not 2025.")

    assert response["used_session_items"], "expected the correction in the session working set"
    assert "2026" in fake_qwen.prompts[0]


def test_prompt_builder_receives_session_working_set(
    database_path: Path, fake_qwen: _CapturingQwen
) -> None:
    """Session Working Set items are merged into the prompt context."""
    session_id = create_session("jerry")

    # First turn establishes a session constraint via the micro-path.
    handle_user_message(session_id, "We must run make check before every PR.")
    # Second turn should still carry the constraint into the prompt context.
    response = handle_user_message(session_id, "Anything else to remember?")

    assert response["used_session_items"]
    assert "make check" in fake_qwen.prompts[-1]


def test_retrieval_mode_is_reported(database_path: Path, fake_qwen: _CapturingQwen) -> None:
    """The response reports the routed retrieval mode."""
    session_id = create_session("jerry")

    response = handle_user_message(session_id, "What kind of developer am I?")

    assert response["retrieval_mode"] == "deep"


def test_agent_wrapper_chats(database_path: Path, fake_qwen: _CapturingQwen) -> None:
    """The Agent wrapper supports a basic chat call."""
    session_id = create_session("jerry")
    mira = Agent(session_id)

    assert mira.handle_turn("Hello MIRA") == "Acknowledged."
    assert _roles(session_id) == ["user", "assistant"]


def test_empty_message_is_rejected(database_path: Path) -> None:
    """A blank user message is rejected before any persistence."""
    session_id = create_session("jerry")
    with pytest.raises(ValueError, match="user_message"):
        handle_user_message(session_id, "   ")
