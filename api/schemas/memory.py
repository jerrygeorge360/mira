"""Memory read-model schemas for the MIRA API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class MemoryGraphResponse(BaseModel):
    """Typed graph shape consumed by graph visualizations."""

    nodes: list[dict[str, object]]
    edges: list[dict[str, object]]


class ItemsResponse(BaseModel):
    """Generic list response for memory surfaces."""

    items: list[dict[str, object]]


class MemoryLifecycleResponse(BaseModel):
    """Recent observation lifecycle rows for the memory pipeline view."""

    items: list[dict[str, object]]


class MemoryHealthResponse(BaseModel):
    """Tier, retention, and status summary for the memory health view."""

    health: dict[str, object]


class MemorySleepRequest(BaseModel):
    """Bounded sleep-cycle controls."""

    max_items: int = Field(default=100, ge=1, le=1000)


class MemorySleepConfigRequest(BaseModel):
    """Partial workspace-scoped scheduler settings update."""

    enabled: bool | None = None
    interval_hours: float | None = Field(default=None, ge=1, le=168)


class MemorySleepConfigResponse(BaseModel):
    """Durable workspace sleep scheduler settings."""

    config: dict[str, object]


class MemorySleepRunsResponse(BaseModel):
    """Paginated workspace sleep history."""

    items: list[dict[str, object]]
    total: int
    limit: int
    offset: int


class MemorySleepRunResponse(BaseModel):
    """One workspace sleep run with snapshots and compact changes."""

    run: dict[str, object]


class MemorySleepResponse(BaseModel):
    """Summary of one durable sleep cycle."""

    sleep: dict[str, object]


class MemoryForgetRequest(BaseModel):
    """Reason recorded with a user-requested memory forgetting operation."""

    reason: str = Field(default="user requested forgetting", min_length=1, max_length=500)


class MemoryForgetResponse(BaseModel):
    """Lifecycle state after a public forgetting operation."""

    memory: dict[str, object]


class ForesightConfirmRequest(BaseModel):
    """Explicitly accept a document-derived foresight proposal."""

    confirmed: bool
