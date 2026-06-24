"""MCP-compatible memory server skeleton over MIRA core modules.

Ownership: Kelechi.
Related issue: ISSUE-042.
Architecture area: interface.

This exposes MIRA's memory operations as MCP-style tools so MIRA can be used as
a memory backend beyond a single chat UI. It is a thin, framework-agnostic
skeleton: every tool delegates straight to a core module and adds no agent
orchestration of its own (no fast-path/micro-path/prompt/generation loop). The
real MCP transport (stdio/websocket) can be attached later via ``run_mcp_server``;
the skeleton itself depends only on the standard library and ``core``.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Callable
from dataclasses import dataclass

from core.db.repositories import list_active_foresight
from core.memory.graph import find_edges_by_type, get_neighbors
from core.memory.observation import persist_turn_fast_path
from core.retrieval.auto import route_retrieval
from core.retrieval.deep import retrieve_deep
from core.retrieval.quick import retrieve_quick
from core.session.working_set import export_prompt_ready_session_items

ToolParams = dict[str, object]
ToolResult = dict[str, object]
ToolHandler = Callable[[ToolParams], ToolResult]

LOGGER = logging.getLogger(__name__)

DEFAULT_LIMIT = 8
DEFAULT_SESSION_ITEMS = 20


@dataclass(frozen=True)
class MCPTool:
    """A single MCP-exposed tool wired to a core operation."""

    name: str
    description: str
    handler: ToolHandler
    input_schema: dict[str, object]


class MCPServer:
    """Registry and dispatcher for MIRA memory tools, transport-agnostic."""

    def __init__(self, name: str = "mira-memory") -> None:
        self.name = name
        self._tools: dict[str, MCPTool] = {}
        self._running = False

    def register(self, tool: MCPTool) -> None:
        """Register a tool, rejecting duplicate names."""
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool: {tool.name}")
        self._tools[tool.name] = tool

    def tool_names(self) -> list[str]:
        """Return registered tool names in deterministic order."""
        return sorted(self._tools)

    def tool_definitions(self) -> list[dict[str, object]]:
        """Return MCP-style tool definitions for discovery."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in (self._tools[name] for name in self.tool_names())
        ]

    def call_tool(self, name: str, params: ToolParams | None = None) -> ToolResult:
        """Dispatch a tool call and wrap the result in a stable envelope."""
        tool = self._tools.get(name)
        if tool is None:
            return {"tool": name, "ok": False, "error": f"unknown tool: {name}"}
        try:
            result = tool.handler(params or {})
        except (ValueError, KeyError) as error:
            LOGGER.warning("MCP tool %s failed: %s", name, error)
            return {"tool": name, "ok": False, "error": str(error)}
        return {"tool": name, "ok": True, "result": result}

    def start(self) -> MCPServer:
        """Mark the server ready to serve tool calls."""
        self._running = True
        LOGGER.info("MCP server %s started with %d tools", self.name, len(self._tools))
        return self

    @property
    def running(self) -> bool:
        """Whether the server has been started."""
        return self._running


def build_mcp_server() -> MCPServer:
    """Build a server with MIRA's memory tools registered."""
    server = MCPServer()
    server.register(
        MCPTool(
            "save_observation",
            "Persist a raw observation on the fast path.",
            _save_observation,
            {
                "session_id": "string",
                "content": "string",
                "role": "string (optional, default user)",
            },
        )
    )
    server.register(
        MCPTool(
            "retrieve_memory",
            "Retrieve direct fact memory for a query (Quick Mode).",
            _retrieve_memory,
            {"query": "string", "session_id": "string (optional)", "limit": "int (optional)"},
        )
    )
    server.register(
        MCPTool(
            "inspect_session_working_set",
            "List prompt-ready Session Working Set items for a session.",
            _inspect_session_working_set,
            {"session_id": "string", "max_items": "int (optional)"},
        )
    )
    server.register(
        MCPTool(
            "inspect_graph",
            "Inspect typed graph neighbors of a node or edges of a type.",
            _inspect_graph,
            {
                "node_id": "string (optional)",
                "edge_type": "string (optional)",
                "depth": "int (optional)",
            },
        )
    )
    server.register(
        MCPTool(
            "list_active_foresight",
            "List active foresight records, optionally scoped to a session.",
            _list_active_foresight,
            {"session_id": "string (optional)"},
        )
    )
    server.register(
        MCPTool(
            "run_retrieval_query",
            "Route a query and return retrieval results for the chosen mode.",
            _run_retrieval_query,
            {
                "query": "string",
                "session_id": "string (optional)",
                "mode": "string (optional)",
                "limit": "int (optional)",
            },
        )
    )
    return server


def run_mcp_server(server: MCPServer | None = None) -> MCPServer:
    """Start the MCP server, attaching a real transport if the SDK is present."""
    server = server or build_mcp_server()
    server.start()
    try:
        importlib.import_module("mcp")
    except ModuleNotFoundError:
        LOGGER.warning("mcp SDK not installed; running skeleton without a network transport")
    return server


def _save_observation(params: ToolParams) -> ToolResult:
    session_id = _require_str(params, "session_id")
    content = _require_str(params, "content")
    role = _optional_str(params, "role") or "user"
    observation_id = persist_turn_fast_path(session_id, role, content)
    return {"observation_id": observation_id}


def _retrieve_memory(params: ToolParams) -> ToolResult:
    query = _require_str(params, "query")
    session_id = _optional_str(params, "session_id")
    limit = _int(params.get("limit"), DEFAULT_LIMIT)
    results = retrieve_quick(query, session_id, limit)
    return {"results": results, "count": len(results)}


def _inspect_session_working_set(params: ToolParams) -> ToolResult:
    session_id = _require_str(params, "session_id")
    max_items = _int(params.get("max_items"), DEFAULT_SESSION_ITEMS)
    items = export_prompt_ready_session_items(session_id, max_items)
    return {"items": items, "count": len(items)}


def _inspect_graph(params: ToolParams) -> ToolResult:
    node_id = _optional_str(params, "node_id")
    edge_type = _optional_str(params, "edge_type")
    if node_id:
        depth = _int(params.get("depth"), 1)
        edge_types = [edge_type] if edge_type else None
        neighbors = get_neighbors(node_id, edge_types, depth)
        return {"node_id": node_id, "neighbors": neighbors, "count": len(neighbors)}
    if edge_type:
        edges = find_edges_by_type(edge_type)
        return {"edge_type": edge_type, "edges": edges, "count": len(edges)}
    raise ValueError("inspect_graph requires node_id or edge_type")


def _list_active_foresight(params: ToolParams) -> ToolResult:
    session_id = _optional_str(params, "session_id")
    records = list_active_foresight(session_id)
    return {"foresight": records, "count": len(records)}


def _run_retrieval_query(params: ToolParams) -> ToolResult:
    query = _require_str(params, "query")
    session_id = _optional_str(params, "session_id")
    limit = _int(params.get("limit"), DEFAULT_LIMIT)
    decision = route_retrieval(query, session_id)
    mode = _optional_str(params, "mode") or str(decision["mode"])
    if mode == "deep":
        results = retrieve_deep(query, session_id, limit)
    else:
        # Quick Mode also backs the relational fallback here: resolving graph
        # anchors from free text is agent-side logic and is not duplicated.
        results = retrieve_quick(query, session_id, limit)
    return {
        "mode": mode,
        "reason": decision.get("reason"),
        "results": results,
        "count": len(results),
    }


def _require_str(params: ToolParams, key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing required parameter: {key}")
    return value


def _optional_str(params: ToolParams, key: str) -> str | None:
    value = params.get(key)
    return value if isinstance(value, str) and value.strip() else None


def _int(value: object, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return default
