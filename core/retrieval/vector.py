"""Vector-index lookup boundary for retrieval candidates.

Ownership: Jerry.
Related issue: ISSUE-305.
Architecture area: retrieval.
"""

from __future__ import annotations

from core.db import chroma
from core.db.schema import LEGACY_WORKSPACE_ID
from core.llm.embeddings import embed_text

DEFAULT_COLLECTIONS = ("observations", "reflections", "community_summaries")


def vector_search(
    query: str,
    limit: int = 8,
    collections: tuple[str, ...] = DEFAULT_COLLECTIONS,
    *,
    workspace_id: str = LEGACY_WORKSPACE_ID,
) -> list[dict[str, object]]:
    """Search configured Chroma collections and return SQLite pointer candidates."""
    if limit < 1:
        raise ValueError("limit must be a positive integer")
    if not query.strip():
        return []
    embedding = embed_text(query)
    results: list[dict[str, object]] = []
    for collection in collections:
        try:
            pointers = chroma.query_embeddings(
                collection, embedding, top_k=limit, workspace_id=workspace_id
            )
        except ValueError:
            continue
        for pointer in pointers:
            item = dict(pointer)
            item["collection"] = collection
            item["source"] = "vector"
            results.append(item)
    results.sort(key=_distance)
    return results[:limit]


def _distance(item: dict[str, object]) -> float:
    value = item.get("distance", 1.0)
    return float(value) if isinstance(value, int | float | str) else 1.0
