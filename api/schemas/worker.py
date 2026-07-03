"""Worker status schemas for the MIRA API."""

from __future__ import annotations

from pydantic import BaseModel


class WorkerStatusResponse(BaseModel):
    """Queue and worker status payload."""

    queue: dict[str, int]
    worker: dict[str, object]
