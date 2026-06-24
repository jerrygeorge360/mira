"""Verify ISSUE-035 Relational Mode graph-traversal retrieval.

Ownership: MIRA contributors.
Related issue: ISSUE-035.
Architecture area: retrieval.
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
from core.memory.change import apply_contradiction, apply_supersession
from core.memory.graph import canonicalize_entity, create_graph_edge, create_graph_node
from core.retrieval.relational import relational_retrieve


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    """Configure relational retrieval tests to use an isolated database."""
    path = tmp_path / "mira.sqlite3"
    configure_database(path)
    yield path


def _preference_fact(observation_id: str, object_value: str) -> str:
    return create_atomic_fact(
        {
            "subject": "Jerry",
            "predicate": "PREFERS",
            "object": object_value,
            "confidence": 0.9,
            "source_observation_id": observation_id,
        }
    )


def _atomic_fact_node_id(fact_id: str) -> str:
    with repository_connection() as connection:
        row = connection.execute(
            """
            SELECT id FROM graph_nodes
            WHERE node_type = ? AND source_table = ? AND source_id = ?
            """,
            ("atomic_fact", "atomic_facts", fact_id),
        ).fetchone()
    assert row is not None
    return str(row["id"])


def test_contradiction_is_visible_from_either_side(database_path: Path) -> None:
    """An anchor fact surfaces the fact it contradicts via an incident edge."""
    session_id = create_session("jerry")
    python_observation_id = save_observation(session_id, "user", "I prefer Python.")
    rust_observation_id = save_observation(session_id, "user", "I prefer Rust.")
    python_fact_id = _preference_fact(python_observation_id, "Python")
    rust_fact_id = _preference_fact(rust_observation_id, "Rust")
    apply_contradiction(
        python_fact_id,
        rust_fact_id,
        evidence=[python_observation_id, rust_observation_id],
    )

    # Anchored by the fact source id (not the graph node id) on the *target* side,
    # incoming-edge traversal still surfaces the contradiction.
    results = relational_retrieve([rust_fact_id], {"CONTRADICTS"})

    assert len(results) == 1
    relation = results[0]
    assert relation["relation"] == "CONTRADICTS"
    assert relation["direction"] == "incoming"
    assert relation["content"] == "Jerry PREFERS Python CONTRADICTS Jerry PREFERS Rust"
    assert relation["related_source_id"] == python_fact_id
    assert relation["source_observations"] == [python_observation_id, rust_observation_id]


def test_supersession_traversal_from_node_id(database_path: Path) -> None:
    """Supersession edges are reachable when anchored by a graph node id."""
    session_id = create_session("jerry")
    old_observation_id = save_observation(session_id, "user", "I prefer Python.")
    new_observation_id = save_observation(
        session_id, "user", "I switched from Python to Rust for backend work."
    )
    old_fact_id = _preference_fact(old_observation_id, "Python")
    new_fact_id = _preference_fact(new_observation_id, "Rust")
    apply_supersession(old_fact_id, new_fact_id, evidence=[old_observation_id, new_observation_id])

    results = relational_retrieve([_atomic_fact_node_id(old_fact_id)], {"SUPERSEDED_BY"})

    assert len(results) == 1
    assert results[0]["relation"] == "SUPERSEDED_BY"
    assert results[0]["direction"] == "outgoing"
    assert results[0]["related_source_id"] == new_fact_id


def test_empty_relation_types_uses_default_families(database_path: Path) -> None:
    """An empty relation-type set traverses every relational family."""
    session_id = create_session("jerry")
    cause_observation_id = save_observation(session_id, "user", "The retry storm started.")
    effect_observation_id = save_observation(session_id, "user", "The queue backed up.")
    cause_node = create_graph_node(
        node_type="observation",
        label="retry storm",
        source_table="observations",
        source_id=cause_observation_id,
    )
    effect_node = create_graph_node(
        node_type="observation",
        label="queue backlog",
        source_table="observations",
        source_id=effect_observation_id,
    )
    edge_id = create_graph_edge(
        cause_node,
        effect_node,
        "CAUSED_BY",
        confidence=0.7,
        source_observations=[cause_observation_id],
    )

    results = relational_retrieve([cause_node], set())

    assert [item["source_id"] for item in results] == [edge_id]
    assert results[0]["relation"] == "CAUSED_BY"


def test_results_ranked_by_confidence(database_path: Path) -> None:
    """Higher-confidence relationships rank ahead of weaker ones."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "anchor turn")
    anchor = create_graph_node(node_type="entity", label="Anchor")
    weak_target = create_graph_node(node_type="entity", label="Weak")
    strong_target = create_graph_node(node_type="entity", label="Strong")
    weak_edge = create_graph_edge(
        anchor, weak_target, "LEADS_TO", confidence=0.2, source_observations=[observation_id]
    )
    strong_edge = create_graph_edge(
        anchor, strong_target, "LEADS_TO", confidence=0.95, source_observations=[observation_id]
    )

    results = relational_retrieve([anchor], {"LEADS_TO"}, limit=10)

    assert [item["source_id"] for item in results] == [strong_edge, weak_edge]


def test_invalid_relation_type_is_rejected(database_path: Path) -> None:
    """Unknown relation types are rejected rather than silently ignored."""
    with pytest.raises(ValueError, match="Unknown relation type"):
        relational_retrieve(["any"], {"BEFRIENDS"})


def test_unknown_anchor_returns_no_relations(database_path: Path) -> None:
    """An anchor with no graph presence yields no relationships."""
    create_session("jerry")
    assert relational_retrieve(["missing-id"], {"CONTRADICTS"}) == []


def test_entity_anchor_resolves_to_its_graph_nodes(database_path: Path) -> None:
    """Entity source ids resolve to their entity graph nodes for traversal."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "MIRA depends on SQLite.")
    mira_entity_id = canonicalize_entity("MIRA")
    sqlite_entity_id = canonicalize_entity("SQLite")
    mira_node = create_graph_node(
        node_type="entity",
        label="MIRA",
        source_table="entities",
        source_id=mira_entity_id,
    )
    sqlite_node = create_graph_node(
        node_type="entity",
        label="SQLite",
        source_table="entities",
        source_id=sqlite_entity_id,
    )
    edge_id = create_graph_edge(
        mira_node, sqlite_node, "DERIVED_FROM", confidence=0.6, source_observations=[observation_id]
    )

    results = relational_retrieve([mira_entity_id], {"DERIVED_FROM"})

    assert [item["source_id"] for item in results] == [edge_id]
    assert results[0]["related_source_id"] == sqlite_entity_id
