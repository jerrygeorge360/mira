"""Architecture ablation-study contracts for MIRA evaluation.

Ownership: Sarah.
Related issue: ISSUE-803.
Architecture area: evaluation.
"""


def run_ablation(component_names: list[str]) -> dict[str, object]:
    """Evaluate future MIRA behavior with selected components ablated."""
    raise NotImplementedError
