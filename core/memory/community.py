"""Graph-derived community summary contracts consumed by Deep retrieval.

Ownership: Jerry.
Related issue: ISSUE-109.
Architecture area: slow path.
"""


def summarize_community(node_ids: list[str]) -> dict[str, object]:
    """Synthesize a future graph-community summary."""
    raise NotImplementedError


def mark_community_summary_stale(summary_id: str) -> None:
    """Mark a graph-community summary stale for later regeneration."""
    raise NotImplementedError
