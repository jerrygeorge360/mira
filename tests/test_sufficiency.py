"""Verify ISSUE-038 structured retrieval sufficiency check.

Ownership: MIRA contributors.
Related issue: ISSUE-038.
Architecture area: retrieval.
"""

from __future__ import annotations

import pytest

from core.retrieval import sufficiency
from core.retrieval.sufficiency import (
    check_grounded_sufficiency,
    check_retrieval_sufficiency,
    check_sufficiency,
    resolve_with_one_retry,
)


def _ctx(content: str) -> dict[str, object]:
    return {"content": content}


def test_sufficient_context_returns_true() -> None:
    """Context that covers the query's salient terms is sufficient."""
    result = check_retrieval_sufficiency(
        "What did I decide about Postgres?",
        [_ctx("We decided to use Postgres for durable storage.")],
    )

    assert result["is_sufficient"] is True
    assert result["missing"] == []
    assert result["rewrite_query"] is None


def test_missing_entity_returns_rewrite_query() -> None:
    """A query entity absent from context is reported missing with a rewrite."""
    result = check_retrieval_sufficiency(
        "What did I decide about Kubernetes?",
        [_ctx("We decided to use Postgres for durable storage.")],
    )

    assert result["is_sufficient"] is False
    assert "kubernetes" in result["missing"]
    assert isinstance(result["rewrite_query"], str)
    assert "kubernetes" in str(result["rewrite_query"]).lower()


def test_empty_context_is_insufficient() -> None:
    """No retrieved context is never sufficient."""
    result = check_retrieval_sufficiency("Anything about Kubernetes?", [])
    assert result["is_sufficient"] is False


def test_one_retry_only() -> None:
    """An always-insufficient retrieval retries exactly once, then answers uncertain."""
    calls: list[str] = []

    def retrieve(query: str) -> list[dict[str, object]]:
        calls.append(query)
        return []  # never satisfies the query

    outcome = resolve_with_one_retry("Plan for the Kubernetes migration?", retrieve)

    assert len(calls) == 2  # initial + exactly one retry
    assert outcome["retries"] == 1
    assert outcome["answered_with_uncertainty"] is True


def test_retry_can_resolve_sufficiency() -> None:
    """A successful retry yields sufficient context without uncertainty."""
    calls: list[str] = []

    def retrieve(query: str) -> list[dict[str, object]]:
        calls.append(query)
        if len(calls) == 1:
            return []
        return [_ctx("Kubernetes migration runbook and rollout plan.")]

    outcome = resolve_with_one_retry("What is the Kubernetes migration plan?", retrieve)

    assert len(calls) == 2
    assert outcome["retries"] == 1
    assert outcome["answered_with_uncertainty"] is False
    assert outcome["sufficiency"]["is_sufficient"] is True


def test_no_retry_when_first_pass_sufficient() -> None:
    """A sufficient first pass performs no retry."""
    calls: list[str] = []

    def retrieve(query: str) -> list[dict[str, object]]:
        calls.append(query)
        return [_ctx("The Postgres backup schedule runs nightly.")]

    outcome = resolve_with_one_retry("When is the Postgres backup?", retrieve)

    assert len(calls) == 1
    assert outcome["retries"] == 0
    assert outcome["answered_with_uncertainty"] is False


def test_check_sufficiency_alias() -> None:
    """The legacy alias matches the primary entry point."""
    context = [_ctx("We decided to use Postgres.")]
    assert check_sufficiency("Postgres decision?", context) == check_retrieval_sufficiency(
        "Postgres decision?", context
    )


def test_cache_evidence_does_not_satisfy_database_requirement() -> None:
    result = check_retrieval_sufficiency(
        "What database do I use?",
        [
            {
                "source": "atomic_facts",
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

    assert result["is_sufficient"] is False
    assert "database" in result["missing"]


def test_attribute_evidence_must_match_the_requested_property_anchor() -> None:
    result = check_retrieval_sufficiency(
        "Where is my frontend hosted?",
        [
            {
                "id": "dns",
                "content": "I switched my DNS provider to Cloudflare.",
            }
        ],
    )

    assert result["is_sufficient"] is False
    assert {"frontend", "hosted"} & set(result["missing"])


def test_transition_evidence_does_not_satisfy_causal_requirement() -> None:
    result = check_retrieval_sufficiency(
        "Why did I make that switch?",
        [
            {
                "source": "graph_edge",
                "source_id": "transition",
                "relation": "SUPERSEDED_BY",
                "content": "Redis SUPERSEDED_BY Memcached",
            }
        ],
    )

    assert result["is_sufficient"] is False
    assert result["missing"]


def test_explicit_problem_evidence_can_satisfy_causal_requirement() -> None:
    result = check_retrieval_sufficiency(
        "Why did I switch away from Redis?",
        [
            {
                "source": "atomic_facts",
                "source_id": "reason",
                "content": "Redis was giving the user trouble.",
                "record": {
                    "subject": "Redis",
                    "predicate": "caused trouble",
                    "object": "user",
                },
            }
        ],
    )

    assert result["is_sufficient"] is True


def test_semantic_grounding_rejects_plausible_but_unstated_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def judge(_messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
        assert schema_name == "sufficiency_check"
        return {
            "json": {
                "sufficient": False,
                "missing": ["the user's reason for choosing three replicas"],
                "evidence_ids": [],
                "reason": "The evidence states the replica count but gives no reason.",
            }
        }

    monkeypatch.setattr(sufficiency, "call_qwen_json", judge)
    result = check_grounded_sufficiency(
        "Why did I choose 3 replicas?",
        [{"id": "replicas", "content": "I set the replica count to 3."}],
    )

    assert result["is_sufficient"] is False
    assert result["assessment_source"] == "semantic_grounding"
    assert "reason" in str(result["missing"])


def test_semantic_grounding_matches_meaning_across_different_vocabulary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def judge(messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
        assert schema_name == "sufficiency_check"
        prompt = messages[0]["content"]
        assert "Kubernetes" in prompt
        assert "liveness probe every 15 seconds" in prompt
        return {
            "json": {
                "sufficient": True,
                "missing": [],
                "evidence_ids": ["platform", "probe"],
                "reason": "Both requested configuration facts are explicitly recorded.",
            }
        }

    monkeypatch.setattr(sufficiency, "call_qwen_json", judge)
    result = check_grounded_sufficiency(
        "What am I using for orchestration, and is the liveness probe configured?",
        [
            {"id": "platform", "content": "I deployed my app using Kubernetes."},
            {"id": "probe", "content": "I configured a liveness probe every 15 seconds."},
        ],
    )

    assert result["is_sufficient"] is True
    assert result["evidence_ids"] == ["platform", "probe"]


def test_semantic_grounding_verifies_every_part_of_compound_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def judge(_messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
        assert schema_name == "sufficiency_check"
        return {
            "json": {
                "sufficient": False,
                "missing": ["frontend hosting provider"],
                "evidence_ids": ["dns"],
                "reason": "The evidence supports DNS management but not frontend hosting.",
            }
        }

    monkeypatch.setattr(sufficiency, "call_qwen_json", judge)
    result = check_grounded_sufficiency(
        "Where is my frontend hosted, and who manages my DNS?",
        [
            {
                "id": "dns",
                "content": "Cloudflare manages my DNS and hosts DNS records.",
            }
        ],
    )

    assert result["is_sufficient"] is False
    assert result["assessment_source"] == "semantic_grounding"
    assert result["evidence_ids"] == ["dns"]


def test_semantic_grounding_rejects_out_of_set_evidence_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sufficiency,
        "call_qwen_json",
        lambda *_args, **_kwargs: {
            "json": {
                "sufficient": True,
                "missing": [],
                "evidence_ids": ["invented"],
                "reason": "Unsupported citation.",
            }
        },
    )

    result = check_grounded_sufficiency(
        "What am I using for orchestration?",
        [{"id": "platform", "content": "I deployed my app using Kubernetes."}],
    )

    assert result["is_sufficient"] is False
