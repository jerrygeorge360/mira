"""Structured internal functions for concrete agent workflows.

These functions are not a generic provider-side tool-calling abstraction. They are
small, typed runtime calls that MIRA can invoke when the user explicitly asks for
an operational memory workflow.
"""

from __future__ import annotations

from collections.abc import Mapping

from core.db.chroma import vector_store_status
from core.db.repositories import repository_connection, workspace_id_for_session
from core.memory.read_models import (
    get_memory_graph_read_model,
    list_community_summaries_read_model,
    list_foresight_read_model,
    list_reflections_read_model,
)
from core.memory.tiers import list_hot_memory_for_context
from core.session.working_set import list_active_session_items

StructuredFunctionResult = dict[str, object]

INSPECT_MEMORY_FUNCTION = "inspect_memory"

MEMORY_INSPECTION_MARKERS = (
    "inspect memory",
    "memory inspector",
    "memory status",
    "show memory",
    "show me memory",
    "show me your memory",
    "what do you remember",
    "what memory do you have",
    "what memories do you have",
)

_COUNT_QUERIES = {
    "observations": "SELECT COUNT(*) AS count FROM observations",
    "atomic_facts": "SELECT COUNT(*) AS count FROM atomic_facts",
    "graph_nodes": "SELECT COUNT(*) AS count FROM graph_nodes",
    "graph_edges": "SELECT COUNT(*) AS count FROM graph_edges WHERE invalidated_at IS NULL",
    "reflections": "SELECT COUNT(*) AS count FROM reflections",
    "foresight_records": "SELECT COUNT(*) AS count FROM foresight_records",
    "community_summaries": "SELECT COUNT(*) AS count FROM community_summaries",
    "session_working_set": (
        "SELECT COUNT(*) AS count FROM session_working_set WHERE status = 'active'"
    ),
}


def maybe_structured_tool_call(
    session_id: str,
    user_message: str,
) -> StructuredFunctionResult | None:
    """Invoke a structured function only for an explicit supported workflow."""
    normalized = " ".join(user_message.casefold().split())
    if not any(marker in normalized for marker in MEMORY_INSPECTION_MARKERS):
        return None
    return invoke_structured_function(
        INSPECT_MEMORY_FUNCTION,
        {"session_id": session_id, "query": user_message},
    )


def invoke_structured_function(
    function_name: str,
    arguments: Mapping[str, object],
) -> StructuredFunctionResult:
    """Dispatch a supported structured function with validated arguments."""
    if function_name != INSPECT_MEMORY_FUNCTION:
        raise ValueError(f"Unsupported structured function: {function_name}")
    session_id = _required_string(arguments, "session_id")
    query = str(arguments.get("query", ""))
    return inspect_memory(session_id, query=query)


def inspect_memory(session_id: str, *, query: str = "", limit: int = 5) -> StructuredFunctionResult:
    """Return a compact memory snapshot for agent-facing inspection answers."""
    if not session_id:
        raise ValueError("session_id must not be empty")
    if limit < 1:
        raise ValueError("limit must be a positive integer")

    workspace_id = workspace_id_for_session(session_id)
    graph = get_memory_graph_read_model(limit=limit, workspace_id=workspace_id)
    return {
        "tool": INSPECT_MEMORY_FUNCTION,
        "session_id": session_id,
        "counts": _memory_counts(workspace_id),
        "session_working_set": _compact_records(list_active_session_items(session_id), limit),
        "hot_memory": _compact_records(
            list_hot_memory_for_context(session_id, query, limit),
            limit,
        ),
        "reflections": _compact_records(
            list_reflections_read_model(limit, workspace_id=workspace_id), limit
        ),
        "foresight": _compact_records(
            list_foresight_read_model(
                session_id=session_id, limit=limit, workspace_id=workspace_id
            ),
            limit,
        ),
        "community_summaries": _compact_records(
            list_community_summaries_read_model(limit, workspace_id=workspace_id), limit
        ),
        "graph": {
            "nodes": len(graph.get("nodes", [])),
            "edges": len(graph.get("edges", [])),
            "sample_nodes": _compact_records(graph.get("nodes", []), limit),
        },
        "vector_store": vector_store_status(workspace_id),
    }


def tool_result_context_record(result: StructuredFunctionResult) -> dict[str, object]:
    """Convert a structured function result into a prompt-ready retrieval record."""
    tool_name = str(result.get("tool", "structured_function"))
    return {
        "id": f"tool:{tool_name}",
        "source_id": f"tool:{tool_name}",
        "source": "structured_tool",
        "score": 1.0,
        "content": _tool_result_summary(result),
        "record": dict(result),
    }


def _memory_counts(workspace_id: str) -> dict[str, int]:
    with repository_connection() as connection:
        return {
            name: int(
                connection.execute(_workspace_count_query(name, query), (workspace_id,)).fetchone()[
                    "count"
                ]
            )
            for name, query in _COUNT_QUERIES.items()
        }


def _workspace_count_query(name: str, query: str) -> str:
    if name == "session_working_set":
        return (
            "SELECT COUNT(*) AS count FROM session_working_set "
            "JOIN sessions ON sessions.id = session_working_set.session_id "
            "WHERE sessions.workspace_id = ? AND session_working_set.status = 'active'"
        )
    if " WHERE " in query:
        return query.replace(" WHERE ", " WHERE workspace_id = ? AND ", 1)
    return f"{query} WHERE workspace_id = ?"


def _compact_records(records: object, limit: int) -> list[dict[str, object]]:
    if not isinstance(records, list):
        return []
    return [_compact_record(record) for record in records[:limit] if isinstance(record, dict)]


def _compact_record(record: dict[str, object]) -> dict[str, object]:
    keys = (
        "id",
        "type",
        "status",
        "label",
        "kind",
        "relation",
        "content",
        "summary",
        "text",
        "confidence",
        "created_at",
    )
    compact = {key: record[key] for key in keys if key in record and record[key] is not None}
    if not compact:
        compact["id"] = str(record.get("id", ""))
    return compact


def _tool_result_summary(result: StructuredFunctionResult) -> str:
    counts = result.get("counts", {})
    if not isinstance(counts, dict):
        counts = {}
    count_text = ", ".join(
        f"{name}={value}" for name, value in sorted(counts.items()) if isinstance(value, int)
    )
    vector_store = result.get("vector_store", {})
    backend = vector_store.get("backend") if isinstance(vector_store, dict) else None
    return (
        "Structured memory inspection result. "
        f"Counts: {count_text or 'unavailable'}. "
        f"Vector backend: {backend or 'unknown'}."
    )


def _required_string(arguments: Mapping[str, object], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value
