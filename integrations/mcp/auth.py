"""Authentication and workspace binding for the standalone MIRA MCP service."""

from __future__ import annotations

import json
import os
import secrets
from datetime import datetime

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier

from api.oauth import resolve_oauth_access_token
from core.db.repositories import WorkspaceContext, repository_connection


class StaticTokenVerifier(TokenVerifier):
    """Validate configured MCP bearer tokens for the official SDK transport."""

    async def verify_token(self, token: str) -> AccessToken | None:
        oauth_token = resolve_oauth_access_token(token)
        if oauth_token is not None:
            expires_at = int(datetime.fromisoformat(str(oauth_token["expires_at"])).timestamp())
            return AccessToken(
                token=token,
                client_id=str(oauth_token["client_id"]),
                subject=str(oauth_token["user_id"]),
                scopes=str(oauth_token["scope"]).split(),
                expires_at=expires_at,
                resource=str(oauth_token["resource"]),
                claims={
                    "workspace_id": str(oauth_token["workspace_id"]),
                    "membership_role": str(oauth_token["role"]),
                },
            )
        try:
            workspace_id = _workspace_for_token(token)
            _require_active_workspace(workspace_id)
        except ValueError:
            return None
        return AccessToken(
            token=token,
            client_id=workspace_id,
            subject=workspace_id,
            scopes=["mira:memory"],
            claims={"workspace_id": workspace_id},
        )


def authenticated_workspace_context() -> WorkspaceContext:
    """Return the workspace bound to the current authenticated MCP request."""
    access_token = get_access_token()
    return workspace_context_for_access_token(access_token)


def workspace_context_for_access_token(access_token: AccessToken | None) -> WorkspaceContext:
    """Convert a verified MCP access token into a trusted repository context."""
    if access_token is None:
        raise PermissionError("authenticated MCP workspace is unavailable")
    claims = access_token.claims or {}
    workspace_id = claims.get("workspace_id")
    if not isinstance(workspace_id, str) or not workspace_id:
        raise PermissionError("authenticated MCP workspace is unavailable")
    membership_role = claims.get("membership_role")
    return WorkspaceContext(
        workspace_id,
        user_id=access_token.subject if membership_role else None,
        membership_role=str(membership_role) if membership_role else None,
        auth_mode="mcp",
    )


def _workspace_for_token(token: str) -> str:
    mapping = _token_workspace_mapping()
    for configured_token, workspace_id in mapping.items():
        if secrets.compare_digest(token, configured_token):
            return workspace_id
    raise ValueError("MCP token is invalid")


def _token_workspace_mapping() -> dict[str, str]:
    raw_mapping = os.environ.get("MIRA_MCP_TOKEN_WORKSPACES", "").strip()
    if raw_mapping:
        try:
            decoded = json.loads(raw_mapping)
        except json.JSONDecodeError as error:
            raise ValueError("MCP token mapping is invalid") from error
        if not isinstance(decoded, dict):
            raise ValueError("MCP token mapping must be a JSON object")
        mapping = {
            str(token): str(workspace_id)
            for token, workspace_id in decoded.items()
            if str(token).strip() and str(workspace_id).strip()
        }
        if mapping:
            return mapping

    single_token = os.environ.get("MIRA_MCP_API_KEY", "").strip()
    workspace_id = os.environ.get("MIRA_MCP_WORKSPACE_ID", "").strip()
    if single_token and workspace_id:
        return {single_token: workspace_id}
    raise ValueError("MCP authentication is not configured")


def _require_active_workspace(workspace_id: str) -> None:
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT status FROM workspaces WHERE id = ?",
            (workspace_id,),
        ).fetchone()
    if row is None or row["status"] != "active":
        raise ValueError("MCP workspace is unavailable")
