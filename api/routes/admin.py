"""Read-only platform administration routes."""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Query

from api.auth import PlatformAdmin
from core.db.admin import get_admin_overview, get_llm_usage_overview
from core.db.repositories import set_runtime_setting
from core.llm.profiles import (
    LLM_GATEWAY_SETTING,
    LLM_PROFILE_SETTING,
    PROVIDER_PROFILES,
    active_gateway_name,
    active_profile,
    active_profile_name,
)
from core.llm.qwen import PARITOK_UPSTREAM_PROFILE_ENV

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/overview")
def admin_overview(_admin: PlatformAdmin) -> dict[str, object]:
    """Return aggregate product and runtime counts without workspace content."""
    return get_admin_overview()


@router.get("/llm-usage")
def admin_llm_usage(
    _admin: PlatformAdmin,
    days: int = Query(default=7, ge=1, le=365),
    limit: int = Query(default=30, ge=1, le=200),
) -> dict[str, object]:
    """Return provider-reported token usage and recent call metadata."""
    return get_llm_usage_overview(days=days, limit=limit)


@router.get("/provider")
def admin_provider(_admin: PlatformAdmin) -> dict[str, object]:
    """Return the active LLM provider and available dashboard choices."""
    selected, source = active_profile_name()
    profile = active_profile()
    gateway, gateway_source = active_gateway_name()
    paritok_upstream_profile = os.environ.get(PARITOK_UPSTREAM_PROFILE_ENV, "").casefold().strip()
    paritok_compatible = not paritok_upstream_profile or selected == paritok_upstream_profile
    return {
        "active": selected,
        "source": source,
        "model": profile.chat_model if profile is not None else None,
        "gateway": gateway,
        "gateway_source": gateway_source,
        "gateways": ["direct", "paritok"],
        "paritok_upstream_profile": paritok_upstream_profile or None,
        "paritok_compatible": paritok_compatible,
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
    gateway, _gateway_source = active_gateway_name()
    upstream_profile = os.environ.get(PARITOK_UPSTREAM_PROFILE_ENV, "").casefold().strip()
    if gateway == "paritok" and upstream_profile and profile_name != upstream_profile:
        # Keep provider changes usable when the running proxy targets another upstream.
        set_runtime_setting(LLM_GATEWAY_SETTING, "direct")
    return admin_provider(_admin)


@router.put("/gateway")
def update_admin_gateway(payload: dict[str, object], _admin: PlatformAdmin) -> dict[str, object]:
    """Switch between direct provider calls and the optional Paritok proxy."""
    gateway = str(payload.get("gateway") or "").casefold().strip()
    if gateway not in {"direct", "paritok"}:
        raise HTTPException(status_code=400, detail="unknown LLM gateway")
    selected, _source = active_profile_name()
    upstream_profile = os.environ.get(PARITOK_UPSTREAM_PROFILE_ENV, "").casefold().strip()
    if gateway == "paritok" and upstream_profile and selected != upstream_profile:
        raise HTTPException(
            status_code=409,
            detail=(
                "Paritok is configured for a different provider; update its upstream profile "
                "and restart the proxy first"
            ),
        )
    set_runtime_setting(LLM_GATEWAY_SETTING, gateway)
    return admin_provider(_admin)
