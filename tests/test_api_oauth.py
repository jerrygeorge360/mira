"""Verify MIRA's browser OAuth and public discovery route boundary."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlencode

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from api.auth import allowed_github_return
from api.oauth import MCP_SCOPE, sync_first_party_oauth_clients
from api.routes.oauth import (
    OAuthClientRegistration,
    oauth_authorize,
    oauth_metadata,
    oauth_register,
)
from core.db.repositories import configure_database

CLIENT_ID = "mira-api-test"
REDIRECT_URI = "http://127.0.0.1:45454/callback"
RESOURCE = "http://localhost:8090/mcp"
CHALLENGE = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"


@pytest.fixture
def oauth_api_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "oauth-api.sqlite3"
    monkeypatch.setenv("MIRA_DB_PATH", str(path))
    monkeypatch.setenv("MIRA_AUTH_MODE", "github")
    monkeypatch.setenv("MIRA_OAUTH_ISSUER_URL", "http://localhost:8000")
    monkeypatch.setenv("MIRA_MCP_PUBLIC_URL", RESOURCE)
    monkeypatch.setenv(
        "MIRA_OAUTH_FIRST_PARTY_CLIENTS",
        json.dumps(
            [
                {
                    "client_id": CLIENT_ID,
                    "client_name": "MIRA API Test",
                    "redirect_uris": [REDIRECT_URI],
                }
            ]
        ),
    )
    configure_database(path)
    sync_first_party_oauth_clients()
    return path


def test_discovery_metadata_exposes_pkce_and_registration(oauth_api_database: Path) -> None:
    response = oauth_metadata()
    payload = json.loads(response.body)

    assert payload["issuer"] == "http://localhost:8000"
    assert payload["registration_endpoint"].endswith("/oauth/register")
    assert payload["code_challenge_methods_supported"] == ["S256"]
    assert payload["scopes_supported"] == [MCP_SCOPE]
    assert response.headers["cache-control"] == "no-store"


def test_unauthenticated_authorize_starts_github_login(oauth_api_database: Path) -> None:
    query = urlencode(
        {
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": MCP_SCOPE,
            "resource": RESOURCE,
            "state": "state-1",
            "code_challenge": CHALLENGE,
            "code_challenge_method": "S256",
        }
    )
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "server": ("localhost", 8000),
            "path": "/oauth/authorize",
            "query_string": query.encode(),
            "headers": [],
        }
    )

    response = oauth_authorize(
        request=request,
        client_id=CLIENT_ID,
        redirect_uri=REDIRECT_URI,
        response_type="code",
        scope=MCP_SCOPE,
        resource=RESOURCE,
        state="state-1",
        code_challenge=CHALLENGE,
        code_challenge_method="S256",
    )

    assert response.status_code == 307
    assert response.headers["location"].startswith(
        "http://localhost:8000/auth/github/start?return_to="
    )


def test_dynamic_registration_route_returns_public_client(oauth_api_database: Path) -> None:
    response = oauth_register(
        OAuthClientRegistration(
            client_name="Desktop MCP Client",
            redirect_uris=["http://127.0.0.1:48123/callback"],
        )
    )
    payload = json.loads(response.body)

    assert response.status_code == 201
    assert payload["token_endpoint_auth_method"] == "none"
    assert payload["client_id"].startswith("mira_")


def test_github_return_only_accepts_mira_authorize_route(
    oauth_api_database: Path,
) -> None:
    accepted = allowed_github_return(
        "http://localhost:8000/oauth/authorize?client_id=mira-api-test"
    )
    assert accepted.startswith("http://localhost:8000/oauth/authorize")

    with pytest.raises(HTTPException, match="return target is not allowed"):
        allowed_github_return("https://attacker.invalid/oauth/authorize")
