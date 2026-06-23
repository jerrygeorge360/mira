"""Evaluation-judge contracts for future memory quality scoring.

Ownership: Sarah.
Related issue: ISSUE-801.
Architecture area: evaluation.
"""


def judge_response(
    response: str,
    expected: str,
    context: list[dict[str, object]],
) -> dict[str, object]:
    """Score a future response against expected memory behavior."""
    raise NotImplementedError
