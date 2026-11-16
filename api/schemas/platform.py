"""Request models for dashboard platform and public developer APIs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PlatformModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OrganizationCreate(PlatformModel):
    name: str = Field(min_length=1, max_length=80)


class OrganizationUpdate(PlatformModel):
    name: str = Field(min_length=1, max_length=80)


class ProjectCreate(PlatformModel):
    organization_id: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=80)
    environment: Literal["development", "production"] = "production"


class APIKeyCreate(PlatformModel):
    project_id: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=80)
    scopes: list[str] = Field(min_length=1, max_length=7)
    expires_at: str | None = None


class PublicMemoryWrite(PlatformModel):
    namespace: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=200_000)
    metadata: dict[str, object] = Field(default_factory=dict)


class PublicMemorySearch(PlatformModel):
    namespace: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=20_000)
    mode: Literal["auto", "quick", "deep", "relational"] = "auto"
    limit: int = Field(default=10, ge=1, le=50)
    include_project_knowledge: bool = False


class BillingSubscribe(PlatformModel):
    organization_id: str = Field(min_length=1)
    plan: Literal["developer", "pro", "scale"]
    email: str = Field(min_length=3, max_length=254)


class BillingCancel(PlatformModel):
    organization_id: str = Field(min_length=1)
