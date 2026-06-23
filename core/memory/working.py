"""Durable hot working-memory pool contracts, distinct from session state.

Ownership: Jerry.
Related issue: ISSUE-105.
Architecture area: slow path.
"""


def store_hot_memory(memory_id: str) -> None:
    """Place confirmed durable memory in the hot working pool."""
    raise NotImplementedError


def list_hot_memories(limit: int) -> list[dict[str, object]]:
    """List confirmed durable memories in the hot working pool."""
    raise NotImplementedError
