"""Public routing interface for Quick, Deep, Relational, and Auto modes.

Ownership: Jerry.
Related issue: ISSUE-308.
Architecture area: retrieval.
"""


def route_retrieval(
    query: str,
    mode: str = "auto",
    limit: int = 8,
) -> list[dict[str, object]]:
    """Route a query through the requested public retrieval mode."""
    raise NotImplementedError
