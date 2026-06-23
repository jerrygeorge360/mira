"""Persistence-backed queue facade between fast and slow paths.

Ownership: Kelechi.
Related issue: ISSUE-009.
Architecture area: fast path.
"""

from __future__ import annotations

from core.db.repositories import (
    claim_pending_batch,
    mark_done,
    mark_failed,
    mark_processing,
)
from core.db.repositories import (
    enqueue_observation as enqueue_observation_record,
)


def enqueue_observation(observation_id: str) -> str:
    """Queue a persisted observation for durable slow-path processing."""
    return enqueue_observation_record(observation_id)


def claim_observation() -> str | None:
    """Claim the next observation identifier for slow-path enrichment."""
    claimed = claim_pending_batch(1)
    if not claimed:
        return None
    return str(claimed[0]["observation_id"])


def mark_observation_processing(queue_id: str) -> None:
    """Mark a queue job as processing and increment its attempt count."""
    mark_processing(queue_id)


def mark_observation_done(queue_id: str) -> None:
    """Mark a processing queue job as done."""
    mark_done(queue_id)


def mark_observation_failed(queue_id: str, error: str) -> None:
    """Mark a processing queue job as failed with a retryable error."""
    mark_failed(queue_id, error)
