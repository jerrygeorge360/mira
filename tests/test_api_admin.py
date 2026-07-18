"""Verify the read-only platform administration boundary."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException

from api.auth import AuthenticatedWorkspace, is_platform_admin, require_platform_admin
from core.db.admin import get_admin_overview
from core.db.repositories import (
    WorkspaceContext,
    configure_database,
    create_workspace,
    repository_connection,
)


@pytest.fixture
def admin_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "admin.sqlite3"
    monkeypatch.setenv("MIRA_DB_PATH", str(path))
    configure_database(path)
    return path


def test_platform_admin_requires_explicit_github_login(
    admin_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MIRA_ADMIN_GITHUB_LOGINS", "JerryGeorge360, deltron-fr")
    admin = _auth("jerrygeorge360")

    assert is_platform_admin(admin) is True
    assert require_platform_admin(admin) is admin
    assert is_platform_admin(_auth("someone-else")) is False
    assert is_platform_admin(_auth("jerrygeorge360", auth_mode="demo")) is False

    with pytest.raises(HTTPException, match="platform administrator access required"):
        require_platform_admin(_auth("someone-else"))


def test_admin_overview_counts_registered_people_without_exposing_content(
    admin_database: Path,
) -> None:
    now = datetime.now(timezone.utc)  # noqa: UP017
    created_at = (now - timedelta(days=2)).isoformat()
    with repository_connection() as connection:
        connection.execute(
            "INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "user-github",
                "github-1",
                "registered-user",
                "Registered User",
                None,
                None,
                created_at,
                created_at,
                now.isoformat(),
            ),
        )
        connection.execute(
            "INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "user-demo",
                None,
                None,
                "Demo User",
                None,
                None,
                created_at,
                created_at,
                created_at,
            ),
        )
    personal_workspace = create_workspace(
        "Personal",
        "personal-admin-test",
        "personal",
        owner_user_id="user-github",
    )
    create_workspace(
        "Demo",
        "demo-admin-test",
        "demo",
        owner_user_id="user-demo",
        expires_at=(now + timedelta(hours=1)).isoformat(),
    )
    with repository_connection() as connection:
        connection.execute(
            "INSERT INTO sessions (id, workspace_id, user_id, status, created_at, updated_at) "
            "VALUES (?, ?, ?, 'active', ?, ?)",
            ("session-1", personal_workspace, "user-github", created_at, created_at),
        )

    overview = get_admin_overview()

    assert overview["users"] == {
        "registered": 1,
        "new_last_7_days": 1,
        "new_last_30_days": 1,
        "active_last_7_days": 1,
    }
    assert overview["workspaces"] == {"demo": 1, "legacy": 1, "personal": 1}
    assert overview["activity"]["conversations"] == 1  # type: ignore[index]
    assert "registered-user" not in str(overview)


def _auth(login: str, *, auth_mode: str = "github") -> AuthenticatedWorkspace:
    return AuthenticatedWorkspace(
        context=WorkspaceContext(
            "workspace-test",
            user_id="user-test",
            membership_role="owner",
            auth_mode=auth_mode,
        ),
        github_login=login,
        workspace_name="Test",
    )
