"""Single typed temporal graph contract for durable memory relationships.

Ownership: Jerry.
Related issue: ISSUE-108.
Architecture area: slow path.
"""


def add_typed_edge(
    source_id: str,
    target_id: str,
    edge_type: str,
    valid_at: str | None = None,
) -> str:
    """Add a future typed temporal edge and return its identifier."""
    raise NotImplementedError


def traverse_graph(entity_id: str, relation_types: set[str]) -> list[dict[str, object]]:
    """Traverse durable graph relationships from an entity."""
    raise NotImplementedError
