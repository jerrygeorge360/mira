"""Reusable LLM prompt-template contracts for MIRA pipelines.

Ownership: Jerry.
Related issue: ISSUE-002.
Architecture area: context.
"""


def get_prompt_template(name: str) -> str:
    """Return a future prompt template identified by name."""
    raise NotImplementedError
