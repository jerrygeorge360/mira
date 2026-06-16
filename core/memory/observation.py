"""Fast-path observation for MIRA.

The synchronous entry point of the dual-stream design: captures each incoming
turn as a raw observation, persists it, and enqueues it for slow-path
consolidation without blocking the agent's response.

ISSUE-004: Fast-path observation.
"""

from __future__ import annotations


def observe(session_id: str, role: str, content: str) -> str:
    """Record a single conversational turn as a raw observation.

    Args:
        session_id: Conversation the observation belongs to.
        role: Speaker role for the turn (e.g. ``"user"`` or ``"assistant"``).
        content: The utterance text.

    Returns:
        The identifier of the persisted observation.
    """
    raise NotImplementedError


def enqueue_for_consolidation(observation_id: str) -> None:
    """Hand an observation to the slow path for background consolidation.

    Args:
        observation_id: Identifier of a previously persisted observation.
    """
    raise NotImplementedError
