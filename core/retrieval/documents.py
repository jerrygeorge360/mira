"""Retrieval boundary for document chunks.

Document evidence is deliberately separate from human-memory lifecycle state.
Results are rehydrated from SQLite after the vector lookup so provenance and
workspace isolation remain authoritative even if Chroma is rebuilt or stale.
"""

from __future__ import annotations

from collections.abc import Callable

from core.db import chroma
from core.db.repositories import (
    RepositoryRecord,
    get_document,
    get_document_chunk,
)
from core.db.schema import LEGACY_WORKSPACE_ID
from core.llm.embeddings import embed_text

DocumentEvidence = dict[str, object]


def retrieve_document_chunks(
    query: str,
    *,
    workspace_id: str = LEGACY_WORKSPACE_ID,
    knowledge_base_id: str | None = None,
    limit: int = 8,
    embedder: Callable[[str], list[float]] = embed_text,
) -> list[DocumentEvidence]:
    """Return ready document chunks with document/KB/page provenance."""
    if limit < 1:
        raise ValueError("limit must be a positive integer")
    if not query.strip():
        return []
    query_embedding = embedder(query)
    where: dict[str, object] | None = (
        {"knowledge_base_id": knowledge_base_id} if knowledge_base_id else None
    )
    pointers = chroma.query_embeddings(
        "document_chunks",
        query_embedding,
        top_k=limit,
        workspace_id=workspace_id,
        where=where,
    )
    results: list[DocumentEvidence] = []
    for pointer in pointers:
        chunk_id = str(pointer.get("sqlite_id", ""))
        chunk = get_document_chunk(chunk_id, workspace_id=workspace_id)
        if chunk is None:
            continue
        document_id = str(chunk.get("document_id", ""))
        document = get_document(document_id, workspace_id=workspace_id)
        if document is None or document.get("status") != "ready":
            continue
        if str(chunk.get("knowledge_base_id")) != str(document.get("knowledge_base_id")):
            continue
        if knowledge_base_id and str(document.get("knowledge_base_id")) != knowledge_base_id:
            continue
        distance = _float(pointer.get("distance"), 1.0)
        results.append(_evidence(chunk, document, distance))
    results.sort(key=lambda item: (-_float(item["relevance_score"]), str(item["chunk_id"])))
    return results[:limit]


def search_documents(
    query: str,
    limit: int = 8,
    *,
    workspace_id: str = LEGACY_WORKSPACE_ID,
    knowledge_base_id: str | None = None,
    embedder: Callable[[str], list[float]] = embed_text,
) -> list[DocumentEvidence]:
    """Compatibility alias for callers that use search terminology."""
    return retrieve_document_chunks(
        query,
        workspace_id=workspace_id,
        knowledge_base_id=knowledge_base_id,
        limit=limit,
        embedder=embedder,
    )


def _evidence(
    chunk: RepositoryRecord,
    document: RepositoryRecord,
    distance: float,
) -> DocumentEvidence:
    relevance = max(0.0, 1.0 - distance)
    page_start = chunk.get("page_start")
    page_end = chunk.get("page_end")
    chunk_index = _int(chunk.get("chunk_index"))
    return {
        "source": "document_chunks",
        "source_type": "document_chunk",
        "content": str(chunk["content"]),
        "document_id": str(document["id"]),
        "knowledge_base_id": str(document["knowledge_base_id"]),
        "filename": str(document["filename"]),
        "chunk_id": str(chunk["id"]),
        "chunk_index": chunk_index,
        "page_start": page_start,
        "page_end": page_end,
        "distance": distance,
        "relevance_score": relevance,
        "record": dict(chunk),
        "provenance": {
            "source": "document",
            "document_id": str(document["id"]),
            "knowledge_base_id": str(document["knowledge_base_id"]),
            "filename": str(document["filename"]),
            "page_start": page_start,
            "page_end": page_end,
            "chunk_id": str(chunk["id"]),
            "chunk_index": chunk_index,
            "relevance_score": relevance,
        },
    }


def _float(value: object, default: float = 0.0) -> float:
    if isinstance(value, int | float):
        return float(value)
    return default


def _int(value: object, default: int = 0) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            pass
    return default
