"""Verify ISSUE-036 Deep Mode pattern-level retrieval.

Ownership: MIRA contributors.
Related issue: ISSUE-036.
Architecture area: retrieval.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from core.db import chroma
from core.db.repositories import (
    configure_database,
    create_community_summary,
    create_reflection,
    create_session,
    save_observation,
)
from core.llm.embeddings import embed_text
from core.retrieval.deep import retrieve_deep


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    """Configure Deep Mode tests to use an isolated database."""
    path = tmp_path / "mira.sqlite3"
    configure_database(path)
    yield path


def _community(title: str, summary: str, members: list[str]) -> str:
    return create_community_summary(
        {
            "community_id": f"community_{title.lower().replace(' ', '_')}",
            "title": title,
            "summary": summary,
            "member_nodes_json": members,
        }
    )


def _reflection(reflection_type: str, content: str, confidence: float) -> str:
    """Create a reflection and index it in the vector store, as production does."""
    reflection_id = create_reflection(
        {
            "reflection_type": reflection_type,
            "content": content,
            "confidence": confidence,
            "status": "active",
        }
    )
    chroma.add_embedding("reflections", "reflections", reflection_id, embed_text(content))
    return reflection_id


def test_broad_query_retrieves_community_summaries(database_path: Path) -> None:
    """A broad synthesis query returns cached community summaries."""
    persistence_id = _community(
        "Persistence Architecture",
        "SQLite stores durable memory while ChromaDB indexes remain rebuildable.",
        ["node_1", "node_2"],
    )
    retrieval_id = _community(
        "Retrieval Modes",
        "Quick, Deep, and Relational retrieval answer different question shapes.",
        ["node_3", "node_4"],
    )

    results = retrieve_deep("How does persistence and durable memory work?", None, limit=5)

    assert results[0]["source"] == "community_summary"
    assert results[0]["source_id"] == persistence_id
    returned_ids = {str(result["source_id"]) for result in results}
    assert retrieval_id in returned_ids  # contrasting community included for synthesis


def test_no_community_fallback_to_quick_mode(database_path: Path) -> None:
    """With no communities, Deep Mode falls back to Quick Mode and records why."""
    session_id = create_session("jerry")
    save_observation(session_id, "user", "The deployment runbook lives in the wiki.")

    results = retrieve_deep("deployment runbook", session_id, limit=5)

    assert results, "expected Quick Mode fallback results"
    assert all(result["deep_mode_fallback"] == "no_communities" for result in results)
    assert all(result.get("source") != "community_summary" for result in results)


def test_reflections_can_be_included(database_path: Path) -> None:
    """Relevant reflections are surfaced alongside community summaries."""
    _community(
        "Persistence Architecture",
        "SQLite stores durable memory while indexes stay rebuildable.",
        ["node_1", "node_2"],
    )
    reflection_id = _reflection(
        "self_knowledge",
        "The project prefers repository helpers over ad-hoc SQLite access.",
        0.86,
    )

    results = retrieve_deep("repository helpers and SQLite preferences", None, limit=10)

    sources = {str(result["source"]) for result in results}
    assert "community_summary" in sources
    assert "reflection" in sources
    reflection_ids = {
        str(result["source_id"]) for result in results if result["source"] == "reflection"
    }
    assert reflection_id in reflection_ids


def test_stale_reflection_is_not_included(database_path: Path) -> None:
    """Only active reflections are eligible for Deep Mode synthesis."""
    _community("Topic", "A summary about caching and retrieval performance.", ["node_1", "node_2"])
    create_reflection(
        {
            "reflection_type": "self_knowledge",
            "content": "Stale belief about caching and retrieval that should be excluded.",
            "confidence": 0.9,
            "status": "stale",
        }
    )

    results = retrieve_deep("caching and retrieval", None, limit=10)

    assert all(result["source"] != "reflection" for result in results)


def test_empty_query_returns_nothing(database_path: Path) -> None:
    """A blank query yields no Deep Mode results."""
    _community("Topic", "Some summary.", ["node_1", "node_2"])
    assert retrieve_deep("   ", None, limit=5) == []
