"""Tests for MIRA API memory read routes."""

from __future__ import annotations

from typing import Any

from api.auth import AuthenticatedWorkspace
from api.routes.memory import (
    get_community_summaries,
    get_foresight,
    get_memory_graph,
    get_memory_health,
    get_memory_lifecycle,
    get_reflections,
)
from core.db.repositories import (
    WorkspaceContext,
    configure_database,
    create_atomic_fact,
    create_community_summary,
    create_foresight_record,
    create_reflection,
    create_session,
    create_session_item,
    create_working_memory_item,
    enqueue_observation,
    mark_slow_path_step_completed,
    mark_slow_path_step_started,
    repository_connection,
    save_observation,
)
from core.db.schema import LEGACY_WORKSPACE_ID
from core.memory.graph import create_graph_edge, create_graph_node
from core.memory.read_models import get_memory_graph_read_model

AUTH = AuthenticatedWorkspace(WorkspaceContext(LEGACY_WORKSPACE_ID, auth_mode="development"))


def test_memory_graph_endpoint_returns_shape(tmp_path: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv("MIRA_DB_PATH", str(tmp_path / "api-memory.sqlite3"))

    response = get_memory_graph(AUTH, limit=100)

    assert response.nodes == []
    assert response.edges == []


def test_memory_graph_read_model_includes_missing_edge_endpoints(
    tmp_path: Any, monkeypatch: Any
) -> None:
    """Change/conflict edges stay visible even when one endpoint falls outside the node limit."""
    monkeypatch.setenv("MIRA_DB_PATH", str(tmp_path / "api-memory-edge-endpoints.sqlite3"))
    session_id = create_session("user_1", workspace_id=LEGACY_WORKSPACE_ID)
    observation_id = save_observation(session_id, "user", "I switched from MongoDB to PostgreSQL.")
    old_node_id = create_graph_node(
        node_type="atomic_fact",
        label="Jerry uses MongoDB",
        source_table="atomic_facts",
        source_id="fact_old",
    )
    new_node_id = create_graph_node(
        node_type="atomic_fact",
        label="Jerry uses PostgreSQL",
        source_table="atomic_facts",
        source_id="fact_new",
    )
    edge_id = create_graph_edge(
        old_node_id,
        new_node_id,
        "SUPERSEDED_BY",
        0.9,
        [observation_id],
    )

    graph = get_memory_graph_read_model(limit=1, workspace_id=LEGACY_WORKSPACE_ID)

    assert [edge["id"] for edge in graph["edges"]] == [edge_id]
    assert {node["id"] for node in graph["nodes"]} >= {old_node_id, new_node_id}


def test_memory_surface_endpoints_return_items_shape(tmp_path: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv("MIRA_DB_PATH", str(tmp_path / "api-memory-surfaces.sqlite3"))

    assert get_foresight(AUTH, limit=50).items == []
    assert get_reflections(AUTH, limit=50).items == []
    assert get_community_summaries(AUTH, limit=50).items == []


def test_community_summaries_expose_overlap_review_metadata(
    tmp_path: Any, monkeypatch: Any
) -> None:
    monkeypatch.setenv("MIRA_DB_PATH", str(tmp_path / "api-community-overlap.sqlite3"))
    node_a = create_graph_node(node_type="entity", label="Democracy")
    node_b = create_graph_node(node_type="entity", label="Voting")
    node_c = create_graph_node(node_type="entity", label="Representation")
    node_d = create_graph_node(node_type="entity", label="Exam")
    create_community_summary(
        {
            "community_id": "community_democracy_a",
            "title": "Democracy Principles",
            "summary": "Democracy study memories.",
            "member_nodes_json": [node_a, node_b, node_c],
        }
    )
    create_community_summary(
        {
            "community_id": "community_democracy_b",
            "title": "Democracy Principles",
            "summary": "Overlapping democracy memories.",
            "member_nodes_json": [node_a, node_b, node_d],
        }
    )

    response = get_community_summaries(AUTH, limit=50)

    assert len(response.items) == 2
    first = response.items[0]
    assert first["member_count"] == 3
    assert first["merge_recommendation"] == "review_possible_duplicate"
    assert first["overlapping_communities"]


def test_memory_lifecycle_endpoint_links_pipeline_artifacts(
    tmp_path: Any, monkeypatch: Any
) -> None:
    db_path = tmp_path / "api-memory-lifecycle.sqlite3"
    monkeypatch.setenv("MIRA_DB_PATH", str(db_path))
    configure_database(db_path)
    session_id = create_session("user_1", workspace_id=LEGACY_WORKSPACE_ID)
    observation_id = save_observation(session_id, "user", "Use 2026 for all project dates.")
    enqueue_observation(observation_id)
    create_session_item(
        {
            "session_id": session_id,
            "type": "correction",
            "content": "Use 2026 for all project dates.",
            "scope": "project",
            "status": "confirmed",
            "priority": 0.9,
            "explicitness_label": "direct_correction",
            "source_observations_json": [observation_id],
        }
    )
    create_atomic_fact(
        {
            "subject": "project dates",
            "predicate": "year",
            "object": "2026",
            "confidence": 0.92,
            "source_observation_id": observation_id,
        }
    )
    create_foresight_record(
        {
            "content": "Project dates should use 2026.",
            "status": "active",
            "source_observation_id": observation_id,
        }
    )
    mark_slow_path_step_started(LEGACY_WORKSPACE_ID, observation_id, "atomic_fact_extraction")
    mark_slow_path_step_completed(LEGACY_WORKSPACE_ID, observation_id, "atomic_fact_extraction")
    with repository_connection() as connection:
        connection.execute(
            "UPDATE observations SET processed_at = created_at WHERE id = ?",
            (observation_id,),
        )
        connection.execute(
            "UPDATE slow_path_queue SET status = 'done' WHERE observation_id = ?",
            (observation_id,),
        )

    response = get_memory_lifecycle(AUTH, session_id=session_id, limit=10)

    assert len(response.items) == 1
    row = response.items[0]
    assert row["observation"]["id"] == observation_id
    assert row["fast_path"]["status"] == "completed"
    assert row["session_extraction"]["counts"] == {"correction": 1}
    assert row["slow_path"]["status"] == "completed"
    assert row["artifacts"]["atomic_facts"] == 1
    assert row["artifacts"]["foresight_records"] == 1


def test_memory_health_endpoint_reports_real_tier_and_retention_state(
    tmp_path: Any, monkeypatch: Any
) -> None:
    db_path = tmp_path / "api-memory-health.sqlite3"
    monkeypatch.setenv("MIRA_DB_PATH", str(db_path))
    configure_database(db_path)
    session_id = create_session("user_1", workspace_id=LEGACY_WORKSPACE_ID)
    observation_id = save_observation(session_id, "user", "Use Rust for systems work.")
    create_session_item(
        {
            "session_id": session_id,
            "type": "decision",
            "content": "Use Rust for systems work.",
            "scope": "project",
            "status": "confirmed",
            "priority": 0.8,
            "explicitness_label": "direct_decision",
            "source_observations_json": [observation_id],
        }
    )
    create_session_item(
        {
            "session_id": session_id,
            "type": "correction",
            "content": "Old Python preference was replaced.",
            "scope": "project",
            "status": "superseded",
            "priority": 0.9,
            "explicitness_label": "direct_correction",
            "source_observations_json": [observation_id],
        }
    )
    create_atomic_fact(
        {
            "subject": "systems work",
            "predicate": "language",
            "object": "Rust",
            "confidence": 0.9,
            "source_observation_id": observation_id,
        }
    )
    create_reflection(
        {
            "reflection_type": "user_knowledge",
            "content": "The user prefers explicit implementation details.",
            "confidence": 0.8,
            "status": "stale",
            "stale_reason": "Replaced by a newer preference.",
        }
    )
    create_foresight_record(
        {
            "content": "Check the Rust migration next week.",
            "status": "expired",
            "source_observation_id": observation_id,
        }
    )
    create_working_memory_item(
        {
            "content": "Use Rust for systems work.",
            "memory_type": "behavioral_instruction",
            "scope": "project",
            "priority": 0.8,
            "status": "active",
        }
    )
    create_working_memory_item(
        {
            "content": "Prefer Python for systems work.",
            "memory_type": "behavioral_instruction",
            "scope": "project",
            "priority": 0.7,
            "status": "superseded",
        }
    )

    response = get_memory_health(AUTH)
    health = response.health

    tiers = health["tiers"]
    assert tiers["hot"]["count"] == 1
    assert tiers["hot"]["capacity"] >= 1
    assert tiers["cold"]["components"]["observations"] == 1
    assert tiers["cold"]["components"]["atomic_facts"] == 1
    assert health["working_set"]["active_count"] == 1
    assert health["retention"]["forgetting_signals"]["superseded_hot"] == 1
    assert health["retention"]["forgetting_signals"]["stale_reflections"] == 1
    assert health["retention"]["forgetting_signals"]["expired_foresight"] == 1
    assert any(item["source"] == "working_memory" for item in health["recent_movements"])
    assert "per-record decay factors" in health["instrumentation"]["not_persisted_yet"]
