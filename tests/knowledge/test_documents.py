from __future__ import annotations

import io
import sqlite3
from typing import Any

import pytest

from core.db import chroma, repositories
from core.db.repositories import (
    create_knowledge_base,
    create_workspace,
    get_document,
    get_knowledge_base,
    list_document_chunks,
    list_documents,
)
from core.db.schema import (
    LEGACY_WORKSPACE_ID,
    schema_statements,
    seed_workspace_canonical_registries,
)
from core.knowledge.documents import (
    DocumentLimits,
    DocumentProcessingError,
    DocumentValidationError,
    S3DocumentStorage,
    build_s3_key,
    chunk_document,
    delete_document,
    extract_document,
    ingest_document,
)
from core.retrieval.documents import retrieve_document_chunks


class FakeStorage:
    bucket = "mira-test-documents"

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.uploads: list[dict[str, Any]] = []
        self.deleted: list[str] = []

    def upload(
        self,
        key: str,
        content: bytes,
        *,
        content_type: str,
        metadata: dict[str, str],
    ) -> None:
        self.objects[key] = content
        self.uploads.append({"key": key, "content_type": content_type, "metadata": dict(metadata)})

    def download(self, key: str) -> bytes:
        return self.objects[key]

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)
        self.deleted.append(key)


class FakeS3Client:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.objects: dict[str, bytes] = {}

    def put_object(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)
        self.objects[kwargs["Key"]] = kwargs["Body"]

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        return {"Body": io.BytesIO(self.objects[kwargs["Key"]])}

    def delete_object(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)
        self.objects.pop(kwargs["Key"], None)


@pytest.fixture
def workspace(monkeypatch: pytest.MonkeyPatch) -> str:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    for statement in schema_statements():
        connection.execute(statement)
    now = "2026-01-01T00:00:00+00:00"
    connection.execute(
        """
        INSERT INTO workspaces (
            id, name, slug, owner_user_id, workspace_type, status,
            expires_at, created_at, updated_at
        ) VALUES (?, ?, ?, NULL, 'legacy', 'active', NULL, ?, ?)
        """,
        (LEGACY_WORKSPACE_ID, "Legacy", "legacy-default", now, now),
    )
    seed_workspace_canonical_registries(connection, LEGACY_WORKSPACE_ID)
    connection.commit()
    monkeypatch.setattr(repositories, "_connect", lambda: connection)
    monkeypatch.setattr(chroma, "_load_chroma_client", lambda: None)
    for collection in chroma.SUPPORTED_COLLECTIONS:
        chroma._fallback_collection(collection).clear()
    return create_workspace("Knowledge test", "knowledge-test", "development")


def test_workspace_isolation_and_safe_key(workspace: str) -> None:
    other_workspace = create_workspace("Other", "knowledge-other", "development")
    kb_id = create_knowledge_base("Private docs", workspace_id=workspace)

    assert get_knowledge_base(kb_id, workspace_id=workspace) is not None
    assert get_knowledge_base(kb_id, workspace_id=other_workspace) is None
    assert build_s3_key(workspace, kb_id, "document-1", "../notes/plan.md") == (
        f"mira/workspaces/{workspace}/knowledge-bases/{kb_id}/documents/document-1/plan.md"
    )


def test_ingest_txt_uploads_metadata_chunks_and_retrieves_provenance(workspace: str) -> None:
    kb_id = create_knowledge_base("Project docs", workspace_id=workspace)
    storage = FakeStorage()
    ingested = ingest_document(
        workspace_id=workspace,
        knowledge_base_id=kb_id,
        filename="../project.md",
        mime_type="text/markdown",
        content=(
            b"# Architecture\n\nMIRA stores document originals privately.\n\n"
            b"The chunks retain source provenance."
        ),
        storage=storage,
        embedder=lambda _text: [1.0, 0.0, 0.0],
    )

    assert ingested.document["status"] == "ready"
    assert ingested.document["filename"] == "project.md"
    assert ingested.document["s3_bucket"] == storage.bucket
    assert ingested.document["s3_key"].endswith("/project.md")
    assert storage.uploads[0]["metadata"]["workspace-id"] == workspace
    assert ingested.chunks
    assert list_document_chunks(str(ingested.document["id"]), workspace_id=workspace)

    results = retrieve_document_chunks(
        "private document provenance",
        workspace_id=workspace,
        knowledge_base_id=kb_id,
        embedder=lambda _text: [1.0, 0.0, 0.0],
    )
    assert results
    result = results[0]
    assert result["source_type"] == "document_chunk"
    assert result["document_id"] == ingested.document["id"]
    assert result["knowledge_base_id"] == kb_id
    assert result["chunk_id"] == ingested.chunks[0]["id"]
    assert "relevance_score" in result["provenance"]

    assert (
        retrieve_document_chunks(
            "private document provenance",
            workspace_id="not-the-owner",
            embedder=lambda _text: [1.0, 0.0, 0.0],
        )
        == []
    )


def test_document_limits_and_unsupported_types(workspace: str) -> None:
    limits = DocumentLimits(max_bytes=4, max_pdf_pages=2, max_extracted_characters=10)
    with pytest.raises(DocumentValidationError, match="size limit"):
        extract_document("notes.txt", b"12345", limits=limits)
    with pytest.raises(DocumentValidationError, match="unsupported"):
        extract_document("archive.zip", b"data")
    with pytest.raises(DocumentValidationError, match="UTF-8"):
        extract_document("notes.txt", b"\xff")


def test_pdf_text_and_scanned_pdf_rejection() -> None:
    fitz = pytest.importorskip("fitz")
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Text PDF page")
    pdf_bytes = document.tobytes()
    document.close()
    pages, count = extract_document("text.pdf", pdf_bytes)
    assert pages[0].page_start == 1
    assert "Text PDF page" in pages[0].text
    assert count > 0

    scanned = fitz.open()
    scanned.new_page()
    scanned_bytes = scanned.tobytes()
    scanned.close()
    with pytest.raises(DocumentValidationError, match="scanned|image-only"):
        extract_document("scan.pdf", scanned_bytes)


def test_docx_extraction_and_chunk_bounds() -> None:
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_heading("Heading", level=1)
    document.add_paragraph("A paragraph from a DOCX file.")
    stream = io.BytesIO()
    document.save(stream)
    pages, count = extract_document("brief.docx", stream.getvalue())
    assert "Heading" in pages[0].text
    assert count > 0

    chunks = chunk_document(
        [pages[0]],
        limits=DocumentLimits(chunk_size=20, chunk_overlap=5),
    )
    assert chunks
    assert all(0 < len(chunk.content) <= 20 for chunk in chunks)


def test_failed_processing_records_failed_status_and_delete_preserves_audit(workspace: str) -> None:
    kb_id = create_knowledge_base("Failures", workspace_id=workspace)
    storage = FakeStorage()
    with pytest.raises(DocumentProcessingError, match="PyMuPDF|processing failed"):
        ingest_document(
            workspace_id=workspace,
            knowledge_base_id=kb_id,
            filename="empty.pdf",
            content=b"not-a-pdf",
            storage=storage,
            embedder=lambda _text: [1.0, 0.0],
        )

    # Validation/extraction failures happen after the row exists and are observable.
    # The invalid bytes above fail during PDF parsing, so the storage object remains
    # available for a future controlled retry or cleanup operation.
    assert storage.uploads
    failed_documents = list_documents(kb_id, workspace_id=workspace, include_deleted=True)
    assert failed_documents[0]["status"] == "failed"

    ingested = ingest_document(
        workspace_id=workspace,
        knowledge_base_id=kb_id,
        filename="keep.txt",
        content=b"Keep this audit row.",
        storage=storage,
        embedder=lambda _text: [1.0, 0.0],
    )
    deleted = delete_document(str(ingested.document["id"]), workspace_id=workspace, storage=storage)
    assert deleted["status"] == "deleted"
    assert str(ingested.document["s3_key"]) in storage.deleted
    assert list_document_chunks(str(ingested.document["id"]), workspace_id=workspace) == []
    assert (
        get_document(str(ingested.document["id"]), workspace_id=workspace, include_deleted=True)
        is not None
    )
    assert (
        retrieve_document_chunks(
            "audit row", workspace_id=workspace, embedder=lambda _text: [1.0, 0.0]
        )
        == []
    )


def test_s3_storage_is_injectable_and_uses_private_upload_options() -> None:
    client = FakeS3Client()
    storage = S3DocumentStorage(bucket="bucket", region="eu-north-1", client=client)
    storage.upload("safe.txt", b"hello", content_type="text/plain", metadata={"kind": "test"})
    assert client.calls[0]["ServerSideEncryption"] == "AES256"
    assert storage.download("safe.txt") == b"hello"
    storage.delete("safe.txt")
    assert client.objects == {}
