"""Workspace self-service routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

from api.auth import WorkspaceAuth, require_csrf
from core.workspace_data import delete_workspace_data

router = APIRouter(prefix="/workspace", tags=["workspace"])


@router.delete("/data")
def delete_current_workspace_data(request: Request, auth: WorkspaceAuth) -> dict[str, object]:
    """Delete all product data for the authenticated workspace."""
    require_csrf(request, auth)
    deleted = delete_workspace_data(auth.context.workspace_id)
    return {"status": "deleted", "workspace_id": auth.context.workspace_id, "deleted": deleted}
