"""Chat routes for the MIRA API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.schemas.chat import ChatRequest, ChatResponse
from core.agent import Agent
from core.db.repositories import create_session

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    """Run one real MIRA agent turn."""
    session_id = request.session_id or create_session(request.user_id, "API chat")
    try:
        result = Agent(session_id).respond(
            request.message,
            routing_strategy=request.routing_strategy,
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:  # noqa: BLE001 - API must not leak raw tracebacks
        raise HTTPException(status_code=500, detail=str(error) or "agent runtime failed") from error

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
