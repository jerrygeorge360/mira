"""Knowledge Base and document schemas for the MIRA API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DocumentStatus = Literal["uploaded", "processing", "ready", "failed", "deleted"]


class CreateKnowledgeBaseRequest(BaseModel):
    """Payload used to create a workspace-scoped Knowledge Base."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2_000)


class DocumentResponse(BaseModel):
    """Public metadata for one uploaded document."""

    model_config = ConfigDict(extra="ignore")

    id: str
    workspace_id: str
    knowledge_base_id: str
    filename: str
    mime_type: str | None = None
    size_bytes: int
    checksum: str | None = None
    status: DocumentStatus
    error: str | None = None
    page_count: int | None = None
    character_count: int | None = None
    chunk_count: int | None = None
    created_at: str
    processed_at: str | None = None
    updated_at: str | None = None


class KnowledgeBaseResponse(BaseModel):
    """Summary metadata for one Knowledge Base."""

    model_config = ConfigDict(extra="ignore")

    id: str
    workspace_id: str
    name: str
    description: str | None = None
    document_count: int = 0
    created_at: str
    updated_at: str | None = None


class KnowledgeBaseListResponse(BaseModel):
    """Workspace Knowledge Bases."""

    items: list[KnowledgeBaseResponse]


class KnowledgeBaseDetailResponse(KnowledgeBaseResponse):
    """A Knowledge Base and its current document inventory."""

    documents: list[DocumentResponse] = Field(default_factory=list)


class DocumentListResponse(BaseModel):
    """Documents belonging to one Knowledge Base."""

    items: list[DocumentResponse]
