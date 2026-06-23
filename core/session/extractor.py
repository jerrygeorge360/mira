"""Rule-assisted structured extraction contract for provisional session operations.

Ownership: Jerry.
Related issue: ISSUE-202.
Architecture area: session micro-path.
"""


def extract_session_operations(
    observation_id: str,
    current_message: str,
    recent_turns: list[str],
    current_working_set: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Extract provisional session-state operations from a new user turn."""
    raise NotImplementedError
