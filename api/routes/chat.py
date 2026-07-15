"""Chat routes for the MIRA API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from api.auth import WorkspaceAuth, require_csrf
from api.schemas.chat import ChatRequest, ChatResponse
from core.agent import Agent
from core.db.repositories import bind_workspace
from core.observability import log_event

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(
    request: Request,
    payload: ChatRequest,
    auth: WorkspaceAuth,
) -> ChatResponse:
    """Run one real MIRA agent turn."""
    require_csrf(request, auth)
    repository = bind_workspace(auth.context)
    session_id = payload.session_id or repository.create_session(
        auth.context.user_id or "development", "API chat"
    )
    if repository.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="session_id not found")
    try:
        result = Agent(session_id).respond(
            payload.message,
            routing_strategy=payload.routing_strategy,
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:  # noqa: BLE001 - API boundary logs and sanitizes runtime errors
        log_event(
            "api_chat_error",
            "chat turn failed",
            level=40,
            exc_info=error,
            session_id=session_id,
            error_type=type(error).__name__,
        )
        raise HTTPException(
            status_code=500,
            detail="chat runtime failed; check API logs for details",
        ) from error

    return ChatResponse(
        answer=str(result.get("answer") or ""),
        session_id=str(result.get("session_id") or session_id),
        user_observation_id=(
            str(result["user_observation_id"]) if result.get("user_observation_id") else None
        ),
        assistant_observation_id=(
            str(result["assistant_observation_id"])
            if result.get("assistant_observation_id")
            else None
        ),
        retrieval_mode=str(result.get("retrieval_mode") or "auto"),
        used_session_items=[
            str(item_id) for item_id in _object_list(result.get("used_session_items"))
        ],
        used_memory_items=[
            str(item_id) for item_id in _object_list(result.get("used_memory_items"))
        ],
        trace_id=str(result["trace_id"]) if result.get("trace_id") else None,
    )


def _object_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []
