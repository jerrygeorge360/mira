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

    max_items: int = 100


class MemorySleepResponse(BaseModel):
    """Summary of one durable sleep cycle."""

    sleep: dict[str, object]


class MemoryForgetRequest(BaseModel):
    """Reason recorded with a user-requested memory forgetting operation."""

    reason: str = Field(default="user requested forgetting", min_length=1, max_length=500)


class MemoryForgetResponse(BaseModel):
    """Lifecycle state after a public forgetting operation."""

    memory: dict[str, object]
