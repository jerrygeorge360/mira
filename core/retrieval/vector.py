"""Vector-index lookup boundary for retrieval candidates.

Ownership: Jerry.
Related issue: ISSUE-305.
Architecture area: retrieval.
"""


def vector_search(query: str, limit: int = 8) -> list[dict[str, object]]:
    """Search the future vector index for semantic candidates."""
    raise NotImplementedError
