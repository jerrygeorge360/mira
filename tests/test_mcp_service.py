"""Verify the standalone MCP HTTP service boundary."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from core.db.repositories import configure_database, create_session, create_workspace
from integrations.mcp.auth import StaticTokenVerifier, workspace_context_for_access_token
from integrations.mcp.server import build_mcp_server
from integrations.mcp.service import create_mcp_server


@pytest.fixture
def database_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    path = tmp_path / "mira.sqlite3"
    monkeypatch.setenv("MIRA_DB_PATH", str(path))
    monkeypatch.delenv("MIRA_MCP_API_KEY", raising=False)
    monkeypatch.delenv("MIRA_MCP_TOKEN_WORKSPACES", raising=False)
    monkeypatch.delenv("MIRA_MCP_WORKSPACE_ID", raising=False)
    configure_database(path)
    yield path


@pytest.mark.asyncio
async def test_mcp_service_registers_protocol_tools(database_path: Path) -> None:
    server = create_mcp_server()

    tools = {tool.name for tool in await server.list_tools()}
    routes = {route.path for route in server.streamable_http_app().routes}

    assert tools == {
        "save_observation",
        "retrieve_memory",
        "inspect_session_working_set",
        "inspect_graph",
        "list_active_foresight",
        "run_retrieval_query",
    }
    assert {"/mcp", "/health", "/.well-known/oauth-protected-resource/mcp"} <= routes


def test_mcp_tools_require_verified_access_token(database_path: Path) -> None:
    with pytest.raises(PermissionError, match="authenticated MCP workspace"):
        workspace_context_for_access_token(None)


@pytest.mark.asyncio
async def test_mcp_token_lists_tools_for_bound_workspace(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace_id = create_workspace("MCP", "mcp", "development")
    monkeypatch.setenv("MIRA_MCP_API_KEY", "test-token")
    monkeypatch.setenv("MIRA_MCP_WORKSPACE_ID", workspace_id)

    verified = await StaticTokenVerifier().verify_token("test-token")
    assert verified is not None
    assert verified.subject == workspace_id
    assert verified.scopes == ["mira:memory"]
    context = workspace_context_for_access_token(verified)
    assert context.workspace_id == workspace_id
    assert context.auth_mode == "mcp"


@pytest.mark.asyncio
async def test_mcp_call_cannot_cross_workspace(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace_a = create_workspace("MCP A", "mcp-a", "development")
    workspace_b = create_workspace("MCP B", "mcp-b", "development")
    monkeypatch.setenv("MIRA_MCP_TOKEN_WORKSPACES", f'{{"token-a":"{workspace_a}"}}')
    session_b = create_session("user-b", workspace_id=workspace_b)
    verified = await StaticTokenVerifier().verify_token("token-a")
    context = workspace_context_for_access_token(verified)
    response = build_mcp_server(context).call_tool(
        "retrieve_memory",
        {
            "query": "private memory",
            "session_id": session_b,
            "workspace_id": workspace_b,
        },
    )

    assert response["ok"] is False
    assert "configured MCP workspace" in response["error"]


@pytest.mark.asyncio
async def test_mcp_invalid_token_is_rejected(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace_id = create_workspace("MCP", "mcp", "development")
    monkeypatch.setenv("MIRA_MCP_API_KEY", "test-token")
    monkeypatch.setenv("MIRA_MCP_WORKSPACE_ID", workspace_id)

    assert await StaticTokenVerifier().verify_token("wrong") is None
