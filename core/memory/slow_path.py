"""Slow-path consolidation worker for MIRA.

Asynchronous background worker that drains the consolidation queue and runs the
heavier memory operations (reflection, foresight, graph extraction, community
detection) off the critical path of the agent's response.

ISSUE-005: Slow-path worker.
"""

from __future__ import annotations


class SlowPathWorker:
    """Background worker that consolidates observations into durable memory."""

    def __init__(self) -> None:
        """Initialise the worker and its consolidation queue."""
        raise NotImplementedError

    async def run(self) -> None:
        """Continuously drain the queue and consolidate pending observations."""
        raise NotImplementedError

    async def consolidate(self, observation_id: str) -> None:
        """Consolidate a single observation into long-term memory structures.

        Args:
            observation_id: Identifier of the observation to consolidate.
        """
        raise NotImplementedError

    async def stop(self) -> None:
        """Signal the worker to finish the current item and shut down."""
        raise NotImplementedError
