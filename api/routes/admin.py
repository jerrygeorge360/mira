"""Read-only platform administration routes."""

from __future__ import annotations

from fastapi import APIRouter

from api.auth import PlatformAdmin
from core.db.admin import get_admin_overview

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/overview")
def admin_overview(_admin: PlatformAdmin) -> dict[str, object]:
    """Return aggregate product and runtime counts without workspace content."""
    return get_admin_overview()
