"""Session schemas for the MIRA API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CreateSessionRequest(BaseModel):
    """Request body for session creation."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = None


class UpdateSessionRequest(BaseModel):
    """User-managed conversation metadata."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=120)
    is_starred: bool | None = None

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        title = value.strip()
        if not title:
            raise ValueError("title must not be blank")
        return title

    @model_validator(mode="after")
    def require_update(self) -> UpdateSessionRequest:
        if self.title is None and self.is_starred is None:
            raise ValueError("at least one session field must be provided")
        return self


class SessionResponse(BaseModel):
    """Session metadata returned over HTTP."""

    session_id: str
    user_id: str
    title: str | None = None
    is_starred: bool = False
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


class SessionSummary(BaseModel):
    """Compact session entry for the conversation-history sidebar."""

    session_id: str
    title: str | None = None
    is_starred: bool = False
    user_id: str
    status: str
    created_at: str
    updated_at: str | None = None
    message_count: int


class SessionListResponse(BaseModel):
    """A list of sessions, most recently updated first."""

    sessions: list[SessionSummary]


class ChatMessage(BaseModel):
    """One turn of a conversation."""

    role: str
    content: str
    created_at: str
    retrieval_mode: str | None = None
    context_scope: str | None = None
    trace_id: str | None = None


class SessionMessagesResponse(BaseModel):
    """The turns of a session in creation order."""

    session_id: str
    messages: list[ChatMessage]
