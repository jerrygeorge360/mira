"""Focused tests for the additive memory lifecycle projection."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from core.db.repositories import (
    WorkspaceContext,
    bind_workspace,
    configure_database,
    create_session,
    create_workspace,
    repository_connection,
    save_observation,
)
from core.db.schema import MEMORY_LIFECYCLE_MIGRATION_ID, initialize_database
from core.db.sqlite import connect_sqlite
from core.memory.lifecycle import (
    archive_memory,
    ensure_memory_state,
    forget_memory,
    get_memory_state,
    lifecycle_for_retrieval,
    list_memory_states,
    record_feedback,
    record_retrieval,
    run_memory_sleep,
    runtime_trust,
)

LEGACY_WORKSPACE = "workspace_legacy_default"
NOW = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    path = tmp_path / "mira.sqlite3"
    configure_database(path)
    yield path


def test_lifecycle_schema_is_additive_and_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "schema.sqlite3"
    initialize_database(path)
    initialize_database(path)

    with connect_sqlite(path) as connection:
        tables = {
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        migration_count = connection.execute(
            "SELECT COUNT(*) AS count FROM schema_migrations WHERE id = ?",
            (MEMORY_LIFECYCLE_MIGRATION_ID,),
        ).fetchone()["count"]

    assert {"memory_state", "memory_reviews", "memory_sleep_runs"} <= tables
    assert migration_count == 1


def test_state_preserves_workspace_provenance_and_rejects_cross_workspace(
    database_path: Path,
) -> None:
    del database_path
    workspace_a = create_workspace("A", "lifecycle-a", "development")
    workspace_b = create_workspace("B", "lifecycle-b", "development")
    repo_a = bind_workspace(WorkspaceContext(workspace_a))
    repo_b = bind_workspace(WorkspaceContext(workspace_b))
    observation_a = repo_a.save_observation(
        repo_a.create_session("user-a"), "user", "Workspace A memory"
    )
    observation_b = repo_b.save_observation(
        repo_b.create_session("user-b"), "user", "Workspace B memory"
    )

    state = ensure_memory_state("observations", observation_a, workspace_a, "direct_user")

    assert state["workspace_id"] == workspace_a
    assert state["source_authority"] == "direct_user"
    with pytest.raises(ValueError, match="does not belong"):
        get_memory_state("observations", observation_a, workspace_b)
    with pytest.raises(ValueError, match="does not belong"):
        ensure_memory_state("observations", observation_b, workspace_a)


def test_archive_and_forget_filter_without_deleting_source(database_path: Path) -> None:
    session_id = create_session("user")
    observation_id = save_observation(session_id, "user", "Keep this historical row")
    ensure_memory_state("observations", observation_id, LEGACY_WORKSPACE)

    archived = archive_memory(
        "observations", observation_id, LEGACY_WORKSPACE, now="2026-01-02T00:00:00+00:00"
    )
    assert archived["lifecycle_status"] == "archived"
    assert list_memory_states(LEGACY_WORKSPACE, include_inactive=False) == []

    forgotten = forget_memory(
        "observations", observation_id, LEGACY_WORKSPACE, now="2026-01-03T00:00:00+00:00"
    )
    assert forgotten["lifecycle_status"] == "forgotten"
    assert len(list_memory_states(LEGACY_WORKSPACE, include_inactive=True)) == 1
    with repository_connection() as connection:
        source = connection.execute(
            "SELECT content FROM observations WHERE id = ?", (observation_id,)
        ).fetchone()
        events = connection.execute(
            "SELECT event_type FROM memory_reviews WHERE memory_state_id = ? ORDER BY created_at",
            (forgotten["id"],),
        ).fetchall()
    assert source is not None and source["content"] == "Keep this historical row"
    assert [str(event["event_type"]) for event in events] == ["archived", "forgotten"]


def test_retrieval_feedback_and_trust_are_persisted(database_path: Path) -> None:
    session_id = create_session("user")
    observation_id = save_observation(session_id, "user", "A remembered preference")
    state = ensure_memory_state("observations", observation_id, LEGACY_WORKSPACE)

    retrieved = record_retrieval("observations", observation_id, LEGACY_WORKSPACE)
    feedback = record_feedback(
        "observations",
        observation_id,
        LEGACY_WORKSPACE,
        answer_correct=True,
        verified=True,
        evidence={"source": "test"},
    )
    candidate = lifecycle_for_retrieval(
        "observations", observation_id, LEGACY_WORKSPACE, record={"updated_at": NOW.isoformat()}
    )
    trust = runtime_trust(feedback, freshness=1.0)

    assert retrieved["last_accessed_at"] is not None
    assert feedback["successful_uses"] == 1
    assert feedback["verification_count"] == 1
    assert feedback["refuted_count"] == 0
    assert candidate["eligible"] is True
    assert 0.0 <= trust <= 1.0
    with repository_connection() as connection:
        review_count = connection.execute(
            "SELECT COUNT(*) AS count FROM memory_reviews WHERE memory_state_id = ?",
            (state["id"],),
        ).fetchone()["count"]
    assert review_count == 2


def test_memory_sleep_is_bounded_and_idempotent(database_path: Path) -> None:
    session_id = create_session("user")
    first = save_observation(session_id, "user", "Old one")
    second = save_observation(session_id, "user", "Old two")
    ensure_memory_state(
        "observations", first, LEGACY_WORKSPACE, created_at="2025-01-01T00:00:00+00:00"
    )
    ensure_memory_state(
        "observations", second, LEGACY_WORKSPACE, created_at="2025-01-01T00:00:00+00:00"
    )

    first_pass = run_memory_sleep(LEGACY_WORKSPACE, 1, now=NOW)
    second_pass = run_memory_sleep(LEGACY_WORKSPACE, 1, now=NOW)

    assert first_pass["reviewed_count"] == 1
    assert second_pass["id"] == first_pass["id"]
    with repository_connection() as connection:
        run_count = connection.execute(
            "SELECT COUNT(*) AS count FROM memory_sleep_runs WHERE workspace_id = ?",
            (LEGACY_WORKSPACE,),
        ).fetchone()["count"]
    assert run_count == 1
    with pytest.raises(ValueError, match="positive"):
        run_memory_sleep(LEGACY_WORKSPACE, 0, now=NOW)
