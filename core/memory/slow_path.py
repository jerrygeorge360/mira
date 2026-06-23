"""Shared slow-path worker contract for cross-session memory processing.

Ownership: Jerry.
Related issue: ISSUE-022.
Architecture area: slow path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

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
    raise NotImplementedError
