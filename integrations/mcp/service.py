"""Standalone MCP Streamable HTTP service for MIRA memory tools."""

from __future__ import annotations

import os

from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.access_logging import install_health_access_filter
from api.dependencies import configure_runtime_database, load_runtime_environment
from api.oauth import MCP_SCOPE, mcp_resource_url, oauth_issuer_url
from integrations.mcp.auth import StaticTokenVerifier, authenticated_workspace_context
from integrations.mcp.server import MCP_SERVER_INSTRUCTIONS, MCP_TOOL_DESCRIPTIONS, build_mcp_server


def create_mcp_server() -> FastMCP:
    """Create the authenticated MIRA MCP protocol server."""
    load_runtime_environment()
    configure_runtime_database()
    install_health_access_filter()
    public_url = mcp_resource_url()
    issuer_url = oauth_issuer_url()
    mcp = FastMCP(
        "MIRA Memory",
        instructions=MCP_SERVER_INSTRUCTIONS,
        token_verifier=StaticTokenVerifier(),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(issuer_url),
            resource_server_url=AnyHttpUrl(public_url),
            required_scopes=[MCP_SCOPE],
        ),
        host="0.0.0.0",  # nosec B104
        port=int(os.environ.get("MCP_PORT", "8090")),
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
    )

    def call(tool: str, params: dict[str, object]) -> dict[str, object]:
        context = authenticated_workspace_context()
        return build_mcp_server(context).call_tool(tool, params)

    @mcp.tool(description=MCP_TOOL_DESCRIPTIONS["save_observation"])
    def save_observation(session_id: str, content: str, role: str = "user") -> dict[str, object]:
        return call(
            "save_observation",
            {"session_id": session_id, "content": content, "role": role},
        )

    @mcp.tool(description=MCP_TOOL_DESCRIPTIONS["retrieve_memory"])
    def retrieve_memory(
        query: str,
        session_id: str | None = None,
        limit: int = 8,
    ) -> dict[str, object]:
        return call(
            "retrieve_memory",
            {"query": query, "session_id": session_id, "limit": limit},
        )

    @mcp.tool(description=MCP_TOOL_DESCRIPTIONS["inspect_session_working_set"])
    def inspect_session_working_set(
        session_id: str,
        max_items: int = 20,
    ) -> dict[str, object]:
        return call(
            "inspect_session_working_set",
            {"session_id": session_id, "max_items": max_items},
        )

    @mcp.tool(description=MCP_TOOL_DESCRIPTIONS["inspect_graph"])
    def inspect_graph(
        node_id: str | None = None,
        edge_type: str | None = None,
        depth: int = 1,
    ) -> dict[str, object]:
        return call(
            "inspect_graph",
            {"node_id": node_id, "edge_type": edge_type, "depth": depth},
        )

    @mcp.tool(description=MCP_TOOL_DESCRIPTIONS["list_active_foresight"])
    def list_active_foresight(session_id: str | None = None) -> dict[str, object]:
        return call("list_active_foresight", {"session_id": session_id})

    @mcp.tool(description=MCP_TOOL_DESCRIPTIONS["run_retrieval_query"])
    def run_retrieval_query(
        query: str,
        session_id: str | None = None,
        mode: str | None = None,
        limit: int = 8,
    ) -> dict[str, object]:
        return call(
            "run_retrieval_query",
            {
                "query": query,
                "session_id": session_id,
                "mode": mode,
                "limit": limit,
            },
        )

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "service": "mira-mcp"})

    return mcp


mcp = create_mcp_server()
app = mcp.streamable_http_app()
