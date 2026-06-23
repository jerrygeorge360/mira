"""Subject-predicate-object atomic fact model and persistence contracts.

Ownership: Jerry.
Related issue: ISSUE-102.
Architecture area: slow path.
"""


def create_atomic_fact(
    subject: str,
    predicate: str,
    object_value: str,
    observation_ids: list[str],
) -> dict[str, object]:
    """Create a future atomic fact record from evidence."""
    raise NotImplementedError
