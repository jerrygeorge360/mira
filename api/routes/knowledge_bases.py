"""Workspace-scoped Knowledge Base and document routes.

The document lifecycle itself belongs to ``core.knowledge.service``.  Keeping
that import lazy lets the API and the core service be developed independently,
while still making the workspace boundary explicit at every service call.
"""

from __future__ import annotations

import dataclasses
import importlib
import os
from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from api.auth import WorkspaceAuth, require_csrf
from api.schemas.knowledge_bases import (
    CreateKnowledgeBaseRequest,
    DocumentListResponse,
    DocumentResponse,
    KnowledgeBaseDetailResponse,
    KnowledgeBaseListResponse,
    KnowledgeBaseResponse,
)
from core.knowledge.documents import (
    MAX_DOCUMENT_BYTES,
    DocumentProcessingError,
    DocumentStorageError,
    DocumentValidationError,
)

router = APIRouter(tags=["knowledge-bases"])

DEFAULT_MAX_DOCUMENT_BYTES = MAX_DOCUMENT_BYTES
MAX_DOCUMENT_BYTES_ENV = "MIRA_DOCUMENT_MAX_BYTES"
LEGACY_MAX_DOCUMENT_BYTES_ENV = "MIRA_KNOWLEDGE_MAX_DOCUMENT_BYTES"


@router.post("/knowledge-bases", response_model=KnowledgeBaseResponse, status_code=201)
def create_knowledge_base(
    request: Request,
    payload: CreateKnowledgeBaseRequest,
    auth: WorkspaceAuth,
) -> KnowledgeBaseResponse:
    """Create a Knowledge Base owned by the authenticated workspace."""
    require_csrf(request, auth)
    result = _service_call(
        "create_knowledge_base",
        workspace_id=auth.context.workspace_id,
        name=payload.name,
        description=payload.description,
    )
    return KnowledgeBaseResponse.model_validate(_with_workspace(result, auth.context.workspace_id))


@router.get("/knowledge-bases", response_model=KnowledgeBaseListResponse)
def list_knowledge_bases(auth: WorkspaceAuth) -> KnowledgeBaseListResponse:
    """List only Knowledge Bases belonging to the authenticated workspace."""
    result = _service_call("list_knowledge_bases", workspace_id=auth.context.workspace_id)
    items = _items(result)
    return KnowledgeBaseListResponse(
        items=[
            KnowledgeBaseResponse.model_validate(_with_workspace(item, auth.context.workspace_id))
            for item in items
        ]
    )


@router.get(
    "/knowledge-bases/{knowledge_base_id}",
    response_model=KnowledgeBaseDetailResponse,
)
def get_knowledge_base(
    knowledge_base_id: str,
    auth: WorkspaceAuth,
) -> KnowledgeBaseDetailResponse:
    """Return one workspace-scoped Knowledge Base and its documents."""
    result = _service_call(
        "get_knowledge_base",
        workspace_id=auth.context.workspace_id,
        knowledge_base_id=knowledge_base_id,
    )
    record = _with_workspace(result, auth.context.workspace_id)
    documents = _items(record.get("documents"))
    if not documents:
        documents = _items(
            _service_call(
                "list_documents",
                workspace_id=auth.context.workspace_id,
                knowledge_base_id=knowledge_base_id,
            )
        )
    record["documents"] = [
        _document_record(document, auth.context.workspace_id, knowledge_base_id)
        for document in documents
    ]
    record.setdefault("document_count", len(documents))
    return KnowledgeBaseDetailResponse.model_validate(record)


@router.delete("/knowledge-bases/{knowledge_base_id}")
def delete_knowledge_base(
    request: Request,
    knowledge_base_id: str,
    auth: WorkspaceAuth,
) -> dict[str, object]:
    """Delete a Knowledge Base and clean up its document retrieval artifacts."""
    require_csrf(request, auth)
    result = _service_call(
        "delete_knowledge_base",
        workspace_id=auth.context.workspace_id,
        knowledge_base_id=knowledge_base_id,
    )
    return _deletion_response(result, knowledge_base_id, "knowledge_base")


@router.post(
    "/knowledge-bases/{knowledge_base_id}/documents",
    response_model=DocumentResponse,
    status_code=201,
)
async def upload_document(
    request: Request,
    knowledge_base_id: str,
    auth: WorkspaceAuth,
    file: UploadFile = File(...),  # noqa: B008
) -> DocumentResponse:
    """Upload, process, and index one supported document synchronously."""
    require_csrf(request, auth)
    filename = (file.filename or "").strip()
    if not filename:
        raise HTTPException(status_code=400, detail="a document filename is required")

    content = await file.read(_max_document_bytes() + 1)
    if len(content) > _max_document_bytes():
        raise HTTPException(
            status_code=413,
            detail=f"document exceeds the {_max_document_bytes() // (1024 * 1024)} MB limit",
        )

    result = _service_call_any(
        ("process_document_upload", "upload_document"),
        workspace_id=auth.context.workspace_id,
        knowledge_base_id=knowledge_base_id,
        filename=filename,
        mime_type=file.content_type,
        content=content,
    )
    return DocumentResponse.model_validate(
        _document_record(result, auth.context.workspace_id, knowledge_base_id)
    )


@router.get(
    "/knowledge-bases/{knowledge_base_id}/documents",
    response_model=DocumentListResponse,
)
def list_documents(
    knowledge_base_id: str,
    auth: WorkspaceAuth,
) -> DocumentListResponse:
    """List documents for a Knowledge Base in the current workspace."""
    result = _service_call(
        "list_documents",
        workspace_id=auth.context.workspace_id,
        knowledge_base_id=knowledge_base_id,
    )
    return DocumentListResponse(
        items=[
            DocumentResponse.model_validate(
                _document_record(item, auth.context.workspace_id, knowledge_base_id)
            )
            for item in _items(result)
        ]
    )


@router.get("/documents/{document_id}", response_model=DocumentResponse)
def get_document(document_id: str, auth: WorkspaceAuth) -> DocumentResponse:
    """Return one document only when it belongs to the current workspace."""
    result = _service_call(
        "get_document",
        workspace_id=auth.context.workspace_id,
        document_id=document_id,
    )
    return DocumentResponse.model_validate(
        _document_record(result, auth.context.workspace_id)
    )


@router.delete("/documents/{document_id}")
def delete_document(
    request: Request,
    document_id: str,
    auth: WorkspaceAuth,
) -> dict[str, object]:
    """Delete a document's retrieval artifacts and S3 original via the core service."""
    require_csrf(request, auth)
    result = _service_call(
        "delete_document",
        workspace_id=auth.context.workspace_id,
        document_id=document_id,
    )
    return _deletion_response(result, document_id, "document")


def _knowledge_service() -> Any:
    """Load the planned core service without making API import order brittle."""
    try:
        return importlib.import_module("core.knowledge.service")
    except ModuleNotFoundError as error:
        if error.name in {"core.knowledge", "core.knowledge.service"}:
            raise HTTPException(
                status_code=503,
                detail="Knowledge Base service is not available",
            ) from error
        raise


def _service_call(function_name: str, **kwargs: object) -> object:
    """Call a core service function and turn domain errors into API errors."""
    service = _knowledge_service()
    function = getattr(service, function_name, None)
    if not callable(function):
        raise HTTPException(
            status_code=503,
            detail=f"Knowledge Base service does not implement {function_name}",
        )
    return _invoke_service_function(function, **kwargs)


def _service_call_any(function_names: tuple[str, ...], **kwargs: object) -> object:
    """Call the first available name while the core service API is settling."""
    service = _knowledge_service()
    for function_name in function_names:
        function = getattr(service, function_name, None)
        if callable(function):
            return _invoke_service_function(function, **kwargs)
    names = ", ".join(function_names)
    raise HTTPException(
        status_code=503,
        detail=f"Knowledge Base service does not implement any of: {names}",
    )


def _invoke_service_function(function: Any, **kwargs: object) -> object:
    """Invoke a service function and map expected domain failures to HTTP errors."""
    try:
        return function(**kwargs)
    except HTTPException:
        raise
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error) or "access denied") from error
    except (FileNotFoundError, LookupError) as error:
        raise HTTPException(status_code=404, detail=str(error) or "resource not found") from error
    except DocumentStorageError as error:
        raise HTTPException(
            status_code=502,
            detail=str(error) or "document storage is unavailable",
        ) from error
    except (DocumentValidationError, DocumentProcessingError) as error:
        raise HTTPException(
            status_code=400,
            detail=str(error) or "document processing failed",
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error) or "invalid document request",
        ) from error


def _max_document_bytes() -> int:
    raw = os.environ.get(MAX_DOCUMENT_BYTES_ENV) or os.environ.get(LEGACY_MAX_DOCUMENT_BYTES_ENV)
    if not raw:
        return DEFAULT_MAX_DOCUMENT_BYTES
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_DOCUMENT_BYTES
    return value if value > 0 else DEFAULT_MAX_DOCUMENT_BYTES


def _items(value: object) -> list[dict[str, object]]:
    if isinstance(value, Mapping):
        nested = next(
            (value.get(key) for key in ("items", "knowledge_bases", "documents") if key in value),
            None,
        )
        if isinstance(nested, list):
            value = nested
        else:
            return [_record(value)]
    if not isinstance(value, list | tuple):
        return []
    return [_record(item) for item in value]


def _record(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        if isinstance(dumped, dict):
            return {str(key): item for key, item in dumped.items()}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {str(key): item for key, item in dataclasses.asdict(value).items()}
    raise TypeError("Knowledge Base service returned an unsupported record")


def _with_workspace(value: object, workspace_id: str) -> dict[str, object]:
    record = _record(value)
    nested = record.get("knowledge_base")
    if isinstance(nested, Mapping):
        record = {str(key): item for key, item in nested.items()}
    record.setdefault("workspace_id", workspace_id)
    if "id" not in record and "knowledge_base_id" in record:
        record["id"] = record["knowledge_base_id"]
    return record


def _document_record(
    value: object,
    workspace_id: str,
    knowledge_base_id: str | None = None,
) -> dict[str, object]:
    record = _record(value)
    nested = record.get("document")
    if isinstance(nested, Mapping):
        record = {str(key): item for key, item in nested.items()}
    record.setdefault("workspace_id", workspace_id)
    if "id" not in record and "document_id" in record:
        record["id"] = record["document_id"]
    if knowledge_base_id is not None:
        record.setdefault("knowledge_base_id", knowledge_base_id)
    _copy_alias(record, "checksum", "checksum_sha256")
    _copy_alias(record, "error", "error_message")
    _copy_alias(record, "character_count", "extracted_char_count")
    return record


def _copy_alias(record: dict[str, object], public_name: str, stored_name: str) -> None:
    if public_name not in record and stored_name in record:
        record[public_name] = record[stored_name]


def _deletion_response(value: object, resource_id: str, resource_type: str) -> dict[str, object]:
    response = _record(value) if value is not None else {}
    response.setdefault("status", "deleted")
    response.setdefault(f"{resource_type}_id", resource_id)
    return response

