"""Verify the ISSUE-023 slow-path worker skeleton.

Ownership: MIRA contributors.
Related issue: ISSUE-023.
Architecture area: slow path.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from core.db.repositories import (
    configure_database,
    create_session,
    enqueue_observation,
    repository_connection,
    save_observation,
)
from core.memory import slow_path
from core.memory.slow_path import (
    SlowPathBatch,
    SlowPathStepResult,
    register_slow_path_step,
    run_slow_path_once,
)


class MockWorkerStep:
    """Slow-path worker test step with configurable output."""

    def __init__(
        self,
        step_name: str,
        *,
        created_record_ids: list[str] | None = None,
        failed_observation_ids: list[str] | None = None,
        error_message: str | None = None,
    ) -> None:
        self.step_name = step_name
        self.created_record_ids = created_record_ids or []
        self.failed_observation_ids = failed_observation_ids or []
        self.error_message = error_message
        self.seen_batches: list[SlowPathBatch] = []

    def run(self, batch: SlowPathBatch) -> SlowPathStepResult:
        """Return a deterministic result for worker orchestration tests."""
        self.seen_batches.append(batch)
        return SlowPathStepResult(
            step_name=self.step_name,
            succeeded=not self.failed_observation_ids,
            created_record_ids=self.created_record_ids,
            failed_observation_ids=self.failed_observation_ids,
            error_message=self.error_message,
        )


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    """Configure worker tests to use an isolated SQLite database."""
    path = tmp_path / "mira.sqlite3"
    configure_database(path)
    slow_path.REGISTERED_SLOW_PATH_STEPS.clear()
    yield path
    slow_path.REGISTERED_SLOW_PATH_STEPS.clear()


def test_worker_can_process_batch_with_mocked_steps(database_path: Path) -> None:
    """A claimed queue batch is passed to registered steps in order."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "Remember this across sessions.")
    queue_id = enqueue_observation(observation_id)
    first_step = MockWorkerStep("embedding_index", created_record_ids=["vec_1"])
    second_step = MockWorkerStep("atomic_fact_extraction", created_record_ids=["fact_1"])
    register_slow_path_step(first_step)
    register_slow_path_step(second_step)

    results = run_slow_path_once(batch_size=10)

    assert [result["step_name"] for result in results] == [
        "embedding_index",
        "atomic_fact_extraction",
    ]
    assert first_step.seen_batches[0].observation_ids == [observation_id]
    assert first_step.seen_batches[0].session_id == session_id
    assert second_step.seen_batches[0] == first_step.seen_batches[0]
    assert _queue_status(queue_id) == "done"


def test_failed_step_marks_item_failed(database_path: Path) -> None:
    """A failed step result marks the corresponding queue item failed."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "This extraction will fail.")
    queue_id = enqueue_observation(observation_id)
    register_slow_path_step(
        MockWorkerStep(
            "atomic_fact_extraction",
            failed_observation_ids=[observation_id],
            error_message="parse failed",
        )
    )

    results = run_slow_path_once(batch_size=10)

    queue_record = _queue_record(queue_id)
    assert results[0]["succeeded"] is False
    assert queue_record["status"] == "failed"
    assert queue_record["last_error"] == "parse failed"


def test_retry_path_reprocesses_failed_items(database_path: Path) -> None:
    """Failed jobs are claimable again and can later be marked done."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "Retry this job.")
    queue_id = enqueue_observation(observation_id)
    register_slow_path_step(
        MockWorkerStep(
            "entity_extraction",
            failed_observation_ids=[observation_id],
            error_message="temporary failure",
        )
    )
    run_slow_path_once(batch_size=10)
    assert _queue_record(queue_id)["attempt_count"] == 1

    slow_path.REGISTERED_SLOW_PATH_STEPS.clear()
    register_slow_path_step(MockWorkerStep("entity_extraction", created_record_ids=["entity_1"]))
    retry_results = run_slow_path_once(batch_size=10)

    queue_record = _queue_record(queue_id)
    assert retry_results[0]["created_record_ids"] == ["entity_1"]
    assert queue_record["status"] == "done"
    assert queue_record["attempt_count"] == 2
    assert queue_record["last_error"] is None


def test_done_path_marks_all_successful_items_done(database_path: Path) -> None:
    """Successful batches mark all claimed queue records done."""
    session_id = create_session("jerry")
    first_observation_id = save_observation(session_id, "user", "First queued item.")
    second_observation_id = save_observation(session_id, "assistant", "Second queued item.")
    first_queue_id = enqueue_observation(first_observation_id)
    second_queue_id = enqueue_observation(second_observation_id)
    register_slow_path_step(MockWorkerStep("graph_update", created_record_ids=["edge_1"]))

    run_slow_path_once(batch_size=10)

    assert _queue_status(first_queue_id) == "done"
    assert _queue_status(second_queue_id) == "done"


def _queue_status(queue_id: str) -> str:
    return str(_queue_record(queue_id)["status"])


def _queue_record(queue_id: str) -> dict[str, object]:
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT * FROM slow_path_queue WHERE id = ?",
            (queue_id,),
        ).fetchone()
    assert row is not None
    return dict(row)
