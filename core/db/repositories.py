"""Define repository boundaries over MIRA's future durable source of truth.

Ownership: Kelechi.
Related issue: ISSUE-504.
Architecture area: slow path.
"""


def save_record(collection: str, record: dict[str, object]) -> str:
    """Persist a future durable record through its repository contract."""
    raise NotImplementedError


def get_record(collection: str, record_id: str) -> dict[str, object] | None:
    """Retrieve a future durable record by collection and identifier."""
    raise NotImplementedError
