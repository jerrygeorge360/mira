"""Tests for MIRA API worker status routes."""

from __future__ import annotations

from typing import Any

from api.auth import AuthenticatedWorkspace
from api.routes.worker import get_worker_status
from core.db.repositories import WorkspaceContext


def test_worker_status_endpoint_returns_queue_counts(tmp_path: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv("MIRA_DB_PATH", str(tmp_path / "api-worker.sqlite3"))

    auth = AuthenticatedWorkspace(context=WorkspaceContext("workspace_legacy_default"))
    response = get_worker_status(auth)

    assert set(response.queue) >= {"pending", "processing", "done", "failed", "dead_letter"}
    assert response.worker["status"] == "unknown"
