"""Verify the ISSUE-022 slow-path step interface contract.

Ownership: MIRA contributors.
Related issue: ISSUE-022.
Architecture area: slow path.
"""

from __future__ import annotations

import pytest

from core.memory.slow_path import (
    SlowPathBatch,
    SlowPathStepResult,
    run_slow_path_steps,
    validate_step_result,
)


class MockStep:
    """Test slow-path step that records the batch it received."""

    def __init__(self, result: SlowPathStepResult) -> None:
        self.result = result
        self.seen_batch: SlowPathBatch | None = None

    def run(self, batch: SlowPathBatch) -> SlowPathStepResult:
        """Return a preconfigured result for contract testing."""
        self.seen_batch = batch
        return self.result


def test_mock_step_can_be_run() -> None:
    """A class implementing the protocol can run against a slow-path batch."""
    batch = SlowPathBatch(
        batch_id="batch_1",
        observation_ids=["obs_1"],
        session_id="session_1",
    )
    step = MockStep(
        SlowPathStepResult(
            step_name="embedding_index",
            succeeded=True,
            created_record_ids=["vec_1"],
            failed_observation_ids=[],
            error_message=None,
        )
    )

    results = run_slow_path_steps(batch, [step])

    assert step.seen_batch == batch
    assert results[0].created_record_ids == ["vec_1"]


def test_result_reports_created_records_and_failures() -> None:
    """Step results carry both created records and failed observations."""
    batch = SlowPathBatch(
        batch_id="batch_2",
        observation_ids=["obs_1", "obs_2"],
        session_id=None,
    )
    result = SlowPathStepResult(
        step_name="atomic_fact_extraction",
        succeeded=False,
        created_record_ids=["fact_1"],
        failed_observation_ids=["obs_2"],
        error_message="Could not parse obs_2.",
    )

    validate_step_result(result, batch)

    assert result.created_record_ids == ["fact_1"]
    assert result.failed_observation_ids == ["obs_2"]
    assert result.error_message == "Could not parse obs_2."


def test_worker_can_call_a_list_of_steps() -> None:
    """The worker skeleton runs steps in order and returns each result."""
    batch = SlowPathBatch(
        batch_id="batch_3",
        observation_ids=["obs_1"],
        session_id="session_1",
    )
    steps = [
        MockStep(
            SlowPathStepResult(
                step_name="embedding_index",
                succeeded=True,
                created_record_ids=["vec_1"],
                failed_observation_ids=[],
                error_message=None,
            )
        ),
        MockStep(
            SlowPathStepResult(
                step_name="reflection_check",
                succeeded=True,
                created_record_ids=["reflection_1"],
                failed_observation_ids=[],
                error_message=None,
            )
        ),
    ]

    results = run_slow_path_steps(batch, steps)

    assert [result.step_name for result in results] == ["embedding_index", "reflection_check"]
    assert [step.seen_batch for step in steps] == [batch, batch]


def test_unknown_step_name_is_rejected() -> None:
    """Worker contract rejects results from unregistered step names."""
    batch = SlowPathBatch(batch_id="batch_4", observation_ids=["obs_1"], session_id=None)
    result = SlowPathStepResult(
        step_name="mystery_step",
        succeeded=True,
        created_record_ids=[],
        failed_observation_ids=[],
        error_message=None,
    )

    with pytest.raises(ValueError, match="Unknown slow-path step"):
        validate_step_result(result, batch)
