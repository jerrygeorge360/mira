"""Future-relevant constraint records and lifecycle status contracts.

Ownership: Jerry.
Related issue: ISSUE-107.
Architecture area: slow path.
"""


def create_foresight(
    content: str,
    evidence_ids: list[str],
    lifecycle_status: str,
) -> dict[str, object]:
    """Create a future-relevant constraint backed by evidence."""
    raise NotImplementedError


def update_foresight_status(foresight_id: str, lifecycle_status: str) -> None:
    """Update the lifecycle status of a foresight record."""
    raise NotImplementedError
