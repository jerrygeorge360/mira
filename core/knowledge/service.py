"""Workspace-scoped service operations for document Knowledge Bases."""

from __future__ import annotations

import os
from datetime import UTC, datetime

from core.db import chroma
from core.db.repositories import (
    create_knowledge_base as repository_create_knowledge_base,
)
from core.db.repositories import (
    get_document as repository_get_document,
)
from core.db.repositories import (
    get_knowledge_base as repository_get_knowledge_base,
)
from core.db.repositories import (
    list_documents as repository_list_documents,
)
from core.db.repositories import (
    list_knowledge_bases as repository_list_knowledge_bases,
)
from core.db.repositories import (
    repository_connection,
)
from core.knowledge.documents import (
    DOCUMENTS_BUCKET_ENV,
    DocumentProcessingError,
    DocumentStorage,
    DocumentStorageError,
    S3DocumentStorage,
    ingest_document,
)
from core.knowledge.documents import (
    delete_document as ingest_delete_document,
)


def create_knowledge_base(
    *, workspace_id: str, name: str, description: str | None = None
) -> dict[str, object]:
    identifier = repository_create_knowledge_base(
        name,
        description=description,
        workspace_id=workspace_id,
    )
    record = repository_get_knowledge_base(identifier, workspace_id=workspace_id)
    if record is None:
        raise DocumentProcessingError("knowledge base was not created")
    return _knowledge_base_record(record, workspace_id=workspace_id)


def list_knowledge_bases(*, workspace_id: str) -> list[dict[str, object]]:
    return [
        _knowledge_base_record(record, workspace_id=workspace_id)
        for record in repository_list_knowledge_bases(workspace_id=workspace_id)
    ]


def get_knowledge_base(
    *, workspace_id: str, knowledge_base_id: str
) -> dict[str, object]:
    record = repository_get_knowledge_base(knowledge_base_id, workspace_id=workspace_id)
    if record is None:
        raise LookupError("knowledge base not found in workspace")
    documents = repository_list_documents(knowledge_base_id, workspace_id=workspace_id)
    return {
        **_knowledge_base_record(record, workspace_id=workspace_id),
        "documents": [
            _document_record(document, workspace_id=workspace_id)
            for document in documents
        ],
    }


def list_documents(
    *, workspace_id: str, knowledge_base_id: str
) -> list[dict[str, object]]:
    _require_knowledge_base(workspace_id, knowledge_base_id)
    return [
        _document_record(document, workspace_id=workspace_id)
        for document in repository_list_documents(
            knowledge_base_id,
            workspace_id=workspace_id,
        )
    ]


def get_document(*, workspace_id: str, document_id: str) -> dict[str, object]:
    record = repository_get_document(document_id, workspace_id=workspace_id)
    if record is None:
        raise LookupError("document not found in workspace")
    return _document_record(record, workspace_id=workspace_id)


def process_document_upload(
    *,
    workspace_id: str,
    knowledge_base_id: str,
    filename: str,
    content: bytes,
    mime_type: str | None = None,
) -> dict[str, object]:
    _require_knowledge_base(workspace_id, knowledge_base_id)
    result = ingest_document(
        workspace_id=workspace_id,
        knowledge_base_id=knowledge_base_id,
        filename=filename,
        content=content,
        mime_type=mime_type,
        storage=get_document_storage(),
    )
    return _document_record(
        result.document,
        workspace_id=workspace_id,
        chunk_count=len(result.chunks),
    )


def delete_document(*, workspace_id: str, document_id: str) -> dict[str, object]:
    record = repository_get_document(document_id, workspace_id=workspace_id, include_deleted=True)
    if record is None:
        raise LookupError("document not found in workspace")
    if record.get("status") != "deleted":
        ingest_delete_document(
            document_id,
            workspace_id=workspace_id,
            storage=get_document_storage(),
        )
    deleted = repository_get_document(document_id, workspace_id=workspace_id, include_deleted=True)
    if deleted is None:
        raise DocumentProcessingError("deleted document audit row was not found")
    return _document_record(deleted, workspace_id=workspace_id, chunk_count=0)


def delete_knowledge_base(*, workspace_id: str, knowledge_base_id: str) -> dict[str, object]:
    base = _require_knowledge_base(workspace_id, knowledge_base_id)
    documents = repository_list_documents(knowledge_base_id, workspace_id=workspace_id)
    storage = get_document_storage()
    deleted_documents = 0
    for document in documents:
        if document.get("status") == "deleted":
            continue
        ingest_delete_document(
            str(document["id"]),
            workspace_id=workspace_id,
            storage=storage,
        )
        deleted_documents += 1
    now = _now()
    with repository_connection() as connection:
        connection.execute(
            "UPDATE knowledge_bases SET status = 'deleted', updated_at = ? "
            "WHERE id = ? AND workspace_id = ?",
            (now, knowledge_base_id, workspace_id),
        )
    return {
        "status": "deleted",
        "knowledge_base_id": knowledge_base_id,
        "documents_deleted": deleted_documents,
        "name": base.get("name"),
    }


def delete_workspace_knowledge_data(*, workspace_id: str) -> dict[str, int]:
    """Remove workspace document rows, vectors, and originals during a reset."""
    documents = _workspace_documents(workspace_id)
    s3_deleted = 0
    storage: DocumentStorage | None = None
    if documents:
        try:
            storage = get_document_storage()
        except DocumentStorageError:
            storage = None
    for document in documents:
        if storage is not None:
            try:
                storage.delete(str(document["s3_key"]))
                s3_deleted += 1
            except DocumentStorageError:
                pass
    chroma.delete_workspace_vectors("document_chunks", workspace_id=workspace_id)
    with repository_connection() as connection:
        chunk_count = connection.execute(
            "SELECT COUNT(*) AS count FROM document_chunks WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()
        document_count = connection.execute(
            "SELECT COUNT(*) AS count FROM documents WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()
        base_count = connection.execute(
            "SELECT COUNT(*) AS count FROM knowledge_bases WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()
        connection.execute("DELETE FROM document_chunks WHERE workspace_id = ?", (workspace_id,))
        connection.execute("DELETE FROM documents WHERE workspace_id = ?", (workspace_id,))
        connection.execute("DELETE FROM knowledge_bases WHERE workspace_id = ?", (workspace_id,))
    return {
        "chunks": int(chunk_count["count"] if chunk_count else 0),
        "documents": int(document_count["count"] if document_count else 0),
        "knowledge_bases": int(base_count["count"] if base_count else 0),
        "s3_objects": s3_deleted,
    }


def get_document_storage() -> DocumentStorage:
    """Build storage lazily so local tests can run without AWS credentials."""
    return S3DocumentStorage(
        bucket=os.environ.get(DOCUMENTS_BUCKET_ENV),
        region=os.environ.get("AWS_REGION", "eu-north-1"),
    )


def _require_knowledge_base(workspace_id: str, knowledge_base_id: str) -> dict[str, object]:
    record = repository_get_knowledge_base(knowledge_base_id, workspace_id=workspace_id)
    if record is None:
        raise LookupError("knowledge base not found in workspace")
    return record


def _workspace_documents(workspace_id: str) -> list[dict[str, object]]:
    with repository_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM documents WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _knowledge_base_record(record: dict[str, object], *, workspace_id: str) -> dict[str, object]:
    result = dict(record)
    result["workspace_id"] = workspace_id
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM documents "
            "WHERE knowledge_base_id = ? AND workspace_id = ? AND status != 'deleted'",
            (str(record["id"]), workspace_id),
        ).fetchone()
    result["document_count"] = int(row["count"] if row else 0)
    return result


def _document_record(
    record: dict[str, object],
    *,
    workspace_id: str,
    chunk_count: int | None = None,
) -> dict[str, object]:
    result = dict(record)
    result["workspace_id"] = workspace_id
    result["checksum"] = result.get("checksum_sha256")
    result["error"] = result.get("error_message")
    result["character_count"] = result.get("extracted_char_count")
    if chunk_count is None:
        with repository_connection() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM document_chunks WHERE document_id = ? "
                "AND workspace_id = ?",
                (str(record["id"]), workspace_id),
            ).fetchone()
        chunk_count = int(row["count"] if row else 0)
    result["chunk_count"] = chunk_count
    return result


def _now() -> str:
    return datetime.now(UTC).isoformat()

