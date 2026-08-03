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
from core.agent import Agent, AgentTurnCancelled, handle_user_message
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
        if schema_name == "turn_purpose_classification":
            return {
                "json": {
                    "purpose": "casual_message",
                    "reason": "Unit-test default for an otherwise ambiguous turn.",
                }
            }
        assert schema_name == "answer_generation"
        self.prompts.append(messages[0]["content"])
        return {"json": {"answer": self.answer, "used_memory_ids": []}}


@pytest.fixture
def fake_qwen(monkeypatch: pytest.MonkeyPatch) -> _CapturingQwen:
    """Mock the Qwen call so tests never hit the network."""
    fake = _CapturingQwen()
    monkeypatch.setattr(agent, "call_qwen_json", fake)
    return fake


@pytest.fixture(autouse=True)
def disable_live_router(monkeypatch: pytest.MonkeyPatch) -> None:
    """Agent unit tests never use credentials inherited from the developer shell."""
    monkeypatch.setattr("core.retrieval.auto._llm_routing_available", lambda: False)


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
    """A correction enters the SWS without paying for answer retrieval."""
    session_id = create_session("jerry")

    response = handle_user_message(session_id, "Use 2026, not 2025.")

    assert response["used_session_items"], "expected the correction in the session working set"
    assert "2026" in response["answer"]
    assert "2025" in response["answer"]
    assert response["routing_decision"]["context_scope"] == "no_retrieval"
    assert response["retrieval_trace"]["retrieved"] == []
    assert fake_qwen.prompts == []


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


def test_casual_reaction_does_not_replay_recent_roles(
    database_path: Path, fake_qwen: _CapturingQwen, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_id = create_session("jerry")
    handle_user_message(session_id, "What is Othello?")

    def fail_retrieval(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        raise AssertionError("casual reactions must not retrieve durable memory")

    monkeypatch.setattr(agent, "retrieve_by_mode", fail_retrieval)
    response = handle_user_message(session_id, "that is unfortunate")

    assert response["routing_decision"]["context_scope"] == "no_retrieval"
    assert response["retrieval_trace"]["retrieved"] == []
    assert "[recent_turn role=user] What is Othello?" not in fake_qwen.prompts[-1]
    assert "[recent_turn role=assistant] Acknowledged." not in fake_qwen.prompts[-1]


def test_vague_deictic_correction_asks_for_target_without_retrieval(
    database_path: Path, fake_qwen: _CapturingQwen, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_id = create_session("jerry")
    handle_user_message(session_id, "What cache do I use?")

    def fail_retrieval(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        raise AssertionError("an unresolved correction must ask for clarification first")

    monkeypatch.setattr(agent, "retrieve_by_mode", fail_retrieval)
    response = handle_user_message(session_id, "that's no longer true")

    assert response["answer"] == "What specifically in the previous answer is no longer true?"
    assert response["routing_decision"]["route"] == "clarify_update"
    assert response["routing_decision"]["context_scope"] == "recent_conversation"
    assert response["used_memory_items"] == []


@pytest.mark.parametrize(
    ("message", "expected_purpose"),
    [
        ("nice. by the way I have a system design interview next Tuesday", "informational_update"),
        ("oh also, I moved my caching layer from Redis to Memcached", "correction"),
        ("fair enough. anyway Redis kept timing out on me", "informational_update"),
        ("no I mean the interview thing, it's not next Tuesday anymore", "correction"),
        ("so anyway, I'm using Postgres for my main app database", "informational_update"),
        ("I also set up a cron job for nightly backups", "informational_update"),
    ],
)
def test_discourse_prefixed_updates_keep_their_semantic_purpose(
    message: str,
    expected_purpose: str,
) -> None:
    assert agent._classify_turn_purpose(message, recent_turns=[]) == expected_purpose


def test_contextual_schedule_amendment_is_a_correction() -> None:
    purpose = agent._classify_turn_purpose(
        "it moved to the following week",
        recent_turns=[
            {"role": "user", "content": "My interview is next Tuesday."},
            {"role": "assistant", "content": "Noted."},
        ],
    )

    assert purpose == "correction"


def test_actually_that_is_wrong_requires_clarification(
    database_path: Path, fake_qwen: _CapturingQwen
) -> None:
    session_id = create_session("jerry")
    response = handle_user_message(session_id, "actually that's wrong")

    assert response["answer"] == "What specifically in the previous answer is no longer true?"
    assert response["routing_decision"]["route"] == "clarify_update"
    assert response["used_session_items"] == []


def test_declarative_update_skips_retrieval_and_generation(
    database_path: Path, fake_qwen: _CapturingQwen, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plain informational updates are saved without dumping old memory into an answer."""
    session_id = create_session("jerry")

    def fail_retrieval(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        raise AssertionError("informational updates should not retrieve memory")

    monkeypatch.setattr(agent, "retrieve_by_mode", fail_retrieval)
    response = handle_user_message(
        session_id,
        "The prompt is an execution buffer, not the memory store.",
    )

    assert response["answer"] == "Noted."
    assert response["retrieval_mode"] == "general"
    assert response["used_memory_items"] == []
    assert response["routing_decision"]["route"] == "acknowledge_and_store"
    assert response["retrieval_trace"]["used_memory"] is False
    assert fake_qwen.prompts == []
    assert _roles(session_id) == ["user", "assistant"]


def test_discourse_prefixed_personal_updates_acknowledge_the_latest_fact(
    database_path: Path,
    fake_qwen: _CapturingQwen,
) -> None:
    session_id = create_session("jerry")
    handle_user_message(session_id, "What is a message queue?")

    database_update = handle_user_message(
        session_id,
        "so anyway, I'm using Postgres for my main app database",
    )
    backup_update = handle_user_message(
        session_id,
        "I also set up a cron job that backs up the database every night at 2am",
    )
    cloud_update = handle_user_message(
        session_id,
        "oh, side note, I'm currently deploying my app on AWS",
    )
    autoscaling_update = handle_user_message(
        session_id,
        "also I set up autoscaling to trigger at 80% CPU usage",
    )

    assert database_update["answer"] == (
        "Got it. I'll remember that you're using Postgres for your main app database."
    )
    assert "cron job" in str(backup_update["answer"])
    assert "2am" in str(backup_update["answer"])
    assert "AWS" in str(cloud_update["answer"])
    assert "autoscaling" in str(autoscaling_update["answer"])
    assert "80%" in str(autoscaling_update["answer"])
    assert len(fake_qwen.prompts) == 1


def test_low_information_reactions_do_not_repeat_the_previous_answer(
    database_path: Path,
    fake_qwen: _CapturingQwen,
) -> None:
    session_id = create_session("jerry")
    handle_user_message(session_id, "What's my main database?")

    reaction = handle_user_message(session_id, "good, that's one less thing to worry about")
    closing = handle_user_message(session_id, "thanks, that's all for now")

    assert reaction["answer"] == "Glad that's sorted."
    assert closing["answer"] == "You're welcome."
    assert reaction["routing_decision"]["route"] == "direct_conversation"
    assert closing["routing_decision"]["context_scope"] == "no_retrieval"
    assert len(fake_qwen.prompts) == 1


def test_resolution_turns_do_not_echo_the_previous_answer(
    database_path: Path,
    fake_qwen: _CapturingQwen,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = create_session("jerry")
    handle_user_message(session_id, "What database am I using?")
    monkeypatch.setattr(agent, "_llm_classify_turn_purpose", lambda *_args: "resolution")

    def resolve_latest(
        _session_id: str,
        _message: str,
        recent_turns: list[dict[str, object]],
    ) -> dict[str, object]:
        target = next(turn for turn in reversed(recent_turns) if turn.get("role") == "user")
        return {
            "status": "resolved",
            "target_observation_id": str(target["id"]),
            "target_content": str(target["content"]),
            "source": "recent_turn",
            "confidence": 0.99,
            "reason": "Structured resolver selected the latest user statement.",
            "clarification": None,
            "candidate_ids": [f"observation:{target['id']}"],
        }

    monkeypatch.setattr(agent, "resolve_discourse_reference", resolve_latest)
    ignored = handle_user_message(session_id, "wait, ignore that last thing I said")
    dropped = handle_user_message(session_id, "ok never mind, forget it")

    assert "What database am I using?" in str(ignored["answer"])
    assert "wait, ignore that last thing I said" in str(dropped["answer"])
    assert ignored["routing_decision"]["turn_purpose"] == "resolution"
    assert dropped["routing_decision"]["route"] == "acknowledge_and_store"
    assert len(fake_qwen.prompts) == 1


def test_resolution_reference_binds_to_the_previous_user_turn(
    database_path: Path,
    fake_qwen: _CapturingQwen,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = create_session("jerry")
    handle_user_message(session_id, "nice, that takes one thing off my plate")
    monkeypatch.setattr(agent, "_llm_classify_turn_purpose", lambda *_args: "resolution")
    handle_user_message(session_id, "hold on, disregard what I just said")

    response = handle_user_message(session_id, "what did I just tell you to disregard?")

    assert response["routing_decision"]["context_scope"] == "recent_conversation"
    assert response["used_memory_items"] == []
    assert (
        "Resolved memory operation target: nice, that takes one thing off my plate"
        in (fake_qwen.prompts[-1])
    )


def test_undo_followup_names_the_resolved_user_turn(
    database_path: Path,
    fake_qwen: _CapturingQwen,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = create_session("jerry")
    handle_user_message(session_id, "nice, one less config to think about")
    initial_prompt_count = len(fake_qwen.prompts)
    monkeypatch.setattr(
        agent,
        "_classify_turn_purpose",
        lambda message, **_kwargs: "resolution" if message.startswith("undo") else "question",
    )
    handle_user_message(session_id, "undo what I just said")

    response = handle_user_message(session_id, "what did you just undo?")

    assert response["routing_decision"]["context_scope"] == "recent_conversation"
    assert len(fake_qwen.prompts) == initial_prompt_count + 1
    assert (
        "Resolved memory operation target: nice, one less config to think about"
        in (fake_qwen.prompts[-1])
    )


def test_ambiguous_resolution_asks_before_mutating_session_memory(
    database_path: Path,
    fake_qwen: _CapturingQwen,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = create_session("jerry")
    handle_user_message(session_id, "We must run make check before every PR.")
    existing_ids = {str(item["id"]) for item in agent.list_active_session_items(session_id)}
    initial_prompt_count = len(fake_qwen.prompts)
    monkeypatch.setattr(
        agent,
        "resolve_discourse_reference",
        lambda *_args, **_kwargs: {
            "status": "ambiguous",
            "target_observation_id": None,
            "target_content": None,
            "source": None,
            "confidence": 0.0,
            "reason": "Two statements are plausible targets.",
            "clarification": 'Which statement should I disregard: "A" or "B"?',
            "candidate_ids": ["observation:a", "observation:b"],
        },
    )
    monkeypatch.setattr(agent, "_llm_classify_turn_purpose", lambda *_args: "resolution")

    response = handle_user_message(session_id, "Ignore that.")

    assert response["answer"] == 'Which statement should I disregard: "A" or "B"?'
    assert response["routing_decision"]["route"] == "clarify_update"
    assert {str(item["id"]) for item in agent.list_active_session_items(session_id)} == existing_ids
    assert len(fake_qwen.prompts) == initial_prompt_count


def test_recent_personal_why_question_requires_stated_causal_evidence(
    database_path: Path,
    fake_qwen: _CapturingQwen,
) -> None:
    session_id = create_session("jerry")
    handle_user_message(session_id, "I set up autoscaling at 80% CPU usage")

    response = handle_user_message(session_id, "why 80% though?")

    assert response["sufficiency"]["answered_with_uncertainty"] is True
    assert "Must answer with uncertainty: True" in fake_qwen.prompts[-1]


def test_informational_update_about_corrections_does_not_enter_sws(
    database_path: Path, fake_qwen: _CapturingQwen
) -> None:
    """Architecture descriptions that mention corrections do not become hot corrections."""
    session_id = create_session("jerry")

    response = handle_user_message(
        session_id,
        (
            "The Session Working Set immediately tracks current goals, corrections, "
            "constraints, decisions, and open questions."
        ),
    )

    assert response["answer"] == "Noted."
    assert response["retrieval_mode"] == "general"
    assert response["used_session_items"] == []
    assert fake_qwen.prompts == []


def test_ambiguous_turn_can_use_llm_purpose_classifier(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The LLM classifier can turn ambiguous notes into store-only updates."""
    session_id = create_session("jerry")
    calls: list[str] = []

    def classify(messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
        calls.append(schema_name)
        assert schema_name == "turn_purpose_classification"
        assert "MemoryAgent track" in messages[0]["content"]
        return {
            "json": {
                "purpose": "informational_update",
                "reason": "Project note without an answer request.",
            }
        }

    monkeypatch.setattr(agent, "call_qwen_json", classify)
    response = handle_user_message(session_id, "MIRA MemoryAgent track submission context")

    assert response["answer"] == "Noted."
    assert response["routing_decision"]["route"] == "acknowledge_and_store"
    assert calls == ["turn_purpose_classification"]


def test_unlisted_memory_action_uses_semantic_purpose_classifier(
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def classify(messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
        calls.append(schema_name)
        assert "Withdraw the previous claim." in messages[0]["content"]
        return {
            "json": {
                "purpose": "resolution",
                "reason": "The user wants to retract an earlier statement.",
            }
        }

    monkeypatch.setattr(agent, "call_qwen_json", classify)

    purpose = agent._classify_turn_purpose(
        "Withdraw the previous claim.",
        recent_turns=[{"id": "obs-1", "role": "user", "content": "The deployment uses AWS."}],
    )

    assert purpose == "resolution"
    assert calls == ["turn_purpose_classification"]


def test_personal_temporal_update_is_acknowledged_without_retrieval(
    database_path: Path, fake_qwen: _CapturingQwen, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A new personal event is stored instead of being answered from stale memory."""
    session_id = create_session("jerry")

    def fail_retrieval(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        raise AssertionError("personal updates should not retrieve memory")

    monkeypatch.setattr(agent, "retrieve_by_mode", fail_retrieval)
    response = handle_user_message(session_id, "I have an exam tomorrow")

    assert response["answer"] == "Got it. I'll remember that you have an exam tomorrow."
    assert response["routing_decision"]["route"] == "acknowledge_and_store"
    assert response["used_memory_items"] == []
    assert fake_qwen.prompts == []


def test_additional_event_followup_uses_recent_turns_without_retrieval(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A short additive follow-up creates a separate event and asks only for missing detail."""
    session_id = create_session("jerry")
    handle_user_message(session_id, "I have an exam tomorrow")
    classifier_prompts: list[str] = []

    def classify(messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
        assert schema_name == "turn_purpose_classification"
        classifier_prompts.append(messages[0]["content"])
        return {
            "json": {
                "purpose": "question",
                "reason": "Deliberately wrong verdict to exercise the additive-event guard.",
            }
        }

    def fail_retrieval(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        raise AssertionError("additive event updates should not retrieve memory")

    monkeypatch.setattr(agent, "call_qwen_json", classify)
    monkeypatch.setattr(agent, "retrieve_by_mode", fail_retrieval)
    response = handle_user_message(session_id, "another exam")

    assert response["answer"] == "Got it. I'll treat that as a separate exam. When is it?"
    assert response["routing_decision"]["route"] == "acknowledge_and_store"
    assert classifier_prompts and "I have an exam tomorrow" in classifier_prompts[0]


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


def test_anaphoric_general_followup_does_not_retrieve_memory(
    database_path: Path, fake_qwen: _CapturingQwen
) -> None:
    """A follow-up to a public topic stays grounded in recent conversation, not old memory."""
    session_id = create_session("jerry")

    handle_user_message(session_id, "What is the Holocaust?")
    response = handle_user_message(session_id, "That is mad, what was the purpose of that")

    assert response["retrieval_mode"] == "general"
    assert response["routing_decision"]["used_memory"] is False
    assert response["routing_decision"]["context_scope"] == "recent_conversation"
    assert response["retrieval_trace"]["retrieved"] == []
    assert "Holocaust" in fake_qwen.prompts[-1]


def test_session_scope_uses_working_set_without_durable_retrieval(
    database_path: Path, fake_qwen: _CapturingQwen, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_id = create_session("jerry")
    handle_user_message(session_id, "We must run make check before every PR.")

    monkeypatch.setattr(
        agent,
        "route_retrieval",
        lambda *_args, **_kwargs: {
            "mode": "general",
            "route": "session_context",
            "intent": "procedural",
            "context_scope": "session_memory",
            "used_memory": True,
            "reason": "The current Session Working Set is sufficient.",
            "confidence": 0.9,
            "needs_sufficiency_check": False,
        },
    )

    def _no_retrieval(*args: object, **kwargs: object) -> list[dict[str, object]]:
        raise AssertionError("session-only scope must not query durable retrieval")

    monkeypatch.setattr(agent, "retrieve_by_mode", _no_retrieval)
    response = handle_user_message(session_id, "What is the current constraint?")

    assert response["retrieval_mode"] == "general"
    assert response["used_session_items"]
    assert response["used_memory_items"] == []
    assert "make check" in fake_qwen.prompts[-1]


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

    def _route(
        query: str,
        session_id: str | None,
        *,
        strategy: str = "fast",
        context: list[dict[str, object]] | None = None,
        turn_purpose: str | None = None,
    ) -> dict[str, object]:
        del turn_purpose
        calls.append({"query": query, "session_id": session_id, "strategy": strategy})
        assert context is not None
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
        "context_scope": "durable_memory",
        "used_memory": True,
        "reason": "test",
        "confidence": confidence,
        "needs_sufficiency_check": needs_sufficiency_check,
    }


def test_sufficiency_wraps_every_durable_retrieval(
    database_path: Path, fake_qwen: _CapturingQwen, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Durable retrieval is verified even when routing itself is confident."""
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
    assert calls["n"] == 1


def test_insufficient_attribute_evidence_reaches_answer_prompt(
    database_path: Path,
    fake_qwen: _CapturingQwen,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = create_session("jerry")
    monkeypatch.setattr(
        agent,
        "route_retrieval",
        lambda *_a, **_k: _routing_decision(needs_sufficiency_check=False, confidence=0.9),
    )
    monkeypatch.setattr(
        agent,
        "retrieve_by_mode",
        lambda *_a, **_k: [
            {
                "source": "working_memory",
                "source_id": "cache-fact",
                "content": "project caching uses Memcached",
                "record": {
                    "subject": "project caching",
                    "predicate": "uses",
                    "object": "Memcached",
                },
            }
        ],
    )

    response = handle_user_message(session_id, "What database do I use?")

    assert response["sufficiency"]["answered_with_uncertainty"] is True
    assert "Missing requirements: ['What database do I use?']" in fake_qwen.prompts[-1]
    assert "Must answer with uncertainty: True" in fake_qwen.prompts[-1]


def test_cancelled_turn_does_not_persist_assistant_answer(
    database_path: Path,
    fake_qwen: _CapturingQwen,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = create_session("jerry")
    cancelled = False

    def _generate_answer(_: str) -> str:
        nonlocal cancelled
        cancelled = True
        return "This should not be saved."

    monkeypatch.setattr(agent, "_generate_answer", _generate_answer)

    with pytest.raises(AgentTurnCancelled):
        handle_user_message(
            session_id,
            "What is an apple?",
            should_cancel=lambda: cancelled,
        )

    assert _roles(session_id) == ["user"]
