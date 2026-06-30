"""Worker status routes for the MIRA API."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from api.schemas.worker import WorkerStatusResponse
from core.memory.slow_path import get_slow_path_queue_status

router = APIRouter(prefix="/worker", tags=["worker"])


@router.get("/status", response_model=WorkerStatusResponse)
def get_worker_status() -> WorkerStatusResponse:
    """Return slow-path queue counts and basic runtime metadata."""
    queue = get_slow_path_queue_status()
    return WorkerStatusResponse(
        queue=queue,
        worker={
            "status": "unknown",
            "last_batch_at": None,
            "last_error": None,
            "reported_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017
        },
    )
