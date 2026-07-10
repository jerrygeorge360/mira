"""Verify ISSUE-125 semantic slow-path orchestration.

Ownership: MIRA contributors.
Related issue: ISSUE-125.
Architecture area: slow path.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from core.db.repositories import (
    configure_database,
    create_atomic_fact,
    create_session,
    repository_connection,
    save_observation,
)
from core.memory import slow_path
from core.memory.graph import create_graph_node
from core.memory.reflection import store_reflection_with_evidence
from core.memory.slow_path import (
    SlowPathSemanticConfig,
    maybe_run_community_refresh,
    maybe_run_reflection_pass,
    run_slow_path_for_observation,
)
from core.retrieval.deep import retrieve_deep
from core.retrieval.quick import retrieve_quick


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    """Configure semantic slow-path tests to use an isolated database."""
    path = tmp_path / "mira.sqlite3"
    configure_database(path)
    yield path


def _count(table: str) -> int:
    with repository_connection() as connection:
        row = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()  # noqa: S608
    return int(row[0])


def _reflection_status(reflection_id: str) -> str:
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT status FROM reflections WHERE id = ?",
            (reflection_id,),
        ).fetchone()
    return str(row["status"])


def _stub_factual_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(slow_path, "extract_atomic_facts", lambda oid, content: [])
    monkeypatch.setattr(slow_path, "extract_entities", lambda text: [])


def test_foresight_runs_in_per_observation_slow_path(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Future-relevant observations create source-backed foresight records."""
    session_id = create_session("jerry")
    observation_id = save_observation(
        session_id,
        "user",
        "We need to run the official benchmark before the final demo.",
    )
    _stub_factual_steps(monkeypatch)
    monkeypatch.setattr(
        slow_path,
        "detect_foresight",
        lambda oid, content, ambient: [
            {
                "content": "Run official benchmark before the final demo.",
                "reason": "User stated this as a future task.",
                "status": "active",
                "source_observation_id": oid,
            }
        ],
    )

    result = run_slow_path_for_observation(observation_id)

    assert result["succeeded"] is True
    assert _count("foresight_records") == 1
    with repository_connection() as connection:
        row = connection.execute("SELECT * FROM foresight_records").fetchone()
    assert row["source_observation_id"] == observation_id
    assert row["content"] == "Run official benchmark before the final demo."


def test_foresight_is_idempotent(database_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Rerunning the foresight step does not duplicate the same source/content pair."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "Remember the demo deadline.")
    _stub_factual_steps(monkeypatch)
    monkeypatch.setattr(
        slow_path,
        "detect_foresight",
        lambda oid, content, ambient: [
            {
                "content": "Remember the demo deadline.",
                "status": "active",
                "source_observation_id": oid,
            }
        ],
    )

    first = slow_path.run_foresight_step_for_observation(observation_id)
    second = slow_path.run_foresight_step_for_observation(observation_id)

    assert first.created_record_ids
    assert second.created_record_ids == []
    assert _count("foresight_records") == 1


def test_reflection_is_gated_and_evidence_backed(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reflection waits for enough evidence, then stores evidence-backed memory."""
    session_id = create_session("jerry")
    monkeypatch.setattr(
        slow_path,
        "synthesize_reflections",
        lambda observation_ids: [
            {
                "reflection_type": "self_knowledge",
                "content": "The user cares about credible and cost-controlled evaluation.",
                "confidence": 0.9,
                "evidence_ids": observation_ids,
            }
        ],
    )
    config = SlowPathSemanticConfig(reflection_min_observations=2)

    # Reflection accumulates recent observations from the store, not a single batch:
    # one observation is below the gate; a second one crosses it.
    one = save_observation(session_id, "user", "Official benchmark support is important.")
    early = maybe_run_reflection_pass(config)
    two = save_observation(session_id, "user", "We need LLM-as-Judge and budget control.")
    created = maybe_run_reflection_pass(config)

    assert early[0].created_record_ids == []
    assert len(created[0].created_record_ids) == 1
    reflection_id = created[0].created_record_ids[0]
    with repository_connection() as connection:
        evidence_rows = connection.execute(
            "SELECT observation_id FROM reflection_evidence WHERE reflection_id = ?",
            (reflection_id,),
        ).fetchall()
    assert {str(row["observation_id"]) for row in evidence_rows} == {one, two}


def test_reflection_invalidation_marks_unsupported_reflection_stale(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Superseded supporting evidence invalidates an affected reflection."""
    _stub_factual_steps(monkeypatch)
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "The user wants prototype only.")
    reflection_id = store_reflection_with_evidence(
        {
            "reflection_type": "self_knowledge",
            "content": "The user prefers prototype-only evaluation.",
            "confidence": 0.9,
        },
        [observation_id],
    )
    create_atomic_fact(
        {
            "subject": "user",
            "predicate": "PREFERS",
            "object": "prototype-only evaluation",
            "confidence": 0.9,
            "status": "superseded",
            "source_observation_id": observation_id,
        }
    )

    run_slow_path_for_observation(
        observation_id,
        SlowPathSemanticConfig(enable_foresight=False, enable_reflection=False),
    )

    assert _reflection_status(reflection_id) == "invalidated"


def test_community_refresh_is_periodic_and_evidence_backed(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Community summaries run only after the configured observation threshold."""
    left = create_graph_node("entity", "MIRA benchmark")
    right = create_graph_node("entity", "LLM-as-Judge")
    monkeypatch.setattr(
        slow_path,
        "detect_graph_communities",
        lambda: [{"community_id": "community_eval", "member_node_ids": [left, right]}],
    )
    monkeypatch.setattr(
        slow_path,
        "summarize_community",
        lambda community_id, member_node_ids: {
            "community_id": community_id,
            "title": "MIRA evaluation work",
            "summary": "Benchmark work uses LLM-as-Judge and budget controls.",
            "member_node_ids": member_node_ids,
        },
    )
    config = SlowPathSemanticConfig(community_refresh_every_observations=2)

    # The trigger is a cumulative observation count derived from the store, so drive it
    # through the counter helper rather than a per-call batch size.
    monkeypatch.setattr(slow_path, "_observations_since_last_community_refresh", lambda: 1)
    skipped = maybe_run_community_refresh(config)
    monkeypatch.setattr(slow_path, "_observations_since_last_community_refresh", lambda: 2)
    created = maybe_run_community_refresh(config)
    duplicate = maybe_run_community_refresh(config)

    assert skipped[0].created_record_ids == []
    assert len(created[0].created_record_ids) == 1
    assert duplicate[0].created_record_ids == []
    assert _count("community_summaries") == 1


def test_semantic_steps_can_be_disabled(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Config switches prevent semantic records from being created."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "Remember the final demo deadline.")
    _stub_factual_steps(monkeypatch)
    monkeypatch.setattr(
        slow_path,
        "detect_foresight",
        lambda oid, content, ambient: [
            {"content": "Remember final demo deadline.", "source_observation_id": oid}
        ],
    )

    run_slow_path_for_observation(
        observation_id,
        SlowPathSemanticConfig(
            enable_foresight=False,
            enable_reflection=False,
            enable_reflection_invalidation=False,
            enable_community_summaries=False,
        ),
    )

    assert _count("foresight_records") == 0
    assert _count("reflections") == 0


def test_retrieval_can_use_semantic_records(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Foresight, reflections, and community summaries are reachable by retrieval."""
    session_id = create_session("jerry")
    observation_id = save_observation(
        session_id, "user", "We need to run the official benchmark before the demo."
    )
    _stub_factual_steps(monkeypatch)
    monkeypatch.setattr(
        slow_path,
        "detect_foresight",
        lambda oid, content, ambient: [
            {
                "content": "Run official benchmark before the demo.",
                "status": "active",
                "source_observation_id": oid,
            }
        ],
    )
    run_slow_path_for_observation(observation_id)
    store_reflection_with_evidence(
        {
            "reflection_type": "self_knowledge",
            "content": "The user cares about official benchmark credibility.",
            "confidence": 0.8,
        },
        [observation_id],
    )
    left = create_graph_node("entity", "official benchmark")
    right = create_graph_node("entity", "demo readiness")
    monkeypatch.setattr(
        slow_path,
        "detect_graph_communities",
        lambda: [{"community_id": "community_demo", "member_node_ids": [left, right]}],
    )
    monkeypatch.setattr(
        slow_path,
        "summarize_community",
        lambda community_id, member_node_ids: {
            "community_id": community_id,
            "title": "Official benchmark demo readiness",
            "summary": "The demo work centers on official benchmark credibility.",
            "member_node_ids": member_node_ids,
        },
    )
    maybe_run_community_refresh(
        SlowPathSemanticConfig(community_refresh_every_observations=1),
    )

    quick = retrieve_quick("What future benchmark task should I remember?", session_id, 5)
    deep = retrieve_deep("Summarize official benchmark demo work", session_id, 5)

    assert any(result["source"] == "foresight_records" for result in quick)
    assert any(result["source"] == "reflection" for result in deep)
    assert any(result["source"] == "community_summary" for result in deep)
