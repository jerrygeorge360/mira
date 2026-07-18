"""Compatibility import for the MIRA MCP integration.

The MCP adapter is no longer Slack-owned. Import from ``integrations.mcp`` in
new code; this module remains so older tests and callers keep working.
"""

from integrations.mcp.server import MCPServer, MCPTool, build_mcp_server, run_mcp_server

__all__ = ["MCPServer", "MCPTool", "build_mcp_server", "run_mcp_server"]
