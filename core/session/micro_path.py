"""Orchestration contract for the complete session micro-path.

Ownership: Jerry.
Related issue: ISSUE-201.
Architecture area: session micro-path.
"""


def process_session_turn(
    observation_id: str,
    current_message: str,
    recent_turns: list[str],
) -> list[dict[str, object]]:
    """Extract, validate, and apply provisional state for a new user turn."""
    raise NotImplementedError
