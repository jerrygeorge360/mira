"""Tests for MIRA API memory read routes."""

from __future__ import annotations

from typing import Any

from api.auth import AuthenticatedWorkspace
from api.routes.memory import (
    get_community_summaries,
    get_foresight,
    get_memory_graph,
    get_reflections,
)
from core.db.repositories import WorkspaceContext
from core.db.schema import LEGACY_WORKSPACE_ID

AUTH = AuthenticatedWorkspace(WorkspaceContext(LEGACY_WORKSPACE_ID, auth_mode="development"))


def test_memory_graph_endpoint_returns_shape(tmp_path: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv("MIRA_DB_PATH", str(tmp_path / "api-memory.sqlite3"))

    response = get_memory_graph(AUTH, limit=100)

    assert response.nodes == []
    assert response.edges == []


def test_memory_surface_endpoints_return_items_shape(tmp_path: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv("MIRA_DB_PATH", str(tmp_path / "api-memory-surfaces.sqlite3"))

    assert get_foresight(AUTH, limit=50).items == []
    assert get_reflections(AUTH, limit=50).items == []
    assert get_community_summaries(AUTH, limit=50).items == []
