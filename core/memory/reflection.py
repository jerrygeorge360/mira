"""Reflection synthesis and reflection-staleness contracts.

Ownership: Jerry.
Related issue: ISSUE-106.
Architecture area: slow path.
"""


def synthesize_reflection(memory_ids: list[str]) -> dict[str, object]:
    """Synthesize a future reflection from confirmed durable memories."""
    raise NotImplementedError


def mark_reflection_stale(reflection_id: str, reason: str) -> None:
    """Mark a reflection stale when supporting memory changes."""
    raise NotImplementedError
