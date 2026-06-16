"""Formal (graph/symbolic) retrieval for MIRA.

Answers queries by traversing the knowledge graph and community summaries:
exact entity lookups, multi-hop relation walks, and community-scoped reads.
Complements semantic vector search with precise, explainable retrieval.

ISSUE-011: Formal retrieval.
"""

from __future__ import annotations


def retrieve(query: str, max_hops: int = 2) -> list[str]:
    """Retrieve memory items by traversing the knowledge graph.

    Args:
        query: The natural-language or entity query to resolve.
        max_hops: Maximum relation hops to traverse from seed entities.

    Returns:
        Identifiers of matching memory items, most relevant first.
    """
    raise NotImplementedError
