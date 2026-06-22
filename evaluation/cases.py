"""Define evaluation-case loading contracts for MIRA memory behavior.

Ownership: Sarah.
Related issue: ISSUE-804.
Architecture area: evaluation.
"""


def load_evaluation_cases(source: str) -> list[dict[str, object]]:
    """Load future evaluation cases from a named standard representation."""
    raise NotImplementedError
