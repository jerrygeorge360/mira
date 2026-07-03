"""Memory read-model schemas for the MIRA API."""

from __future__ import annotations

from pydantic import BaseModel


class MemoryGraphResponse(BaseModel):
    """Typed graph shape consumed by graph visualizations."""

    nodes: list[dict[str, object]]
    edges: list[dict[str, object]]


class ItemsResponse(BaseModel):
    """Generic list response for memory surfaces."""

    items: list[dict[str, object]]
