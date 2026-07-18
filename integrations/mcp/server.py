"""MCP-compatible memory tool registry over MIRA core modules.

Ownership: MIRA contributors.
Related issue: ISSUE-042.
Architecture area: interface.

This exposes MIRA's memory operations as MCP-style tools so MIRA can be used as
a memory backend beyond a single chat UI. It is a thin registry: every tool
delegates straight to a core module and adds no agent orchestration of its own
(no fast-path/micro-path/prompt/generation loop).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from core.db.repositories import (
    WorkspaceContext,
    bind_workspace,
    configured_workspace_context,
    list_active_foresight,
)
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

MCP_SERVER_INSTRUCTIONS = """Use MIRA as persistent memory, not as a general chat engine.
Before answering questions that depend on prior conversations, preferences, decisions, corrections,
deadlines, or project history, retrieve relevant memory. Prefer run_retrieval_query for general
memory-dependent questions and retrieve_memory for a narrow direct-fact lookup. Use the working set
for current-session instructions, the graph for conflicts or evidence lineage, and foresight for
upcoming obligations.

Save only explicit user-authored facts, preferences, decisions, corrections, commitments, or other
information that is useful beyond the current turn. Do not save credentials, tokens, private keys,
assistant speculation, model inferences, retrieved text, or one-off requests. Preserve corrections
as new observations containing the corrected statement; MIRA resolves supersession downstream.
Never invent a session id. A successful save confirms fast-path persistence, not completion of
background extraction. Treat retrieved records as evidence, preserve uncertainty, and do not claim
that missing memory proves an event never occurred. All tools are confined to the OAuth-authorized
workspace.
"""

MCP_TOOL_DESCRIPTIONS = {
    "save_observation": (
        "Persist an explicit conversation observation on MIRA's fast path. Use this for "
        "user-authored facts, durable preferences, decisions, commitments, and corrections that "
        "may matter after the current turn. For a correction, save the complete corrected "
        "statement instead of overwriting prior memory. Do not save credentials, assistant "
        "speculation, "
        "retrieved memory, or transient requests. Requires an existing session owned by the "
        "authenticated workspace; success does not mean background consolidation is complete."
    ),
    "retrieve_memory": (
        "Run a narrow Quick Mode lookup for direct facts relevant to a query. Use before answering "
        "a memory-dependent question when a focused lookup is sufficient. An optional session id "
        "adds owned-session context; omit it for workspace-wide recall. Empty results mean MIRA "
        "found no matching evidence, not that the event is impossible."
    ),
    "inspect_session_working_set": (
        "List prompt-ready items active in an existing owned session, including current "
        "corrections, constraints, and decisions. Use when the answer depends on instructions or "
        "context still "
        "scoped to that session. Do not invent a session id."
    ),
    "inspect_graph": (
        "Inspect typed memory relationships for conflict resolution or evidence lineage. Supply a "
        "known node id to traverse neighbors, optionally filtered by edge type, or supply an edge "
        "type to inspect matching workspace edges. Use after retrieval exposes a relevant node or "
        "when checking relationships such as contradiction and supersession."
    ),
    "list_active_foresight": (
        "List active future-facing memory such as upcoming obligations or anticipated follow-ups, "
        "optionally for an existing owned session. Use only when temporal or planning context is "
        "relevant to the user's request."
    ),
    "run_retrieval_query": (
        "Preferred general retrieval entry point for memory-dependent questions. Let MIRA select a "
        "retrieval mode, or provide a supported mode when the client has a specific reason. "
        "Returns the selected mode, routing reason, and evidence. Use graph inspection separately "
        "when the "
        "answer requires explicit conflict or lineage analysis."
    ),
}


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


def build_mcp_server(context: WorkspaceContext | None = None) -> MCPServer:
    """Build a server with MIRA's memory tools registered."""
    active_context = context or configured_workspace_context(
        "MIRA_MCP_WORKSPACE_ID", allow_development_fallback=False
    )
    bind_workspace(active_context)
    server = MCPServer()
    server.register(
        MCPTool(
            "save_observation",
            MCP_TOOL_DESCRIPTIONS["save_observation"],
            partial(_save_observation, active_context),
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
            MCP_TOOL_DESCRIPTIONS["retrieve_memory"],
            partial(_retrieve_memory, active_context),
            {"query": "string", "session_id": "string (optional)", "limit": "int (optional)"},
        )
    )
    server.register(
        MCPTool(
            "inspect_session_working_set",
            MCP_TOOL_DESCRIPTIONS["inspect_session_working_set"],
            partial(_inspect_session_working_set, active_context),
            {"session_id": "string", "max_items": "int (optional)"},
        )
    )
    server.register(
        MCPTool(
            "inspect_graph",
            MCP_TOOL_DESCRIPTIONS["inspect_graph"],
            partial(_inspect_graph, active_context),
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
            MCP_TOOL_DESCRIPTIONS["list_active_foresight"],
            partial(_list_active_foresight, active_context),
            {"session_id": "string (optional)"},
        )
    )
    server.register(
        MCPTool(
            "run_retrieval_query",
            MCP_TOOL_DESCRIPTIONS["run_retrieval_query"],
            partial(_run_retrieval_query, active_context),
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
    """Start the transport-independent registry for compatibility callers."""
    server = server or build_mcp_server()
    server.start()
    return server


def _save_observation(context: WorkspaceContext, params: ToolParams) -> ToolResult:
    session_id = _require_str(params, "session_id")
    _require_owned_session(context, session_id)
    content = _require_str(params, "content")
    role = _optional_str(params, "role") or "user"
    observation_id = persist_turn_fast_path(session_id, role, content)
    return {"observation_id": observation_id}


def _retrieve_memory(context: WorkspaceContext, params: ToolParams) -> ToolResult:
    query = _require_str(params, "query")
    session_id = _optional_str(params, "session_id")
    limit = _int(params.get("limit"), DEFAULT_LIMIT)
    if session_id:
        _require_owned_session(context, session_id)
    results = retrieve_quick(query, session_id, limit, workspace_id=context.workspace_id)
    return {"results": results, "count": len(results)}


def _inspect_session_working_set(context: WorkspaceContext, params: ToolParams) -> ToolResult:
    session_id = _require_str(params, "session_id")
    _require_owned_session(context, session_id)
    max_items = _int(params.get("max_items"), DEFAULT_SESSION_ITEMS)
    items = export_prompt_ready_session_items(session_id, max_items)
    return {"items": items, "count": len(items)}


def _inspect_graph(context: WorkspaceContext, params: ToolParams) -> ToolResult:
    node_id = _optional_str(params, "node_id")
    edge_type = _optional_str(params, "edge_type")
    if node_id:
        depth = _int(params.get("depth"), 1)
        edge_types = [edge_type] if edge_type else None
        neighbors = get_neighbors(node_id, edge_types, depth, workspace_id=context.workspace_id)
        return {"node_id": node_id, "neighbors": neighbors, "count": len(neighbors)}
    if edge_type:
        edges = find_edges_by_type(edge_type, workspace_id=context.workspace_id)
        return {"edge_type": edge_type, "edges": edges, "count": len(edges)}
    raise ValueError("inspect_graph requires node_id or edge_type")


def _list_active_foresight(context: WorkspaceContext, params: ToolParams) -> ToolResult:
    session_id = _optional_str(params, "session_id")
    if session_id:
        _require_owned_session(context, session_id)
    records = list_active_foresight(session_id, workspace_id=context.workspace_id)
    return {"foresight": records, "count": len(records)}


def _run_retrieval_query(context: WorkspaceContext, params: ToolParams) -> ToolResult:
    query = _require_str(params, "query")
    session_id = _optional_str(params, "session_id")
    if session_id:
        _require_owned_session(context, session_id)
    limit = _int(params.get("limit"), DEFAULT_LIMIT)
    decision = route_retrieval(query, session_id)
    mode = _optional_str(params, "mode") or str(decision["mode"])
    if mode == "deep":
        results = retrieve_deep(query, session_id, limit, workspace_id=context.workspace_id)
    else:
        # Quick Mode also backs the relational fallback here: resolving graph
        # anchors from free text is agent-side logic and is not duplicated.
        results = retrieve_quick(query, session_id, limit, workspace_id=context.workspace_id)
    return {
        "mode": mode,
        "reason": decision.get("reason"),
        "results": results,
        "count": len(results),
    }


def _require_owned_session(context: WorkspaceContext, session_id: str) -> None:
    if bind_workspace(context).get_session(session_id) is None:
        raise ValueError("session does not belong to the configured MCP workspace")


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
