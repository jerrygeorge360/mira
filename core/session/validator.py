"""Deterministic structural validation contracts for extractor operations.

Ownership: Jerry.
Related issue: ISSUE-203.
Architecture area: session micro-path.
"""


def validate_session_operation(
    operation: dict[str, object],
    known_observation_ids: set[str],
    known_working_set_ids: set[str],
) -> bool:
    """Validate that a session operation is structurally safe before applying it."""
    raise NotImplementedError
