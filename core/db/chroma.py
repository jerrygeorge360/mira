"""ChromaDB vector index wrapper with SQLite as the only source of truth.

Chroma collections store embeddings plus SQLite record pointers only. They are safe to delete and
rebuild from canonical SQLite records.

Ownership: Kelechi.
Related issue: ISSUE-503.
Architecture area: retrieval.
"""

from __future__ import annotations

import importlib
import json
import math
import os
from collections.abc import Callable, Sequence
from typing import Any

from core.db.repositories import repository_connection
from core.llm.embeddings import embed_text

SUPPORTED_COLLECTIONS = frozenset({"observations", "reflections", "community_summaries"})
INDEX_TEXT_VERSION = 1
CHROMA_DB_PATH_ENV = "CHROMA_DB_PATH"

EmbeddingProvider = Callable[[str], list[float]]

_FALLBACK_STORE: dict[str, dict[str, dict[str, object]]] = {
    collection: {} for collection in SUPPORTED_COLLECTIONS
}
_CHROMA_CLIENT: Any | None = None
_CHROMA_CLIENT_INITIALIZED = False
_CHROMA_CLIENT_PATH: str | None = None
_EMBEDDING_PROVIDER: EmbeddingProvider | None = embed_text


def add_embedding(
    collection: str,
    sqlite_table: str,
    sqlite_id: str,
    embedding: list[float],
    metadata: dict[str, object] | None = None,
) -> None:
    """Add an embedding to the vector index using a SQLite pointer as its identity."""
    _validate_collection(collection)
    _validate_sqlite_table(sqlite_table)
    _validate_embedding(embedding)
    _ensure_sqlite_record_exists(sqlite_table, sqlite_id)

    pointer_metadata = {
        "sqlite_table": sqlite_table,
        "sqlite_id": sqlite_id,
        "metadata_json": json.dumps(dict(metadata or {}), sort_keys=True),
    }
    client = _load_chroma_client()
    if client is None:
        _fallback_collection(collection)[sqlite_id] = {
            "embedding": list(embedding),
            "sqlite_table": sqlite_table,
            "sqlite_id": sqlite_id,
            "metadata": dict(metadata or {}),
        }
        return

    client.get_or_create_collection(name=collection).upsert(
        ids=[sqlite_id],
        embeddings=[list(embedding)],
        metadatas=[pointer_metadata],
    )


def query_embeddings(
    collection: str,
    embedding: list[float],
    top_k: int,
) -> list[dict[str, object]]:
    """Query the vector index and return SQLite pointers plus retrieval metadata."""
    _validate_collection(collection)
    _validate_embedding(embedding)
    if top_k < 1:
        raise ValueError("top_k must be a positive integer")

    client = _load_chroma_client()
    if client is None:
        rows = list(_fallback_collection(collection).values())
        ranked = sorted(
            rows,
            key=lambda row: _cosine_distance(embedding, _as_float_list(row["embedding"])),
        )
        return [
            {
                "sqlite_table": str(row["sqlite_table"]),
                "sqlite_id": str(row["sqlite_id"]),
                "distance": _cosine_distance(embedding, _as_float_list(row["embedding"])),
                "metadata": _as_metadata_dict(row["metadata"]),
            }
            for row in ranked[:top_k]
        ]

    result = client.get_or_create_collection(name=collection).query(
        query_embeddings=[list(embedding)],
        n_results=top_k,
        include=["distances", "metadatas"],
    )
    ids = _query_result_rows(result, "ids")
    metadatas = _query_result_rows(result, "metadatas")
    distances = _query_result_rows(result, "distances")
    output: list[dict[str, object]] = []
    for sqlite_id, metadata, distance in zip(ids, metadatas, distances, strict=True):
        pointer = _as_metadata_dict(metadata or {})
        output.append(
            {
                "sqlite_table": str(pointer["sqlite_table"]),
                "sqlite_id": str(pointer.get("sqlite_id", sqlite_id)),
                "distance": _as_float(distance),
                "metadata": _decode_pointer_metadata(pointer),
            }
        )
    return output


def collection_count(collection: str) -> int:
    """Return the number of vector pointers currently stored for one collection."""
    _validate_collection(collection)
    client = _load_chroma_client()
    if client is None:
        return len(_fallback_collection(collection))
    return int(client.get_or_create_collection(name=collection).count())


def vector_store_status() -> dict[str, object]:
    """Return collection counts and backend metadata for diagnostics."""
    return {
        "backend": "chroma" if _load_chroma_client() is not None else "fallback",
        "path": os.environ.get(CHROMA_DB_PATH_ENV),
        "collections": {
            collection: collection_count(collection) for collection in sorted(SUPPORTED_COLLECTIONS)
        },
    }


def delete_collection(collection: str) -> None:
    """Delete a vector collection without touching canonical SQLite records."""
    _validate_collection(collection)
    client = _load_chroma_client()
    if client is None:
        _fallback_collection(collection).clear()
        return
    try:
        client.delete_collection(name=collection)
    except Exception as error:  # pragma: no cover - depends on installed Chroma version
        if error.__class__.__name__ not in {"InvalidCollectionException", "NotFoundError"}:
            raise


def rebuild_collection(collection: str) -> None:
    """Rebuild one vector collection from SQLite records."""
    _validate_collection(collection)
    embedder = _require_embedder()
    delete_collection(collection)
    for row in _fetch_rebuild_rows(collection):
        sqlite_id = str(row["id"])
        add_embedding(
            collection,
            collection,
            sqlite_id,
            embedder(_canonical_index_text(collection, row)),
            metadata=_rebuild_metadata(collection, row),
        )


def configure_embedder(embedder: EmbeddingProvider | None) -> None:
    """Configure the external embedding provider used for collection rebuilds."""
    global _EMBEDDING_PROVIDER
    _EMBEDDING_PROVIDER = embedder


def index_memory(memory_id: str, text: str, metadata: dict[str, object]) -> None:
    """Deprecated adapter kept to avoid silently treating Chroma as source-of-truth storage."""
    raise NotImplementedError("Use add_embedding() with an externally generated embedding")


def remove_from_index(memory_id: str) -> None:
    """Remove a SQLite record pointer from all supported collections."""
    client = _load_chroma_client()
    for collection in SUPPORTED_COLLECTIONS:
        if client is None:
            _fallback_collection(collection).pop(memory_id, None)
            continue
        client.get_or_create_collection(name=collection).delete(ids=[memory_id])


def _validate_collection(collection: str) -> None:
    if collection not in SUPPORTED_COLLECTIONS:
        allowed = ", ".join(sorted(SUPPORTED_COLLECTIONS))
        raise ValueError(f"Unsupported collection: {collection!r}. Expected one of: {allowed}")


def _validate_sqlite_table(sqlite_table: str) -> None:
    if sqlite_table not in SUPPORTED_COLLECTIONS:
        allowed = ", ".join(sorted(SUPPORTED_COLLECTIONS))
        raise ValueError(f"Unsupported sqlite_table: {sqlite_table!r}. Expected one of: {allowed}")


def _validate_embedding(embedding: Sequence[float]) -> None:
    if not embedding:
        raise ValueError("embedding must not be empty")
    for value in embedding:
        if not isinstance(value, int | float):
            raise ValueError("embedding values must be numeric")


def _ensure_sqlite_record_exists(sqlite_table: str, sqlite_id: str) -> None:
    with repository_connection() as connection:
        row = connection.execute(
            f"SELECT id FROM {sqlite_table} WHERE id = ?",  # nosec B608
            (sqlite_id,),
        ).fetchone()
    if row is None:
        raise ValueError(f"SQLite record not found in {sqlite_table}: {sqlite_id}")


def _fallback_collection(collection: str) -> dict[str, dict[str, object]]:
    return _FALLBACK_STORE[collection]


def _load_chroma_client() -> Any | None:
    global _CHROMA_CLIENT_INITIALIZED, _CHROMA_CLIENT, _CHROMA_CLIENT_PATH
    configured_path = os.environ.get(CHROMA_DB_PATH_ENV)
    if _CHROMA_CLIENT_INITIALIZED and configured_path == _CHROMA_CLIENT_PATH:
        return _CHROMA_CLIENT
    _CHROMA_CLIENT_INITIALIZED = True
    _CHROMA_CLIENT_PATH = configured_path
    try:
        chromadb = importlib.import_module("chromadb")
    except ModuleNotFoundError:
        _CHROMA_CLIENT = None
        return None
    if configured_path:
        _CHROMA_CLIENT = chromadb.PersistentClient(path=configured_path)
        return _CHROMA_CLIENT
    if hasattr(chromadb, "EphemeralClient"):
        _CHROMA_CLIENT = chromadb.EphemeralClient()
        return _CHROMA_CLIENT
    _CHROMA_CLIENT = chromadb.Client()
    return _CHROMA_CLIENT


def _require_embedder() -> EmbeddingProvider:
    if _EMBEDDING_PROVIDER is None:
        raise ValueError("No embedding provider configured for rebuild_collection()")
    return _EMBEDDING_PROVIDER


def _fetch_rebuild_rows(collection: str) -> list[dict[str, object]]:
    with repository_connection() as connection:
        rows = connection.execute(
            f"SELECT * FROM {collection} ORDER BY created_at ASC",  # nosec B608
        ).fetchall()
    return [dict(row) for row in rows]


def _canonical_index_text(collection: str, row: dict[str, object]) -> str:
    if collection == "observations":
        return str(row["content"])
    if collection == "reflections":
        return str(row["content"])
    if collection == "community_summaries":
        return f"{row['title']}\n\n{row['summary']}"
    raise ValueError(f"Unsupported collection: {collection!r}")


def _rebuild_metadata(collection: str, row: dict[str, object]) -> dict[str, object]:
    metadata: dict[str, object] = {"index_text_version": INDEX_TEXT_VERSION}
    if collection == "observations":
        metadata["role"] = row["role"]
        metadata["source"] = row["source"]
        return metadata
    if collection == "reflections":
        metadata["reflection_type"] = row["reflection_type"]
        metadata["status"] = row["status"]
        return metadata
    if collection == "community_summaries":
        metadata["community_id"] = row["community_id"]
        metadata["title"] = row["title"]
        return metadata
    raise ValueError(f"Unsupported collection: {collection!r}")


def _query_result_rows(result: dict[str, object], key: str) -> list[object]:
    values = result.get(key, [])
    if not isinstance(values, list):
        raise ValueError(f"Chroma query result field {key!r} must be a list")
    if not values:
        return []
    first = values[0]
    if not isinstance(first, list):
        raise ValueError(f"Chroma query result field {key!r} must contain row lists")
    return list(first)


def _cosine_distance(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("embedding lengths must match")
    left_norm = math.sqrt(sum(float(value) ** 2 for value in left))
    right_norm = math.sqrt(sum(float(value) ** 2 for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        raise ValueError("embedding norm must be non-zero")
    dot_product = sum(float(a) * float(b) for a, b in zip(left, right, strict=True))
    cosine_similarity = dot_product / (left_norm * right_norm)
    return 1.0 - cosine_similarity


def _as_float_list(value: object) -> list[float]:
    if not isinstance(value, list):
        raise ValueError("stored embedding must be a list")
    return [float(item) for item in value]


def _as_metadata_dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("metadata must be a dictionary")
    return {str(key): item for key, item in value.items()}


def _decode_pointer_metadata(pointer: dict[str, object]) -> dict[str, object]:
    metadata_json = pointer.get("metadata_json")
    if metadata_json is None:
        return _as_metadata_dict(pointer.get("metadata", {}))
    if not isinstance(metadata_json, str):
        raise ValueError("metadata_json must be a string")
    decoded = json.loads(metadata_json)
    return _as_metadata_dict(decoded)


def _as_float(value: object) -> float:
    if not isinstance(value, int | float):
        raise ValueError("distance must be numeric")
    return float(value)
