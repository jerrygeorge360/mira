"""Focused coverage for automatic memory-sleep scheduling and run history."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest

from core.db.repositories import (
    configure_database,
    create_session,
    create_workspace,
    repository_connection,
    save_observation,
)
from core.memory import sleep_scheduler
from core.memory.lifecycle import ensure_memory_state, forget_memory_by_id

NOW = "2026-01-01T00:00:00+00:00"


@pytest.fixture(scope="module")
def database_path(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    path = tmp_path_factory.mktemp("memory-sleep") / "mira.sqlite3"
    configure_database(path)
    yield path


@pytest.fixture
def workspace(database_path: Path) -> str:
    workspace_id = f"sleep-test-{uuid4().hex}"
    create_workspace(
        "Sleep test workspace",
        workspace_id,
        "development",
        workspace_id=workspace_id,
    )
    return workspace_id


def test_schedule_due_disabled_and_interval_change(database_path: Path, workspace: str) -> None:
    config = sleep_scheduler.get_sleep_config(workspace, now=NOW)
    assert config["enabled"] is True
    assert config["next_sleep_at"] == "2026-01-01T06:00:00+00:00"

    before_due = sleep_scheduler.maybe_run_scheduled_sleep(
        workspace, now="2026-01-01T05:59:00+00:00"
    )
    assert before_due["status"] == "not_due"

    disabled = sleep_scheduler.update_sleep_config(workspace, enabled=False, now=NOW)
    assert disabled["next_sleep_at"] is None
    assert (
        sleep_scheduler.maybe_run_scheduled_sleep(workspace, now="2026-01-02T00:00:00+00:00")[
            "status"
        ]
        == "disabled"
    )

    changed = sleep_scheduler.update_sleep_config(
        workspace, enabled=True, interval_hours=2, now=NOW
    )
    assert changed["next_sleep_at"] == "2026-01-01T02:00:00+00:00"

    completed = sleep_scheduler.maybe_run_scheduled_sleep(
        workspace, now="2026-01-01T02:00:00+00:00"
    )
    assert completed["status"] == "completed"
    assert completed["trigger"] == "automatic"


def test_run_records_snapshots_changes_and_history(database_path: Path, workspace: str) -> None:
    session_id = create_session("jerry", workspace_id=workspace)
    observation_id = save_observation(session_id, "user", "The project uses SQLite.")
    state = ensure_memory_state("observations", observation_id, workspace)
    with repository_connection() as connection:
        connection.execute(
            "UPDATE memory_state SET failed_uses = 1 WHERE id = ?",
            (state["id"],),
        )

    result = sleep_scheduler.run_scheduled_sleep(
        workspace, max_items=10, now="2030-01-01T00:00:00+00:00"
    )

    assert result["status"] == "completed"
    assert result["before"]["active_memories"] == 1
    assert result["after"]["active_memories"] + result["after"]["weakening_memories"] == 1
    assert result["sleep_run_id"]
    assert any(change["memory_id"] == state["id"] for change in result["changes"])

    history = sleep_scheduler.list_sleep_runs(workspace)
    assert history["total"] == 1
    saved = sleep_scheduler.get_sleep_run(result["sleep_run_id"], workspace)
    assert saved is not None
    assert saved["before"]["active_memories"] == 1
    assert saved["after"]["active_memories"] + saved["after"]["weakening_memories"] == 1


def test_manual_and_automatic_runs_are_single_flight(database_path: Path, workspace: str) -> None:
    config = sleep_scheduler.get_sleep_config(workspace, now=NOW)
    running = sleep_scheduler._begin_run(
        workspace, "manual", 10, config, sleep_scheduler._parse_time(NOW)
    )

    result = sleep_scheduler.run_scheduled_sleep(workspace, now=NOW)

    assert running["status"] == "running"
    assert result["status"] == "already_running"
    assert result["sleep_run_id"] == running["sleep_run_id"]

    with repository_connection() as connection:
        connection.execute(
            "UPDATE memory_sleep_runs SET status = 'failed', finished_at = ?, error = ? "
            "WHERE id = ?",
            (NOW, "test cleanup", running["sleep_run_id"]),
        )


def test_stale_running_run_is_recorded_failed_before_retry(
    database_path: Path, workspace: str
) -> None:
    config = sleep_scheduler.get_sleep_config(workspace, now=NOW)
    running = sleep_scheduler._begin_run(
        workspace, "automatic", 10, config, sleep_scheduler._parse_time(NOW)
    )

    retried = sleep_scheduler.maybe_run_scheduled_sleep(workspace, now="2026-01-02T01:00:00+00:00")

    assert retried["status"] == "completed"
    stale = sleep_scheduler.get_sleep_run(running["sleep_run_id"], workspace)
    assert stale is not None
    assert stale["status"] == "failed"
    assert "interrupted" in str(stale["error"])


def test_failed_run_is_recorded_without_raising(database_path: Path, workspace: str) -> None:
    def fail(*args: object, **kwargs: object) -> dict[str, object]:
        raise RuntimeError("synthetic sleep failure")

    result = sleep_scheduler.run_scheduled_sleep(
        workspace,
        now=NOW,
        lifecycle_runner=fail,
    )

    assert result["status"] == "failed"
    assert "synthetic sleep failure" in str(result["errors"])
    saved = sleep_scheduler.get_sleep_run(result["sleep_run_id"], workspace)
    assert saved is not None
    assert saved["status"] == "failed"
    assert "synthetic sleep failure" in str(saved["error"])


def test_forgotten_memory_stays_forgotten_and_is_not_strengthened(
    database_path: Path, workspace: str
) -> None:
    session_id = create_session("jerry", workspace_id=workspace)
    observation_id = save_observation(session_id, "user", "Forget this detail.")
    state = ensure_memory_state("observations", observation_id, workspace)
    forgotten = forget_memory_by_id(state["id"], workspace)
    assert forgotten["lifecycle_status"] == "forgotten"

    result = sleep_scheduler.run_scheduled_sleep(workspace, now="2030-01-01T00:00:00+00:00")

    assert result["before"]["forgotten_memories"] == 1
    assert result["after"]["forgotten_memories"] == 1
    assert not any(change["memory_id"] == state["id"] for change in result["changes"])
