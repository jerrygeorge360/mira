"""Chat request/response schemas for the MIRA API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RetrievalMode = Literal["auto"]
RoutingStrategy = Literal["fast", "accurate"]


class ChatRequest(BaseModel):
    """Request body for one MIRA chat turn."""

    user_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    session_id: str | None = None
    retrieval_mode: RetrievalMode = "auto"
    routing_strategy: RoutingStrategy = "fast"


class ChatResponse(BaseModel):
    """Structured response returned by the MIRA agent runtime."""

    answer: str
    session_id: str
    user_observation_id: str | None = None
    assistant_observation_id: str | None = None
    retrieval_mode: str
    used_session_items: list[str]
    used_memory_items: list[str]
    trace_id: str | None = None
