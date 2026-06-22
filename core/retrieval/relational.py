"""Direct graph traversal contracts for typed evidence and temporal relations.

Ownership: Jerry.
Related issue: ISSUE-303.
Architecture area: retrieval.
"""


def relational_retrieve(
    entity_ids: list[str],
    relation_types: set[str],
    limit: int = 20,
) -> list[dict[str, object]]:
    """Traverse contradiction, supersession, causality, and evidence relations."""
    raise NotImplementedError
