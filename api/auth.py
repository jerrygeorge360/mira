"""Server-side authentication and trusted workspace resolution for the MIRA API."""

from __future__ import annotations

import hashlib
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated, cast

import httpx
from fastapi import Depends, HTTPException, Request, Response

from core.db.repositories import WorkspaceContext, repository_connection
from core.db.schema import LEGACY_WORKSPACE_ID, seed_workspace_canonical_registries

SESSION_COOKIE = "mira_session"
CSRF_COOKIE = "mira_csrf"
SESSION_TTL_HOURS = 24 * 7
OAUTH_STATE_TTL_MINUTES = 10


@dataclass(frozen=True)
class AuthenticatedWorkspace:
    context: WorkspaceContext
    github_login: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None
    workspace_name: str = ""
    session_id: str | None = None
    expires_at: str | None = None


def require_authenticated_workspace(request: Request) -> AuthenticatedWorkspace:
    """Resolve auth from a server session or explicit development binding."""
    mode = os.environ.get("MIRA_AUTH_MODE", "github").strip().casefold()
    if mode == "development":
        workspace_id = os.environ.get("MIRA_DEVELOPMENT_WORKSPACE_ID", LEGACY_WORKSPACE_ID)
        with repository_connection() as connection:
            workspace = connection.execute(
                "SELECT name, status FROM workspaces WHERE id = ?", (workspace_id,)
            ).fetchone()
        if workspace is None or workspace["status"] != "active":
            raise HTTPException(status_code=503, detail="development workspace is unavailable")
        return AuthenticatedWorkspace(
            context=WorkspaceContext(workspace_id, auth_mode="development"),
            display_name="Development user",
            workspace_name=str(workspace["name"]),
        )
    if mode != "github":
        raise HTTPException(status_code=503, detail="authentication mode is not configured")

    raw_token = request.cookies.get(SESSION_COOKIE)
    if not raw_token:
        raise HTTPException(status_code=401, detail="authentication required")
    now = _now()
    with repository_connection() as connection:
        row = connection.execute(
            """
            SELECT auth_sessions.id AS auth_session_id,
                   auth_sessions.user_id,
                   auth_sessions.workspace_id,
                   auth_sessions.expires_at,
                   auth_sessions.revoked_at,
                   users.github_login,
                   users.display_name,
                   users.avatar_url,
                   workspaces.name AS workspace_name,
                   workspaces.workspace_type,
                   workspaces.expires_at AS workspace_expires_at,
                   workspaces.status AS workspace_status,
                   workspace_members.role
            FROM auth_sessions
            JOIN users ON users.id = auth_sessions.user_id
            JOIN workspaces ON workspaces.id = auth_sessions.workspace_id
            JOIN workspace_members
              ON workspace_members.workspace_id = auth_sessions.workspace_id
             AND workspace_members.user_id = auth_sessions.user_id
            WHERE auth_sessions.token_hash = ?
            """,
            (_hash(raw_token),),
        ).fetchone()
        if (
            row is None
            or row["revoked_at"] is not None
            or str(row["expires_at"]) <= now
            or row["workspace_status"] != "active"
        ):
            raise HTTPException(status_code=401, detail="authentication session is invalid")
        connection.execute(
            "UPDATE auth_sessions SET last_used_at = ? WHERE id = ?",
            (now, row["auth_session_id"]),
        )
    return AuthenticatedWorkspace(
        context=WorkspaceContext(
            str(row["workspace_id"]),
            user_id=str(row["user_id"]),
            membership_role=str(row["role"]),
            auth_mode="demo" if row["workspace_type"] == "demo" else "github",
        ),
        github_login=str(row["github_login"]) if row["github_login"] else None,
        display_name=str(row["display_name"]) if row["display_name"] else None,
        avatar_url=str(row["avatar_url"]) if row["avatar_url"] else None,
        workspace_name=str(row["workspace_name"]),
        session_id=str(row["auth_session_id"]),
        expires_at=str(row["workspace_expires_at"]) if row["workspace_expires_at"] else None,
    )


WorkspaceAuth = Annotated[AuthenticatedWorkspace, Depends(require_authenticated_workspace)]


def require_csrf(request: Request, auth: AuthenticatedWorkspace) -> None:
    """Validate double-submit CSRF protection for cookie-authenticated mutations."""
    if auth.context.auth_mode == "development":
        return
    validate_request_origin(request)
    supplied = request.headers.get("X-CSRF-Token")
    cookie = request.cookies.get(CSRF_COOKIE)
    if not supplied or not cookie or not secrets.compare_digest(supplied, cookie):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT csrf_token_hash FROM auth_sessions WHERE id = ? AND revoked_at IS NULL",
            (auth.session_id,),
        ).fetchone()
    if row is None or not secrets.compare_digest(str(row["csrf_token_hash"]), _hash(supplied)):
        raise HTTPException(status_code=403, detail="CSRF validation failed")


def create_oauth_state(redirect_uri: str) -> str:
    state = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)  # noqa: UP017
    with repository_connection() as connection:
        connection.execute(
            """
            INSERT INTO oauth_states (id, state_hash, redirect_uri, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                secrets.token_hex(16),
                _hash(state),
                redirect_uri,
                now.isoformat(),
                (now + timedelta(minutes=OAUTH_STATE_TTL_MINUTES)).isoformat(),
            ),
        )
    return state


def consume_oauth_state(state: str) -> str:
    now = _now()
    with repository_connection() as connection:
        row = connection.execute(
            """
            UPDATE oauth_states
            SET consumed_at = ?
            WHERE state_hash = ? AND consumed_at IS NULL AND expires_at > ?
            RETURNING redirect_uri
            """,
            (now, _hash(state), now),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=400, detail="OAuth state is invalid or expired")
    return str(row["redirect_uri"])


def exchange_github_code(code: str) -> dict[str, object]:
    client_id = _required_env("GITHUB_CLIENT_ID")
    client_secret = _required_env("GITHUB_CLIENT_SECRET")
    with httpx.Client(timeout=15.0) as client:
        token_response = client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={"client_id": client_id, "client_secret": client_secret, "code": code},
        )
        token_response.raise_for_status()
        access_token = token_response.json().get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise HTTPException(status_code=502, detail="GitHub authentication failed")
        user_response = client.get(
            "https://api.github.com/user",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {access_token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        user_response.raise_for_status()
    profile = cast(dict[str, object], user_response.json())
    if not isinstance(profile.get("id"), int) or not isinstance(profile.get("login"), str):
        raise HTTPException(status_code=502, detail="GitHub identity response was invalid")
    return profile


def provision_github_identity(profile: dict[str, object]) -> tuple[str, str]:
    """Upsert a GitHub user and transactionally obtain its one personal workspace."""
    github_id = str(profile["id"])
    login = str(profile["login"])
    now = _now()
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT id FROM users WHERE github_id = ?", (github_id,)
        ).fetchone()
        user_id = str(row["id"]) if row else secrets.token_hex(16)
        connection.execute(
            """
            INSERT INTO users (
                id, github_id, github_login, display_name, avatar_url, email,
                created_at, updated_at, last_login_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(github_id) DO UPDATE SET
                github_login = excluded.github_login,
                display_name = excluded.display_name,
                avatar_url = excluded.avatar_url,
                email = excluded.email,
                updated_at = excluded.updated_at,
                last_login_at = excluded.last_login_at
            """,
            (
                user_id,
                github_id,
                login,
                profile.get("name"),
                profile.get("avatar_url"),
                profile.get("email"),
                now,
                now,
                now,
            ),
        )
        persisted_user = connection.execute(
            "SELECT id FROM users WHERE github_id = ?", (github_id,)
        ).fetchone()
        if persisted_user is None:
            raise RuntimeError("GitHub user provisioning failed")
        user_id = str(persisted_user["id"])
        workspace = connection.execute(
            "SELECT id FROM workspaces WHERE owner_user_id = ? AND workspace_type = 'personal'",
            (user_id,),
        ).fetchone()
        if workspace is None:
            proposed_workspace_id = secrets.token_hex(16)
            connection.execute(
                """
                INSERT OR IGNORE INTO workspaces (
                    id, name, slug, owner_user_id, workspace_type, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'personal', 'active', ?, ?)
                """,
                (
                    proposed_workspace_id,
                    f"{login}'s workspace",
                    f"github-{github_id}",
                    user_id,
                    now,
                    now,
                ),
            )
            workspace = connection.execute(
                "SELECT id FROM workspaces WHERE owner_user_id = ? AND workspace_type = 'personal'",
                (user_id,),
            ).fetchone()
            if workspace is None:
                raise RuntimeError("personal workspace provisioning failed")
            workspace_id = str(workspace["id"])
            connection.execute(
                "INSERT OR IGNORE INTO workspace_members VALUES (?, ?, 'owner', ?)",
                (workspace_id, user_id, now),
            )
            seed_workspace_canonical_registries(connection, workspace_id)
        else:
            workspace_id = str(workspace["id"])
    return user_id, workspace_id


def issue_auth_session(
    response: Response,
    user_id: str,
    workspace_id: str,
    *,
    ttl: timedelta | None = None,
) -> None:
    raw_token = secrets.token_urlsafe(48)
    csrf_token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)  # noqa: UP017
    session_ttl = ttl or timedelta(hours=SESSION_TTL_HOURS)
    with repository_connection() as connection:
        connection.execute(
            """
            INSERT INTO auth_sessions (
                id, token_hash, csrf_token_hash, user_id, workspace_id,
                created_at, expires_at, last_used_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                secrets.token_hex(16),
                _hash(raw_token),
                _hash(csrf_token),
                user_id,
                workspace_id,
                now.isoformat(),
                (now + session_ttl).isoformat(),
                now.isoformat(),
            ),
        )
    secure = os.environ.get("COOKIE_SECURE", "true").casefold() == "true"
    response.set_cookie(
        SESSION_COOKIE,
        raw_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=int(session_ttl.total_seconds()),
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        httponly=False,
        secure=secure,
        samesite="lax",
        max_age=int(session_ttl.total_seconds()),
        path="/",
    )


def revoke_auth_session(response: Response, auth: AuthenticatedWorkspace) -> None:
    if auth.session_id:
        with repository_connection() as connection:
            connection.execute(
                "UPDATE auth_sessions SET revoked_at = ? WHERE id = ?",
                (_now(), auth.session_id),
            )
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


def revoke_request_session(request: Request) -> None:
    """Revoke a pre-login browser session before rotating its token."""
    raw_token = request.cookies.get(SESSION_COOKIE)
    if not raw_token:
        return
    with repository_connection() as connection:
        connection.execute(
            "UPDATE auth_sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
            (_now(), _hash(raw_token)),
        )


def validate_request_origin(request: Request) -> None:
    """Require browser mutations to originate from the configured frontend."""
    origin = request.headers.get("Origin")
    allowed = allowed_app_redirect().rstrip("/")
    if not origin or origin.rstrip("/") != allowed:
        raise HTTPException(status_code=403, detail="request origin is not allowed")


def allowed_app_redirect(candidate: str | None = None) -> str:
    configured = os.environ.get("APP_BASE_URL", "http://localhost:5173").rstrip("/")
    if candidate and candidate.rstrip("/") != configured:
        raise HTTPException(status_code=400, detail="redirect target is not allowed")
    return configured


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise HTTPException(status_code=503, detail="GitHub authentication is not configured")
    return value


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()  # noqa: UP017
