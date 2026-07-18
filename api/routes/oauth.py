"""OAuth 2.1 discovery, consent, token, and client-registration routes."""

from __future__ import annotations

import html
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from api.auth import (
    CSRF_COOKIE,
    WorkspaceAuth,
    require_authenticated_workspace,
    validate_csrf_value,
)
from api.oauth import (
    MCP_SCOPE,
    OAuthProtocolError,
    authorization_server_metadata,
    begin_authorization,
    decide_authorization,
    exchange_authorization_code,
    exchange_refresh_token,
    oauth_issuer_url,
    register_dynamic_client,
    revoke_oauth_token,
)

router = APIRouter(tags=["oauth"])


class OAuthClientRegistration(BaseModel):
    """Supported RFC 7591 public-client registration fields."""

    model_config = ConfigDict(extra="allow")

    client_name: str = Field(min_length=1, max_length=160)
    redirect_uris: list[str] = Field(min_length=1, max_length=10)
    token_endpoint_auth_method: str = "none"
    grant_types: list[str] = Field(default_factory=lambda: ["authorization_code", "refresh_token"])
    response_types: list[str] = Field(default_factory=lambda: ["code"])
    scope: str = MCP_SCOPE


@router.get("/.well-known/oauth-authorization-server")
def oauth_metadata() -> JSONResponse:
    return _oauth_json(authorization_server_metadata())


@router.post("/oauth/register", status_code=201)
def oauth_register(registration: OAuthClientRegistration) -> JSONResponse:
    return _oauth_json(register_dynamic_client(registration.model_dump()), status_code=201)


@router.get("/oauth/authorize")
def oauth_authorize(
    request: Request,
    client_id: str,
    redirect_uri: str,
    response_type: str,
    code_challenge: str,
    code_challenge_method: str,
    resource: str,
    scope: str = MCP_SCOPE,
    state: str | None = None,
) -> Response:
    try:
        auth = require_authenticated_workspace(request)
    except HTTPException as error:
        if error.status_code != 401:
            raise
        return_to = f"{oauth_issuer_url()}/oauth/authorize?{request.url.query}"
        login_query = urlencode({"return_to": return_to})
        return RedirectResponse(f"{oauth_issuer_url()}/auth/github/start?{login_query}")
    if auth.context.user_id is None or auth.context.auth_mode != "github":
        raise OAuthProtocolError(
            "access_denied", "a GitHub-authenticated MIRA account is required", 403
        )
    consent = begin_authorization(
        client_id=client_id,
        redirect_uri=redirect_uri,
        response_type=response_type,
        scope=scope,
        resource=resource,
        state=state,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        user_id=auth.context.user_id,
        workspace_id=auth.context.workspace_id,
    )
    csrf = request.cookies.get(CSRF_COOKIE)
    if not csrf:
        raise OAuthProtocolError("server_error", "browser session CSRF state is unavailable", 500)
    return HTMLResponse(_consent_page(consent, auth.workspace_name, csrf))


@router.post("/oauth/authorize/decision")
def oauth_authorization_decision(
    request: Request,
    auth: WorkspaceAuth,
    request_token: Annotated[str, Form(min_length=1)],
    decision: Annotated[str, Form(pattern="^(approve|deny)$")],
    csrf_token: Annotated[str, Form(min_length=1)],
) -> RedirectResponse:
    if auth.context.user_id is None or auth.context.auth_mode != "github":
        raise OAuthProtocolError(
            "access_denied", "a GitHub-authenticated MIRA account is required", 403
        )
    validate_csrf_value(auth, csrf_token, request.cookies.get(CSRF_COOKIE))
    location = decide_authorization(
        request_token,
        approved=decision == "approve",
        user_id=auth.context.user_id,
        workspace_id=auth.context.workspace_id,
    )
    return RedirectResponse(location, status_code=303)


@router.post("/oauth/token")
def oauth_token(
    grant_type: Annotated[str, Form(min_length=1)],
    client_id: Annotated[str, Form(min_length=1)],
    resource: Annotated[str, Form(min_length=1)],
    code: Annotated[str | None, Form()] = None,
    redirect_uri: Annotated[str | None, Form()] = None,
    code_verifier: Annotated[str | None, Form()] = None,
    refresh_token: Annotated[str | None, Form()] = None,
    scope: Annotated[str | None, Form()] = None,
) -> JSONResponse:
    if grant_type == "authorization_code":
        if not code or not redirect_uri or not code_verifier:
            raise OAuthProtocolError(
                "invalid_request",
                "code, redirect_uri, and code_verifier are required",
            )
        payload = exchange_authorization_code(
            code=code,
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier,
            resource=resource,
        )
    elif grant_type == "refresh_token":
        if not refresh_token:
            raise OAuthProtocolError("invalid_request", "refresh_token is required")
        payload = exchange_refresh_token(
            refresh_token=refresh_token,
            client_id=client_id,
            resource=resource,
            scope=scope,
        )
    else:
        raise OAuthProtocolError("unsupported_grant_type", "grant_type is not supported")
    return _oauth_json(payload)


@router.post("/oauth/revoke")
def oauth_revoke(
    token: Annotated[str, Form(min_length=1)],
    client_id: Annotated[str, Form(min_length=1)],
) -> Response:
    revoke_oauth_token(token, client_id)
    return Response(status_code=200, headers={"Cache-Control": "no-store"})


def oauth_error_response(error: OAuthProtocolError) -> JSONResponse:
    return _oauth_json(
        {"error": error.error, "error_description": error.description},
        status_code=error.status_code,
    )


def _oauth_json(payload: dict[str, object], status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        payload,
        status_code=status_code,
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


def _consent_page(consent: dict[str, object], workspace_name: str, csrf: str) -> str:
    client_name = html.escape(str(consent["client_name"]))
    workspace = html.escape(workspace_name)
    resource = html.escape(str(consent["resource"]))
    request_token = html.escape(str(consent["request_token"]), quote=True)
    csrf_token = html.escape(csrf, quote=True)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Authorize {client_name} | MIRA</title>
  <style>
    body {{ margin: 0; font-family: system-ui, sans-serif; background: #f7f6f2; color: #25231f; }}
    main {{
      max-width: 540px; margin: 10vh auto; padding: 32px; background: white;
      border: 1px solid #d9d6ce; border-radius: 8px;
    }}
    h1 {{ font-size: 24px; margin: 0 0 12px; }}
    p, li {{ line-height: 1.55; }}
    .meta {{ padding: 14px; background: #f2f1ed; border-radius: 6px; overflow-wrap: anywhere; }}
    .actions {{ display: flex; justify-content: flex-end; gap: 10px; margin-top: 24px; }}
    button {{
      border: 1px solid #aaa69d; border-radius: 6px; padding: 10px 16px;
      background: white; cursor: pointer;
    }}
    button[value="approve"] {{ border-color: #25231f; background: #25231f; color: white; }}
  </style>
</head>
<body>
  <main>
    <h1>Connect {client_name} to MIRA</h1>
    <p>This client is requesting access to the <strong>{workspace}</strong> workspace.</p>
    <ul>
      <li>Read and retrieve memory</li>
      <li>Save new observations</li>
      <li>Inspect graph, working-set, and foresight records</li>
    </ul>
    <p class="meta">MCP resource: {resource}</p>
    <form method="post" action="/oauth/authorize/decision">
      <input type="hidden" name="request_token" value="{request_token}">
      <input type="hidden" name="csrf_token" value="{csrf_token}">
      <div class="actions">
        <button type="submit" name="decision" value="deny">Deny</button>
        <button type="submit" name="decision" value="approve">Allow access</button>
      </div>
    </form>
  </main>
</body>
</html>"""
