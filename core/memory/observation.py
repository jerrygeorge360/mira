"""Strict raw-observation persistence and queueing contracts with no model calls.

Ownership: Jerry.
Related issue: ISSUE-101.
Architecture area: fast path.
"""

from __future__ import annotations

from core.db.repositories import (
    enqueue_observation as enqueue_observation_record,
)
from core.db.repositories import (
    save_observation,
    workspace_id_for_session,
)
from core.memory.lifecycle import ensure_memory_state


def persist_turn_fast_path(
    session_id: str,
    role: str,
    content: str,
    metadata: dict[str, object] | None = None,
) -> str:
    """Persist a raw turn and queue it for slow-path processing."""
    observation_id = save_observation(session_id, role, content, metadata=metadata)
    ensure_memory_state(
        "observations",
        observation_id,
        workspace_id_for_session(session_id),
        source_authority="direct_observation" if role == "user" else "untrusted_observation",
    )
    enqueue_observation_record(observation_id)
    return observation_id


def persist_observation(
    session_id: str,
    role: str,
    content: str,
    metadata: dict[str, object] | None = None,
) -> str:
    """Persist one raw observation and return its identifier."""
    observation_id = save_observation(session_id, role, content, metadata=metadata)
    ensure_memory_state(
        "observations",
        observation_id,
        workspace_id_for_session(session_id),
        source_authority="direct_observation" if role == "user" else "untrusted_observation",
    )
    return observation_id


def enqueue_observation(observation_id: str) -> None:
    """Queue a persisted observation for later durable enrichment."""
    enqueue_observation_record(observation_id)
