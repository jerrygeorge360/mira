"""OAuth 2.1 authorization-server primitives for MIRA MCP access."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, cast
from urllib.parse import urlparse

from core.db.repositories import repository_connection

MCP_SCOPE = "mira:memory"
AUTHORIZATION_REQUEST_TTL_MINUTES = 10
AUTHORIZATION_CODE_TTL_MINUTES = 5
DEFAULT_ACCESS_TOKEN_TTL_SECONDS = 900
DEFAULT_REFRESH_TOKEN_TTL_DAYS = 30
PKCE_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")


@dataclass(frozen=True)
class OAuthProtocolError(Exception):
    """An OAuth error suitable for protocol-level serialization."""

    error: str
    description: str
    status_code: int = 400


def oauth_issuer_url() -> str:
    configured = os.environ.get("MIRA_OAUTH_ISSUER_URL") or os.environ.get(
        "MIRA_MCP_ISSUER_URL", "http://localhost:8000"
    )
    return configured.rstrip("/")


def mcp_resource_url() -> str:
    configured = os.environ.get("MIRA_MCP_PUBLIC_URL", "http://localhost:8090").rstrip("/")
    return configured if configured.endswith("/mcp") else f"{configured}/mcp"


def authorization_server_metadata() -> dict[str, object]:
    issuer = oauth_issuer_url()
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/oauth/authorize",
        "token_endpoint": f"{issuer}/oauth/token",
        "registration_endpoint": f"{issuer}/oauth/register",
        "revocation_endpoint": f"{issuer}/oauth/revoke",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["none"],
        "code_challenge_methods_supported": ["S256"],
        "scopes_supported": [MCP_SCOPE],
        "resource_indicators_supported": True,
    }


def sync_first_party_oauth_clients() -> int:
    """Upsert explicitly configured first-party public OAuth clients."""
    raw = os.environ.get("MIRA_OAUTH_FIRST_PARTY_CLIENTS", "").strip()
    if not raw:
        return 0
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as error:
        raise RuntimeError("MIRA_OAUTH_FIRST_PARTY_CLIENTS must be valid JSON") from error
    if not isinstance(decoded, list):
        raise RuntimeError("MIRA_OAUTH_FIRST_PARTY_CLIENTS must be a JSON array")
    count = 0
    for item in decoded:
        if not isinstance(item, dict):
            raise RuntimeError("each first-party OAuth client must be an object")
        client_id = _required_metadata_string(item, "client_id")
        client_name = _required_metadata_string(item, "client_name")
        redirect_uris = _validate_redirect_uris(item.get("redirect_uris"))
        now = _now()
        with repository_connection() as connection:
            connection.execute(
                """
                INSERT INTO oauth_clients (
                    client_id, client_name, redirect_uris_json, scope,
                    token_endpoint_auth_method, client_type, created_at
                ) VALUES (?, ?, ?, ?, 'none', 'first_party', ?)
                ON CONFLICT(client_id) DO UPDATE SET
                    client_name = excluded.client_name,
                    redirect_uris_json = excluded.redirect_uris_json,
                    scope = excluded.scope,
                    token_endpoint_auth_method = excluded.token_endpoint_auth_method,
                    disabled_at = NULL
                WHERE oauth_clients.client_type = 'first_party'
                """,
                (client_id, client_name, json.dumps(redirect_uris), MCP_SCOPE, now),
            )
        count += 1
    return count


def register_dynamic_client(metadata: dict[str, object]) -> dict[str, object]:
    """Register an untrusted public client using the RFC 7591 subset MIRA supports."""
    client_name = _required_metadata_string(metadata, "client_name")
    redirect_uris = _validate_redirect_uris(metadata.get("redirect_uris"))
    auth_method = str(metadata.get("token_endpoint_auth_method", "none"))
    if auth_method != "none":
        raise OAuthProtocolError(
            "invalid_client_metadata",
            "only public clients using token_endpoint_auth_method=none are supported",
        )
    _validate_registration_capabilities(metadata)
    client_id = f"mira_{secrets.token_urlsafe(24)}"
    created_at = _now()
    with repository_connection() as connection:
        connection.execute(
            """
            INSERT INTO oauth_clients (
                client_id, client_name, redirect_uris_json, scope,
                token_endpoint_auth_method, client_type, created_at
            ) VALUES (?, ?, ?, ?, 'none', 'dynamic', ?)
            """,
            (client_id, client_name, json.dumps(redirect_uris), MCP_SCOPE, created_at),
        )
    return {
        "client_id": client_id,
        "client_id_issued_at": int(datetime.fromisoformat(created_at).timestamp()),
        "client_name": client_name,
        "redirect_uris": redirect_uris,
        "token_endpoint_auth_method": "none",  # nosec B105
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "scope": MCP_SCOPE,
    }


def begin_authorization(
    *,
    client_id: str,
    redirect_uri: str,
    response_type: str,
    scope: str,
    resource: str,
    state: str | None,
    code_challenge: str,
    code_challenge_method: str,
    user_id: str,
    workspace_id: str,
) -> dict[str, object]:
    """Validate an authorization request and persist a consent transaction."""
    client = _active_client(client_id)
    if response_type != "code":
        raise OAuthProtocolError("unsupported_response_type", "response_type must be code")
    if redirect_uri not in cast(list[str], client["redirect_uris"]):
        raise OAuthProtocolError("invalid_request", "redirect_uri is not registered")
    normalized_scope = _validate_scope(scope)
    if resource.rstrip("/") != mcp_resource_url().rstrip("/"):
        raise OAuthProtocolError("invalid_target", "resource does not identify this MCP server")
    if code_challenge_method != "S256" or not PKCE_PATTERN.fullmatch(code_challenge):
        raise OAuthProtocolError("invalid_request", "PKCE with S256 is required")
    request_token = secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)  # noqa: UP017
    with repository_connection() as connection:
        membership = connection.execute(
            """
            SELECT 1 FROM workspace_members
            JOIN workspaces ON workspaces.id = workspace_members.workspace_id
            WHERE workspace_members.user_id = ? AND workspace_members.workspace_id = ?
              AND workspaces.status = 'active'
            """,
            (user_id, workspace_id),
        ).fetchone()
        if membership is None:
            raise OAuthProtocolError("access_denied", "workspace access is unavailable", 403)
        connection.execute(
            """
            INSERT INTO oauth_authorization_requests (
                id, request_token_hash, client_id, user_id, workspace_id,
                redirect_uri, scope, resource, state, code_challenge,
                code_challenge_method, status, created_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'S256', 'pending', ?, ?)
            """,
            (
                secrets.token_hex(16),
                _hash(request_token),
                client_id,
                user_id,
                workspace_id,
                redirect_uri,
                normalized_scope,
                mcp_resource_url(),
                state,
                code_challenge,
                now.isoformat(),
                (now + timedelta(minutes=AUTHORIZATION_REQUEST_TTL_MINUTES)).isoformat(),
            ),
        )
    return {
        "request_token": request_token,
        "client_name": client["client_name"],
        "scope": normalized_scope,
        "resource": mcp_resource_url(),
    }


def decide_authorization(
    request_token: str,
    *,
    approved: bool,
    user_id: str,
    workspace_id: str,
) -> str:
    """Consume a consent transaction and return its client redirect URL."""
    now = datetime.now(timezone.utc)  # noqa: UP017
    with repository_connection() as connection:
        row = connection.execute(
            """
            SELECT * FROM oauth_authorization_requests
            WHERE request_token_hash = ? AND status = 'pending' AND expires_at > ?
              AND user_id = ? AND workspace_id = ?
            """,
            (_hash(request_token), now.isoformat(), user_id, workspace_id),
        ).fetchone()
        if row is None:
            raise OAuthProtocolError(
                "invalid_request", "authorization request is invalid or expired"
            )
        if not approved:
            connection.execute(
                "UPDATE oauth_authorization_requests SET status = 'denied' WHERE id = ?",
                (row["id"],),
            )
            return _authorization_redirect(
                str(row["redirect_uri"]), error="access_denied", state=row["state"]
            )
        code = secrets.token_urlsafe(48)
        updated = connection.execute(
            """
            UPDATE oauth_authorization_requests
            SET code_hash = ?, code_expires_at = ?, status = 'approved'
            WHERE id = ? AND status = 'pending'
            RETURNING id
            """,
            (
                _hash(code),
                (now + timedelta(minutes=AUTHORIZATION_CODE_TTL_MINUTES)).isoformat(),
                row["id"],
            ),
        ).fetchone()
        if updated is None:
            raise OAuthProtocolError(
                "invalid_request", "authorization request was already consumed"
            )
    return _authorization_redirect(str(row["redirect_uri"]), code=code, state=row["state"])


def exchange_authorization_code(
    *,
    code: str,
    client_id: str,
    redirect_uri: str,
    code_verifier: str,
    resource: str,
) -> dict[str, object]:
    """Exchange one authorization code for a rotating opaque token pair."""
    if not PKCE_PATTERN.fullmatch(code_verifier):
        raise OAuthProtocolError("invalid_grant", "code_verifier is invalid")
    _active_client(client_id)
    now = _now()
    with repository_connection() as connection:
        row = connection.execute(
            """
            SELECT * FROM oauth_authorization_requests
            WHERE code_hash = ? AND status = 'approved' AND code_expires_at > ?
            """,
            (_hash(code), now),
        ).fetchone()
        if row is None:
            raise OAuthProtocolError("invalid_grant", "authorization code is invalid or expired")
        if (
            str(row["client_id"]) != client_id
            or str(row["redirect_uri"]) != redirect_uri
            or str(row["resource"]).rstrip("/") != resource.rstrip("/")
        ):
            raise OAuthProtocolError("invalid_grant", "authorization code binding is invalid")
        expected_challenge = _pkce_challenge(code_verifier)
        if not secrets.compare_digest(expected_challenge, str(row["code_challenge"])):
            raise OAuthProtocolError("invalid_grant", "PKCE verification failed")
        consumed = connection.execute(
            """
            UPDATE oauth_authorization_requests
            SET status = 'consumed', consumed_at = ?
            WHERE id = ? AND status = 'approved'
            RETURNING id
            """,
            (now, row["id"]),
        ).fetchone()
        if consumed is None:
            raise OAuthProtocolError("invalid_grant", "authorization code was already used")
        return _issue_token_pair(connection, row)


def exchange_refresh_token(
    *,
    refresh_token: str,
    client_id: str,
    resource: str,
    scope: str | None = None,
) -> dict[str, object]:
    """Rotate a refresh token and issue a fresh access-token pair."""
    _active_client(client_id)
    now = _now()
    with repository_connection() as connection:
        row = connection.execute(
            """
            SELECT * FROM oauth_refresh_tokens
            WHERE token_hash = ? AND rotated_at IS NULL AND revoked_at IS NULL AND expires_at > ?
            """,
            (_hash(refresh_token), now),
        ).fetchone()
        if row is None:
            raise OAuthProtocolError("invalid_grant", "refresh token is invalid or expired")
        requested_scope = _validate_scope(scope or str(row["scope"]))
        if (
            str(row["client_id"]) != client_id
            or str(row["resource"]).rstrip("/") != resource.rstrip("/")
            or requested_scope != str(row["scope"])
        ):
            raise OAuthProtocolError("invalid_grant", "refresh token binding is invalid")
        rotated = connection.execute(
            """
            UPDATE oauth_refresh_tokens SET rotated_at = ?
            WHERE id = ? AND rotated_at IS NULL AND revoked_at IS NULL
            RETURNING id
            """,
            (now, row["id"]),
        ).fetchone()
        if rotated is None:
            raise OAuthProtocolError("invalid_grant", "refresh token was already used")
        return _issue_token_pair(connection, row)


def revoke_oauth_token(token: str, client_id: str) -> None:
    """Revoke an access or refresh token without revealing whether it existed."""
    now = _now()
    token_hash = _hash(token)
    with repository_connection() as connection:
        connection.execute(
            """
            UPDATE oauth_access_tokens SET revoked_at = ?
            WHERE token_hash = ? AND client_id = ? AND revoked_at IS NULL
            """,
            (now, token_hash, client_id),
        )
        connection.execute(
            """
            UPDATE oauth_refresh_tokens SET revoked_at = ?
            WHERE token_hash = ? AND client_id = ? AND revoked_at IS NULL
            """,
            (now, token_hash, client_id),
        )


def resolve_oauth_access_token(token: str) -> dict[str, object] | None:
    """Resolve an active, resource-bound OAuth token for the MCP resource server."""
    with repository_connection() as connection:
        row = connection.execute(
            """
            SELECT oauth_access_tokens.*, workspace_members.role, workspaces.status
            FROM oauth_access_tokens
            JOIN workspaces ON workspaces.id = oauth_access_tokens.workspace_id
            JOIN workspace_members
              ON workspace_members.workspace_id = oauth_access_tokens.workspace_id
             AND workspace_members.user_id = oauth_access_tokens.user_id
            WHERE oauth_access_tokens.token_hash = ?
              AND oauth_access_tokens.revoked_at IS NULL
              AND oauth_access_tokens.expires_at > ?
            """,
            (_hash(token), _now()),
        ).fetchone()
    if (
        row is None
        or row["status"] != "active"
        or str(row["resource"]).rstrip("/") != mcp_resource_url().rstrip("/")
    ):
        return None
    return {key: row[key] for key in row.keys()}  # noqa: SIM118


def _issue_token_pair(connection: sqlite3.Connection, source: Any) -> dict[str, object]:
    access_token = secrets.token_urlsafe(48)
    refresh_token = secrets.token_urlsafe(64)
    now = datetime.now(timezone.utc)  # noqa: UP017
    access_ttl = _positive_int_env(
        "MIRA_OAUTH_ACCESS_TOKEN_TTL_SECONDS", DEFAULT_ACCESS_TOKEN_TTL_SECONDS
    )
    refresh_days = _positive_int_env(
        "MIRA_OAUTH_REFRESH_TOKEN_TTL_DAYS", DEFAULT_REFRESH_TOKEN_TTL_DAYS
    )
    common = (
        str(source["client_id"]),
        str(source["user_id"]),
        str(source["workspace_id"]),
        str(source["scope"]),
        str(source["resource"]),
    )
    connection.execute(
        """
        INSERT INTO oauth_access_tokens (
            id, token_hash, client_id, user_id, workspace_id,
            scope, resource, created_at, expires_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            secrets.token_hex(16),
            _hash(access_token),
            *common,
            now.isoformat(),
            (now + timedelta(seconds=access_ttl)).isoformat(),
        ),
    )
    connection.execute(
        """
        INSERT INTO oauth_refresh_tokens (
            id, token_hash, client_id, user_id, workspace_id,
            scope, resource, created_at, expires_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            secrets.token_hex(16),
            _hash(refresh_token),
            *common,
            now.isoformat(),
            (now + timedelta(days=refresh_days)).isoformat(),
        ),
    )
    return {
        "access_token": access_token,
        "token_type": "Bearer",  # nosec B105
        "expires_in": access_ttl,
        "refresh_token": refresh_token,
        "scope": str(source["scope"]),
    }


def _active_client(client_id: str) -> dict[str, object]:
    with repository_connection() as connection:
        row = connection.execute(
            """
            SELECT * FROM oauth_clients
            WHERE client_id = ? AND disabled_at IS NULL
              AND (expires_at IS NULL OR expires_at > ?)
            """,
            (client_id, _now()),
        ).fetchone()
    if row is None:
        raise OAuthProtocolError("unauthorized_client", "OAuth client is unknown or disabled", 401)
    result = {key: row[key] for key in row.keys()}  # noqa: SIM118
    result["redirect_uris"] = json.loads(str(result["redirect_uris_json"]))
    return result


def _validate_registration_capabilities(metadata: dict[str, object]) -> None:
    grant_types = metadata.get("grant_types", ["authorization_code", "refresh_token"])
    response_types = metadata.get("response_types", ["code"])
    supported_grants = {"authorization_code", "refresh_token"}
    if not isinstance(grant_types, list) or set(grant_types) - supported_grants:
        raise OAuthProtocolError("invalid_client_metadata", "unsupported grant_types")
    if "authorization_code" not in grant_types:
        raise OAuthProtocolError("invalid_client_metadata", "authorization_code grant is required")
    if response_types != ["code"]:
        raise OAuthProtocolError("invalid_client_metadata", "response_types must contain only code")
    _validate_scope(str(metadata.get("scope", MCP_SCOPE)))


def _validate_redirect_uris(value: object) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(uri, str) for uri in value):
        raise OAuthProtocolError(
            "invalid_client_metadata",
            "redirect_uris must be a non-empty string array",
        )
    redirects: list[str] = []
    for raw_uri in cast(list[str], value):
        parsed = urlparse(raw_uri)
        localhost = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if (
            not parsed.scheme
            or not parsed.netloc
            or parsed.fragment
            or parsed.username
            or parsed.password
            or (parsed.scheme != "https" and not (parsed.scheme == "http" and localhost))
        ):
            raise OAuthProtocolError(
                "invalid_redirect_uri",
                "redirect URIs must use HTTPS, except HTTP loopback addresses",
            )
        redirects.append(raw_uri)
    return list(dict.fromkeys(redirects))


def _validate_scope(scope: str) -> str:
    requested = {item for item in scope.split() if item}
    if requested != {MCP_SCOPE}:
        raise OAuthProtocolError("invalid_scope", f"supported scope is {MCP_SCOPE}")
    return MCP_SCOPE


def _required_metadata_string(metadata: dict[str, object], key: str) -> str:
    value = metadata.get(key)
    if not isinstance(value, str) or not value.strip():
        raise OAuthProtocolError("invalid_client_metadata", f"{key} is required")
    return value.strip()


def _authorization_redirect(
    redirect_uri: str,
    *,
    code: str | None = None,
    error: str | None = None,
    state: object = None,
) -> str:
    from urllib.parse import urlencode

    params: dict[str, str] = {}
    if code:
        params["code"] = code
    if error:
        params["error"] = error
    if state is not None:
        params["state"] = str(state)
    separator = "&" if "?" in redirect_uri else "?"
    return f"{redirect_uri}{separator}{urlencode(params)}"


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()  # noqa: UP017
