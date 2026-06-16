"""Chroma embedding store adapter for MIRA.

Wraps the Chroma vector database: manages the embedding collection and exposes
upsert and similarity-search primitives consumed by vector retrieval.

ISSUE-015: Chroma vector store.
"""

from __future__ import annotations

from collections.abc import Sequence


class ChromaStore:
    """Adapter over a Chroma collection of memory embeddings."""

    def __init__(self, persist_path: str, collection: str = "mira") -> None:
        """Initialise the store against a persistent Chroma collection.

        Args:
            persist_path: Directory where Chroma persists its data.
            collection: Name of the embedding collection to use.
        """
        raise NotImplementedError

    def upsert(self, memory_id: str, text: str) -> None:
        """Embed and store (or replace) a single memory item.

        Args:
            memory_id: Stable identifier for the memory item.
            text: The text to embed and index.
        """
        raise NotImplementedError

    def query(self, text: str, top_k: int = 8) -> Sequence[str]:
        """Return the ids of the nearest memory items to the query text.

        Args:
            text: Query text to embed and search with.
            top_k: Maximum number of neighbours to return.

        Returns:
            Identifiers of the nearest memory items, most similar first.
        """
        raise NotImplementedError
