"""Verify ISSUE-015 cross-session Session Working Set hydration.

Ownership: MIRA contributors.
Related issue: ISSUE-015.
Architecture area: session micro-path.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from core.db.repositories import (
    configure_database,
    create_reflection,
    create_session,
    create_working_memory_item,
    save_observation,
)
from core.session.hydration import hydrate_session_from_memory
from core.session.working_set import list_active_session_items, upsert_session_item


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    """Configure hydration tests to use an isolated database."""
    path = tmp_path / "mira.sqlite3"
    configure_database(path)
    yield path


def _hot_item(content: str, memory_type: str = "project_constraint", scope: str = "project") -> str:
    return create_working_memory_item(
        {
            "content": content,
            "memory_type": memory_type,
            "scope": scope,
            "priority": 0.9,
            "status": "active",
        }
    )


def _hydrated_items(session_id: str) -> list[dict[str, object]]:
    return [
        item
        for item in list_active_session_items(session_id)
        if item["origin"] == "cross_session_hydration"
    ]


def test_empty_session_hydrates_project_state(database_path: Path) -> None:
    """A new empty session is seeded from durable hot memory."""
    _hot_item("Keep MIRA session memory separate from durable tiers.")
    session_id = create_session("jerry")

    hydrated_ids = hydrate_session_from_memory(session_id, "let's keep working on MIRA", 10)

    assert hydrated_ids
    items = _hydrated_items(session_id)
    assert {item["id"] for item in items} == set(hydrated_ids)
    assert all(item["status"] == "hydrated" for item in items)
    assert all(item["origin"] == "cross_session_hydration" for item in items)
    assert any("durable tiers" in str(item["content"]) for item in items)


def test_continue_from_where_we_stopped_retrieves_relevant_memory(database_path: Path) -> None:
    """A continuation request hydrates the matching durable design state."""
    _hot_item("MIRA must page context to avoid context overflow in long sessions.")
    _hot_item("Unrelated billing invoice formatting rule.", memory_type="behavioral_instruction")
    create_reflection(
        {
            "reflection_type": "self_knowledge",
            "content": "The MIRA context overflow work favors summary paging.",
            "confidence": 0.82,
            "status": "active",
        }
    )
    session_id = create_session("jerry")

    hydrated_ids = hydrate_session_from_memory(
        session_id, "Continue from where we stopped on MIRA context overflow.", 10
    )

    contents = [str(item["content"]) for item in _hydrated_items(session_id)]
    assert hydrated_ids
    assert any("context overflow" in content for content in contents)
    assert not any("billing invoice" in content for content in contents)


def test_current_session_correction_overrides_hydrated_item(database_path: Path) -> None:
    """A current-session correction is not overridden by a conflicting durable item."""
    _hot_item("Store MIRA context in MongoDB.", memory_type="confirmed_correction")
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "Store MIRA context in PostgreSQL.")
    correction_id = upsert_session_item(
        session_id,
        {
            "type": "correction",
            "content": "Store MIRA context in PostgreSQL, not MongoDB.",
            "scope": "project",
            "status": "confirmed",
            "priority": 0.95,
            "explicitness_label": "direct_correction",
            "evidence_span": "Store MIRA context in PostgreSQL.",
            "source_observations": [observation_id],
            "supersedes": [],
        },
    )

    hydrate_session_from_memory(session_id, "continue MIRA storage work", 10)

    contents = [str(item["content"]) for item in list_active_session_items(session_id)]
    assert "Store MIRA context in PostgreSQL, not MongoDB." in contents
    assert not any("MongoDB." in content and "PostgreSQL" not in content for content in contents)
    # The current-session correction is untouched (same id, not hydrated).
    correction = next(
        item for item in list_active_session_items(session_id) if item["id"] == correction_id
    )
    assert correction["origin"] == "micro_path"
    assert correction["status"] == "confirmed"


def test_hot_memory_preserves_source_correction_provenance(database_path: Path) -> None:
    """Hydration keeps correction type and explicitness from the source session item."""
    source_session_id = create_session("jerry")
    observation_id = save_observation(
        source_session_id,
        "user",
        "Use 2026, not 2025, for all MIRA dates.",
    )
    source_item_id = upsert_session_item(
        source_session_id,
        {
            "type": "correction",
            "content": "Use 2026, not 2025, for all MIRA dates.",
            "scope": "project",
            "status": "confirmed",
            "priority": 0.96,
            "explicitness_label": "direct_correction",
            "evidence_span": "Use 2026, not 2025, for all MIRA dates.",
            "source_observations": [observation_id],
            "supersedes": [],
        },
    )
    create_working_memory_item(
        {
            "content": "Use 2026, not 2025, for all MIRA dates.",
            "memory_type": "project_constraint",
            "scope": "project",
            "priority": 0.9,
            "status": "active",
            "source_record_type": "session_working_set",
            "source_record_id": source_item_id,
        }
    )
    new_session_id = create_session("jerry")

    hydrate_session_from_memory(new_session_id, "continue MIRA date work", 10)

    hydrated = _hydrated_items(new_session_id)
    assert hydrated
    assert hydrated[0]["type"] == "correction"
    assert hydrated[0]["explicitness_label"] == "direct_correction"
    assert hydrated[0]["source_observations"] == [observation_id]


def test_no_relevant_memory_results_in_no_hydration(database_path: Path) -> None:
    """With no durable memory, hydration adds nothing."""
    session_id = create_session("jerry")

    assert hydrate_session_from_memory(session_id, "anything at all", 10) == []
    assert _hydrated_items(session_id) == []


def test_max_items_must_be_positive(database_path: Path) -> None:
    """A non-positive max_items is rejected."""
    session_id = create_session("jerry")
    with pytest.raises(ValueError, match="max_items"):
        hydrate_session_from_memory(session_id, "anything", 0)
