"""Verify ISSUE-042 MCP memory tool registry.

Ownership: MIRA contributors.
Related issue: ISSUE-042.
Architecture area: interface.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from core.db.repositories import (
    WorkspaceContext,
    bind_workspace,
    configure_database,
    create_session,
    create_workspace,
    save_observation,
)
from core.db.schema import LEGACY_WORKSPACE_ID
from slack.mcp_server import build_mcp_server, run_mcp_server

EXPECTED_TOOLS = {
    "save_observation",
    "retrieve_memory",
    "inspect_session_working_set",
    "inspect_graph",
    "list_active_foresight",
    "run_retrieval_query",
}
MCP_CONTEXT = WorkspaceContext(LEGACY_WORKSPACE_ID, auth_mode="configured")


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    """Configure MCP tests to use an isolated database."""
    path = tmp_path / "mira.sqlite3"
    configure_database(path)
    yield path


def test_server_starts() -> None:
    """The registry can be built and started independently of its transport."""
    server = run_mcp_server(build_mcp_server(MCP_CONTEXT))
    assert server.running is True


def test_tools_are_registered() -> None:
    """All contracted memory tools are registered with definitions."""
    server = build_mcp_server(MCP_CONTEXT)

    assert set(server.tool_names()) == EXPECTED_TOOLS
    definitions = {definition["name"] for definition in server.tool_definitions()}
    assert definitions == EXPECTED_TOOLS
    assert all(definition["description"] for definition in server.tool_definitions())


def test_save_observation_tool_returns_expected_shape(database_path: Path) -> None:
    """The save_observation tool persists and returns an observation id."""
    server = build_mcp_server(MCP_CONTEXT)
    session_id = create_session("jerry")

    response = server.call_tool(
        "save_observation",
        {"session_id": session_id, "content": "Remember to ship the demo."},
    )

    assert response["ok"] is True
    assert response["tool"] == "save_observation"
    assert isinstance(response["result"]["observation_id"], str)


def test_inspect_session_working_set_tool_shape(database_path: Path) -> None:
    """The session working set tool returns an items/count envelope."""
    server = build_mcp_server(MCP_CONTEXT)
    session_id = create_session("jerry")

    response = server.call_tool("inspect_session_working_set", {"session_id": session_id})

    assert response["ok"] is True
    assert response["result"]["count"] == 0
    assert response["result"]["items"] == []


def test_retrieve_memory_tool_shape(database_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The retrieve_memory tool returns a results/count envelope."""
    monkeypatch.setattr("integrations.mcp.server.retrieve_quick", lambda *args, **kwargs: [])
    server = build_mcp_server(MCP_CONTEXT)
    session_id = create_session("jerry")
    save_observation(session_id, "user", "The deploy key lives in the vault.")

    response = server.call_tool(
        "retrieve_memory", {"query": "deploy key", "session_id": session_id, "limit": 5}
    )

    assert response["ok"] is True
    assert response["result"]["count"] == len(response["result"]["results"])


def test_list_active_foresight_tool_shape(database_path: Path) -> None:
    """The foresight tool returns a foresight/count envelope."""
    server = build_mcp_server(MCP_CONTEXT)
    create_session("jerry")

    response = server.call_tool("list_active_foresight", {})

    assert response["ok"] is True
    assert response["result"] == {"foresight": [], "count": 0}


def test_unknown_tool_is_rejected() -> None:
    """An unknown tool name returns an error envelope, not an exception."""
    server = build_mcp_server(MCP_CONTEXT)

    response = server.call_tool("teleport_memory", {})

    assert response["ok"] is False
    assert "unknown tool" in str(response["error"])


def test_missing_required_param_is_reported(database_path: Path) -> None:
    """A missing required parameter is reported as a failed tool call."""
    server = build_mcp_server(MCP_CONTEXT)

    response = server.call_tool("save_observation", {"content": "no session"})

    assert response["ok"] is False
    assert "session_id" in str(response["error"])


def test_tool_arguments_cannot_switch_the_bound_workspace(database_path: Path) -> None:
    workspace_a = create_workspace("MCP A", "mcp-a", "development")
    workspace_b = create_workspace("MCP B", "mcp-b", "development")
    server = build_mcp_server(WorkspaceContext(workspace_a, auth_mode="configured"))
    session_b = bind_workspace(WorkspaceContext(workspace_b)).create_session("user-b")

    response = server.call_tool(
        "retrieve_memory",
        {
            "query": "private memory",
            "session_id": session_b,
            "workspace_id": workspace_b,
        },
    )

    assert response["ok"] is False
    assert "configured MCP workspace" in str(response["error"])
