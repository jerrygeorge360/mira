"""Verify ISSUE-006 repository functions over SQLite.

Ownership: MIRA contributors.
Related issue: ISSUE-006.
Architecture area: slow path.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from core.db.repositories import (
    claim_slow_path_batch,
    configure_database,
    create_atomic_fact,
    create_entity,
    create_foresight_record,
    create_graph_edge,
    create_graph_node,
    create_prompt_log,
    create_reflection,
    create_retrieval_log,
    create_session,
    create_session_item,
    create_working_memory_item,
    end_session,
    enqueue_observation,
    link_reflection_evidence,
    list_active_foresight,
    list_active_session_items,
    list_observations,
    list_session_items_by_status,
    mark_queue_done,
    mark_queue_failed,
    save_observation,
    update_session_item_status,
)
from core.db.sqlite import connect_sqlite


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    """Configure repositories to use an isolated SQLite database."""
    path = tmp_path / "mira.sqlite3"
    configure_database(path)
    yield path


def _fetch_status(database_path: Path, table_name: str, record_id: str) -> str:
    with connect_sqlite(database_path) as connection:
        row = connection.execute(
            f"SELECT status FROM {table_name} WHERE id = ?",
            (record_id,),
        ).fetchone()
    assert row is not None
    return str(row["status"])


def _fetch_count(database_path: Path, table_name: str) -> int:
    with connect_sqlite(database_path) as connection:
        row = connection.execute(f"SELECT COUNT(*) AS count FROM {table_name}").fetchone()
    assert row is not None
    return int(row["count"])


def test_session_observation_and_queue_flow(database_path: Path) -> None:
    """Sessions, observations, and queue records can be created/read/updated."""
    session_id = create_session("user-1", "Demo")
    observation_id = save_observation(
        session_id,
        "user",
        "remember the schema work",
        metadata={"issue": "ISSUE-006", "tags": ["db", "repo"]},
    )

    observations = list_observations(session_id)
    assert observations[0]["id"] == observation_id
    assert observations[0]["metadata_json"] == {"issue": "ISSUE-006", "tags": ["db", "repo"]}

    queue_id = enqueue_observation(observation_id)
    assert claim_slow_path_batch(1) == [queue_id]
    assert _fetch_status(database_path, "slow_path_queue", queue_id) == "processing"

    mark_queue_failed(queue_id, "transient parse error")
    assert _fetch_status(database_path, "slow_path_queue", queue_id) == "failed"

    second_queue_id = enqueue_observation(observation_id)
    mark_queue_done(second_queue_id)
    assert _fetch_status(database_path, "slow_path_queue", second_queue_id) == "done"

    end_session(session_id)
    assert _fetch_status(database_path, "sessions", session_id) == "ended"


def test_session_item_crud_flow(database_path: Path) -> None:
    """Session Working Set items can be created, listed, and status-updated."""
    session_id = create_session("user-1")
    observation_id = save_observation(session_id, "user", "finish ISSUE-006")
    item_id = create_session_item(
        {
            "session_id": session_id,
            "type": "current_goal",
            "content": "finish repository layer",
            "scope": "current_task",
            "status": "provisional",
            "priority": 0.9,
            "explicitness_label": "direct_instruction",
            "source_observations_json": [observation_id],
            "supersedes_json": [],
        }
    )

    active_items = list_active_session_items(session_id)
    assert active_items[0]["id"] == item_id
    assert active_items[0]["source_observations_json"] == [observation_id]

    update_session_item_status(item_id, "resolved")
    resolved_items = list_session_items_by_status(session_id, "resolved")
    assert resolved_items[0]["id"] == item_id


def test_memory_graph_reflection_and_foresight_flow(database_path: Path) -> None:
    """Durable memory, graph, reflection, and foresight records can be created."""
    session_id = create_session("user-1")
    observation_id = save_observation(session_id, "assistant", "repository layer created")
    fact_id = create_atomic_fact(
        {
            "subject": "MIRA",
            "predicate": "has_layer",
            "object": "repository",
            "confidence": 0.95,
            "source_observation_id": observation_id,
        }
    )
    entity_id = create_entity(
        {"name": "MIRA", "entity_type": "project", "aliases_json": ["Memory Agent"]}
    )
    fact_node_id = create_graph_node(
        {
            "node_type": "atomic_fact",
            "source_table": "atomic_facts",
            "source_id": fact_id,
            "label": "MIRA has repository layer",
        }
    )
    entity_node_id = create_graph_node(
        {
            "node_type": "entity",
            "source_table": "entities",
            "source_id": entity_id,
            "label": "MIRA",
        }
    )
    create_graph_edge(
        {
            "source_node_id": fact_node_id,
            "target_node_id": entity_node_id,
            "edge_type": "MENTIONS",
            "confidence": 0.9,
            "source_observations_json": [observation_id],
        }
    )
    reflection_id = create_reflection(
        {
            "reflection_type": "self_knowledge",
            "content": "Repository API exists.",
            "confidence": 0.8,
            "status": "active",
        }
    )
    evidence_id = link_reflection_evidence(reflection_id, observation_id)
    foresight_id = create_foresight_record(
        {
            "content": "Use repositories before memory logic.",
            "status": "active",
            "source_observation_id": observation_id,
            "always_inject": 1,
        }
    )
    working_memory_id = create_working_memory_item(
        {
            "content": "Use repository functions instead of ad-hoc SQL.",
            "memory_type": "project_constraint",
            "scope": "project",
            "priority": 0.75,
            "status": "active",
            "source_record_type": "foresight_records",
            "source_record_id": foresight_id,
        }
    )

    assert _fetch_count(database_path, "atomic_facts") == 1
    assert _fetch_count(database_path, "entities") == 1
    assert _fetch_count(database_path, "graph_edges") == 1
    assert _fetch_count(database_path, "reflections") == 1
    assert _fetch_count(database_path, "reflection_evidence") == 1
    assert _fetch_count(database_path, "working_memory") == 1
    assert evidence_id
    assert working_memory_id
    assert list_active_foresight(session_id)[0]["id"] == foresight_id


def test_retrieval_and_prompt_logs_round_trip_json(database_path: Path) -> None:
    """Retrieval and prompt logs preserve structured JSON fields."""
    session_id = create_session("user-1")
    observation_id = save_observation(session_id, "user", "what should MIRA remember?")
    retrieval_log_id = create_retrieval_log(
        {
            "session_id": session_id,
            "query": "repository",
            "retrieval_mode": "quick",
            "retrieved_records_json": [{"table": "atomic_facts", "id": "fact-1"}],
            "sufficiency_json": {"sufficient": True},
        }
    )
    prompt_log_id = create_prompt_log(
        {
            "session_id": session_id,
            "user_observation_id": observation_id,
            "included_session_items_json": ["item-1"],
            "included_memory_items_json": ["memory-1"],
            "included_recent_turns_json": [observation_id],
            "token_budget_json": {"budget": 32000},
        }
    )

    with connect_sqlite(database_path) as connection:
        retrieval_row = connection.execute(
            "SELECT id FROM retrieval_logs WHERE id = ?",
            (retrieval_log_id,),
        ).fetchone()
        prompt_row = connection.execute(
            "SELECT id FROM prompt_logs WHERE id = ?",
            (prompt_log_id,),
        ).fetchone()

    assert retrieval_row is not None
    assert prompt_row is not None


def test_repository_rejects_invalid_enum_values(database_path: Path) -> None:
    """Enum-like fields are rejected before invalid records are written."""
    session_id = create_session("user-1")

    with pytest.raises(ValueError, match="Invalid observation_role"):
        save_observation(session_id, "human", "bad role")

    with pytest.raises(ValueError, match="Invalid session_item_status"):
        list_session_items_by_status(session_id, "active")


def test_repository_errors_are_clear(database_path: Path) -> None:
    """Missing records and missing required fields raise clear ValueError messages."""
    with pytest.raises(ValueError, match="Session not found"):
        end_session("missing-session")

    with pytest.raises(ValueError, match="Missing required field"):
        create_atomic_fact({"subject": "MIRA"})
