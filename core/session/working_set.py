"""Temporary Session Working Set storage contract, separate from durable memory tiers.

Ownership: Jerry.
Related issue: ISSUE-204.
Architecture area: session micro-path.
"""


def upsert_item(item: dict[str, object]) -> str:
    """Insert or update a provisional Session Working Set item."""
    raise NotImplementedError


def supersede_item(item_id: str, replacement_item_id: str) -> None:
    """Supersede one provisional item with a newer session item."""
    raise NotImplementedError


def resolve_item(item_id: str, resolution: str) -> None:
    """Resolve a provisional item within the current session."""
    raise NotImplementedError


def expire_item(item_id: str, reason: str) -> None:
    """Expire a provisional item that is no longer session-relevant."""
    raise NotImplementedError


def list_active_items(session_id: str) -> list[dict[str, object]]:
    """List active provisional items for a session."""
    raise NotImplementedError


def export_prompt_ready_items(session_id: str) -> list[dict[str, object]]:
    """Export validated active items at hot-level prompt priority."""
    raise NotImplementedError
