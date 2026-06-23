"""Verify the index-only vector wrapper over canonical SQLite records.

Ownership: MIRA contributors.
Related issue: ISSUE-503.
Architecture area: retrieval.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from core.db import chroma
from core.db.repositories import (
    configure_database,
    create_reflection,
    create_session,
    save_observation,
)
from core.db.sqlite import connect_sqlite


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    """Configure SQLite storage and clear disposable vector collections."""
    path = tmp_path / "mira.sqlite3"
    configure_database(path)
    chroma.configure_embedder(None)
    for collection in sorted(chroma.SUPPORTED_COLLECTIONS):
        chroma.delete_collection(collection)
    yield path
    chroma.configure_embedder(None)
    for collection in sorted(chroma.SUPPORTED_COLLECTIONS):
        chroma.delete_collection(collection)


def test_add_query_round_trip_returns_sqlite_pointers_only(database_path: Path) -> None:
    """Query results contain SQLite pointers and retrieval metadata, not canonical content."""
    session_id = create_session("user-1")
    observation_id = save_observation(session_id, "user", "Remember vector pointers.")
    chroma.add_embedding(
        "observations",
        "observations",
        observation_id,
        [1.0, 0.0, 0.0],
        metadata={"source": "test", "kind": "observation"},
    )
    chroma.add_embedding(
        "observations",
        "observations",
        save_observation(session_id, "user", "A different vector."),
        [0.0, 1.0, 0.0],
        metadata={"source": "test", "kind": "observation"},
    )

    results = chroma.query_embeddings("observations", [1.0, 0.0, 0.0], top_k=1)

    assert len(results) == 1
    assert results[0]["sqlite_table"] == "observations"
    assert results[0]["sqlite_id"] == observation_id
    assert "distance" in results[0]
    assert results[0]["metadata"] == {"source": "test", "kind": "observation"}
    assert "content" not in results[0]


def test_delete_collection_removes_index_but_not_sqlite_record(database_path: Path) -> None:
    """Deleting a Chroma collection does not delete the canonical SQLite row."""
    session_id = create_session("user-1")
    observation_id = save_observation(session_id, "assistant", "SQLite remains canonical.")
    chroma.add_embedding(
        "observations",
        "observations",
        observation_id,
        [0.0, 0.0, 1.0],
        metadata={"source": "test"},
    )

    chroma.delete_collection("observations")

    assert chroma.query_embeddings("observations", [0.0, 0.0, 1.0], top_k=5) == []
    with connect_sqlite(database_path) as connection:
        row = connection.execute(
            "SELECT id, content FROM observations WHERE id = ?",
            (observation_id,),
        ).fetchone()
    assert row is not None
    assert row["id"] == observation_id
    assert row["content"] == "SQLite remains canonical."


def test_supported_reflection_and_community_summary_collections(database_path: Path) -> None:
    """All supported collections accept SQLite-backed pointers."""
    session_id = create_session("user-1")
    observation_id = save_observation(session_id, "user", "Support reflection collection.")
    reflection_id = create_reflection(
        {
            "reflection_type": "self_knowledge",
            "content": "Reflections are indexed, not canonicalized in Chroma.",
            "confidence": 0.9,
            "status": "active",
        }
    )
    with connect_sqlite(database_path) as connection:
        connection.execute(
            """
            INSERT INTO community_summaries (
                id, community_id, title, summary, member_nodes_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "community-1",
                "community-demo",
                "Demo Community",
                "A disposable vector index can point here.",
                "[]",
                "2026-06-23T00:00:00+00:00",
                "2026-06-23T00:00:00+00:00",
            ),
        )

    chroma.add_embedding(
        "reflections",
        "reflections",
        reflection_id,
        [0.0, 1.0],
        metadata={"source_observation_id": observation_id},
    )
    chroma.add_embedding(
        "community_summaries",
        "community_summaries",
        "community-1",
        [1.0, 1.0],
        metadata={"community_id": "community-demo"},
    )

    reflection_results = chroma.query_embeddings("reflections", [0.0, 1.0], top_k=1)
    community_results = chroma.query_embeddings("community_summaries", [1.0, 1.0], top_k=1)

    assert reflection_results[0]["sqlite_table"] == "reflections"
    assert reflection_results[0]["sqlite_id"] == reflection_id
    assert reflection_results[0]["metadata"] == {"source_observation_id": observation_id}
    assert community_results[0]["sqlite_table"] == "community_summaries"
    assert community_results[0]["sqlite_id"] == "community-1"
    assert community_results[0]["metadata"] == {"community_id": "community-demo"}


def test_rebuild_collection_recreates_observation_index_from_sqlite(database_path: Path) -> None:
    """Rebuild derives deterministic observation index text from SQLite records."""
    session_id = create_session("user-1")
    first_id = save_observation(session_id, "user", "alpha")
    second_id = save_observation(session_id, "assistant", "beta")

    def fake_embedder(text: str) -> list[float]:
        if text == "alpha":
            return [1.0, 0.0]
        if text == "beta":
            return [0.0, 1.0]
        raise AssertionError(f"unexpected rebuild text: {text}")

    chroma.configure_embedder(fake_embedder)
    chroma.rebuild_collection("observations")

    first_results = chroma.query_embeddings("observations", [1.0, 0.0], top_k=1)
    second_results = chroma.query_embeddings("observations", [0.0, 1.0], top_k=1)

    assert first_results[0]["sqlite_table"] == "observations"
    assert first_results[0]["sqlite_id"] == first_id
    assert first_results[0]["metadata"] == {
        "index_text_version": chroma.INDEX_TEXT_VERSION,
        "role": "user",
        "source": "chat",
    }
    assert second_results[0]["sqlite_table"] == "observations"
    assert second_results[0]["sqlite_id"] == second_id
    assert second_results[0]["metadata"] == {
        "index_text_version": chroma.INDEX_TEXT_VERSION,
        "role": "assistant",
        "source": "chat",
    }


def test_rebuild_collection_requires_configured_embedder(database_path: Path) -> None:
    """Rebuild fails clearly until an external embedding provider is configured."""
    session_id = create_session("user-1")
    save_observation(session_id, "user", "alpha")

    with pytest.raises(ValueError, match="No embedding provider configured"):
        chroma.rebuild_collection("observations")
