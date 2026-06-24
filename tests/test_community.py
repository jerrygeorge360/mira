"""Verify ISSUE-032 graph-derived community detection and summaries.

Ownership: MIRA contributors.
Related issue: ISSUE-032.
Architecture area: slow path.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from core.db import chroma
from core.db.repositories import (
    configure_database,
    create_session,
    repository_connection,
    save_observation,
)
from core.memory import community
from core.memory.community import (
    detect_graph_communities,
    store_community_summary,
    summarize_community,
)
from core.memory.graph import create_graph_edge, create_graph_node


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    """Configure community tests to use an isolated database."""
    path = tmp_path / "mira.sqlite3"
    configure_database(path)
    yield path


def _node(label: str) -> str:
    return create_graph_node(node_type="entity", label=label)


def _edge(source_node_id: str, target_node_id: str, observation_id: str) -> None:
    create_graph_edge(
        source_node_id,
        target_node_id,
        "MENTIONS",
        confidence=0.9,
        source_observations=[observation_id],
    )


def _fake_summary(title: str, summary: str):
    def _call(messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
        assert schema_name == "community_summary_generation"
        return {"json": {"title": title, "summary": summary, "member_node_ids": []}}

    return _call


def _stored_summary(summary_id: str) -> dict[str, object]:
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT * FROM community_summaries WHERE id = ?",
            (summary_id,),
        ).fetchone()
    assert row is not None
    return dict(row)


def test_detection_groups_connected_nodes(database_path: Path) -> None:
    """Connected nodes form one community; a separate cluster forms another."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "MIRA uses SQLite and ChromaDB.")
    a, b, c = _node("MIRA"), _node("SQLite"), _node("ChromaDB")
    d, e = _node("Hackathon"), _node("Deadline")
    _edge(a, b, observation_id)
    _edge(b, c, observation_id)
    _edge(d, e, observation_id)

    communities = detect_graph_communities()

    member_sets = sorted((sorted(c["member_node_ids"]) for c in communities), key=len, reverse=True)
    assert member_sets == [sorted([a, b, c]), sorted([d, e])]


def test_fake_graph_creates_community_summary(
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A detected community can be summarized and stored end to end."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "Persistence uses SQLite and ChromaDB.")
    a, b, c = _node("SQLite"), _node("ChromaDB"), _node("Persistence")
    _edge(a, b, observation_id)
    _edge(b, c, observation_id)

    communities = detect_graph_communities()
    assert len(communities) == 1
    community_id = str(communities[0]["community_id"])
    member_node_ids = [str(node_id) for node_id in communities[0]["member_node_ids"]]

    monkeypatch.setattr(
        community,
        "call_qwen_json",
        _fake_summary("Persistence Architecture", "SQLite is durable; Chroma is rebuildable."),
    )
    summary = summarize_community(community_id, member_node_ids)
    summary_id = store_community_summary(summary)

    stored = _stored_summary(summary_id)
    assert stored["title"] == "Persistence Architecture"
    assert stored["community_id"] == community_id
    assert json.loads(str(stored["member_nodes_json"])) == sorted(member_node_ids)


def test_summary_has_title_content_and_member_nodes(
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A community summary carries a title, summary text, and member node ids."""
    create_session("jerry")
    a, b = _node("Quick Mode"), _node("Relational Mode")

    monkeypatch.setattr(
        community,
        "call_qwen_json",
        _fake_summary("Retrieval Modes", "Quick and Relational answer different questions."),
    )
    summary = summarize_community("community_test", [a, b])

    assert summary["title"] == "Retrieval Modes"
    assert summary["summary"] == "Quick and Relational answer different questions."
    assert sorted(summary["member_node_ids"]) == sorted([a, b])


def test_summary_can_be_indexed_for_retrieval(database_path: Path) -> None:
    """A stored community summary is indexed and queryable in ChromaDB."""
    create_session("jerry")
    a, b = _node("SQLite"), _node("ChromaDB")

    summary_id = store_community_summary(
        {
            "community_id": "community_persistence",
            "title": "Persistence Architecture",
            "summary": "SQLite stores durable memory while indexes remain rebuildable.",
            "member_node_ids": [a, b],
        }
    )

    embedding = community._embed_text(
        "Persistence Architecture SQLite stores durable memory while indexes remain rebuildable."
    )
    pointers = chroma.query_embeddings(community.INDEX_COLLECTION, embedding, top_k=5)
    assert summary_id in [str(pointer["sqlite_id"]) for pointer in pointers]


def test_store_rejects_summary_without_members(database_path: Path) -> None:
    """A summary with no member nodes is rejected."""
    with pytest.raises(ValueError, match="member node"):
        store_community_summary(
            {
                "community_id": "community_x",
                "title": "Title",
                "summary": "Body",
                "member_node_ids": [],
            }
        )
