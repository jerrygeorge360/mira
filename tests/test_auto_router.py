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
        "Why did Desdemona trick him?",
        "So what did Iago gain?",
        "What made Iago seek revenge?",
    ],
)
def test_public_causal_questions_do_not_use_personal_memory(query: str) -> None:
    """Causal language alone cannot turn public knowledge into graph retrieval."""
    decision = route_retrieval(query, None, strategy="fast")

    assert decision["context_scope"] == "general_knowledge"
    assert decision["mode"] == "general"
    assert decision["retrieval_required"] is False


def test_did_iago_does_not_match_first_person_memory_cue() -> None:
    decision = route_retrieval("So what did Iago gain?", None, strategy="fast")

    assert decision["explicit_memory_cue"] is False
    assert decision["intent"] == "general_knowledge"


@pytest.mark.parametrize(
    "query",
    [
        "revenge? why",
        "lost handkerchief?",
        "so that is the poem?",
    ],
)
def test_elliptical_followups_use_recent_conversation(query: str) -> None:
    context = [
        {"role": "user", "content": "Tell me about Othello."},
        {"role": "assistant", "content": "Othello was manipulated by Iago."},
    ]

    decision = route_retrieval(query, "session-1", strategy="fast", context=context)

    assert decision["context_scope"] == "recent_conversation"
    assert decision["mode"] == "general"
    assert decision["retrieval_required"] is False


def test_casual_reaction_does_not_replay_recent_factual_context() -> None:
    decision = route_retrieval(
        "that is unfortunate",
        "session-1",
        strategy="fast",
        turn_purpose="casual_message",
        context=[
            {"role": "assistant", "content": "The handkerchief was planted by Iago."},
        ],
    )

    assert decision["context_scope"] == "no_retrieval"
    assert decision["retrieval_mode"] is None
    assert decision["mode"] == "general"
    assert decision["retrieval_required"] is False
    assert decision["needs_sufficiency_check"] is False


def test_standalone_greeting_does_not_pull_conversation_context() -> None:
    decision = route_retrieval(
        "hello",
        "session-1",
        strategy="fast",
        turn_purpose="casual_message",
        context=[{"role": "assistant", "content": "A previous answer."}],
    )

    assert decision["context_scope"] == "no_retrieval"
    assert decision["retrieval_required"] is False


def test_standalone_closing_does_not_repeat_recent_answer() -> None:
    decision = route_retrieval(
        "appreciate it",
        "session-1",
        strategy="fast",
        turn_purpose="casual_message",
        context=[{"role": "assistant", "content": "The interview moved."}],
    )

    assert decision["context_scope"] == "no_retrieval"
    assert decision["retrieval_required"] is False


def test_quick_question_prefix_does_not_turn_general_knowledge_into_a_followup() -> None:
    decision = route_retrieval(
        "quick question, what is a message queue?",
        "session-1",
        strategy="fast",
        turn_purpose="question",
        context=[{"role": "assistant", "content": "Your agenda is empty."}],
    )

    assert decision["context_scope"] == "general_knowledge"
    assert decision["retrieval_required"] is False


@pytest.mark.parametrize(
    "query",
    [
        "What is on the agenda today?",
        "What is on my schedule today?",
        "What database am I using again?",
    ],
)
def test_personal_agenda_and_usage_queries_use_durable_memory(query: str) -> None:
    decision = route_retrieval(
        query,
        "session-1",
        strategy="fast",
        turn_purpose="question",
        context=[{"role": "assistant", "content": "A previous answer."}],
    )

    assert decision["context_scope"] == "durable_memory"
    assert decision["retrieval_required"] is True
    assert decision["mode"] == "quick"


def test_recent_reminder_stays_in_bounded_conversation_context() -> None:
    decision = route_retrieval(
        "remind me what I just told yo",
        "session-1",
        strategy="fast",
        turn_purpose="question",
        context=[{"role": "user", "content": "I have an interview next Tuesday."}],
    )

    assert decision["context_scope"] == "recent_conversation"
    assert decision["retrieval_required"] is False


def test_recent_user_fact_wins_before_durable_retrieval() -> None:
    decision = route_retrieval(
        "What's my container memory limit?",
        "session-1",
        strategy="accurate",
        turn_purpose="question",
        context=[
            {
                "id": "obs-limit",
                "role": "user",
                "content": "I set the memory limit per container to 512MB.",
            },
            {"id": "obs-ack", "role": "assistant", "content": "Noted."},
        ],
    )

    assert decision["context_scope"] == "recent_conversation"
    assert decision["retrieval_required"] is False
    assert decision["scope_confidence"] == 0.94


def test_dns_only_recent_context_cannot_satisfy_compound_hosting_question() -> None:
    decision = route_retrieval(
        "Where is my frontend hosted, and who manages my DNS?",
        "session-1",
        strategy="fast",
        turn_purpose="question",
        context=[
            {
                "id": "dns",
                "role": "user",
                "content": "I switched my DNS provider to Cloudflare.",
            }
        ],
    )

    assert decision["context_scope"] != "recent_conversation"
    assert decision["retrieval_required"] is True


def test_semantic_recent_evidence_can_avoid_unnecessary_durable_retrieval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("core.retrieval.auto._llm_routing_available", lambda: True)
    monkeypatch.setattr(
        "core.retrieval.auto.check_grounded_sufficiency",
        lambda _query, _evidence: {
            "is_sufficient": True,
            "evidence_ids": ["platform"],
            "reason": "The recent statement directly identifies the platform.",
        },
    )

    decision = route_retrieval(
        "Which orchestration platform am I using?",
        "session-1",
        strategy="hybrid",
        turn_purpose="question",
        context=[
            {
                "id": "platform",
                "role": "user",
                "content": "I deployed the app with Kubernetes.",
            }
        ],
    )

    assert decision["context_scope"] == "recent_conversation"
    assert decision["scope_source"] == "semantic_grounding"
    assert decision["retrieval_required"] is False


def test_conversation_addressed_question_can_use_llm_scope_classifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("core.retrieval.auto._llm_routing_available", lambda: True)

    def classify(_messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
        assert schema_name == "context_scope_classification"
        return {
            "json": {
                "context_scope": "recent_conversation",
                "confidence": 0.96,
                "reason": "The question asks about the immediately preceding operation.",
            }
        }

    monkeypatch.setattr("core.retrieval.auto.call_qwen_json", classify)
    decision = route_retrieval(
        "What was the instruction you carried out?",
        "session-1",
        strategy="hybrid",
        turn_purpose="question",
        context=[
            {
                "id": "operation",
                "role": "user",
                "content": (
                    "Please reverse that action.\n"
                    "[Resolved memory operation target: a prior casual statement]"
                ),
            }
        ],
    )

    assert decision["context_scope"] == "recent_conversation"
    assert decision["scope_source"] == "llm"
    assert decision["retrieval_required"] is False


def test_strong_general_definition_is_not_downgraded_by_accurate_router() -> None:
    decision = route_retrieval(
        "What does idempotent mean?",
        "session-1",
        strategy="accurate",
        turn_purpose="question",
        context=[{"role": "user", "content": "Hello."}],
    )

    assert decision["context_scope"] == "general_knowledge"
    assert decision["retrieval_required"] is False


def test_personal_lookup_with_general_advice_uses_mixed_context() -> None:
    decision = route_retrieval(
        "What database do I use, and should I look into read replicas for it?",
        "session-1",
        strategy="fast",
    )

    assert decision["context_scope"] == "mixed"
    assert decision["retrieval_required"] is True


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
        assert schema_name == "context_scope_classification"
        assert "What is an apple?" in messages[0]["content"]
        return {
            "json": {
                "context_scope": "general_knowledge",
                "confidence": 0.96,
                "reason": "definition question",
            }
        }

    monkeypatch.setattr("core.retrieval.auto.call_qwen_json", _fake_call)

    decision = route_retrieval("What is an apple?", None, strategy="accurate")

    assert decision["mode"] == "general"
    assert decision["reason"] == "definition question"


def test_llm_router_reports_scope_and_confidence(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_call(messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
        return {
            "json": {
                "context_scope": "durable_memory",
                "mode": "quick",
                "confidence": 0.83,
                "reason": "The answer depends on a stored preference.",
            }
        }

    monkeypatch.setattr("core.retrieval.auto.call_qwen_json", _fake_call)
    decision = route_retrieval("What do I prefer?", None, strategy="accurate")

    assert decision["context_scope"] == "durable_memory"
    assert decision["confidence"] == 0.83
    assert decision["mode"] == "quick"
    assert decision["needs_sufficiency_check"] is False


def test_low_confidence_llm_route_keeps_sufficiency_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_call(messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
        return {
            "json": {
                "context_scope": "mixed",
                "mode": "quick",
                "confidence": 0.7,
                "reason": "The scope is still somewhat ambiguous.",
            }
        }

    monkeypatch.setattr("core.retrieval.auto.call_qwen_json", _fake_call)
    decision = route_retrieval("What should I do next?", None, strategy="accurate")

    assert decision["mode"] == "quick"
    assert decision["needs_sufficiency_check"] is True


def test_scope_guard_blocks_general_question_from_relational_retrieval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A model cannot turn a clear public question into a personal graph traversal."""

    def _fake_call(messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
        return {
            "json": {
                "context_scope": "durable_memory",
                "mode": "relational",
                "confidence": 0.99,
                "reason": "The question asks about purpose.",
            }
        }

    monkeypatch.setattr("core.retrieval.auto.call_qwen_json", _fake_call)
    decision = route_retrieval("What was the purpose of the Holocaust?", None, strategy="accurate")

    assert decision["context_scope"] == "general_knowledge"
    assert decision["mode"] == "general"
    assert decision["used_memory"] is False


def test_recent_scope_normalizes_incompatible_relational_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_call(messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
        return {
            "json": {
                "context_scope": "recent_conversation",
                "mode": "relational",
                "confidence": 0.76,
                "reason": "The pronoun refers to the current discussion.",
            }
        }

    monkeypatch.setattr("core.retrieval.auto.call_qwen_json", _fake_call)
    decision = route_retrieval("Explain that further", None, strategy="accurate")

    assert decision["context_scope"] == "recent_conversation"
    assert decision["mode"] == "general"
    assert decision["used_memory"] is False


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


def test_hybrid_keeps_clear_recent_followup_out_of_llm_router(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("core.retrieval.auto._llm_routing_available", lambda: True)

    def _no_call(*args: object, **kwargs: object) -> dict[str, object]:
        raise AssertionError("clear recent follow-up must not call a routing model")

    monkeypatch.setattr("core.retrieval.auto.call_qwen_json", _no_call)

    decision = route_retrieval(
        "Tell me more about that.",
        "session-1",
        strategy="hybrid",
        context=[{"role": "user", "content": "Discuss the PostgreSQL migration."}],
    )

    assert decision["mode"] == "general"
    assert decision["context_scope"] == "recent_conversation"
    assert decision["retrieval_required"] is False


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

    monkeypatch.setattr("core.retrieval.auto._llm_routing_available", lambda: True)
    monkeypatch.setattr(
        "core.retrieval.auto._deterministic_context_scope",
        lambda *_args: {
            "context_scope": "durable_memory",
            "reason": "forced personal",
            "confidence": 0.5,
            "source": "deterministic",
            "explicit_memory_cue": True,
        },
    )

    def _fake_call(messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
        if schema_name == "retrieval_mode_classification":
            return {
                "json": {
                    "mode": "quick",
                    "confidence": 0.9,
                    "reason": "direct fact lookup",
                }
            }
        assert schema_name == "context_scope_classification"
        return {
            "json": {
                "context_scope": "general_knowledge",
                "confidence": 0.99,
                "reason": "no memory",
            }
        }

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
