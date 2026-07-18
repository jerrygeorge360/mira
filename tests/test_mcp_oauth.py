"""Verify first-party and discoverable OAuth access to the MCP resource."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from api.auth import provision_github_identity
from api.oauth import (
    MCP_SCOPE,
    OAuthProtocolError,
    authorization_server_metadata,
    begin_authorization,
    decide_authorization,
    exchange_authorization_code,
    exchange_refresh_token,
    mcp_resource_url,
    register_dynamic_client,
    resolve_oauth_access_token,
    revoke_oauth_token,
    sync_first_party_oauth_clients,
)
from core.db.repositories import configure_database, repository_connection
from integrations.mcp.auth import StaticTokenVerifier, workspace_context_for_access_token

FIRST_PARTY_CLIENT = "mira-first-party"
REDIRECT_URI = "http://127.0.0.1:43110/oauth/callback"
CODE_VERIFIER = "mira-oauth-verifier-abcdefghijklmnopqrstuvwxyz0123456789"


@pytest.fixture
def oauth_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "oauth.sqlite3"
    monkeypatch.setenv("MIRA_DB_PATH", str(path))
    monkeypatch.setenv("MIRA_OAUTH_ISSUER_URL", "http://localhost:8000")
    monkeypatch.setenv("MIRA_MCP_PUBLIC_URL", "http://localhost:8090/mcp")
    monkeypatch.setenv(
        "MIRA_OAUTH_FIRST_PARTY_CLIENTS",
        json.dumps(
            [
                {
                    "client_id": FIRST_PARTY_CLIENT,
                    "client_name": "MIRA First-party Client",
                    "redirect_uris": [REDIRECT_URI],
                }
            ]
        ),
    )
    configure_database(path)
    assert sync_first_party_oauth_clients() == 1
    return path


@pytest.mark.asyncio
async def test_first_party_pkce_flow_binds_token_to_workspace(oauth_database: Path) -> None:
    user_id, workspace_id = provision_github_identity({"id": 1101, "login": "oauth-user"})
    consent = begin_authorization(
        client_id=FIRST_PARTY_CLIENT,
        redirect_uri=REDIRECT_URI,
        response_type="code",
        scope=MCP_SCOPE,
        resource=mcp_resource_url(),
        state="client-state",
        code_challenge=_challenge(CODE_VERIFIER),
        code_challenge_method="S256",
        user_id=user_id,
        workspace_id=workspace_id,
    )
    callback = decide_authorization(
        str(consent["request_token"]),
        approved=True,
        user_id=user_id,
        workspace_id=workspace_id,
    )
    callback_query = parse_qs(urlparse(callback).query)
    assert callback_query["state"] == ["client-state"]

    tokens = exchange_authorization_code(
        code=callback_query["code"][0],
        client_id=FIRST_PARTY_CLIENT,
        redirect_uri=REDIRECT_URI,
        code_verifier=CODE_VERIFIER,
        resource=mcp_resource_url(),
    )
    access_token = str(tokens["access_token"])
    refresh_token = str(tokens["refresh_token"])
    resolved = resolve_oauth_access_token(access_token)
    assert resolved is not None
    assert resolved["workspace_id"] == workspace_id
    assert resolved["user_id"] == user_id
    with repository_connection() as connection:
        stored = connection.execute("SELECT token_hash FROM oauth_access_tokens").fetchone()[
            "token_hash"
        ]
    assert stored != access_token

    verified = await StaticTokenVerifier().verify_token(access_token)
    context = workspace_context_for_access_token(verified)
    assert context.workspace_id == workspace_id
    assert context.user_id == user_id

    refreshed = exchange_refresh_token(
        refresh_token=refresh_token,
        client_id=FIRST_PARTY_CLIENT,
        resource=mcp_resource_url(),
    )
    with pytest.raises(OAuthProtocolError, match="refresh token is invalid"):
        exchange_refresh_token(
            refresh_token=refresh_token,
            client_id=FIRST_PARTY_CLIENT,
            resource=mcp_resource_url(),
        )
    refreshed_access = str(refreshed["access_token"])
    revoke_oauth_token(refreshed_access, FIRST_PARTY_CLIENT)
    assert resolve_oauth_access_token(refreshed_access) is None


def test_authorization_code_is_one_time_and_pkce_bound(oauth_database: Path) -> None:
    user_id, workspace_id = provision_github_identity({"id": 1102, "login": "pkce-user"})
    consent = begin_authorization(
        client_id=FIRST_PARTY_CLIENT,
        redirect_uri=REDIRECT_URI,
        response_type="code",
        scope=MCP_SCOPE,
        resource=mcp_resource_url(),
        state=None,
        code_challenge=_challenge(CODE_VERIFIER),
        code_challenge_method="S256",
        user_id=user_id,
        workspace_id=workspace_id,
    )
    callback = decide_authorization(
        str(consent["request_token"]),
        approved=True,
        user_id=user_id,
        workspace_id=workspace_id,
    )
    code = parse_qs(urlparse(callback).query)["code"][0]
    with pytest.raises(OAuthProtocolError, match="PKCE verification failed"):
        exchange_authorization_code(
            code=code,
            client_id=FIRST_PARTY_CLIENT,
            redirect_uri=REDIRECT_URI,
            code_verifier="incorrect-verifier-abcdefghijklmnopqrstuvwxyz0123456789",
            resource=mcp_resource_url(),
        )
    exchange_authorization_code(
        code=code,
        client_id=FIRST_PARTY_CLIENT,
        redirect_uri=REDIRECT_URI,
        code_verifier=CODE_VERIFIER,
        resource=mcp_resource_url(),
    )
    with pytest.raises(OAuthProtocolError, match="authorization code is invalid"):
        exchange_authorization_code(
            code=code,
            client_id=FIRST_PARTY_CLIENT,
            redirect_uri=REDIRECT_URI,
            code_verifier=CODE_VERIFIER,
            resource=mcp_resource_url(),
        )


def test_dynamic_registration_and_discovery(oauth_database: Path) -> None:
    metadata = authorization_server_metadata()
    assert metadata["registration_endpoint"] == "http://localhost:8000/oauth/register"
    assert metadata["code_challenge_methods_supported"] == ["S256"]
    registered = register_dynamic_client(
        {
            "client_name": "Open MCP Client",
            "redirect_uris": ["https://client.example/callback"],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "scope": MCP_SCOPE,
        }
    )
    assert str(registered["client_id"]).startswith("mira_")
    assert registered["redirect_uris"] == ["https://client.example/callback"]


def test_dynamic_registration_rejects_insecure_redirect(oauth_database: Path) -> None:
    with pytest.raises(OAuthProtocolError, match="must use HTTPS"):
        register_dynamic_client(
            {
                "client_name": "Unsafe Client",
                "redirect_uris": ["http://client.example/callback"],
            }
        )


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
