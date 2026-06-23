"""Verify ISSUE-027 contradiction versus supersession semantics.

Ownership: MIRA contributors.
Related issue: ISSUE-027.
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
from core.memory.change import (
    apply_contradiction,
    apply_supersession,
    detect_memory_change,
)
from core.memory.graph import find_edges_by_type, get_neighbors


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    """Configure memory change tests to use an isolated database."""
    path = tmp_path / "mira.sqlite3"
    configure_database(path)
    yield path


def test_python_to_rust_switch_creates_supersession(database_path: Path) -> None:
    """Explicit transition language creates SUPERSEDED_BY and closes the old fact."""
    session_id = create_session("jerry")
    old_observation_id = save_observation(session_id, "user", "I prefer Python.")
    new_observation_id = save_observation(
        session_id,
        "user",
        "I switched from Python to Rust for backend work.",
    )
    old_fact_id = _create_preference_fact(old_observation_id, "Python")
    new_fact_id = _create_preference_fact(new_observation_id, "Rust")

    changes = detect_memory_change(new_fact_id, [old_fact_id])
    edge_id = apply_supersession(
        old_fact_id,
        new_fact_id,
        evidence=[old_observation_id, new_observation_id],
    )

    assert changes[0]["relation"] == "SUPERSEDED_BY"
    assert changes[0]["source_id"] == old_fact_id
    assert changes[0]["target_id"] == new_fact_id
    edges = find_edges_by_type("SUPERSEDED_BY")
    assert edges[0]["id"] == edge_id
    assert edges[0]["source_observations"] == [old_observation_id, new_observation_id]
    old_fact = _atomic_fact(old_fact_id)
    assert old_fact["status"] == "superseded"
    assert old_fact["valid_until"] is not None


def test_later_preference_without_transition_creates_contradiction(database_path: Path) -> None:
    """Incompatible claims without transition language remain unresolved conflicts."""
    session_id = create_session("jerry")
    python_observation_id = save_observation(session_id, "user", "I prefer Python.")
    rust_observation_id = save_observation(session_id, "user", "I prefer Rust.")
    python_fact_id = _create_preference_fact(python_observation_id, "Python")
    rust_fact_id = _create_preference_fact(rust_observation_id, "Rust")

    changes = detect_memory_change(rust_fact_id, [python_fact_id])
    edge_id = apply_contradiction(
        python_fact_id,
        rust_fact_id,
        evidence=[python_observation_id, rust_observation_id],
    )

    assert changes[0]["relation"] == "CONTRADICTS"
    assert changes[0]["source_id"] == python_fact_id
    assert changes[0]["target_id"] == rust_fact_id
    assert _atomic_fact(python_fact_id)["status"] == "active"
    assert _atomic_fact(rust_fact_id)["status"] == "active"
    edges = find_edges_by_type("CONTRADICTS")
    assert edges[0]["id"] == edge_id


def test_relational_mode_can_see_both_conflicting_facts(database_path: Path) -> None:
    """Graph traversal exposes both sides of an unresolved contradiction."""
    session_id = create_session("jerry")
    python_observation_id = save_observation(session_id, "user", "I prefer Python.")
    rust_observation_id = save_observation(session_id, "user", "I prefer Rust.")
    python_fact_id = _create_preference_fact(python_observation_id, "Python")
    rust_fact_id = _create_preference_fact(rust_observation_id, "Rust")
    apply_contradiction(
        python_fact_id,
        rust_fact_id,
        evidence=[python_observation_id, rust_observation_id],
    )

    neighbors = get_neighbors(_atomic_fact_node_id(python_fact_id), ["CONTRADICTS"])

    assert neighbors[0]["edge"]["edge_type"] == "CONTRADICTS"
    assert neighbors[0]["node"]["source_id"] == rust_fact_id
    assert _atomic_fact(python_fact_id)["object"] == "Python"
    assert _atomic_fact(rust_fact_id)["object"] == "Rust"


def _create_preference_fact(observation_id: str, object_value: str) -> str:
    return create_atomic_fact(
        {
            "subject": "Jerry",
            "predicate": "PREFERS",
            "object": object_value,
            "confidence": 0.9,
            "source_observation_id": observation_id,
        }
    )


def _atomic_fact(fact_id: str) -> dict[str, object]:
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT * FROM atomic_facts WHERE id = ?",
            (fact_id,),
        ).fetchone()
    assert row is not None
    return dict(row)


def _atomic_fact_node_id(fact_id: str) -> str:
    with repository_connection() as connection:
        row = connection.execute(
            """
            SELECT id
            FROM graph_nodes
            WHERE node_type = ? AND source_table = ? AND source_id = ?
            """,
            ("atomic_fact", "atomic_facts", fact_id),
        ).fetchone()
    assert row is not None
    return str(row["id"])
