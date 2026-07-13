"""Read models for memory-oriented API and UI surfaces.

Ownership: Jerry.
Related issue: ISSUE-134.
Architecture area: memory read models.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable

from core.db.repositories import list_active_foresight, repository_connection
from core.db.schema import LEGACY_WORKSPACE_ID

MemoryRecord = dict[str, object]


def get_memory_graph_read_model(
    entity: str | None = None,
    limit: int = 100,
    workspace_id: str = LEGACY_WORKSPACE_ID,
) -> dict[str, list[MemoryRecord]]:
    """Return graph nodes and active edges for memory visualization."""
    node_params: list[object] = [workspace_id]
    node_where = "WHERE workspace_id = ?"
    if entity:
        node_where += " AND label LIKE ?"
        node_params.append(f"%{entity}%")

    nodes = _fetch_all(
        f"SELECT * FROM graph_nodes {node_where} ORDER BY created_at DESC LIMIT ?",  # nosec B608
        (*node_params, limit),
    )
    node_ids = {str(node["id"]) for node in nodes}
    if not node_ids:
        return {"nodes": [], "edges": []}

    placeholders = ", ".join("?" for _ in node_ids)
    edges = _fetch_all(
        f"""
        SELECT * FROM graph_edges
        WHERE workspace_id = ? AND invalidated_at IS NULL
          AND source_node_id IN ({placeholders})
          AND target_node_id IN ({placeholders})
        ORDER BY created_at DESC
        LIMIT ?
        """,  # nosec B608
        (workspace_id, *sorted(node_ids), *sorted(node_ids), limit),
    )
    return {"nodes": nodes, "edges": edges}


def list_foresight_read_model(
    session_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    workspace_id: str = LEGACY_WORKSPACE_ID,
) -> list[MemoryRecord]:
    """Return foresight records for read-only presentation."""
    if status in (None, "active"):
        if session_id is None:
            return _fetch_all(
                "SELECT * FROM foresight_records WHERE workspace_id = ? AND status = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (workspace_id, "active", limit),
            )
        return list_active_foresight(session_id)[:limit]

    query = (
        "SELECT * FROM foresight_records WHERE workspace_id = ? AND status = ? "
        "ORDER BY created_at DESC LIMIT ?"
    )
    params: tuple[object, ...] = (workspace_id, status, limit)
    if session_id:
        query = """
        SELECT foresight_records.*
        FROM foresight_records
        JOIN observations ON observations.id = foresight_records.source_observation_id
        WHERE foresight_records.workspace_id = ?
          AND foresight_records.status = ? AND observations.session_id = ?
        ORDER BY foresight_records.created_at DESC
        LIMIT ?
        """
        params = (workspace_id, status, session_id, limit)
    return _fetch_all(query, params)


def list_reflections_read_model(
    limit: int = 50, *, workspace_id: str = LEGACY_WORKSPACE_ID
) -> list[MemoryRecord]:
    """Return reflection records for read-only presentation."""
    return _fetch_all(
        "SELECT * FROM reflections WHERE workspace_id = ? ORDER BY created_at DESC LIMIT ?",
        (workspace_id, limit),
    )


def list_community_summaries_read_model(
    limit: int = 50, *, workspace_id: str = LEGACY_WORKSPACE_ID
) -> list[MemoryRecord]:
    """Return community summaries for read-only presentation."""
    return _fetch_all(
        "SELECT * FROM community_summaries WHERE workspace_id = ? ORDER BY created_at DESC LIMIT ?",
        (workspace_id, limit),
    )


def _fetch_all(query: str, params: Iterable[object]) -> list[MemoryRecord]:
    with repository_connection() as connection:
        rows = connection.execute(query, tuple(params)).fetchall()
    return [_row_to_record(row) for row in rows]


def _row_to_record(row: sqlite3.Row) -> MemoryRecord:
    record: MemoryRecord = {}
    for key in tuple(row.keys()):
        value = row[key]
        if key.endswith("_json") and value is not None:
            try:
                record[key] = json.loads(str(value))
            except json.JSONDecodeError:
                record[key] = value
        else:
            record[key] = value
    return record
