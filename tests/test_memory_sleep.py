"""Verify the bounded deterministic memory-sleep integration."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from core.db.repositories import (
    configure_database,
    create_atomic_fact,
    create_reflection,
    create_session,
    link_reflection_evidence,
    repository_connection,
    save_observation,
)
from core.db.schema import LEGACY_WORKSPACE_ID
from core.memory import slow_path


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    """Configure one isolated SQLite database for each sleep test."""
    path = tmp_path / "mira.sqlite3"
    configure_database(path)
    yield path


def _status(table: str, record_id: str) -> str:
    with repository_connection() as connection:
        row = connection.execute(
            f"SELECT status FROM {table} WHERE id = ?", (record_id,)
        ).fetchone()
    return str(row["status"])


def _fact(
    observation_id: str,
    object_value: str,
) -> str:
    return create_atomic_fact(
        {
            "subject": "user",
            "predicate": "uses",
            "object": object_value,
            "confidence": 0.9,
            "source_observation_id": observation_id,
        }
    )


def test_sleep_is_bounded_and_calls_lifecycle_once(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A capped sleep examines only its cap and invokes lifecycle once."""
    calls: list[tuple[str, str, int]] = []
    monkeypatch.setattr(
        slow_path,
        "run_memory_sleep",
        lambda workspace_id, max_items, *, now: (
            calls.append((now, workspace_id, max_items)) or {"evaluated": 0, "weakened": 0}
        ),
    )
    session_id = create_session("jerry")
    observation_ids = [
        save_observation(session_id, "user", "One"),
        save_observation(session_id, "user", "Two"),
        save_observation(session_id, "user", "Three"),
    ]
    for observation_id, value in zip(observation_ids, ("one", "two", "three"), strict=True):
        _fact(observation_id, value)

    result = slow_path.run_memory_sleep_once(
        max_items=2,
        now="2026-01-01T00:00:00+00:00",
    )

    assert result["max_items"] == 2
    assert result["facts_reviewed"] == 2
    assert result["reflections_reviewed"] == 0
    assert calls == [("2026-01-01T00:00:00+00:00", LEGACY_WORKSPACE_ID, 2)]


def test_sleep_refreshes_changes_and_reflections_idempotently(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sleep consolidates a deterministic change and invalidates its old reflection once."""
    lifecycle_calls: list[str] = []
    monkeypatch.setattr(
        slow_path,
        "run_memory_sleep",
        lambda workspace_id, max_items, *, now: (
            lifecycle_calls.append(workspace_id) or {"evaluated": 0, "weakened": 0}
        ),
    )
    session_id = create_session("jerry")
    old_observation = save_observation(session_id, "user", "The database is PostgreSQL.")
    new_observation = save_observation(
        session_id,
        "user",
        "The database changed from PostgreSQL to SQLite.",
    )
    old_fact = _fact(old_observation, "PostgreSQL")
    new_fact = _fact(new_observation, "SQLite")
    reflection_id = create_reflection(
        {
            "reflection_type": "user_knowledge",
            "content": "The user's database choice is durable context.",
            "confidence": 0.9,
            "status": "active",
        }
    )
    link_reflection_evidence(reflection_id, old_observation)

    # Make ordering explicit so the test does not depend on clock resolution.
    with repository_connection() as connection:
        connection.execute(
            "UPDATE observations SET created_at = ? WHERE id = ?",
            ("2026-01-01T00:00:00+00:00", old_observation),
        )
        connection.execute(
            "UPDATE observations SET created_at = ? WHERE id = ?",
            ("2026-01-02T00:00:00+00:00", new_observation),
        )
        connection.execute(
            "UPDATE atomic_facts SET created_at = ? WHERE id = ?",
            ("2026-01-01T00:00:00+00:00", old_fact),
        )
        connection.execute(
            "UPDATE atomic_facts SET created_at = ? WHERE id = ?",
            ("2026-01-02T00:00:00+00:00", new_fact),
        )

    first = slow_path.run_memory_sleep_once(max_items=10, now="2026-01-03T00:00:00+00:00")
    second = slow_path.run_memory_sleep_once(max_items=10, now="2026-01-03T00:00:00+00:00")

    assert first["changes_found"] == 1
    assert first["changes_applied"] == 1
    assert first["reflections_updated"] == 1
    assert _status("atomic_facts", old_fact) == "superseded"
    assert _status("atomic_facts", new_fact) == "active"
    assert _status("reflections", reflection_id) == "invalidated"
    assert second["changes_found"] == 0
    assert second["changes_applied"] == 0
    assert second["reflections_updated"] == 0
    assert lifecycle_calls == [LEGACY_WORKSPACE_ID, LEGACY_WORKSPACE_ID]
