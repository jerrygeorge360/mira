"""Deterministic tests for retrieval trust and answer verification."""

from __future__ import annotations

from datetime import UTC, datetime

from core.retrieval.trust import (
    AUTHORITY_DIRECT_USER,
    AUTHORITY_EXTERNAL_UNVERIFIED,
    AUTHORITY_MODEL_GENERATED,
    AUTHORITY_PROVISIONAL_SESSION,
    FRESHNESS_CURRENT,
    FRESHNESS_EXPIRED,
    FRESHNESS_FUTURE,
    FRESHNESS_STALE,
    RUNTIME_CONDITIONAL,
    RUNTIME_INELIGIBLE,
    RUNTIME_TRUSTED,
    RUNTIME_UNTRUSTED,
    VERDICT_INSUFFICIENT,
    VERDICT_UNCERTAIN,
    VERDICT_VERIFIED,
    annotate_evidence,
    assess_freshness,
    assess_provenance_completeness,
    assess_runtime_trust,
    assess_source_authority,
    assess_stability,
    is_prompt_eligible,
    verify_before_answer,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)
NOW_TEXT = "2026-01-01T00:00:00Z"


def user_observation(**overrides: object) -> dict[str, object]:
    evidence: dict[str, object] = {
        "source": "observations",
        "source_id": "obs-1",
        "content": "My preferred editor is Vim",
        "role": "user",
        "workspace_id": "workspace-1",
        "score": 0.01,
        "record": {"id": "obs-1", "role": "user", "workspace_id": "workspace-1"},
    }
    evidence.update(overrides)
    return evidence


def atomic_fact(**overrides: object) -> dict[str, object]:
    evidence: dict[str, object] = {
        "source": "atomic_facts",
        "source_id": "fact-1",
        "content": "Jerry prefers Vim",
        "confidence": 0.95,
        "status": "active",
        "workspace_id": "workspace-1",
        "source_observation_id": "obs-1",
        "record": {
            "id": "fact-1",
            "workspace_id": "workspace-1",
            "source_observation_id": "obs-1",
        },
    }
    evidence.update(overrides)
    return evidence


def test_direct_user_authority_and_relevance_are_separate() -> None:
    evidence = user_observation()

    assert assess_source_authority(evidence) == AUTHORITY_DIRECT_USER
    assessment = assess_runtime_trust(evidence, now=NOW, expected_workspace_id="workspace-1")
    assert assessment["runtime_trust"] == RUNTIME_TRUSTED
    assert assessment["prompt_eligible"] is True
    assert assessment["relevance_score"] == 0.01
    assert assessment["provenance"]["complete"] is True
    assert assessment["provenance"]["workspace_match"] is True

    annotated = annotate_evidence(evidence, now=NOW, expected_workspace_id="workspace-1")
    assert annotated["score"] == 0.01
    assert annotated["trust"] == assessment
    assert evidence["score"] == 0.01


def test_derived_fact_requires_source_observation_lineage() -> None:
    trusted = assess_runtime_trust(atomic_fact(), now=NOW, expected_workspace_id="workspace-1")
    assert trusted["runtime_trust"] == RUNTIME_TRUSTED
    assert trusted["source_authority_class"] == "derived_validated"
    assert trusted["stability_class"] == "durable_derived"

    incomplete = atomic_fact(
        source_observation_id=None,
        record={"id": "fact-1", "workspace_id": "workspace-1", "source_observation_id": None},
    )
    assessment = assess_runtime_trust(incomplete, now=NOW, expected_workspace_id="workspace-1")
    assert assessment["runtime_trust"] == RUNTIME_CONDITIONAL
    assert assessment["prompt_eligible"] is False
    assert "source_observation_id" in assessment["provenance"]["missing"]


def test_model_and_external_evidence_do_not_become_prompt_eligible() -> None:
    assistant = user_observation(role="assistant")
    tool = user_observation(
        source="structured_tool",
        role="tool",
        source_id="tool-1",
        record={"id": "tool-1", "workspace_id": "workspace-1"},
    )

    assert assess_source_authority(assistant) == AUTHORITY_MODEL_GENERATED
    assert assess_runtime_trust(assistant)["runtime_trust"] == RUNTIME_UNTRUSTED
    assert is_prompt_eligible(assistant) is False

    assert assess_source_authority(tool) == AUTHORITY_EXTERNAL_UNVERIFIED
    assert assess_runtime_trust(tool)["runtime_trust"] == RUNTIME_UNTRUSTED
    assert is_prompt_eligible(tool) is False


def test_provisional_session_is_conditional_and_opt_in_only() -> None:
    evidence = {
        "source": "session_working_set",
        "source_id": "sws-1",
        "content": "The user is considering Vim",
        "explicitness_label": "provisional",
        "source_observations": ["obs-1"],
        "workspace_id": "workspace-1",
    }

    assert assess_source_authority(evidence) == AUTHORITY_PROVISIONAL_SESSION
    assessment = assess_runtime_trust(evidence, expected_workspace_id="workspace-1")
    assert assessment["runtime_trust"] == RUNTIME_CONDITIONAL
    assert assessment["prompt_eligible"] is False
    assert is_prompt_eligible(evidence) is False
    assert is_prompt_eligible(evidence, allow_conditional=True) is True


def test_freshness_is_deterministic_and_supports_windows_and_max_age() -> None:
    current = atomic_fact(
        valid_from="2025-12-01T00:00:00Z",
        valid_until="2026-02-01T00:00:00Z",
    )
    future = atomic_fact(valid_from="2026-02-02T00:00:00Z")
    expired = atomic_fact(expires_at="2025-12-31T23:59:59Z")
    old = atomic_fact(created_at="2025-12-01T00:00:00Z")

    assert assess_freshness(current, now=NOW)["freshness"] == FRESHNESS_CURRENT
    assert assess_freshness(future, now=NOW)["freshness"] == FRESHNESS_FUTURE
    assert assess_freshness(expired, now=NOW)["freshness"] == FRESHNESS_EXPIRED
    assert assess_freshness(old, now=NOW, max_age_seconds=3600)["freshness"] == FRESHNESS_STALE
    assert assess_freshness(atomic_fact(), now=NOW)["freshness"] == "unspecified"


def test_invalid_reflection_and_workspace_mismatch_are_ineligible() -> None:
    reflection = {
        "source": "reflection",
        "source_id": "reflection-1",
        "content": "The user prefers concise tooling",
        "status": "stale",
        "evidence_ids": ["obs-1"],
        "workspace_id": "workspace-1",
    }
    mismatched = user_observation(workspace_id="workspace-2")

    stale = assess_runtime_trust(reflection, now=NOW)
    assert stale["runtime_trust"] == RUNTIME_INELIGIBLE
    assert stale["freshness"]["freshness"] == "invalid"
    assert (
        assess_runtime_trust(mismatched, expected_workspace_id="workspace-1")["runtime_trust"]
        == RUNTIME_INELIGIBLE
    )


def test_graph_and_community_lineage_is_checked() -> None:
    graph = {
        "source": "graph_edge",
        "source_id": "edge-1",
        "content": "Jerry uses Vim",
        "status": "active",
        "workspace_id": "workspace-1",
        "origin_node_id": "node-1",
        "related_node_id": "node-2",
        "source_observations": ["obs-1"],
    }
    community = {
        "source": "community_summary",
        "source_id": "community-1",
        "content": "Editor preferences",
        "workspace_id": "workspace-1",
        "member_node_ids": ["node-1", "node-2"],
    }

    assert assess_provenance_completeness(graph)["complete"] is True
    assert assess_runtime_trust(graph)["runtime_trust"] == RUNTIME_TRUSTED
    assert assess_provenance_completeness(community)["complete"] is True
    assert assess_stability(community) == "durable_derived"


def test_verify_before_answer_requires_trusted_covered_context() -> None:
    evidence = user_observation(score=0.0)
    result = verify_before_answer(
        "What is my preferred editor?",
        [evidence],
        now=NOW,
        expected_workspace_id="workspace-1",
    )

    assert result["verdict"] == VERDICT_VERIFIED
    assert result["uncertain"] is False
    assert result["prompt_eligible"] is True
    assert result["eligible_count"] == 1
    assert evidence["score"] == 0.0


def test_verify_before_answer_separates_insufficient_and_uncertain() -> None:
    empty = verify_before_answer("What is my preferred editor?", [], now=NOW)
    assert empty["verdict"] == VERDICT_INSUFFICIENT
    assert empty["uncertain"] is True

    uncovered = verify_before_answer(
        "What is my preferred editor?",
        [user_observation(content="I like writing")],
        now=NOW,
    )
    assert uncovered["verdict"] == VERDICT_UNCERTAIN
    assert uncovered["prompt_eligible"] is False
    assert "editor" in uncovered["missing"]

    conditional = verify_before_answer(
        "What is my preferred editor?",
        [
            {
                "source": "session_working_set",
                "source_id": "sws-1",
                "content": "My preferred editor is Vim",
                "explicitness_label": "provisional",
                "source_observations": ["obs-1"],
            }
        ],
        now=NOW,
    )
    assert conditional["verdict"] == VERDICT_INSUFFICIENT
    assert conditional["eligible_count"] == 0

    conditional_allowed = verify_before_answer(
        "What is my preferred editor?",
        [
            {
                "source": "session_working_set",
                "source_id": "sws-1",
                "content": "My preferred editor is Vim",
                "explicitness_label": "provisional",
                "source_observations": ["obs-1"],
            }
        ],
        now=NOW,
        allow_conditional=True,
    )
    assert conditional_allowed["verdict"] == VERDICT_UNCERTAIN
    assert conditional_allowed["uncertain"] is True


def test_malformed_lineage_json_is_incomplete_not_an_exception() -> None:
    evidence = {
        "source": "graph_edge",
        "source_id": "edge-1",
        "content": "Jerry uses Vim",
        "origin_node_id": "node-1",
        "related_node_id": "node-2",
        "source_observations_json": "not-json",
    }

    provenance = assess_provenance_completeness(evidence)
    assert provenance["complete"] is False
    assert "source_observations" in provenance["missing"]
