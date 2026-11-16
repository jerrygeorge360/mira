"""Session routes for the MIRA API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from api.auth import WorkspaceAuth, require_csrf
from api.dependencies import fetch_one
from api.schemas.sessions import (
    ChatMessage,
    CreateSessionRequest,
    SessionKnowledgeBase,
    SessionKnowledgeBasesResponse,
    SessionListResponse,
    SessionMessagesResponse,
    SessionResponse,
    SessionSummary,
    SessionWorkingSetResponse,
    UpdateSessionKnowledgeBasesRequest,
)
from core.db.repositories import (
    bind_workspace,
    list_knowledge_bases,
    list_observations,
    list_session_knowledge_base_ids,
    message_counts_by_session,
    replace_session_knowledge_base_ids,
)
from core.retrieval.router import source_aware_retrieval_enabled_for_workspace
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
    messages = [
        ChatMessage(
            role=str(row["role"]),
            content=str(row["content"]),
            created_at=str(row["created_at"]),
        )
        for row in list_observations(session_id, limit)
        if str(row.get("role")) in _MESSAGE_ROLES
    ]
    return SessionMessagesResponse(session_id=session_id, messages=messages)


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


@router.get("/{session_id}", response_model=SessionResponse)
def get_session_route(
    session_id: str,
    auth: WorkspaceAuth,
) -> SessionResponse:
    """Return session metadata."""
    return _session_response(_get_session_or_404(session_id, auth.context.workspace_id))


@router.get("/{session_id}/knowledge-bases", response_model=SessionKnowledgeBasesResponse)
def get_session_knowledge_bases_route(
    session_id: str,
    auth: WorkspaceAuth,
) -> SessionKnowledgeBasesResponse:
    """List workspace KBs and the allowlist currently attached to this session."""
    workspace_id = auth.context.workspace_id
    _get_session_or_404(session_id, workspace_id)
    attached = set(list_session_knowledge_base_ids(session_id, workspace_id=workspace_id))
    knowledge_bases = [
        SessionKnowledgeBase(
            id=str(row["id"]),
            name=str(row["name"]),
            description=str(row["description"]) if row.get("description") is not None else None,
            attached=str(row["id"]) in attached,
        )
        for row in list_knowledge_bases(workspace_id=workspace_id)
    ]
    return SessionKnowledgeBasesResponse(
        session_id=session_id,
        knowledge_bases=knowledge_bases,
        retrieval_enabled=source_aware_retrieval_enabled_for_workspace(workspace_id=workspace_id),
    )


@router.put("/{session_id}/knowledge-bases", response_model=SessionKnowledgeBasesResponse)
def update_session_knowledge_bases_route(
    request: Request,
    session_id: str,
    payload: UpdateSessionKnowledgeBasesRequest,
    auth: WorkspaceAuth,
) -> SessionKnowledgeBasesResponse:
    """Replace a session's KB allowlist; unselected libraries stay private to the shelf."""
    require_csrf(request, auth)
    workspace_id = auth.context.workspace_id
    _get_session_or_404(session_id, workspace_id)
    try:
        replace_session_knowledge_base_ids(
            session_id, payload.knowledge_base_ids, workspace_id=workspace_id
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return get_session_knowledge_bases_route(session_id, auth)


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
        status=str(row["status"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]) if row.get("updated_at") is not None else None,
        ended_at=str(row["ended_at"]) if row.get("ended_at") is not None else None,
    )


def _items_of_type(items: list[dict[str, object]], item_type: str) -> list[dict[str, object]]:
    return [item for item in items if item.get("type") == item_type]
