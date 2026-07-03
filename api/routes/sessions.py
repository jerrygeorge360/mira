"""Session routes for the MIRA API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.dependencies import fetch_one
from api.schemas.sessions import (
    CreateSessionRequest,
    SessionResponse,
    SessionWorkingSetResponse,
)
from core.db.repositories import create_session
from core.session.working_set import list_active_session_items

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionResponse)
def create_session_route(request: CreateSessionRequest) -> SessionResponse:
    """Create a MIRA session."""
    session_id = create_session(request.user_id, request.title)
    session = _get_session_or_404(session_id)
    return _session_response(session)


@router.get("/{session_id}", response_model=SessionResponse)
def get_session_route(session_id: str) -> SessionResponse:
    """Return session metadata."""
    return _session_response(_get_session_or_404(session_id))


@router.get("/{session_id}/working-set", response_model=SessionWorkingSetResponse)
def get_working_set_route(session_id: str) -> SessionWorkingSetResponse:
    """Return active Session Working Set state grouped for UI clients."""
    _get_session_or_404(session_id)
    items = list_active_session_items(session_id)
    return SessionWorkingSetResponse(
        session_id=session_id,
        active_goals=_items_of_type(items, "current_goal"),
        corrections=_items_of_type(items, "correction"),
        constraints=_items_of_type(items, "active_constraint"),
        unresolved_questions=_items_of_type(items, "open_question"),
        provisional_decisions=[
            item
            for item in items
            if item.get("type") == "decision" and item.get("status") == "provisional"
        ],
        items=items,
    )


def _get_session_or_404(session_id: str) -> dict[str, object]:
    row = fetch_one("SELECT * FROM sessions WHERE id = ?", (session_id,))
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
