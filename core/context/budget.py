"""Context-budget allocation and trimming-priority contracts.

Ownership: Jerry.
Related issue: ISSUE-402.
Architecture area: context.
"""


def allocate_budget(total_tokens: int) -> dict[str, int]:
    """Allocate a prompt token budget among context sources."""
    raise NotImplementedError


def trim_context(items: list[str], token_budget: int) -> list[str]:
    """Trim ordered context items to a future token budget."""
    raise NotImplementedError
