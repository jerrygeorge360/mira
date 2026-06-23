"""Shared slow-path worker contract for cross-session memory processing.

Ownership: Jerry.
Related issue: ISSUE-022.
Architecture area: slow path.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from core.db.repositories import (
    claim_pending_batch,
    mark_done,
    mark_failed,
    repository_connection,
)

WorkerRunRecord = dict[str, object]

LOGGER = logging.getLogger(__name__)

SLOW_PATH_STEP_NAMES = frozenset(
    {
        "embedding_index",
        "atomic_fact_extraction",
        "entity_extraction",
        "graph_update",
        "foresight_detection",
        "contradiction_supersession_detection",
        "reflection_check",
        "tier_update",
        "community_update",
    }
)


@dataclass(frozen=True)
class SlowPathBatch:
    """Payload claimed by the worker and passed to each slow-path step."""

    batch_id: str
    observation_ids: list[str]
    session_id: str | None


@dataclass(frozen=True)
class SlowPathStepResult:
    """Result returned by one slow-path memory-processing step."""

    step_name: str
    succeeded: bool
    created_record_ids: list[str]
    failed_observation_ids: list[str]
    error_message: str | None


class SlowPathStep(Protocol):
    """Stable protocol implemented by each slow-path memory-processing step."""

    def run(self, batch: SlowPathBatch) -> SlowPathStepResult:
        """Run the step for a claimed slow-path batch."""


REGISTERED_SLOW_PATH_STEPS: list[SlowPathStep] = []


def run_slow_path_steps(
    batch: SlowPathBatch,
    steps: list[SlowPathStep],
) -> list[SlowPathStepResult]:
    """Run slow-path steps sequentially and return their reported results."""
    results: list[SlowPathStepResult] = []
    for step in steps:
        result = step.run(batch)
        validate_step_result(result, batch)
        results.append(result)
    return results


def register_slow_path_step(step: SlowPathStep) -> None:
    """Register a slow-path step for subsequent worker runs."""
    if step not in REGISTERED_SLOW_PATH_STEPS:
        REGISTERED_SLOW_PATH_STEPS.append(step)


def run_slow_path_once(batch_size: int) -> list[WorkerRunRecord]:
    """Claim one queue batch, run registered steps, and update queue statuses."""
    if batch_size < 1:
        raise ValueError("batch_size must be a positive integer")
    queue_records = claim_pending_batch(batch_size)
    if not queue_records:
        return []

    batch = _build_batch(queue_records)
    queue_ids_by_observation_id = {
        str(record["observation_id"]): str(record["id"]) for record in queue_records
    }
    run_records: list[WorkerRunRecord] = []
    failed_observation_ids: set[str] = set()

    try:
        for result in run_slow_path_steps(batch, REGISTERED_SLOW_PATH_STEPS):
            failed_observation_ids.update(result.failed_observation_ids)
            run_record = _result_record(batch, result)
            run_records.append(run_record)
            LOGGER.info("Slow-path step completed: %s", run_record)
    except Exception as error:
        LOGGER.exception("Slow-path batch failed: %s", batch.batch_id)
        error_message = str(error) or error.__class__.__name__
        failed_observation_ids.update(batch.observation_ids)
        run_records.append(
            {
                "batch_id": batch.batch_id,
                "step_name": "worker",
                "succeeded": False,
                "created_record_ids": [],
                "failed_observation_ids": list(batch.observation_ids),
                "error_message": error_message,
            }
        )

    _complete_queue_records(
        queue_ids_by_observation_id,
        failed_observation_ids,
        _failure_message(run_records),
    )
    return run_records


def run_slow_path_loop(batch_size: int, poll_interval_s: float) -> None:
    """Continuously process slow-path batches until interrupted by the caller."""
    if poll_interval_s < 0:
        raise ValueError("poll_interval_s must not be negative")
    while True:
        results = run_slow_path_once(batch_size)
        if not results:
            time.sleep(poll_interval_s)


def validate_step_result(result: SlowPathStepResult, batch: SlowPathBatch) -> None:
    """Validate that a step result follows the shared worker contract."""
    if result.step_name not in SLOW_PATH_STEP_NAMES:
        raise ValueError(f"Unknown slow-path step: {result.step_name}")
    unknown_failures = sorted(set(result.failed_observation_ids) - set(batch.observation_ids))
    if unknown_failures:
        joined_ids = ", ".join(unknown_failures)
        raise ValueError(f"Step {result.step_name} failed unknown observation(s): {joined_ids}")
    if result.succeeded and result.error_message is not None:
        raise ValueError(f"Successful step {result.step_name} must not include an error")
    if not result.succeeded and not result.failed_observation_ids:
        raise ValueError(f"Failed step {result.step_name} must report failed observations")


async def enrich_observation(observation_id: str) -> None:
    """Synthesize durable memory artifacts from one queued observation."""
    raise NotImplementedError


async def run_slow_path(batch_size: int = 20) -> None:
    """Process queued observations once worker orchestration is implemented."""
    run_slow_path_once(batch_size)


def _build_batch(queue_records: list[WorkerRunRecord]) -> SlowPathBatch:
    observation_ids = [str(record["observation_id"]) for record in queue_records]
    session_ids = _session_ids_for_observations(observation_ids)
    session_id = session_ids[0] if len(session_ids) == 1 else None
    return SlowPathBatch(
        batch_id=f"batch_{uuid4().hex}",
        observation_ids=observation_ids,
        session_id=session_id,
    )


def _session_ids_for_observations(observation_ids: list[str]) -> list[str]:
    if not observation_ids:
        return []
    placeholders = ", ".join("?" for _ in observation_ids)
    with repository_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT DISTINCT session_id
            FROM observations
            WHERE id IN ({placeholders})
            ORDER BY session_id ASC
            """,  # nosec B608
            tuple(observation_ids),
        ).fetchall()
    return [str(row["session_id"]) for row in rows]


def _result_record(batch: SlowPathBatch, result: SlowPathStepResult) -> WorkerRunRecord:
    return {
        "batch_id": batch.batch_id,
        "step_name": result.step_name,
        "succeeded": result.succeeded,
        "created_record_ids": list(result.created_record_ids),
        "failed_observation_ids": list(result.failed_observation_ids),
        "error_message": result.error_message,
    }


def _complete_queue_records(
    queue_ids_by_observation_id: dict[str, str],
    failed_observation_ids: set[str],
    error_message: str | None,
) -> None:
    for observation_id, queue_id in queue_ids_by_observation_id.items():
        if observation_id in failed_observation_ids:
            mark_failed(queue_id, error_message or "slow-path step failed")
        else:
            mark_done(queue_id)


def _failure_message(run_records: list[WorkerRunRecord]) -> str | None:
    for record in run_records:
        if not bool(record["succeeded"]):
            error = record.get("error_message")
            if isinstance(error, str) and error:
                return error
    return None
