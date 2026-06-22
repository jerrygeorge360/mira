"""Direct fact lookup contracts across vectors, keywords, and atomic facts.

Ownership: Jerry.
Related issue: ISSUE-301.
Architecture area: retrieval.
"""


def quick_retrieve(query: str, limit: int = 8) -> list[dict[str, object]]:
    """Retrieve direct fact candidates for a query."""
    raise NotImplementedError
