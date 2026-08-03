"""Session routes for the MIRA API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from api.auth import WorkspaceAuth, require_csrf
from api.dependencies import fetch_all, fetch_one
from api.schemas.sessions import (
    ChatMessage,
    CreateSessionRequest,
    SessionListResponse,
    SessionMessagesResponse,
    SessionResponse,
    SessionSummary,
    SessionWorkingSetResponse,
    UpdateSessionRequest,
)
from core.db.repositories import bind_workspace, list_observations, message_counts_by_session
from core.session.read_models import active_session_items, list_session_working_set_read_model
from core.session_deletion import delete_session_data

router = APIRouter(prefix="/sessions", tags=["sessions"])

_MESSAGE_ROLES = frozenset({"user", "assistant"})


@router.post("", response_model=SessionResponse)
def create_session_route(
    request: Request,
    payload: CreateSessionRequest,
    auth: WorkspaceAuth,
) -> SessionResponse:
    """Create a MIRA session."""
    require_csrf(request, auth)
    repository = bind_workspace(auth.context)
    session_id = repository.create_session(auth.context.user_id or "development", payload.title)
    session = _get_session_or_404(session_id, auth.context.workspace_id)
    return _session_response(session)


@router.get("", response_model=SessionListResponse)
def list_sessions_route(
    auth: WorkspaceAuth,
    limit: int = 50,
) -> SessionListResponse:
    """List sessions (most recently updated first) for the conversation-history sidebar."""
    counts = message_counts_by_session(workspace_id=auth.context.workspace_id)
    sessions = [
        SessionSummary(
            session_id=str(row["id"]),
            title=str(row["title"]) if row.get("title") is not None else None,
            is_starred=bool(row.get("is_starred", False)),
            user_id=str(row["user_id"]),
            status=str(row["status"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]) if row.get("updated_at") is not None else None,
            message_count=counts.get(str(row["id"]), 0),
        )
        for row in bind_workspace(auth.context).list_sessions(limit=limit)
    ]
    return SessionListResponse(sessions=sessions)


@router.get("/{session_id}/messages", response_model=SessionMessagesResponse)
def get_session_messages_route(
    session_id: str,
    auth: WorkspaceAuth,
    limit: int = 200,
) -> SessionMessagesResponse:
    """Return a session's user/assistant turns in order, to reopen a conversation."""
    _get_session_or_404(session_id, auth.context.workspace_id)
    traces = _message_trace_metadata(session_id, auth.context.workspace_id)
    messages = [
        ChatMessage(
            role=str(row["role"]),
            content=str(row["content"]),
            created_at=str(row["created_at"]),
            retrieval_mode=traces.get(str(row["id"]), {}).get("retrieval_mode"),
            context_scope=traces.get(str(row["id"]), {}).get("context_scope"),
            trace_id=traces.get(str(row["id"]), {}).get("trace_id"),
        )
        for row in list_observations(session_id, limit)
        if str(row.get("role")) in _MESSAGE_ROLES
    ]
    return SessionMessagesResponse(session_id=session_id, messages=messages)


def _message_trace_metadata(
    session_id: str,
    workspace_id: str,
) -> dict[str, dict[str, str | None]]:
    rows = fetch_all(
        """
        SELECT
            answer_traces.id AS trace_id,
            answer_traces.assistant_observation_id,
            answer_traces.retrieval_mode,
            retrieval_logs.sufficiency_json
        FROM answer_traces
        LEFT JOIN retrieval_logs ON retrieval_logs.id = answer_traces.retrieval_log_id
        WHERE answer_traces.session_id = ? AND answer_traces.workspace_id = ?
        """,
        (session_id, workspace_id),
    )
    metadata: dict[str, dict[str, str | None]] = {}
    for row in rows:
        observation_id = row.get("assistant_observation_id")
        if observation_id is None:
            continue
        metadata[str(observation_id)] = {
            "trace_id": str(row["trace_id"]),
            "retrieval_mode": (
                str(row["retrieval_mode"]) if row.get("retrieval_mode") is not None else None
            ),
            "context_scope": _trace_context_scope(row.get("sufficiency_json")),
        }
    return metadata


def _trace_context_scope(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    decision = value.get("routing_decision")
    if not isinstance(decision, dict):
        return None
    scope = decision.get("context_scope")
    return str(scope) if scope is not None else None


@router.delete("/{session_id}")
def delete_session_route(
    request: Request,
    session_id: str,
    auth: WorkspaceAuth,
) -> dict[str, object]:
    """Delete one chat session and deactivate memory derived only from it."""
    require_csrf(request, auth)
    try:
        deleted = delete_session_data(session_id, workspace_id=auth.context.workspace_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"status": "deleted", "session_id": session_id, "deleted": deleted}


@router.patch("/{session_id}", response_model=SessionResponse)
def update_session_route(
    request: Request,
    session_id: str,
    payload: UpdateSessionRequest,
    auth: WorkspaceAuth,
) -> SessionResponse:
    """Rename or star a conversation in the authenticated workspace."""
    require_csrf(request, auth)
    try:
        session = bind_workspace(auth.context).update_session(
            session_id,
            title=payload.title,
            is_starred=payload.is_starred,
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail="session_id not found") from error
    return _session_response(session)


@router.get("/{session_id}", response_model=SessionResponse)
def get_session_route(
    session_id: str,
    auth: WorkspaceAuth,
) -> SessionResponse:
    """Return session metadata."""
    return _session_response(_get_session_or_404(session_id, auth.context.workspace_id))


@router.get("/{session_id}/working-set", response_model=SessionWorkingSetResponse)
def get_working_set_route(
    session_id: str,
    auth: WorkspaceAuth,
) -> SessionWorkingSetResponse:
    """Return active Session Working Set state grouped for UI clients."""
    _get_session_or_404(session_id, auth.context.workspace_id)
    items = list_session_working_set_read_model(session_id, workspace_id=auth.context.workspace_id)
    active_items = active_session_items(items)
    return SessionWorkingSetResponse(
        session_id=session_id,
        active_goals=_items_of_type(active_items, "current_goal"),
        corrections=_items_of_type(active_items, "correction"),
        constraints=_items_of_type(active_items, "active_constraint"),
        unresolved_questions=_items_of_type(active_items, "open_question"),
        provisional_decisions=[
            item
            for item in active_items
            if item.get("type") == "decision" and item.get("status") == "provisional"
        ],
        items=items,
    )


def _get_session_or_404(session_id: str, workspace_id: str) -> dict[str, object]:
    row = fetch_one(
        "SELECT * FROM sessions WHERE id = ? AND workspace_id = ? AND status != 'deleted'",
        (session_id, workspace_id),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="session_id not found")
    return row


def _session_response(row: dict[str, object]) -> SessionResponse:
    return SessionResponse(
        session_id=str(row["id"]),
        user_id=str(row["user_id"]),
        title=str(row["title"]) if row.get("title") is not None else None,
        is_starred=bool(row.get("is_starred", False)),
        status=str(row["status"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]) if row.get("updated_at") is not None else None,
        ended_at=str(row["ended_at"]) if row.get("ended_at") is not None else None,
    )


def _items_of_type(items: list[dict[str, object]], item_type: str) -> list[dict[str, object]]:
    return [item for item in items if item.get("type") == item_type]
