"""Verify ISSUE-038 structured retrieval sufficiency check.

Ownership: MIRA contributors.
Related issue: ISSUE-038.
Architecture area: retrieval.
"""

from __future__ import annotations

from core.retrieval.sufficiency import (
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
