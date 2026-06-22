"""Cold, warm, and hot durable-memory promotion and demotion policy contracts.

Ownership: Jerry.
Related issue: ISSUE-104.
Architecture area: slow path.
"""


def promote_memory(memory_id: str, target_tier: str) -> None:
    """Promote durable memory to a warmer target tier."""
    raise NotImplementedError


def demote_memory(memory_id: str, target_tier: str) -> None:
    """Demote durable memory to a colder target tier."""
    raise NotImplementedError
