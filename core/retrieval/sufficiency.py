"""Structured retrieval sufficiency check and one-retry contracts.

Ownership: Jerry.
Related issue: ISSUE-307.
Architecture area: retrieval.
"""


def check_sufficiency(
    query: str,
    results: list[dict[str, object]],
) -> dict[str, object]:
    """Assess whether retrieved context sufficiently addresses a query."""
    raise NotImplementedError


def retry_retrieval_once(
    query: str,
    prior_results: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Perform the single permitted retrieval retry."""
    raise NotImplementedError
