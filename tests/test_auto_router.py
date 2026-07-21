"""Verify ISSUE-037 automatic retrieval-mode routing.

Ownership: MIRA contributors.
Related issue: ISSUE-037.
Architecture area: retrieval.
"""

from __future__ import annotations

import pytest

from core.llm.qwen import LLMRequestError
from core.retrieval.auto import classify_retrieval_mode, route_retrieval


def test_mongodb_to_postgres_routes_relational() -> None:
    """An entity-centered change question routes to Relational Mode."""
    decision = route_retrieval("I switched from MongoDB to PostgreSQL — what changed?", None)

    assert decision["mode"] == "relational"
    assert decision["reason"]
    assert decision["confidence"] >= 0.8


def test_arrow_change_routes_relational() -> None:
    """A compact arrow transition is still recognized as relational."""
    assert route_retrieval("MongoDB → PostgreSQL?", None)["mode"] == "relational"


def test_identity_question_routes_deep() -> None:
    """A broad identity question routes to Deep Mode."""
    decision = route_retrieval("What kind of developer am I?", None)

    assert decision["mode"] == "deep"
    assert decision["reason"]


def test_specific_fact_routes_quick() -> None:
    """A specific factual lookup routes to Quick Mode."""
    decision = route_retrieval("What is my deadline?", None)

    assert decision["mode"] == "quick"
    assert decision["intent"] == "personal_memory"
    assert decision["used_memory"] is True
    assert decision["route"] == "quick"
    assert decision["needs_sufficiency_check"] is False


def test_general_knowledge_routes_direct_llm() -> None:
    """Public definition questions bypass memory retrieval."""
    decision = route_retrieval("What is an apple?", None)

    assert decision["mode"] == "general"
    assert decision["intent"] == "general_knowledge"
    assert decision["used_memory"] is False
    assert decision["route"] == "direct_llm"


@pytest.mark.parametrize(
    "query",
    [
        "What is a project?",
        "How does task scheduling work?",
        "Explain deadline scheduling.",
        "What kind of database is PostgreSQL?",
    ],
)
def test_general_questions_with_domain_words_do_not_force_memory(query: str) -> None:
    decision = route_retrieval(query, "memory-heavy-session")

    assert decision["mode"] == "general"
    assert decision["used_memory"] is False


def test_explicit_personal_project_question_still_uses_memory() -> None:
    decision = route_retrieval("What is my project?", None)

    assert decision["mode"] == "quick"
    assert decision["explicit_memory_cue"] is True


def test_contextual_reference_is_ambiguous_without_explicit_owner() -> None:
    decision = route_retrieval("When is the project deadline?", None)

    assert decision["mode"] == "quick"
    assert decision["intent"] == "mixed"
    assert decision["needs_sufficiency_check"] is True


def test_ambiguous_query_runs_quick_first_with_sufficiency() -> None:
    """An ambiguous query routes to Quick and flags the sufficiency check."""
    decision = route_retrieval("Tell me more about that.", None)

    assert decision["mode"] == "quick"
    assert decision["needs_sufficiency_check"] is True
    assert decision["confidence"] < 0.6
    assert "sufficiency" in str(decision["reason"]).lower()


def test_relational_is_ordered_before_deep() -> None:
    """A query with both broad and relational cues prefers Relational Mode."""
    decision = route_retrieval("Overall, why did I switch from Python to Rust?", None)

    assert decision["mode"] == "relational"


def test_decision_shape_and_classify_helper() -> None:
    """The router returns mode/reason/confidence and the helper returns the mode."""
    decision = route_retrieval("What is my deadline?", None)

    assert {"mode", "reason", "confidence"} <= set(decision)
    assert classify_retrieval_mode("What kind of person am I?") == "deep"
    assert classify_retrieval_mode("What is my deadline?") == "quick"


def test_empty_query_defaults_to_quick() -> None:
    """A blank query defaults to Quick and is flagged ambiguous."""
    decision = route_retrieval("   ", None)

    assert decision["mode"] == "quick"
    assert decision["needs_sufficiency_check"] is True


def test_accurate_strategy_uses_llm_router(monkeypatch: pytest.MonkeyPatch) -> None:
    """Accurate routing can choose the no-memory general route."""

    def _fake_call(messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
        assert schema_name == "retrieval_router_classification"
        assert "What is an apple?" in messages[0]["content"]
        return {"json": {"mode": "general", "reason": "definition question"}}

    monkeypatch.setattr("core.retrieval.auto.call_qwen_json", _fake_call)

    decision = route_retrieval("What is an apple?", None, strategy="accurate")

    assert decision["mode"] == "general"
    assert decision["reason"] == "definition question"


def test_accurate_strategy_falls_back_to_fast_router(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM router failures fall back to the deterministic route."""

    def _fake_call(messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
        raise LLMRequestError("provider unavailable")

    monkeypatch.setattr("core.retrieval.auto.call_qwen_json", _fake_call)

    decision = route_retrieval("What is my deadline?", None, strategy="accurate")

    assert decision["mode"] == "quick"


def test_invalid_strategy_is_rejected() -> None:
    with pytest.raises(ValueError, match="strategy"):
        route_retrieval("What is my deadline?", None, strategy="slow")


def test_hybrid_stays_deterministic_without_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no provider configured, hybrid never calls the LLM router."""
    monkeypatch.setattr("core.retrieval.auto._llm_routing_available", lambda: False)

    def _no_call(*args: object, **kwargs: object) -> dict[str, object]:
        raise AssertionError("LLM router must not be called without a configured provider")

    monkeypatch.setattr("core.retrieval.auto.call_qwen_json", _no_call)

    decision = route_retrieval("What do I prefer?", None, strategy="hybrid")

    assert decision["mode"] == "quick"  # deterministic memory-grounded route


def test_hybrid_escalates_low_confidence_to_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """An ambiguous deterministic route defers to the LLM classifier under hybrid."""
    monkeypatch.setattr("core.retrieval.auto._llm_routing_available", lambda: True)

    def _fake_call(messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
        return {"json": {"mode": "relational", "reason": "preference comparison"}}

    monkeypatch.setattr("core.retrieval.auto.call_qwen_json", _fake_call)

    decision = route_retrieval("What should I do next?", None, strategy="hybrid")

    assert decision["mode"] == "relational"
    assert decision["reason"] == "preference comparison"


def test_hybrid_passes_recent_context_to_llm_router(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("core.retrieval.auto._llm_routing_available", lambda: True)

    def _fake_call(messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
        assert "PostgreSQL migration" in messages[0]["content"]
        return {"json": {"mode": "quick", "reason": "contextual follow-up"}}

    monkeypatch.setattr("core.retrieval.auto.call_qwen_json", _fake_call)

    decision = route_retrieval(
        "Tell me more about that.",
        "session-1",
        strategy="hybrid",
        context=[{"role": "user", "content": "Discuss the PostgreSQL migration."}],
    )

    assert decision["mode"] == "quick"
    assert decision["reason"] == "contextual follow-up"


@pytest.mark.parametrize("strategy", ["fast", "hybrid", "accurate"])
def test_anaphoric_followup_inherits_general_topic(
    strategy: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A conversational pronoun must not trigger unrelated durable-memory retrieval."""

    def _no_call(*args: object, **kwargs: object) -> dict[str, object]:
        raise AssertionError("a clear general follow-up must not consult the LLM router")

    monkeypatch.setattr("core.retrieval.auto.call_qwen_json", _no_call)
    decision = route_retrieval(
        "That is mad, what was the purpose of that",
        "session-1",
        strategy=strategy,
        context=[
            {"role": "user", "content": "What is the Holocaust?"},
            {"role": "assistant", "content": "The Holocaust was a genocide."},
        ],
    )

    assert decision["mode"] == "general"
    assert decision["intent"] == "general_knowledge"
    assert decision["used_memory"] is False


def test_anaphoric_personal_followup_still_uses_memory() -> None:
    """Explicit personal ownership prevents general-topic inheritance."""
    decision = route_retrieval(
        "Was that in my notes?",
        "session-1",
        strategy="fast",
        context=[{"role": "user", "content": "What is the Holocaust?"}],
    )

    assert decision["mode"] != "general"
    assert decision["used_memory"] is True


def test_hybrid_keeps_borderline_personal_memory_route(monkeypatch: pytest.MonkeyPatch) -> None:
    """A borderline (0.7) personal-memory route is kept, not handed to the LLM classifier."""
    monkeypatch.setattr("core.retrieval.auto._llm_routing_available", lambda: True)

    def _no_call(*args: object, **kwargs: object) -> dict[str, object]:
        raise AssertionError("a >=0.65-confidence route must not consult the LLM router")

    monkeypatch.setattr("core.retrieval.auto.call_qwen_json", _no_call)

    # A memory cue -> deterministic quick at 0.7, which is now above the 0.65 escalation bar.
    decision = route_retrieval("What do I prefer?", None, strategy="hybrid")

    assert decision["mode"] == "quick"
    assert decision["intent"] == "personal_memory"


def test_hybrid_blocks_personal_to_general_downgrade(monkeypatch: pytest.MonkeyPatch) -> None:
    """When a personal-memory route does escalate, the LLM may not downgrade it to general."""
    from core.retrieval.auto import PERSONAL_MEMORY_INTENT, _decision

    monkeypatch.setattr("core.retrieval.auto._llm_routing_available", lambda: True)
    # Force a low-confidence personal-memory deterministic route so hybrid escalates.
    monkeypatch.setattr(
        "core.retrieval.auto._deterministic_route_retrieval",
        lambda query: _decision(
            "quick",
            "forced personal",
            0.5,
            intent=PERSONAL_MEMORY_INTENT,
            explicit_memory=True,
        ),
    )

    def _fake_call(messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
        return {"json": {"mode": "general", "reason": "no memory", "intent": "general_knowledge"}}

    monkeypatch.setattr("core.retrieval.auto.call_qwen_json", _fake_call)

    decision = route_retrieval("anything at all", None, strategy="hybrid")

    # The explicit-memory downgrade is rejected; the deterministic route is kept.
    assert decision["intent"] == "personal_memory"
    assert decision["mode"] == "quick"


def test_hybrid_keeps_confident_deterministic_route(monkeypatch: pytest.MonkeyPatch) -> None:
    """A confident deterministic route is used as-is; the LLM router is not consulted."""
    monkeypatch.setattr("core.retrieval.auto._llm_routing_available", lambda: True)

    def _no_call(*args: object, **kwargs: object) -> dict[str, object]:
        raise AssertionError("confident routes must not consult the LLM router")

    monkeypatch.setattr("core.retrieval.auto.call_qwen_json", _no_call)

    decision = route_retrieval(
        "I switched from MongoDB to PostgreSQL — what changed?", None, strategy="hybrid"
    )

    assert decision["mode"] == "relational"  # deterministic route, confidence 0.86
