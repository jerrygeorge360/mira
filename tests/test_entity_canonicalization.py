"""Verify the ISSUE-025 entity extraction and canonicalization path.

Ownership: MIRA contributors.
Related issue: ISSUE-025.
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
from core.memory import graph
from core.memory.graph import canonicalize_entity, extract_entities, link_entity_mention


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    """Configure entity tests to use an isolated SQLite database."""
    path = tmp_path / "mira.sqlite3"
    configure_database(path)
    yield path


def test_same_entity_name_resolves_to_same_id(database_path: Path) -> None:
    """Exact entity names are canonicalized to the same SQLite entity ID."""
    first_id = canonicalize_entity("MIRA")
    second_id = canonicalize_entity("MIRA")

    assert first_id == second_id
    assert _entity_count() == 1


def test_alias_resolves_correctly(database_path: Path) -> None:
    """Known aliases resolve to the canonical entity instead of creating duplicates."""
    entity_id = canonicalize_entity("Session Working Set", aliases=["SWS"])
    alias_id = canonicalize_entity("SWS")

    assert alias_id == entity_id
    assert _entity_count() == 1
    assert "SWS" in _entity_aliases(entity_id)


def test_ambiguous_entity_does_not_force_bad_merge(database_path: Path) -> None:
    """Different ambiguous names do not merge without exact or alias evidence."""
    first_id = canonicalize_entity("Apple")
    second_id = canonicalize_entity("Apple Records")

    assert first_id != second_id
    assert _entity_count() == 2


def test_extract_entities_canonicalizes_model_output(
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Entity extraction uses Qwen output but normalizes identity through SQLite."""
    monkeypatch.setattr(
        graph,
        "call_qwen_json",
        lambda messages, schema_name: {
            "json": {
                "entities": [
                    {"name": "ChromaDB", "entity_type": "technology", "aliases": ["Chroma"]},
                    {"name": "Relational Mode", "entity_type": "system_concept", "aliases": []},
                ]
            }
        },
    )

    entities = extract_entities("ChromaDB supports Relational Mode retrieval.")

    assert [entity["name"] for entity in entities] == ["ChromaDB", "Relational Mode"]
    assert len({entity["id"] for entity in entities}) == 2
    assert _entity_count() == 2


def test_link_entity_mention_creates_graph_node(database_path: Path) -> None:
    """Entity mentions can be linked to observations without graph traversal."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "MIRA uses SQLite.")
    entity_id = canonicalize_entity("MIRA")

    node_id = link_entity_mention(entity_id, observation_id)

    with repository_connection() as connection:
        row = connection.execute("SELECT * FROM graph_nodes WHERE id = ?", (node_id,)).fetchone()
    assert row is not None
    assert row["node_type"] == "entity"
    assert row["source_id"] == entity_id


def _entity_count() -> int:
    with repository_connection() as connection:
        row = connection.execute("SELECT COUNT(*) AS count FROM entities").fetchone()
    assert row is not None
    return int(row["count"])


def _entity_aliases(entity_id: str) -> list[str]:
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT aliases_json FROM entities WHERE id = ?",
            (entity_id,),
        ).fetchone()
    assert row is not None
    aliases = row["aliases_json"]
    assert isinstance(aliases, str)
    import json

    decoded = json.loads(aliases)
    assert isinstance(decoded, list)
    return [alias for alias in decoded if isinstance(alias, str)]
