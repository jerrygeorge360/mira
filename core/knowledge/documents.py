"""Document ingestion, extraction, storage, chunking, and indexing.

Documents are source evidence for retrieval, not durable human memory. SQLite
owns metadata and provenance; S3 owns private originals; Chroma stores only
rebuildable chunk pointers and embeddings.
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import re
import unicodedata
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from core.db import chroma
from core.db.repositories import (
    RepositoryRecord,
    create_document,
    create_document_chunk,
    delete_document_chunks,
    get_document,
    get_knowledge_base,
    list_document_chunks,
    mark_document_deleted,
    update_document,
)
from core.llm.embeddings import embed_text

LOGGER = logging.getLogger(__name__)

DEFAULT_S3_REGION = "eu-north-1"
DOCUMENTS_BUCKET_ENV = "MIRA_DOCUMENTS_S3_BUCKET"

MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 100
MAX_EXTRACTED_CHARACTERS = 200_000
DEFAULT_CHUNK_SIZE = 1_200
DEFAULT_CHUNK_OVERLAP = 200

SUPPORTED_EXTENSIONS = frozenset({".txt", ".md", ".docx", ".pdf"})
DOCUMENT_STATUS_VALUES = frozenset({"uploaded", "processing", "ready", "failed", "deleted"})
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
_SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")
_HEADING_PATTERN = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$")


class DocumentValidationError(ValueError):
    """Raised when a document violates the supported-input contract."""


class DocumentStorageError(RuntimeError):
    """Raised when an original cannot be written to or read from S3."""


class DocumentProcessingError(RuntimeError):
    """Raised when an uploaded document cannot be extracted or indexed."""


def _aws_error_detail(error: Exception) -> str:
    """Return a safe AWS error code/message without exposing credentials."""
    response = getattr(error, "response", None)
    if isinstance(response, dict):
        details = response.get("Error")
        if isinstance(details, dict):
            code = str(details.get("Code") or error.__class__.__name__).strip()
            message = str(details.get("Message") or "").strip()
            if message:
                return f"{code}: {message}"
            return code
    return error.__class__.__name__


@dataclass(frozen=True)
class DocumentLimits:
    max_bytes: int = MAX_DOCUMENT_BYTES
    max_pdf_pages: int = MAX_PDF_PAGES
    max_extracted_characters: int = MAX_EXTRACTED_CHARACTERS
    chunk_size: int = DEFAULT_CHUNK_SIZE
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP

    def __post_init__(self) -> None:
        if self.max_bytes < 1 or self.max_pdf_pages < 1 or self.max_extracted_characters < 1:
            raise ValueError("document limits must be positive")
        if self.chunk_size < 1 or self.chunk_overlap < 0 or self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be less than a positive chunk_size")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value


DEFAULT_LIMITS = DocumentLimits(
    max_bytes=_env_int("MIRA_DOCUMENT_MAX_BYTES", MAX_DOCUMENT_BYTES),
    max_pdf_pages=_env_int("MIRA_DOCUMENT_MAX_PDF_PAGES", MAX_PDF_PAGES),
    max_extracted_characters=_env_int(
        "MIRA_DOCUMENT_MAX_EXTRACTED_CHARACTERS", MAX_EXTRACTED_CHARACTERS
    ),
    chunk_size=_env_int("MIRA_DOCUMENT_CHUNK_SIZE", DEFAULT_CHUNK_SIZE),
    chunk_overlap=int(os.environ.get("MIRA_DOCUMENT_CHUNK_OVERLAP", DEFAULT_CHUNK_OVERLAP)),
)


@dataclass(frozen=True)
class ExtractedPage:
    text: str
    page_start: int | None = None
    page_end: int | None = None
    heading: str | None = None


@dataclass(frozen=True)
class DocumentChunk:
    content: str
    chunk_index: int
    page_start: int | None
    page_end: int | None
    heading: str | None
    char_start: int
    char_end: int


@dataclass(frozen=True)
class IngestedDocument:
    document: RepositoryRecord
    chunks: tuple[RepositoryRecord, ...]


class DocumentStorage(Protocol):
    def upload(
        self,
        key: str,
        content: bytes,
        *,
        content_type: str,
        metadata: dict[str, str],
    ) -> None:
        """Write one private original."""

    def download(self, key: str) -> bytes:
        """Read one original."""

    def delete(self, key: str) -> None:
        """Delete one original."""


class S3DocumentStorage:
    """Private S3 storage using boto3's default credential provider chain."""

    def __init__(
        self,
        *,
        bucket: str | None = None,
        region: str = DEFAULT_S3_REGION,
        client: Any | None = None,
    ) -> None:
        self.bucket = (bucket or os.environ.get(DOCUMENTS_BUCKET_ENV, "")).strip()
        if not self.bucket:
            raise DocumentStorageError(f"{DOCUMENTS_BUCKET_ENV} must be configured")
        self.region = region
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                import boto3
            except ImportError as error:
                raise DocumentStorageError("boto3 is required for document storage") from error
            self._client = boto3.client("s3", region_name=self.region)
        return self._client

    def upload(
        self,
        key: str,
        content: bytes,
        *,
        content_type: str,
        metadata: dict[str, str],
    ) -> None:
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=content,
                ContentType=content_type,
                Metadata=metadata,
                ServerSideEncryption="AES256",
            )
        except Exception as error:
            raise DocumentStorageError(f"S3 upload failed ({_aws_error_detail(error)})") from error

    def download(self, key: str) -> bytes:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            body = response["Body"]
            try:
                return bytes(body.read())
            finally:
                close = getattr(body, "close", None)
                if callable(close):
                    close()
        except Exception as error:
            raise DocumentStorageError(f"S3 download failed for {key}") from error

    def delete(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except Exception as error:
            raise DocumentStorageError(f"S3 delete failed for {key}") from error


def safe_filename(filename: str) -> str:
    """Return a path-safe basename suitable for an S3 object key."""
    if not isinstance(filename, str) or not filename.strip():
        raise DocumentValidationError("filename must not be empty")
    normalized = unicodedata.normalize("NFKC", filename).replace("\\", "/")
    basename = normalized.rsplit("/", 1)[-1].strip()
    if basename in {"", ".", ".."} or "\x00" in basename:
        raise DocumentValidationError("filename must contain a safe basename")
    sanitized = _SAFE_FILENAME_PATTERN.sub("_", basename).strip("._")
    if not sanitized:
        raise DocumentValidationError("filename must contain letters or numbers")
    suffix = os.path.splitext(sanitized)[1].casefold()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise DocumentValidationError("unsupported document type; use .txt, .md, .docx, or .pdf")
    return sanitized


def validate_document(
    filename: str,
    content: bytes,
    *,
    mime_type: str | None = None,
    limits: DocumentLimits = DEFAULT_LIMITS,
) -> tuple[str, str]:
    """Validate size, extension, and MIME compatibility before persistence."""
    if not isinstance(content, bytes):
        raise DocumentValidationError("document content must be bytes")
    if len(content) > limits.max_bytes:
        raise DocumentValidationError(
            f"document exceeds the {limits.max_bytes // (1024 * 1024)} MB size limit"
        )
    safe_name = safe_filename(filename)
    suffix = os.path.splitext(safe_name)[1].casefold()
    canonical_mime = {
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".pdf": "application/pdf",
    }[suffix]
    supplied = (mime_type or "").split(";", 1)[0].strip().casefold()
    allowed_mimes = {canonical_mime, "application/octet-stream"}
    if supplied and supplied not in allowed_mimes:
        raise DocumentValidationError(f"MIME type does not match {suffix} documents")
    return safe_name, canonical_mime


def build_s3_key(
    workspace_id: str,
    knowledge_base_id: str,
    document_id: str,
    filename: str,
) -> str:
    """Build the stable, workspace-scoped original object key."""
    for name, value in (
        ("workspace_id", workspace_id),
        ("knowledge_base_id", knowledge_base_id),
        ("document_id", document_id),
    ):
        if not _IDENTIFIER_PATTERN.fullmatch(value):
            raise DocumentValidationError(f"{name} must be a safe identifier")
    return (
        f"mira/workspaces/{workspace_id}/knowledge-bases/{knowledge_base_id}/"
        f"documents/{document_id}/{safe_filename(filename)}"
    )


def extract_document(
    filename: str,
    content: bytes,
    *,
    mime_type: str | None = None,
    limits: DocumentLimits = DEFAULT_LIMITS,
) -> tuple[tuple[ExtractedPage, ...], int]:
    """Extract supported text and return pages/sections plus character count."""
    safe_name, _ = validate_document(filename, content, mime_type=mime_type, limits=limits)
    suffix = os.path.splitext(safe_name)[1].casefold()
    pages: tuple[ExtractedPage, ...]
    if suffix in {".txt", ".md"}:
        text = _decode_text(content)
        pages = (ExtractedPage(text=_normalize_text(text)),)
    elif suffix == ".docx":
        pages = (_extract_docx(content),)
    else:
        pages = _extract_pdf(content, limits=limits)
    character_count = sum(len(page.text) for page in pages)
    if character_count > limits.max_extracted_characters:
        raise DocumentValidationError(
            f"extracted text exceeds the {limits.max_extracted_characters:,} character limit"
        )
    if not any(page.text.strip() for page in pages):
        raise DocumentValidationError(
            "PDF contains no extractable text; scanned or image-only PDFs are not supported"
        )
    return pages, character_count


def chunk_document(
    pages: Iterable[ExtractedPage],
    *,
    limits: DocumentLimits = DEFAULT_LIMITS,
) -> tuple[DocumentChunk, ...]:
    """Create bounded, paragraph-aware chunks with overlap and page provenance."""
    chunks: list[DocumentChunk] = []
    current = ""
    current_start = 0
    current_page_start: int | None = None
    current_page_end: int | None = None
    current_heading: str | None = None
    absolute_offset = 0

    def flush() -> None:
        nonlocal current, current_start, current_page_start, current_page_end, current_heading
        content = current.strip()
        if not content:
            current = ""
            return
        chunks.append(
            DocumentChunk(
                content=content,
                chunk_index=len(chunks),
                page_start=current_page_start,
                page_end=current_page_end,
                heading=current_heading,
                char_start=current_start,
                char_end=current_start + len(content),
            )
        )
        overlap = content[-limits.chunk_overlap :]
        current = overlap
        current_start = max(current_start, current_start + len(content) - len(overlap))
        current_page_start = current_page_start
        current_page_end = current_page_end

    for page in pages:
        page_text = _normalize_text(page.text)
        if not page_text.strip():
            absolute_offset += len(page_text)
            continue
        units = _paragraph_units(page_text, page.heading)
        for unit, heading in units:
            if len(unit) > limits.chunk_size:
                if current.strip():
                    flush()
                for part in _split_long_text(unit, limits.chunk_size, limits.chunk_overlap):
                    chunks.append(
                        DocumentChunk(
                            content=part,
                            chunk_index=len(chunks),
                            page_start=page.page_start,
                            page_end=page.page_end,
                            heading=heading,
                            char_start=absolute_offset,
                            char_end=absolute_offset + len(part),
                        )
                    )
                absolute_offset += len(unit)
                current = ""
                current_page_start = None
                current_page_end = None
                current_heading = None
                continue
            candidate = f"{current}\n\n{unit}".strip() if current.strip() else unit
            if current.strip() and len(candidate) > limits.chunk_size:
                flush()
                candidate = f"{current}\n\n{unit}".strip() if current.strip() else unit
            if not current.strip():
                current_start = absolute_offset
                current_page_start = page.page_start
                current_page_end = page.page_end
                current_heading = heading
            current = candidate
            if page.page_start is not None:
                current_page_start = (
                    page.page_start
                    if current_page_start is None
                    else min(current_page_start, page.page_start)
                )
                page_end = page.page_end if page.page_end is not None else page.page_start
                current_page_end = (
                    page_end if current_page_end is None else max(current_page_end, page_end)
                )
            if heading and not current_heading:
                current_heading = heading
            absolute_offset += len(unit)
        absolute_offset += 2
    if current.strip():
        flush()
    return tuple(chunks)


def ingest_document(
    *,
    workspace_id: str,
    knowledge_base_id: str,
    filename: str,
    content: bytes,
    storage: DocumentStorage,
    mime_type: str | None = None,
    limits: DocumentLimits = DEFAULT_LIMITS,
    embedder: Callable[[str], list[float]] = embed_text,
    document_id: str | None = None,
) -> IngestedDocument:
    """Persist, extract, chunk, and index one document synchronously."""
    safe_name, canonical_mime = validate_document(
        filename, content, mime_type=mime_type, limits=limits
    )
    knowledge_base = get_knowledge_base(knowledge_base_id, workspace_id=workspace_id)
    if knowledge_base is None:
        raise DocumentValidationError("knowledge base not found in workspace")
    identifier = document_id or uuid.uuid4().hex
    key = build_s3_key(workspace_id, knowledge_base_id, identifier, safe_name)
    checksum = hashlib.sha256(content).hexdigest()
    create_document(
        {
            "id": identifier,
            "workspace_id": workspace_id,
            "knowledge_base_id": knowledge_base_id,
            "filename": safe_name,
            "mime_type": canonical_mime,
            "size_bytes": len(content),
            "s3_bucket": getattr(storage, "bucket", os.environ.get(DOCUMENTS_BUCKET_ENV, "")),
            "s3_key": key,
            "checksum_sha256": checksum,
            "status": "uploaded",
        },
        workspace_id=workspace_id,
    )
    indexed_chunk_ids: list[str] = []
    try:
        storage.upload(
            key,
            content,
            content_type=canonical_mime,
            metadata={
                "workspace-id": workspace_id,
                "knowledge-base-id": knowledge_base_id,
                "document-id": identifier,
                "sha256": checksum,
            },
        )
        update_document(identifier, workspace_id=workspace_id, status="processing")
        pages, extracted_characters = extract_document(
            safe_name, content, mime_type=canonical_mime, limits=limits
        )
        chunks = chunk_document(pages, limits=limits)
        if not chunks:
            raise DocumentProcessingError("document produced no searchable chunks")
        for chunk in chunks:
            chunk_id = create_document_chunk(
                {
                    "workspace_id": workspace_id,
                    "knowledge_base_id": knowledge_base_id,
                    "document_id": identifier,
                    "chunk_index": chunk.chunk_index,
                    "content": chunk.content,
                    "heading": chunk.heading,
                    "page_start": chunk.page_start,
                    "page_end": chunk.page_end,
                    "char_start": chunk.char_start,
                    "char_end": chunk.char_end,
                },
                workspace_id=workspace_id,
            )
            chroma.add_embedding(
                "document_chunks",
                "document_chunks",
                chunk_id,
                embedder(chunk.content),
                metadata={
                    "source_type": "document_chunk",
                    "knowledge_base_id": knowledge_base_id,
                    "document_id": identifier,
                    "filename": safe_name,
                    "chunk_index": chunk.chunk_index,
                    "page_start": chunk.page_start,
                    "page_end": chunk.page_end,
                },
                workspace_id=workspace_id,
            )
            indexed_chunk_ids.append(chunk_id)
        update_document(
            identifier,
            workspace_id=workspace_id,
            status="ready",
            page_count=len(pages),
            extracted_char_count=extracted_characters,
            processed_at=_now(),
        )
    except Exception as error:
        for chunk_id in indexed_chunk_ids:
            chroma.remove_from_index(chunk_id, workspace_id=workspace_id)
        delete_document_chunks(identifier, workspace_id=workspace_id)
        update_document(
            identifier,
            workspace_id=workspace_id,
            status="failed",
            error_message=str(error)[:2_000] or error.__class__.__name__,
        )
        if isinstance(
            error,
            (DocumentValidationError, DocumentProcessingError, DocumentStorageError),
        ):
            raise
        raise DocumentProcessingError("document processing failed") from error
    record = get_document(identifier, workspace_id=workspace_id, include_deleted=True)
    if record is None:
        raise DocumentProcessingError("document disappeared after processing")
    # Enrichment is a separate lifecycle. Its queue may be temporarily unavailable,
    # but the already indexed document remains ready for ordinary retrieval.
    from core.knowledge.enrichment import enrichment_enabled_for_workspace

    if enrichment_enabled_for_workspace(workspace_id):
        try:
            from core.db.evidence import enqueue_document_job

            enqueue_document_job(identifier, workspace_id=workspace_id)
        except Exception:
            LOGGER.exception("Could not queue document enrichment for %s", identifier)
    return IngestedDocument(
        record,
        tuple(list_document_chunks(identifier, workspace_id=workspace_id)),
    )


def delete_document(
    document_id: str,
    *,
    workspace_id: str,
    storage: DocumentStorage,
) -> RepositoryRecord:
    """Remove a document from retrieval while retaining an audit row."""
    document = get_document(document_id, workspace_id=workspace_id, include_deleted=True)
    if document is None:
        raise DocumentValidationError("document not found in workspace")
    from core.knowledge.enrichment import cancel_and_retract_document

    cancel_and_retract_document(document_id, workspace_id=workspace_id)
    chunk_ids = mark_document_deleted(document_id, workspace_id=workspace_id)
    for chunk_id in chunk_ids:
        chroma.remove_from_index(chunk_id, workspace_id=workspace_id)
    storage.delete(str(document["s3_key"]))
    updated = get_document(document_id, workspace_id=workspace_id, include_deleted=True)
    if updated is None:
        raise DocumentProcessingError("deleted document audit row was not found")
    return updated


def _decode_text(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise DocumentValidationError("text documents must be UTF-8 encoded") from error


def _extract_docx(content: bytes) -> ExtractedPage:
    try:
        from docx import Document
    except ImportError as error:
        raise DocumentProcessingError("python-docx is required for DOCX extraction") from error
    try:
        document = Document(io.BytesIO(content))
        lines: list[str] = []
        current_heading: str | None = None
        for paragraph in document.paragraphs:
            text = paragraph.text.strip()
            if not text:
                continue
            style_name = str(getattr(paragraph.style, "name", ""))
            if style_name.casefold().startswith("heading"):
                current_heading = text
                lines.append(text)
            else:
                lines.append(text)
        return ExtractedPage(text="\n\n".join(lines), heading=current_heading)
    except Exception as error:
        raise DocumentProcessingError("DOCX extraction failed") from error


def _extract_pdf(content: bytes, *, limits: DocumentLimits) -> tuple[ExtractedPage, ...]:
    try:
        import fitz
    except ImportError as error:
        raise DocumentProcessingError("PyMuPDF is required for PDF extraction") from error
    try:
        with fitz.open(stream=content, filetype="pdf") as document:
            if len(document) > limits.max_pdf_pages:
                raise DocumentValidationError(f"PDF exceeds the {limits.max_pdf_pages} page limit")
            pages = tuple(
                ExtractedPage(
                    text=_normalize_text(page.get_text("text")),
                    page_start=index,
                    page_end=index,
                )
                for index, page in enumerate(document, start=1)
            )
    except DocumentValidationError:
        raise
    except Exception as error:
        raise DocumentProcessingError("PDF extraction failed") from error
    if not any(page.text.strip() for page in pages):
        raise DocumentValidationError(
            "PDF contains no extractable text; scanned or image-only PDFs are not supported"
        )
    return pages


def _paragraph_units(text: str, default_heading: str | None) -> list[tuple[str, str | None]]:
    units: list[tuple[str, str | None]] = []
    heading = default_heading
    for paragraph in re.split(r"\n\s*\n", text):
        value = paragraph.strip()
        if not value:
            continue
        match = _HEADING_PATTERN.match(value)
        if match:
            heading = match.group(2).strip()
        units.append((value, heading))
    return units


def _split_long_text(text: str, size: int, overlap: int) -> list[str]:
    parts: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            boundary = text.rfind(" ", start, end)
            if boundary > start:
                end = boundary
        part = text[start:end].strip()
        if part:
            parts.append(part)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return parts


def _normalize_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in normalized.split("\n")).strip()


def _now() -> str:
    return datetime.now(UTC).isoformat()
