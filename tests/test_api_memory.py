"""Tests for MIRA API memory read routes."""

from __future__ import annotations

from typing import Any

from api.routes.memory import (
    get_community_summaries,
    get_foresight,
    get_memory_graph,
    get_reflections,
)


def test_memory_graph_endpoint_returns_shape(tmp_path: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv("MIRA_DB_PATH", str(tmp_path / "api-memory.sqlite3"))

    response = get_memory_graph(limit=100)

    assert response.nodes == []
    assert response.edges == []


def test_memory_surface_endpoints_return_items_shape(tmp_path: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv("MIRA_DB_PATH", str(tmp_path / "api-memory-surfaces.sqlite3"))

    assert get_foresight(limit=50).items == []
    assert get_reflections(limit=50).items == []
    assert get_community_summaries(limit=50).items == []
