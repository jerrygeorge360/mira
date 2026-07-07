"""Verify the ISSUE-026 single typed graph API.

Ownership: MIRA contributors.
Related issue: ISSUE-026.
Architecture area: slow path.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from core.db.repositories import (
    configure_database,
    create_reflection,
    create_session,
    repository_connection,
    save_observation,
)
from core.memory.graph import (
    build_networkx_memory_graph,
    create_graph_edge,
    create_graph_node,
    find_edges_by_type,
    get_neighbors,
    graph_algorithm_summary,
    inspect_memory_graph,
)


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    """Configure typed graph tests to use an isolated database."""
    path = tmp_path / "mira.sqlite3"
    configure_database(path)
    yield path


def test_nodes_can_be_created(database_path: Path) -> None:
    """Typed graph nodes can be created for canonical source records."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "MIRA uses SQLite.")

    node_id = create_graph_node(
        node_type="observation",
        label="MIRA uses SQLite.",
        source_table="observations",
        source_id=observation_id,
    )

    node = _graph_node(node_id)
    assert node["node_type"] == "observation"
    assert node["source_table"] == "observations"
    assert node["source_id"] == observation_id


def test_mentions_edge_links_observation_to_entity(database_path: Path) -> None:
    """MENTIONS edges connect observation nodes to entity nodes."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "MIRA mentions SQLite.")
    observation_node_id = create_graph_node(
        "observation",
        "MIRA mentions SQLite.",
        "observations",
        observation_id,
    )
    entity_node_id = create_graph_node("entity", "SQLite", "entities", "entity_sqlite")

    edge_id = create_graph_edge(
        observation_node_id,
        entity_node_id,
        "MENTIONS",
        confidence=0.95,
        source_observations=[observation_id],
    )

    edges = find_edges_by_type("MENTIONS")
    assert edges[0]["id"] == edge_id
    assert edges[0]["source_observations"] == [observation_id]
    assert edges[0]["confidence"] == 0.95


def test_graph_inspection_reports_counts_and_edge_provenance(database_path: Path) -> None:
    """Graph inspection exposes visible nodes, edges, labels, and evidence observations."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "MIRA mentions SQLite.")
    observation_node_id = create_graph_node(
        "observation",
        "MIRA mentions SQLite.",
        "observations",
        observation_id,
    )
    entity_node_id = create_graph_node("entity", "SQLite", "entities", "entity_sqlite")
    edge_id = create_graph_edge(
        observation_node_id,
        entity_node_id,
        "MENTIONS",
        confidence=0.95,
        source_observations=[observation_id],
    )

    snapshot = inspect_memory_graph(entity="SQLite")

    assert snapshot["counts"]["nodes"] == 2
    assert snapshot["counts"]["active_edges"] == 1
    assert snapshot["counts"]["visible_nodes"] == 2
    assert snapshot["edges"][0]["id"] == edge_id
    assert snapshot["edges"][0]["source_observations"] == [observation_id]
    assert snapshot["edges"][0]["source_label"] == "MIRA mentions SQLite."
    assert snapshot["edges"][0]["target_label"] == "SQLite"


def test_derived_from_edge_links_reflection_to_evidence(database_path: Path) -> None:
    """DERIVED_FROM edges connect reflections back to evidence observations."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "Jerry prefers SQLite.")
    reflection_id = create_reflection(
        {
            "reflection_type": "user_knowledge",
            "content": "Jerry prefers SQLite.",
            "confidence": 0.8,
            "status": "active",
        }
    )
    reflection_node_id = create_graph_node(
        "reflection",
        "Jerry prefers SQLite.",
        "reflections",
        reflection_id,
    )
    observation_node_id = create_graph_node(
        "observation",
        "Jerry prefers SQLite.",
        "observations",
        observation_id,
    )

    edge_id = create_graph_edge(
        reflection_node_id,
        observation_node_id,
        "DERIVED_FROM",
        confidence=0.8,
        source_observations=[observation_id],
    )

    edges = find_edges_by_type("DERIVED_FROM")
    assert edges[0]["id"] == edge_id
    assert edges[0]["source_node_id"] == reflection_node_id
    assert edges[0]["target_node_id"] == observation_node_id


def test_traversal_by_edge_type_works(database_path: Path) -> None:
    """Neighbor traversal can be restricted to specific edge types."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "MIRA uses SQLite.")
    observation_node_id = create_graph_node(
        "observation",
        "MIRA uses SQLite.",
        "observations",
        observation_id,
    )
    sqlite_node_id = create_graph_node("entity", "SQLite", "entities", "entity_sqlite")
    mira_node_id = create_graph_node("entity", "MIRA", "entities", "entity_mira")
    create_graph_edge(
        observation_node_id,
        sqlite_node_id,
        "MENTIONS",
        confidence=0.9,
        source_observations=[observation_id],
    )
    create_graph_edge(
        observation_node_id,
        mira_node_id,
        "DERIVED_FROM",
        confidence=0.7,
        source_observations=[observation_id],
    )

    neighbors = get_neighbors(observation_node_id, edge_types=["MENTIONS"], depth=1)

    assert len(neighbors) == 1
    assert neighbors[0]["node"]["id"] == sqlite_node_id
    assert neighbors[0]["edge"]["edge_type"] == "MENTIONS"


def test_networkx_view_projects_sqlite_graph(database_path: Path) -> None:
    """NetworkX view exposes SQLite graph nodes/edges without becoming source of truth."""
    pytest.importorskip("networkx")
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "MIRA uses SQLite.")
    observation_node_id = create_graph_node(
        "observation",
        "MIRA uses SQLite.",
        "observations",
        observation_id,
    )
    sqlite_node_id = create_graph_node("entity", "SQLite", "entities", "entity_sqlite")
    edge_id = create_graph_edge(
        observation_node_id,
        sqlite_node_id,
        "MENTIONS",
        confidence=0.9,
        source_observations=[observation_id],
    )

    graph = build_networkx_memory_graph()

    assert graph.number_of_nodes() == 2
    assert graph.number_of_edges() == 1
    assert graph.nodes[sqlite_node_id]["label"] == "SQLite"
    assert graph.edges[observation_node_id, sqlite_node_id, edge_id]["edge_type"] == "MENTIONS"
    assert graph.edges[observation_node_id, sqlite_node_id, edge_id]["source_observations"] == [
        observation_id
    ]


def test_networkx_algorithm_summary_is_read_only(database_path: Path) -> None:
    """NetworkX diagnostics summarize graph structure without mutating SQLite."""
    pytest.importorskip("networkx")
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "MIRA mentions SQLite and Chroma.")
    observation_node_id = create_graph_node(
        "observation",
        "MIRA mentions SQLite and Chroma.",
        "observations",
        observation_id,
    )
    sqlite_node_id = create_graph_node("entity", "SQLite", "entities", "entity_sqlite")
    chroma_node_id = create_graph_node("entity", "Chroma", "entities", "entity_chroma")
    create_graph_edge(
        observation_node_id,
        sqlite_node_id,
        "MENTIONS",
        confidence=0.9,
        source_observations=[observation_id],
    )
    create_graph_edge(
        observation_node_id,
        chroma_node_id,
        "MENTIONS",
        confidence=0.9,
        source_observations=[observation_id],
    )

    summary = graph_algorithm_summary()

    assert summary["nodes"] == 3
    assert summary["edges"] == 2
    assert summary["weakly_connected_components"] == 1
    assert summary["largest_component_size"] == 3
    assert summary["top_degree_nodes"][0]["id"] == observation_node_id
    assert _graph_node(sqlite_node_id)["label"] == "SQLite"


def test_invalid_confidence_is_rejected(database_path: Path) -> None:
    """Graph edge confidence must be bounded."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "MIRA uses SQLite.")
    source_node_id = create_graph_node(
        "observation",
        "MIRA uses SQLite.",
        "observations",
        observation_id,
    )
    target_node_id = create_graph_node("entity", "SQLite", "entities", "entity_sqlite")

    with pytest.raises(ValueError, match="confidence"):
        create_graph_edge(source_node_id, target_node_id, "MENTIONS", 1.5, [observation_id])


def _graph_node(node_id: str) -> dict[str, object]:
    with repository_connection() as connection:
        row = connection.execute("SELECT * FROM graph_nodes WHERE id = ?", (node_id,)).fetchone()
    assert row is not None
    return dict(row)
