"""SQLite schema-definition and migration contracts for durable records.

Ownership: Kelechi.
Related issue: ISSUE-501.
Architecture area: slow path.
"""


def schema_statements() -> list[str]:
    """Return future SQLite schema statements."""
    raise NotImplementedError
