"""Focused lifecycle gates for Deep and Relational retrieval."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from core.db import chroma
from core.db.repositories import (
    configure_database,
    create_atomic_fact,
    create_community_summary,
    create_reflection,
    create_session,
    create_workspace,
    repository_connection,
    save_observation,
)
from core.memory.graph import create_graph_edge, create_graph_node
from core.memory.lifecycle import ensure_memory_state, forget_memory
from core.retrieval.deep import retrieve_deep
from core.retrieval.relational import relational_retrieve


@pytest.fixture
def isolated_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Use deterministic retrieval without starting the Chroma server."""
    database_path = tmp_path / "mira.sqlite3"
    monkeypatch.setenv("EMBEDDING_MODE", "deterministic")

    def no_chromadb(_module_name: str) -> object:
        raise ModuleNotFoundError("focused lifecycle tests use the offline vector fallback")

    monkeypatch.setattr(chroma.importlib, "import_module", no_chromadb)
    configure_database(database_path)
    chroma.reset_vector_store()
    yield database_path
    chroma.reset_vector_store()


def _community(workspace_id: str, title: str, summary: str) -> str:
    return create_community_summary(
        {
            "workspace_id": workspace_id,
            "community_id": f"community-{title.casefold().replace(' ', '-')}",
            "title": title,
            "summary": summary,
            "member_nodes_json": [],
        }
    )


def _edge(workspace_id: str, relation: str = "LEADS_TO") -> tuple[str, str, str]:
    session_id = create_session("jerry", workspace_id=workspace_id)
    observation_id = save_observation(session_id, "user", "The graph transition is supported.")
    source = create_graph_node("entity", "source", workspace_id=workspace_id)
    target = create_graph_node("entity", "target", workspace_id=workspace_id)
    edge_id = create_graph_edge(
        source,
        target,
        relation,
        0.9,
        [observation_id],
        workspace_id=workspace_id,
    )
    return edge_id, source, target


def test_deep_excludes_forgotten_and_superseded_but_historical_query_can_see_them(
    isolated_memory: Path,
) -> None:
    del isolated_memory
    workspace_id = create_workspace("Deep", "deep-lifecycle", "development")
    forgotten_id = _community(workspace_id, "Forgotten policy", "The old database policy.")
    forget_memory("community_summaries", forgotten_id, workspace_id)
    superseded_id = create_reflection(
        {
            "workspace_id": workspace_id,
            "reflection_type": "self_knowledge",
            "content": "The superseded database policy used the old system.",
            "confidence": 0.9,
            "status": "superseded",
        }
    )
    _community(workspace_id, "Current policy", "The current database policy.")

    current = retrieve_deep("database policy", None, limit=10, workspace_id=workspace_id)
    current_ids = {str(item["source_id"]) for item in current}
    assert forgotten_id not in current_ids
    assert superseded_id not in current_ids

    historical = retrieve_deep(
        "database policy", None, limit=10, workspace_id=workspace_id, historical=True
    )
    historical_ids = {str(item["source_id"]) for item in historical}
    assert forgotten_id in historical_ids
    assert superseded_id in historical_ids


def test_deep_workspace_isolation_and_low_trust_active_memory(
    isolated_memory: Path,
) -> None:
    del isolated_memory
    workspace_a = create_workspace("A", "deep-a", "development")
    workspace_b = create_workspace("B", "deep-b", "development")
    active_id = _community(workspace_a, "Private policy", "Private workspace database policy.")
    _community(workspace_b, "Other policy", "Other workspace database policy.")
    state = ensure_memory_state("community_summaries", active_id, workspace_a)
    with repository_connection() as connection:
        connection.execute(
            "UPDATE memory_state SET retention_score = 0.0, failed_uses = 5 WHERE id = ?",
            (state["id"],),
        )

    results = retrieve_deep("database policy", None, limit=10, workspace_id=workspace_a)
    assert any(item["source_id"] == active_id for item in results)
    assert all(item.get("record", {}).get("workspace_id") == workspace_a for item in results)


def test_relational_excludes_forgotten_and_superseded_current_records_but_preserves_history(
    isolated_memory: Path,
) -> None:
    del isolated_memory
    workspace_id = create_workspace("Relational", "rel-lifecycle", "development")
    forgotten_edge, forgotten_source, _ = _edge(workspace_id)
    forget_memory("graph_edges", forgotten_edge, workspace_id)

    session_id = create_session("jerry", workspace_id=workspace_id)
    observation_id = save_observation(
        session_id, "user", "The old relationship is no longer current."
    )
    fact_id = create_atomic_fact(
        {
            "workspace_id": workspace_id,
            "subject": "database",
            "predicate": "uses",
            "object": "old-system",
            "confidence": 0.9,
            "status": "superseded",
            "source_observation_id": observation_id,
        }
    )
    superseded_node = create_graph_node(
        "atomic_fact", "old database fact", "atomic_facts", fact_id, workspace_id=workspace_id
    )
    current_node = create_graph_node("entity", "current", workspace_id=workspace_id)
    superseded_edge = create_graph_edge(
        superseded_node,
        current_node,
        "LEADS_TO",
        0.8,
        [observation_id],
        workspace_id=workspace_id,
    )

    current = relational_retrieve(
        [forgotten_source, superseded_node], {"LEADS_TO"}, workspace_id=workspace_id
    )
    assert all(item["source_id"] not in {forgotten_edge, superseded_edge} for item in current)

    historical = relational_retrieve(
        [forgotten_source, superseded_node],
        {"LEADS_TO"},
        workspace_id=workspace_id,
        historical=True,
    )
    historical_ids = {str(item["source_id"]) for item in historical}
    assert forgotten_edge in historical_ids
    assert superseded_edge in historical_ids


def test_relational_workspace_isolation_and_low_trust_active_edge(
    isolated_memory: Path,
) -> None:
    del isolated_memory
    workspace_a = create_workspace("A", "rel-a", "development")
    workspace_b = create_workspace("B", "rel-b", "development")
    edge_a, source_a, _ = _edge(workspace_a)
    edge_b, source_b, _ = _edge(workspace_b)
    state = ensure_memory_state("graph_edges", edge_a, workspace_a)
    with repository_connection() as connection:
        connection.execute(
            "UPDATE memory_state SET retention_score = 0.0, failed_uses = 5 WHERE id = ?",
            (state["id"],),
        )

    results = relational_retrieve([source_a, source_b], {"LEADS_TO"}, workspace_id=workspace_a)
    result_ids = {str(item["source_id"]) for item in results}
    assert edge_a in result_ids
    assert edge_b not in result_ids
