"""Verify the read-only platform administration boundary."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException

from api.auth import AuthenticatedWorkspace, is_platform_admin, require_platform_admin
from api.routes.admin import (
    admin_llm_usage,
    admin_provider,
    update_admin_gateway,
    update_admin_provider,
)
from core.db.admin import get_admin_overview
from core.db.repositories import (
    WorkspaceContext,
    configure_database,
    create_llm_usage_event,
    create_workspace,
    repository_connection,
)


@pytest.fixture
def admin_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "admin.sqlite3"
    monkeypatch.setenv("MIRA_DB_PATH", str(path))
    monkeypatch.delenv("MIRA_PARITOK_ENABLED", raising=False)
    monkeypatch.delenv("PARITOK_UPSTREAM_PROFILE", raising=False)
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


def test_admin_provider_uses_env_until_dashboard_override(
    admin_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del admin_database
    monkeypatch.setenv("LLM_PROFILE", "deepseek")
    admin = _auth("jerrygeorge360")

    initial = admin_provider(admin)
    updated = update_admin_provider({"profile": "gemini"}, admin)

    assert initial["active"] == "deepseek"
    assert initial["source"] == "env"
    assert updated["active"] == "gemini"
    assert updated["source"] == "dashboard"
    assert updated["model"] == "gemini-3.5-flash"


def test_admin_gateway_switch_is_separate_from_provider(
    admin_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del admin_database
    monkeypatch.setenv("LLM_PROFILE", "deepseek")
    monkeypatch.setenv("PARITOK_UPSTREAM_PROFILE", "deepseek")
    admin = _auth("jerrygeorge360")

    updated = update_admin_gateway({"gateway": "paritok"}, admin)

    assert updated["active"] == "deepseek"
    assert updated["gateway"] == "paritok"
    assert updated["gateway_source"] == "dashboard"
    assert updated["paritok_compatible"] is True


def test_admin_gateway_rejects_provider_upstream_mismatch(
    admin_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del admin_database
    monkeypatch.setenv("LLM_PROFILE", "gemini")
    monkeypatch.setenv("PARITOK_UPSTREAM_PROFILE", "deepseek")

    with pytest.raises(HTTPException, match="configured for a different provider"):
        update_admin_gateway({"gateway": "paritok"}, _auth("jerrygeorge360"))


def test_provider_switch_disables_incompatible_paritok_gateway(
    admin_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del admin_database
    monkeypatch.setenv("LLM_PROFILE", "deepseek")
    monkeypatch.setenv("PARITOK_UPSTREAM_PROFILE", "deepseek")
    admin = _auth("jerrygeorge360")
    update_admin_gateway({"gateway": "paritok"}, admin)

    updated = update_admin_provider({"profile": "gemini"}, admin)

    assert updated["active"] == "gemini"
    assert updated["gateway"] == "direct"
    assert updated["paritok_compatible"] is False


def test_admin_usage_reports_provider_counts_without_prompt_content(
    admin_database: Path,
) -> None:
    del admin_database
    create_llm_usage_event(
        {
            "workspace_id": "workspace_legacy_default",
            "run_id": "admin-run",
            "component": "agent",
            "operation": "answer_generation",
            "provider": "deepseek",
            "model": "deepseek-chat",
            "gateway": "direct",
            "status": "succeeded",
            "usage_source": "provider",
            "input_tokens": 120,
            "output_tokens": 30,
            "total_tokens": 150,
            "estimated_input_tokens": 118,
            "latency_ms": 250,
            "prompt_fingerprint": "fingerprint-only",
        }
    )

    usage = admin_llm_usage(_auth("jerrygeorge360"), days=7, limit=30)

    assert usage["totals"]["input_tokens"] == 120  # type: ignore[index]
    assert usage["totals"]["fully_measured"] is True  # type: ignore[index]
    assert usage["by_gateway"][0]["name"] == "direct"  # type: ignore[index]
    assert "prompt" not in str(usage["recent_calls"]).casefold()


def test_admin_provider_rejects_unknown_profile(admin_database: Path) -> None:
    del admin_database

    with pytest.raises(HTTPException, match="unknown provider profile"):
        update_admin_provider({"profile": "unknown"}, _auth("jerrygeorge360"))


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
