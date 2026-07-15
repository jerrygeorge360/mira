"""Verify ISSUE-124 slow-path worker runtime.

Ownership: MIRA contributors.
Related issue: ISSUE-124.
Architecture area: worker.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

import core.memory.slow_path as sp
from core.db.repositories import (
    configure_database,
    create_session,
    enqueue_observation,
    repository_connection,
    save_observation,
)
from core.memory.slow_path import (
    get_slow_path_queue_status,
    run_slow_path_loop,
    run_worker,
    run_worker_once,
)
from scripts import run_worker as worker_cli

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    """Configure worker tests to use an isolated database."""
    path = tmp_path / "mira.sqlite3"
    configure_database(path)
    yield path


@pytest.fixture
def stub_extraction(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the slow path's LLM extraction so the worker runs offline."""

    def _facts(observation_id: str, content: str) -> list[dict[str, object]]:
        return [
            {
                "subject": "user",
                "predicate": "SAID",
                "object": content[:40],
                "confidence": 0.9,
                "source_observation_id": observation_id,
            }
        ]

    monkeypatch.setattr(sp, "extract_atomic_facts", _facts)
    monkeypatch.setattr(sp, "extract_entities", lambda text, **kwargs: [])


def _enqueue(session_id: str, content: str) -> str:
    observation_id = save_observation(session_id, "user", content)
    enqueue_observation(observation_id)
    return observation_id


def _queue_status(observation_id: str) -> str:
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT status FROM slow_path_queue WHERE observation_id = ?",
            (observation_id,),
        ).fetchone()
    return str(row["status"])


def _queue_last_error(observation_id: str) -> str | None:
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT last_error FROM slow_path_queue WHERE observation_id = ?",
            (observation_id,),
        ).fetchone()
    return str(row["last_error"]) if row and row["last_error"] is not None else None


def _fact_count(observation_id: str) -> int:
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT COUNT(*) FROM atomic_facts WHERE source_observation_id = ?",
            (observation_id,),
        ).fetchone()
    return int(row[0])


def test_worker_processes_queued_observations(database_path: Path, stub_extraction: None) -> None:
    """The worker drains pending observations and marks them done."""
    session_id = create_session("jerry")
    obs_one = _enqueue(session_id, "We use PostgreSQL.")
    obs_two = _enqueue(session_id, "The deadline is Friday.")

    summary = run_worker_once()

    assert summary["processed"] == 2
    assert _queue_status(obs_one) == "done"
    assert _queue_status(obs_two) == "done"


def test_worker_uses_orchestrator_batch_path(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The worker processes through run_slow_path_batch, not the empty registry."""
    calls = {"n": 0}

    def _spy(batch_size: int) -> list[dict[str, object]]:
        calls["n"] += 1
        return []

    monkeypatch.setattr(sp, "run_slow_path_batch", _spy)
    run_worker_once()

    assert calls["n"] == 1
    assert sp.REGISTERED_SLOW_PATH_STEPS == []  # production path does not use it


def test_empty_queue_is_safe(database_path: Path) -> None:
    """Running with no pending work does not fail."""
    summary = run_worker_once()
    assert summary == {"processed": 0, "failed": 0, "iterations": 1}


def test_failed_observation_is_marked_failed(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An extraction failure is visible as a failed, retryable queue item."""
    session_id = create_session("jerry")
    observation_id = _enqueue(session_id, "trigger a failure")

    def _boom(observation_id: str, content: str) -> list[dict[str, object]]:
        raise RuntimeError("extraction boom")

    monkeypatch.setattr(sp, "extract_atomic_facts", _boom)
    monkeypatch.setattr(sp, "extract_entities", lambda text, **kwargs: [])

    summary = run_worker_once()

    assert summary["failed"] == 1
    assert _queue_status(observation_id) == "failed"
    assert _queue_last_error(observation_id) == "extraction boom"


def test_one_bad_item_does_not_stop_batch(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failing observation does not prevent others in the batch from processing."""
    session_id = create_session("jerry")
    good = _enqueue(session_id, "good observation")
    bad = _enqueue(session_id, "BAD observation")

    def _facts(observation_id: str, content: str) -> list[dict[str, object]]:
        if "BAD" in content:
            raise RuntimeError("bad item")
        return []

    monkeypatch.setattr(sp, "extract_atomic_facts", _facts)
    monkeypatch.setattr(sp, "extract_entities", lambda text, **kwargs: [])

    summary = run_worker_once()

    assert summary["processed"] == 1
    assert summary["failed"] == 1
    assert _queue_status(good) == "done"
    assert _queue_status(bad) == "failed"


def test_idempotent_rerun(database_path: Path, stub_extraction: None) -> None:
    """Re-running the worker does not duplicate durable facts."""
    session_id = create_session("jerry")
    observation_id = _enqueue(session_id, "We use PostgreSQL.")

    run_worker_once()
    assert _fact_count(observation_id) == 1

    second = run_worker_once()
    assert second["processed"] == 0  # already done; not reclaimed
    assert _fact_count(observation_id) == 1


def test_cli_once_processes_a_batch(
    database_path: Path, monkeypatch: pytest.MonkeyPatch, stub_extraction: None
) -> None:
    """The CLI --once processes one batch and exits cleanly."""
    session_id = create_session("jerry")
    observation_id = _enqueue(session_id, "We use PostgreSQL.")

    exit_code = worker_cli.main(["--once", "--db", str(database_path)])

    assert exit_code == 0
    assert _queue_status(observation_id) == "done"


def test_run_slow_path_loop_uses_batch_path(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """run_slow_path_loop invokes the orchestrator-backed batch, not the registry."""
    calls = {"n": 0}

    def _spy(batch_size: int) -> list[dict[str, object]]:
        calls["n"] += 1
        return []

    monkeypatch.setattr(sp, "run_slow_path_batch", _spy)
    run_slow_path_loop(1, 0.0, max_iterations=1)

    assert calls["n"] == 1


def test_graceful_shutdown_on_interrupt(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A KeyboardInterrupt stops the worker without corrupting state or raising."""

    def _interrupt(batch_size: int) -> list[dict[str, object]]:
        raise KeyboardInterrupt

    monkeypatch.setattr(sp, "run_slow_path_batch", _interrupt)

    summary = run_worker(once=True)
    assert summary == {"processed": 0, "failed": 0, "iterations": 1}


def test_queue_status_helper_reports_counts(database_path: Path, stub_extraction: None) -> None:
    """get_slow_path_queue_status reports per-status counts."""
    session_id = create_session("jerry")
    _enqueue(session_id, "first")
    _enqueue(session_id, "second")
    assert get_slow_path_queue_status()["pending"] == 2

    run_worker_once()
    status = get_slow_path_queue_status()
    assert status["done"] == 2
    assert status["pending"] == 0
    assert set(status) == {
        "pending",
        "processing",
        "done",
        "failed",
        "dead_letter",
        "quarantined",
    }


def test_makefile_worker_target_points_to_runner() -> None:
    """The Makefile exposes a worker target wired to the entrypoint."""
    makefile = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "worker:" in makefile
    assert "scripts.run_worker" in makefile
    assert "worker     Run the slow-path background memory worker" in makefile
