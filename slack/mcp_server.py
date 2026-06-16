"""MCP server exposing MIRA as tools.

Publishes MIRA's agent and memory operations over the Model Context Protocol so
external MCP clients (including the Slack bot) can query and write memory
through a uniform tool interface.

ISSUE-019: MCP server.
"""

from __future__ import annotations


class MiraMCPServer:
    """Model Context Protocol server fronting MIRA's capabilities."""

    def __init__(self, name: str = "mira") -> None:
        """Initialise the MCP server.

        Args:
            name: Server name advertised to connecting MCP clients.
        """
        raise NotImplementedError

    async def serve(self) -> None:
        """Start serving MCP requests until shut down."""
        raise NotImplementedError
