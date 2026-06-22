"""Slow-path handoff contracts for provisional session-item outcomes.

Ownership: Jerry.
Related issue: ISSUE-205.
Architecture area: session micro-path.
"""


def confirm_item(item_id: str) -> None:
    """Confirm a provisional session item through the slow path."""
    raise NotImplementedError


def reject_item(item_id: str, reason: str) -> None:
    """Reject a provisional item that lacks durable support."""
    raise NotImplementedError


def downgrade_scope(item_id: str, scope: str) -> None:
    """Narrow the scope of a provisional session item."""
    raise NotImplementedError


def promote_to_durable_memory_candidate(item_id: str) -> str:
    """Promote a provisional item to a durable-memory candidate."""
    raise NotImplementedError


def mark_forward_only_correction(item_id: str, replacement_item_id: str) -> None:
    """Record a correction without rewriting historical observations."""
    raise NotImplementedError
