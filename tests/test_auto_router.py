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
