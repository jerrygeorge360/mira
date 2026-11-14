"""Focused API-boundary tests for Knowledge Base routes."""

from __future__ import annotations

import asyncio
import io
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers
from starlette.requests import Request

from api.auth import AuthenticatedWorkspace
from api.routes import knowledge_bases
from api.schemas.knowledge_bases import CreateKnowledgeBaseRequest
from core.db.repositories import WorkspaceContext


def _auth(workspace_id: str = "workspace-a") -> AuthenticatedWorkspace:
    return AuthenticatedWorkspace(WorkspaceContext(workspace_id, auth_mode="development"))


def _request(method: str = "POST") -> Request:
    return Request({"type": "http", "method": method, "path": "/knowledge-bases", "headers": []})


def _fake_service(monkeypatch: pytest.MonkeyPatch, service: Any) -> None:
    monkeypatch.setattr(knowledge_bases, "_knowledge_service", lambda: service)


def _document(document_id: str = "doc-1", kb_id: str = "kb-1") -> dict[str, object]:
    return {
        "id": document_id,
        "workspace_id": "workspace-a",
        "knowledge_base_id": kb_id,
        "filename": "notes.md",
        "mime_type": "text/markdown",
        "size_bytes": 12,
        "checksum": "abc123",
        "status": "ready",
        "error": None,
        "page_count": 1,
        "character_count": 12,
        "chunk_count": 1,
        "created_at": "2026-01-01T00:00:00+00:00",
        "processed_at": "2026-01-01T00:00:01+00:00",
        "updated_at": "2026-01-01T00:00:01+00:00",
    }


def _knowledge_base(kb_id: str = "kb-1") -> dict[str, object]:
    return {
        "id": kb_id,
        "workspace_id": "workspace-a",
        "name": "Engineering",
        "description": "Project docs",
        "document_count": 1,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }


def test_create_list_detail_and_delete_pass_workspace_to_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def create_knowledge_base(**kwargs: object) -> dict[str, object]:
        calls.append(("create", kwargs))
        return _knowledge_base()

    def list_knowledge_bases(**kwargs: object) -> list[dict[str, object]]:
        calls.append(("list", kwargs))
        return [_knowledge_base()]

    def get_knowledge_base(**kwargs: object) -> dict[str, object]:
        calls.append(("get", kwargs))
        return _knowledge_base()

    def list_documents(**kwargs: object) -> list[dict[str, object]]:
        calls.append(("documents", kwargs))
        return [_document()]

    def delete_knowledge_base(**kwargs: object) -> dict[str, object]:
        calls.append(("delete", kwargs))
        return {"deleted_documents": 1}

    service = SimpleNamespace(
        create_knowledge_base=create_knowledge_base,
        list_knowledge_bases=list_knowledge_bases,
        get_knowledge_base=get_knowledge_base,
        list_documents=list_documents,
        delete_knowledge_base=delete_knowledge_base,
    )
    _fake_service(monkeypatch, service)
    auth = _auth()

    created = knowledge_bases.create_knowledge_base(
        _request(), CreateKnowledgeBaseRequest(name="Engineering", description="Project docs"), auth
    )
    listed = knowledge_bases.list_knowledge_bases(auth)
    detail = knowledge_bases.get_knowledge_base("kb-1", auth)
    deleted = knowledge_bases.delete_knowledge_base(_request("DELETE"), "kb-1", auth)

    assert created.id == "kb-1"
    assert listed.items[0].workspace_id == "workspace-a"
    assert detail.documents[0].id == "doc-1"
    assert deleted["status"] == "deleted"
    assert all(call[1]["workspace_id"] == "workspace-a" for call in calls)
    assert calls[-1][1]["knowledge_base_id"] == "kb-1"


def test_upload_is_api_mediated_and_returns_processing_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: dict[str, object] = {}

    def process_document_upload(**kwargs: object) -> dict[str, object]:
        received.update(kwargs)
        return _document()

    _fake_service(monkeypatch, SimpleNamespace(process_document_upload=process_document_upload))
    upload = UploadFile(
        file=io.BytesIO(b"# Notes\n\nA document."),
        filename="notes.md",
        headers=Headers({"content-type": "text/markdown"}),
    )

    response = asyncio.run(
        knowledge_bases.upload_document(_request(), "kb-1", _auth(), upload)
    )

    assert response.status == "ready"
    assert received == {
        "workspace_id": "workspace-a",
        "knowledge_base_id": "kb-1",
        "filename": "notes.md",
        "mime_type": "text/markdown",
        "content": b"# Notes\n\nA document.",
    }


def test_upload_rejects_oversized_payload_before_service_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def process_document_upload(**_: object) -> None:
        nonlocal called
        called = True

    _fake_service(monkeypatch, SimpleNamespace(process_document_upload=process_document_upload))
    monkeypatch.setenv("MIRA_KNOWLEDGE_MAX_DOCUMENT_BYTES", "4")
    upload = UploadFile(file=io.BytesIO(b"12345"), filename="notes.txt")

    with pytest.raises(HTTPException) as error:
        asyncio.run(knowledge_bases.upload_document(_request(), "kb-1", _auth(), upload))

    assert error.value.status_code == 413
    assert "limit" in str(error.value.detail)
    assert called is False


def test_cross_workspace_service_error_is_returned_as_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def get_document(**kwargs: object) -> None:
        assert kwargs["workspace_id"] == "workspace-b"
        raise LookupError("document not found")

    _fake_service(monkeypatch, SimpleNamespace(get_document=get_document))

    with pytest.raises(HTTPException) as error:
        knowledge_bases.get_document("doc-from-another-workspace", _auth("workspace-b"))

    assert error.value.status_code == 404
    assert error.value.detail == "document not found"

