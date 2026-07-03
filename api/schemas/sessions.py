"""Session schemas for the MIRA API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    """Request body for session creation."""

    user_id: str = Field(min_length=1)
    title: str | None = None


class SessionResponse(BaseModel):
    """Session metadata returned over HTTP."""

    session_id: str
    user_id: str
    title: str | None = None
    status: str
    created_at: str
    updated_at: str | None = None
    ended_at: str | None = None


class SessionWorkingSetResponse(BaseModel):
    """Grouped prompt-relevant Session Working Set state."""

    session_id: str
    active_goals: list[dict[str, object]]
    corrections: list[dict[str, object]]
    constraints: list[dict[str, object]]
    unresolved_questions: list[dict[str, object]]
    provisional_decisions: list[dict[str, object]]
    items: list[dict[str, object]]
