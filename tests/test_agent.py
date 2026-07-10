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


def test_general_knowledge_question_skips_memory_retrieval(
    database_path: Path, fake_qwen: _CapturingQwen
) -> None:
    """Ordinary world-knowledge questions are not forced through memory retrieval."""
    session_id = create_session("jerry")

    response = handle_user_message(session_id, "What is an apple?")

    assert response["retrieval_mode"] == "general"
    assert response["used_memory_items"] == []
    assert response["routing_decision"]["intent"] == "general_knowledge"
    assert response["retrieval_trace"]["used_memory"] is False
    assert response["retrieval_trace"]["route"] == "direct_llm"
    assert "Answer mode:\ngeneral_knowledge" in fake_qwen.prompts[0]


def test_followup_general_question_stays_general(
    database_path: Path, fake_qwen: _CapturingQwen
) -> None:
    """A later definition question should not become memory-only because chat history exists."""
    session_id = create_session("jerry")

    handle_user_message(session_id, "What is an apple?")
    handle_user_message(session_id, "Thanks.")
    response = handle_user_message(session_id, "What is an orange?")

    assert response["retrieval_mode"] == "general"
    assert "Answer mode:\ngeneral_knowledge" in fake_qwen.prompts[-1]


def test_memory_question_stays_memory_grounded(
    database_path: Path, fake_qwen: _CapturingQwen
) -> None:
    """Personal/history questions still use memory-grounded answering."""
    session_id = create_session("jerry")

    response = handle_user_message(session_id, "What is my deadline?")

    assert response["retrieval_mode"] == "quick"
    assert response["routing_decision"]["intent"] == "personal_memory"
    assert response["retrieval_trace"]["used_memory"] is True
    assert "Answer mode:\nmemory_grounded" in fake_qwen.prompts[0]


def test_explicit_memory_inspection_uses_structured_tool(
    database_path: Path, fake_qwen: _CapturingQwen
) -> None:
    """Memory-inspection requests call a structured internal function."""
    session_id = create_session("jerry")

    response = handle_user_message(session_id, "What do you remember about me?")

    tool_calls = response["tool_calls"]
    assert isinstance(tool_calls, list)
    assert tool_calls and tool_calls[0]["tool"] == "inspect_memory"
    retrieval_trace = response["retrieval_trace"]
    assert isinstance(retrieval_trace, dict)
    retrieved = retrieval_trace["retrieved"]
    assert isinstance(retrieved, list)
    assert any(isinstance(item, dict) and item["source"] == "structured_tool" for item in retrieved)
    assert "Structured memory inspection result" in fake_qwen.prompts[0]


def test_accurate_router_can_choose_general_mode(
    database_path: Path, fake_qwen: _CapturingQwen, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Accurate routing can use an LLM route decision to bypass memory."""
    session_id = create_session("jerry")
    calls: list[dict[str, object]] = []

    def _route(query: str, session_id: str | None, *, strategy: str = "fast") -> dict[str, object]:
        calls.append({"query": query, "session_id": session_id, "strategy": strategy})
        return {"mode": "general", "reason": "definition question"}

    monkeypatch.setattr(agent, "route_retrieval", _route)

    response = handle_user_message(
        session_id,
        "What is an orange?",
        routing_strategy="accurate",
    )

    assert response["retrieval_mode"] == "general"
    assert calls and calls[0]["strategy"] == "accurate"
    assert "Answer mode:\ngeneral_knowledge" in fake_qwen.prompts[0]


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


def _routing_decision(*, needs_sufficiency_check: bool, confidence: float) -> dict[str, object]:
    return {
        "mode": "quick",
        "route": "quick",
        "intent": "personal_memory",
        "used_memory": True,
        "reason": "test",
        "confidence": confidence,
        "needs_sufficiency_check": needs_sufficiency_check,
    }


def test_sufficiency_retry_runs_only_when_flagged(
    database_path: Path, fake_qwen: _CapturingQwen, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sufficiency resolver runs for an ambiguous route and is skipped for a confident one."""
    calls = {"n": 0}
    real_resolver = agent.resolve_with_one_retry

    def _spy(query: str, retrieve: object) -> dict[str, object]:
        calls["n"] += 1
        return real_resolver(query, retrieve)  # type: ignore[arg-type]

    monkeypatch.setattr(agent, "resolve_with_one_retry", _spy)
    session_id = create_session("jerry")

    monkeypatch.setattr(
        agent,
        "route_retrieval",
        lambda *_a, **_k: _routing_decision(needs_sufficiency_check=True, confidence=0.4),
    )
    handle_user_message(session_id, "anything at all")
    assert calls["n"] == 1

    calls["n"] = 0
    monkeypatch.setattr(
        agent,
        "route_retrieval",
        lambda *_a, **_k: _routing_decision(needs_sufficiency_check=False, confidence=0.8),
    )
    handle_user_message(session_id, "anything at all")
    assert calls["n"] == 0
