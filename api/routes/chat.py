"""Chat routes for the MIRA API."""

from __future__ import annotations

import json
import queue
import threading
from collections.abc import Iterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from api.auth import WorkspaceAuth, require_csrf
from api.schemas.chat import ChatRequest, ChatResponse
from core.agent import Agent, AgentTurnCancelled
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
        auth.context.user_id or "development",
        _session_title_from_message(payload.message),
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


@router.post("/chat/stream")
def chat_stream(
    request: Request,
    payload: ChatRequest,
    auth: WorkspaceAuth,
) -> StreamingResponse:
    """Run one MIRA turn and stream user-facing progress events as NDJSON."""
    require_csrf(request, auth)
    repository = bind_workspace(auth.context)
    session_id = payload.session_id or repository.create_session(
        auth.context.user_id or "development",
        _session_title_from_message(payload.message),
    )
    if repository.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="session_id not found")
    return StreamingResponse(
        _chat_event_stream(payload, session_id),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache"},
    )


def _chat_event_stream(payload: ChatRequest, session_id: str) -> Iterator[str]:
    events: queue.Queue[dict[str, object] | None] = queue.Queue()
    cancelled = threading.Event()

    def emit(event: dict[str, object]) -> None:
        events.put(event)

    def run_turn() -> None:
        try:
            result = Agent(session_id).respond(
                payload.message,
                routing_strategy=payload.routing_strategy,
                progress_callback=emit,
                should_cancel=cancelled.is_set,
            )
        except AgentTurnCancelled:
            events.put({"type": "cancelled", "message": "Response stopped before completion."})
        except ValueError as error:
            events.put({"type": "error", "message": str(error)})
        except Exception as error:  # noqa: BLE001 - API boundary logs and sanitizes runtime errors
            log_event(
                "api_chat_stream_error",
                "streaming chat turn failed",
                level=40,
                exc_info=error,
                session_id=session_id,
                error_type=type(error).__name__,
            )
            events.put({"type": "error", "message": "chat runtime failed; check API logs"})
        else:
            events.put({"type": "answer", "delta": str(result.get("answer") or "")})
            events.put(
                {
                    "type": "trace",
                    "session_id": str(result.get("session_id") or session_id),
                    "user_observation_id": result.get("user_observation_id"),
                    "assistant_observation_id": result.get("assistant_observation_id"),
                    "retrieval_mode": str(result.get("retrieval_mode") or "auto"),
                    "used_session_items": _string_list(result.get("used_session_items")),
                    "used_memory_items": _string_list(result.get("used_memory_items")),
                    "trace_id": result.get("trace_id"),
                }
            )
            events.put(
                {
                    "type": "complete",
                    "session_id": str(result.get("session_id") or session_id),
                }
            )
        finally:
            events.put(None)

    worker = threading.Thread(target=run_turn, name=f"chat-stream-{session_id}", daemon=True)
    worker.start()
    try:
        while True:
            try:
                event = events.get(timeout=0.5)
            except queue.Empty:
                continue
            if event is None:
                break
            yield f"{json.dumps(event, sort_keys=True)}\n"
    finally:
        cancelled.set()


def _object_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _session_title_from_message(message: str) -> str:
    title = " ".join(message.split())
    if not title:
        return "New chat"
    max_length = 56
    if len(title) <= max_length:
        return title
    return f"{title[:max_length].rstrip()}..."
