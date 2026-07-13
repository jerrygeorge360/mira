"""Authentication and server-side workspace binding tests."""

from __future__ import annotations

from http.cookies import SimpleCookie
from pathlib import Path

import pytest
from fastapi import HTTPException, Response
from starlette.requests import Request

from api.auth import (
    SESSION_COOKIE,
    consume_oauth_state,
    create_oauth_state,
    issue_auth_session,
    provision_github_identity,
    require_authenticated_workspace,
    revoke_request_session,
    validate_request_origin,
)
from core.db.repositories import configure_database, get_workspace, repository_connection
from core.demo import cleanup_expired_demo_workspaces, issue_demo_workspace


@pytest.fixture
def auth_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "auth.sqlite3"
    monkeypatch.setenv("MIRA_AUTH_MODE", "github")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    configure_database(path)
    return path


def test_oauth_state_is_single_use(auth_database: Path) -> None:
    state = create_oauth_state("http://localhost:5173")

    assert consume_oauth_state(state) == "http://localhost:5173"
    with pytest.raises(HTTPException, match="OAuth state is invalid"):
        consume_oauth_state(state)


def test_github_identity_reuses_one_personal_workspace(auth_database: Path) -> None:
    profile: dict[str, object] = {
        "id": 123,
        "login": "jerry",
        "name": "Jerry",
        "avatar_url": "https://example.invalid/avatar",
    }

    first = provision_github_identity(profile)
    second = provision_github_identity(profile)

    assert first == second
    with repository_connection() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM workspaces WHERE owner_user_id = ?",
            (first[0],),
        ).fetchone()[0]
    assert count == 1


def test_server_session_stores_hash_and_resolves_workspace(auth_database: Path) -> None:
    user_id, workspace_id = provision_github_identity({"id": 456, "login": "octocat"})
    response = Response()
    issue_auth_session(response, user_id, workspace_id)
    cookies = SimpleCookie()
    for header in response.headers.getlist("set-cookie"):
        cookies.load(header)
    raw_token = cookies[SESSION_COOKIE].value
    with repository_connection() as connection:
        row = connection.execute("SELECT token_hash FROM auth_sessions").fetchone()
    assert row["token_hash"] != raw_token

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/auth/me",
            "headers": [(b"cookie", f"{SESSION_COOKIE}={raw_token}".encode())],
        }
    )
    auth = require_authenticated_workspace(request)

    assert auth.context.user_id == user_id
    assert auth.context.workspace_id == workspace_id


def test_origin_validation_rejects_untrusted_mutation(
    auth_database: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_BASE_URL", "http://localhost:5173")
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/auth/logout",
            "headers": [(b"origin", b"https://attacker.invalid")],
        }
    )

    with pytest.raises(HTTPException, match="origin is not allowed"):
        validate_request_origin(request)


def test_prelogin_session_is_revoked_before_rotation(auth_database: Path) -> None:
    user_id, workspace_id = provision_github_identity({"id": 789, "login": "rotate"})
    response = Response()
    issue_auth_session(response, user_id, workspace_id)
    cookies = SimpleCookie()
    for header in response.headers.getlist("set-cookie"):
        cookies.load(header)
    raw_token = cookies[SESSION_COOKIE].value
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/auth/github/callback",
            "headers": [(b"cookie", f"{SESSION_COOKIE}={raw_token}".encode())],
        }
    )

    revoke_request_session(request)

    with repository_connection() as connection:
        revoked_at = connection.execute("SELECT revoked_at FROM auth_sessions").fetchone()[
            "revoked_at"
        ]
    assert revoked_at is not None


def test_demo_workspaces_are_isolated_limited_and_cleaned(
    auth_database: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded: list[str] = []
    monkeypatch.setattr("core.demo._seed_workspace", seeded.append)
    monkeypatch.setenv("MIRA_DEMO_MAX_ACTIVE", "5")
    monkeypatch.setenv("MIRA_DEMO_MAX_PER_WINDOW", "1")
    first_user, first_workspace, _ = issue_demo_workspace("visitor-a")
    second_user, second_workspace, _ = issue_demo_workspace("visitor-b")

    assert first_user != second_user
    assert first_workspace != second_workspace
    assert first_workspace in seeded and second_workspace in seeded
    with pytest.raises(ValueError, match="issuance limit"):
        issue_demo_workspace("visitor-a")

    with repository_connection() as connection:
        connection.execute(
            "UPDATE workspaces SET expires_at = '2000-01-01T00:00:00+00:00' WHERE id = ?",
            (first_workspace,),
        )
    monkeypatch.setattr("core.demo.chroma.delete_workspace_vectors", lambda *args, **kwargs: None)

    assert cleanup_expired_demo_workspaces() == 1
    assert get_workspace(first_workspace) is None
    assert get_workspace(second_workspace) is not None
