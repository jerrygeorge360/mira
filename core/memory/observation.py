"""Strict raw-observation persistence and queueing contracts with no model calls.

Ownership: Jerry.
Related issue: ISSUE-101.
Architecture area: fast path.
"""


def persist_observation(session_id: str, role: str, content: str) -> str:
    """Persist one raw observation and return its identifier."""
    raise NotImplementedError


def enqueue_observation(observation_id: str) -> None:
    """Queue a persisted observation for later durable enrichment."""
    raise NotImplementedError
