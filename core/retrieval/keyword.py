"""Keyword lookup boundary for direct retrieval candidates.

Ownership: Jerry.
Related issue: ISSUE-306.
Architecture area: retrieval.
"""


def keyword_search(query: str, limit: int = 8) -> list[dict[str, object]]:
    """Search durable memory using future keyword matching."""
    raise NotImplementedError
