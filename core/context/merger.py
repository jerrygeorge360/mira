"""Context merge contract for recent, session, retrieved, and ambient sources.

Ownership: Jerry.
Related issue: ISSUE-403.
Architecture area: context.
"""


def merge_context(
    recent_turns: list[str],
    session_items: list[dict[str, object]],
    retrieved_memories: list[dict[str, object]],
    ambient_context: dict[str, object],
) -> list[dict[str, object]]:
    """Merge context sources according to future prompt priorities."""
    raise NotImplementedError
