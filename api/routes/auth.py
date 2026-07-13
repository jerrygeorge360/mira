"""GitHub OAuth and server-session routes."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse

from api.auth import (
    WorkspaceAuth,
    allowed_app_redirect,
    consume_oauth_state,
    create_oauth_state,
    exchange_github_code,
    issue_auth_session,
    provision_github_identity,
    require_csrf,
    revoke_auth_session,
    revoke_request_session,
    validate_request_origin,
)
from core.demo import issue_demo_workspace

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/github/start")
def github_start(redirect: str | None = None) -> RedirectResponse:
    target = allowed_app_redirect(redirect)
    client_id = os.environ.get("GITHUB_CLIENT_ID", "").strip()
    callback = os.environ.get("GITHUB_CALLBACK_URL", "").strip()
    if not client_id or not callback:
        raise HTTPException(status_code=503, detail="GitHub authentication is not configured")
    state = create_oauth_state(target)
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": callback,
            "state": state,
            "scope": "read:user",
        }
    )
    return RedirectResponse(f"https://github.com/login/oauth/authorize?{query}")


@router.get("/github/callback")
def github_callback(
    request: Request,
    code: str = Query(min_length=1),
    state: str = Query(min_length=1),
) -> Response:
    redirect = consume_oauth_state(state)
    profile = exchange_github_code(code)
    user_id, workspace_id = provision_github_identity(profile)
    response = RedirectResponse(f"{redirect}/?auth=success")
    revoke_request_session(request)
    issue_auth_session(response, user_id, workspace_id)
    return response


@router.get("/me")
def auth_me(
    auth: WorkspaceAuth,
) -> dict[str, object]:
    return {
        "user": {
            "id": auth.context.user_id,
            "github_login": auth.github_login,
            "display_name": auth.display_name,
            "avatar_url": auth.avatar_url,
        },
        "workspace": {
            "id": auth.context.workspace_id,
            "name": auth.workspace_name,
        },
        "auth_mode": auth.context.auth_mode,
        "expires_at": auth.expires_at,
        "ready": True,
    }


@router.post("/demo", status_code=201)
def demo(request: Request, response: Response) -> dict[str, object]:
    validate_request_origin(request)
    requester = request.client.host if request.client else "unknown"
    try:
        user_id, workspace_id, expires_at = issue_demo_workspace(requester)
    except ValueError as error:
        raise HTTPException(status_code=429, detail=str(error)) from error
    revoke_request_session(request)
    ttl = expires_at - datetime.now(timezone.utc)  # noqa: UP017
    issue_auth_session(response, user_id, workspace_id, ttl=ttl)
    return {"status": "ready", "workspace_id": workspace_id, "expires_at": expires_at.isoformat()}


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    auth: WorkspaceAuth,
) -> Response:
    require_csrf(request, auth)
    revoke_auth_session(response, auth)
    response.status_code = 204
    return response
