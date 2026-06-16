"""Knowledge graph for MIRA.

Maintains the entity/relation graph extracted from observations. Nodes are
entities and concepts; edges are typed relations with provenance back to the
source observations. Backs the formal retrieval path and community detection.

ISSUE-009: Knowledge graph.
"""

from __future__ import annotations


class KnowledgeGraph:
    """Typed entity/relation graph over consolidated memory."""

    def __init__(self) -> None:
        """Initialise an empty knowledge graph."""
        raise NotImplementedError

    def add_node(self, node_id: str, attributes: dict[str, str]) -> None:
        """Insert or update an entity node.

        Args:
            node_id: Stable identifier for the entity.
            attributes: Key/value attributes describing the entity.
        """
        raise NotImplementedError

    def add_edge(self, source: str, target: str, relation: str) -> None:
        """Insert a typed relation between two entities.

        Args:
            source: Identifier of the source node.
            target: Identifier of the target node.
            relation: The relation type connecting source to target.
        """
        raise NotImplementedError

    def neighbors(self, node_id: str) -> list[str]:
        """Return the identifiers of nodes adjacent to the given node.

        Args:
            node_id: Node whose neighbours are requested.

        Returns:
            Identifiers of adjacent nodes.
        """
        raise NotImplementedError
