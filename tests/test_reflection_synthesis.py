"""Verify ISSUE-028 evidence-backed reflection synthesis.

Ownership: MIRA contributors.
Related issue: ISSUE-028.
Architecture area: slow path.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from core.db.repositories import (
    configure_database,
    create_session,
    repository_connection,
    save_observation,
)
from core.memory import reflection
from core.memory.graph import find_edges_by_type
from core.memory.reflection import (
    should_reflect,
    store_reflection_with_evidence,
    synthesize_reflections,
)


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    """Configure reflection tests to use an isolated database."""
    path = tmp_path / "mira.sqlite3"
    configure_database(path)
    yield path


def _qwen_reflections(reflections: list[dict[str, object]]):
    def _fake(messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
        assert schema_name == "reflection_synthesis"
        return {"json": {"reflections": reflections}}

    return _fake


def _reflection_evidence_ids(reflection_id: str) -> list[str]:
    with repository_connection() as connection:
        rows = connection.execute(
            "SELECT observation_id FROM reflection_evidence WHERE reflection_id = ?",
            (reflection_id,),
        ).fetchall()
    return [str(row["observation_id"]) for row in rows]


def _graph_node_source_id(node_id: str) -> str:
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT source_id FROM graph_nodes WHERE id = ?",
            (node_id,),
        ).fetchone()
    assert row is not None
    return str(row["source_id"])


def test_should_reflect_requires_important_observations() -> None:
    """Reflection triggers on multiple important or one highly important observation."""
    assert should_reflect(["a", "b"], {"a": 0.6, "b": 0.7}) is True
    assert should_reflect(["a"], {"a": 0.9}) is True
    assert should_reflect(["a", "b"], {"a": 0.1, "b": 0.2}) is False
    assert should_reflect([], {"a": 1.0}) is False


def test_reflection_contains_type_content_confidence_and_evidence(
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Synthesis returns source-backed reflections with the required fields."""
    session_id = create_session("jerry")
    observation_id = save_observation(
        session_id, "user", "Use repository helpers instead of ad-hoc SQL."
    )
    monkeypatch.setattr(
        reflection,
        "call_qwen_json",
        _qwen_reflections(
            [
                {
                    "reflection_type": "self_knowledge",
                    "content": "The project prefers repository APIs over ad-hoc SQL.",
                    "confidence": 0.86,
                    "evidence_ids": [observation_id],
                }
            ]
        ),
    )

    reflections = synthesize_reflections([observation_id])

    assert len(reflections) == 1
    result = reflections[0]
    assert {"reflection_type", "content", "confidence", "evidence_ids"} <= set(result)
    assert result["reflection_type"] == "self_knowledge"
    assert result["confidence"] == 0.86
    assert result["evidence_ids"] == [observation_id]
    assert result["hot_memory_candidate"] is True


def test_derived_from_relation_is_created(database_path: Path) -> None:
    """Storing a reflection writes evidence rows and a DERIVED_FROM graph edge."""
    session_id = create_session("jerry")
    observation_id = save_observation(
        session_id, "user", "Sessions stay separate from durable memory."
    )

    reflection_id = store_reflection_with_evidence(
        {
            "reflection_type": "self_knowledge",
            "content": "Session state is isolated from durable tiers.",
            "confidence": 0.8,
        },
        [observation_id],
    )

    assert _reflection_evidence_ids(reflection_id) == [observation_id]
    edges = find_edges_by_type("DERIVED_FROM")
    assert len(edges) == 1
    assert _graph_node_source_id(str(edges[0]["source_node_id"])) == reflection_id
    assert _graph_node_source_id(str(edges[0]["target_node_id"])) == observation_id
    assert edges[0]["source_observations"] == [observation_id]


def test_ungrounded_reflection_is_rejected(
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reflection citing no real observation is dropped as unsupported."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "Prefer SQLite as the source of truth.")
    monkeypatch.setattr(
        reflection,
        "call_qwen_json",
        _qwen_reflections(
            [
                {
                    "reflection_type": "world_knowledge",
                    "content": "Hallucinated claim with no real evidence.",
                    "confidence": 0.9,
                    "evidence_ids": ["does-not-exist"],
                }
            ]
        ),
    )

    assert synthesize_reflections([observation_id]) == []


def test_unsupported_personality_reflection_is_rejected(
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A grounded but personality-style reflection is still rejected."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "I forgot to run the tests again.")
    monkeypatch.setattr(
        reflection,
        "call_qwen_json",
        _qwen_reflections(
            [
                {
                    "reflection_type": "user_knowledge",
                    "content": "Jerry is careless about testing.",
                    "confidence": 0.9,
                    "evidence_ids": [observation_id],
                }
            ]
        ),
    )

    assert synthesize_reflections([observation_id]) == []


def test_world_knowledge_reflection_is_rejected(
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ordinary world knowledge belongs in facts/answers, not reflections."""
    session_id = create_session("jerry")
    observation_id = save_observation(
        session_id, "user", "The principles of democracy include voting and representation."
    )
    monkeypatch.setattr(
        reflection,
        "call_qwen_json",
        _qwen_reflections(
            [
                {
                    "reflection_type": "world_knowledge",
                    "content": "The principles of democracy include voting and representation.",
                    "confidence": 0.9,
                    "evidence_ids": [observation_id],
                }
            ]
        ),
    )

    assert synthesize_reflections([observation_id]) == []


def test_store_rejects_unsourced_reflection(database_path: Path) -> None:
    """Persistence refuses reflections without an existing evidence observation."""
    with pytest.raises(ValueError, match="source-backed"):
        store_reflection_with_evidence(
            {
                "reflection_type": "self_knowledge",
                "content": "Unsourced reflection.",
                "confidence": 0.8,
            },
            ["missing-observation"],
        )
