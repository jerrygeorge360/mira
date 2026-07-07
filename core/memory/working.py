"""Durable hot working-memory pool facade, distinct from session state.

Ownership: Jerry.
Related issue: ISSUE-105.
Architecture area: slow path.
"""

from __future__ import annotations

from core.memory.tiers import (
    SUPPORTED_RECORD_TYPES,
    evaluate_promotion_candidate,
    list_hot_memory_for_context,
    promote_to_hot_memory,
)


def store_hot_memory(memory_id: str) -> None:
    """Promote a durable memory record into the hot working pool when eligible."""
    if not memory_id:
        raise ValueError("memory_id must not be empty")
    candidate = None
    for record_type in SUPPORTED_RECORD_TYPES:
        evaluated = evaluate_promotion_candidate(record_type, memory_id)
        if evaluated.get("eligible"):
            candidate = evaluated
            break
    if candidate is None:
        raise ValueError(f"no promotable durable memory found for id: {memory_id}")
    promote_to_hot_memory(candidate)


def list_hot_memories(limit: int) -> list[dict[str, object]]:
    """List confirmed durable memories in the hot working pool."""
    return list_hot_memory_for_context(session_id=None, query="", limit=limit)
