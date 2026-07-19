"""Read-only platform administration routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.auth import PlatformAdmin
from core.db.admin import get_admin_overview
from core.db.repositories import set_runtime_setting
from core.llm.profiles import (
    LLM_PROFILE_SETTING,
    PROVIDER_PROFILES,
    active_profile,
    active_profile_name,
)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/overview")
def admin_overview(_admin: PlatformAdmin) -> dict[str, object]:
    """Return aggregate product and runtime counts without workspace content."""
    return get_admin_overview()


@router.get("/provider")
def admin_provider(_admin: PlatformAdmin) -> dict[str, object]:
    """Return the active LLM provider and available dashboard choices."""
    selected, source = active_profile_name()
    profile = active_profile()
    return {
        "active": selected,
        "source": source,
        "model": profile.chat_model if profile is not None else None,
        "providers": [
            {
                "name": provider.name,
                "model": provider.chat_model,
                "endpoint": provider.chat_endpoint,
                "has_cloud_embeddings": provider.embedding_endpoint is not None,
            }
            for provider in PROVIDER_PROFILES.values()
        ],
    }


@router.put("/provider")
def update_admin_provider(payload: dict[str, object], _admin: PlatformAdmin) -> dict[str, object]:
    """Switch the active LLM provider profile for the running deployment."""
    profile_name = str(payload.get("profile") or "").casefold().strip()
    if profile_name not in PROVIDER_PROFILES:
        raise HTTPException(status_code=400, detail="unknown provider profile")
    set_runtime_setting(LLM_PROFILE_SETTING, profile_name)
    return admin_provider(_admin)
