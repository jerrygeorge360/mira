"""Health routes for the MIRA API."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Return basic API process health."""
    return {"status": "ok", "service": "mira-api"}
