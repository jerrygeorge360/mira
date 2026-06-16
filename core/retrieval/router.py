"""Retrieval router for MIRA.

Inspects an incoming query and decides whether to serve it from formal
(graph/symbolic) retrieval, vector (semantic) retrieval, or a blend of both,
then merges and ranks the combined results.

ISSUE-013: Retrieval router.
"""

from __future__ import annotations

from enum import Enum


class RetrievalStrategy(Enum):
    """Strategy the router may select for a given query."""

    FORMAL = "formal"
    VECTOR = "vector"
    HYBRID = "hybrid"


def route(query: str) -> RetrievalStrategy:
    """Choose a retrieval strategy for the given query.

    Args:
        query: The natural-language query to classify.

    Returns:
        The strategy best suited to answering the query.
    """
    raise NotImplementedError


def retrieve(query: str, top_k: int = 8) -> list[str]:
    """Route a query, execute the chosen strategy, and rank the results.

    Args:
        query: The natural-language query to resolve.
        top_k: Maximum number of memory items to return.

    Returns:
        Identifiers of matching memory items, most relevant first.
    """
    raise NotImplementedError
