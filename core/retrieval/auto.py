"""Classifier contract for automatic retrieval-mode selection.

Ownership: Jerry.
Related issue: ISSUE-304.
Architecture area: retrieval.
"""


def classify_retrieval_mode(query: str) -> str:
    """Classify a query into Quick, Deep, or Relational retrieval."""
    raise NotImplementedError
