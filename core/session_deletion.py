"""Session deletion with derived-memory invalidation."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from core.db import chroma
from core.db.repositories import repository_connection
from core.workspace_data import delete_workspace_data


def delete_session_data(session_id: str, *, workspace_id: str) -> dict[str, int]:
    """Tombstone one chat session and deactivate memory derived only from it.

    Observations are scrubbed rather than hard-deleted so existing trace/fact
    foreign keys remain valid. Retrieval surfaces are disabled through session
    status, vector deletion, and derived-record status updates.
    """
    now = _now()
    with repository_connection() as connection:
        session = connection.execute(
            "SELECT id FROM sessions WHERE id = ? AND workspace_id = ? AND status != 'deleted'",
            (session_id, workspace_id),
        ).fetchone()
        if session is None:
            raise ValueError(f"Session not found in workspace: {session_id}")
        observation_ids = [
            str(row["id"])
            for row in connection.execute(
                "SELECT id FROM observations WHERE session_id = ? AND workspace_id = ?",
                (session_id, workspace_id),
            ).fetchall()
        ]

    for observation_id in observation_ids:
        chroma.remove_from_index(observation_id, workspace_id=workspace_id)

    observation_set = set(observation_ids)
    counts: dict[str, int] = {"vectors": len(observation_ids)}
    stale_reflection_ids: list[str] = []
    removed_community_ids: list[str] = []
    with repository_connection() as connection:
        counts["sessions"] = _rowcount(
            connection.execute(
                """
                UPDATE sessions
                SET status = 'deleted', updated_at = ?, ended_at = COALESCE(ended_at, ?)
                WHERE id = ? AND workspace_id = ?
                """,
                (now, now, session_id, workspace_id),
            )
        )
        counts["observations"] = _rowcount(
            connection.execute(
                """
                UPDATE observations
                SET content = '[deleted by user]',
                    metadata_json = ?,
                    processed_at = COALESCE(processed_at, ?)
                WHERE session_id = ? AND workspace_id = ?
                """,
                (
                    json.dumps({"deleted": True, "deleted_at": now}, sort_keys=True),
                    now,
                    session_id,
                    workspace_id,
                ),
            )
        )
        counts["slow_path_queue"] = _rowcount(
            connection.execute(
                """
                UPDATE slow_path_queue
                SET status = 'quarantined',
                    quarantine_reason = 'source session deleted',
                    updated_at = ?
                WHERE workspace_id = ?
                  AND observation_id IN (SELECT id FROM observations WHERE session_id = ?)
                  AND status IN ('pending', 'processing', 'failed')
                """,
                (now, workspace_id, session_id),
            )
        )
        counts["reflection_provenance"] = _remove_reflection_provenance(connection, observation_set)
        counts["session_working_set"] = _rowcount(
            connection.execute(
                """
                UPDATE session_working_set
                SET status = 'expired',
                    resolution_reason = 'source session deleted',
                    updated_at = ?,
                    expires_at = COALESCE(expires_at, ?)
                WHERE session_id = ? AND status NOT IN ('expired', 'rejected', 'superseded')
                """,
                (now, now, session_id),
            )
        )
        counts["atomic_facts"] = _rowcount(
            connection.execute(
                """
                UPDATE atomic_facts
                SET status = 'rejected', valid_until = COALESCE(valid_until, ?)
                WHERE workspace_id = ?
                  AND source_observation_id IN (SELECT id FROM observations WHERE session_id = ?)
                  AND status = 'active'
                """,
                (now, workspace_id, session_id),
            )
        )
        counts["foresight_records"] = _rowcount(
            connection.execute(
                """
                UPDATE foresight_records
                SET status = 'cancelled', resolved_by = 'source session deleted', updated_at = ?
                WHERE workspace_id = ?
                  AND source_observation_id IN (SELECT id FROM observations WHERE session_id = ?)
                  AND status IN ('pending', 'active')
                """,
                (now, workspace_id, session_id),
            )
        )
        stale_reflection_ids = _unsupported_reflection_ids(connection, workspace_id)
        counts["reflections"] = _mark_reflections_stale(connection, stale_reflection_ids, now)
        counts.update(_prune_graph_edge_provenance(connection, observation_set, workspace_id, now))
        unsupported_node_ids = _unsupported_source_node_ids(connection, workspace_id)
        unsupported_node_ids.update(_unsupported_entity_node_ids(connection, workspace_id))
        removed_community_ids = _community_summaries_touching_nodes(
            connection, unsupported_node_ids, workspace_id
        )
        counts["community_summaries"] = _delete_community_summaries(
            connection, removed_community_ids
        )
        counts["graph_edges_from_unsupported_nodes"] = _invalidate_graph_edges_touching_nodes(
            connection, unsupported_node_ids, workspace_id, now
        )
        counts["graph_nodes"] = _delete_graph_nodes(connection, unsupported_node_ids, workspace_id)
        counts["entities"] = _delete_orphaned_entities(connection, workspace_id)
        counts["working_memory"] = _expire_orphaned_working_memory(connection, workspace_id, now)
        should_reset_workspace_memory = _active_session_count(connection, workspace_id) == 0
    for reflection_id in stale_reflection_ids:
        chroma.remove_from_index(reflection_id, workspace_id=workspace_id)
    for community_id in removed_community_ids:
        chroma.remove_from_index(community_id, workspace_id=workspace_id)
    if should_reset_workspace_memory:
        counts["workspace_memory_reset"] = 1
        for table, count in delete_workspace_data(workspace_id).items():
            counts[f"workspace_{table}"] = count
    return counts


def _remove_reflection_provenance(connection: sqlite3.Connection, observation_ids: set[str]) -> int:
    if not observation_ids:
        return 0
    placeholders = ", ".join("?" for _ in observation_ids)
    return _rowcount(
        connection.execute(
            f"""
            DELETE FROM reflection_evidence
            WHERE observation_id IN ({placeholders})
            """,  # nosec B608
            tuple(sorted(observation_ids)),
        )
    )


def _unsupported_reflection_ids(connection: sqlite3.Connection, workspace_id: str) -> list[str]:
    rows = connection.execute(
        """
        SELECT reflections.id
        FROM reflections
        LEFT JOIN reflection_evidence
            ON reflection_evidence.reflection_id = reflections.id
        WHERE reflections.workspace_id = ? AND reflections.status = 'active'
        GROUP BY reflections.id
        HAVING COUNT(reflection_evidence.id) = 0
        """,
        (workspace_id,),
    ).fetchall()
    return [str(row["id"]) for row in rows]


def _prune_graph_edge_provenance(
    connection: sqlite3.Connection, observation_ids: set[str], workspace_id: str, now: str
) -> dict[str, int]:
    if not observation_ids:
        return {"graph_edges_pruned": 0, "graph_edges": 0}
    rows = connection.execute(
        """
        SELECT id, source_observations_json
        FROM graph_edges
        WHERE workspace_id = ? AND invalidated_at IS NULL
        """,
        (workspace_id,),
    ).fetchall()
    pruned = 0
    invalidated = 0
    for row in rows:
        source_ids = _json_string_set(row["source_observations_json"])
        if not source_ids or not source_ids.intersection(observation_ids):
            continue
        remaining_source_ids = sorted(source_ids - observation_ids)
        if remaining_source_ids:
            pruned += _rowcount(
                connection.execute(
                    "UPDATE graph_edges SET source_observations_json = ? WHERE id = ?",
                    (json.dumps(remaining_source_ids, sort_keys=True), row["id"]),
                )
            )
        else:
            invalidated += _rowcount(
                connection.execute(
                    """
                    UPDATE graph_edges
                    SET invalidated_at = ?
                    WHERE id = ? AND invalidated_at IS NULL
                    """,
                    (now, row["id"]),
                )
            )
    return {"graph_edges_pruned": pruned, "graph_edges": invalidated}


def _mark_reflections_stale(
    connection: sqlite3.Connection, reflection_ids: list[str], now: str
) -> int:
    count = 0
    for reflection_id in reflection_ids:
        count += _rowcount(
            connection.execute(
                """
                UPDATE reflections
                SET status = 'stale', stale_reason = 'source session deleted', updated_at = ?
                WHERE id = ? AND status = 'active'
                """,
                (now, reflection_id),
            )
        )
    return count


def _unsupported_source_node_ids(connection: sqlite3.Connection, workspace_id: str) -> set[str]:
    rows = connection.execute(
        """
        SELECT graph_nodes.id
        FROM graph_nodes
        LEFT JOIN atomic_facts
            ON graph_nodes.source_table = 'atomic_facts'
           AND graph_nodes.source_id = atomic_facts.id
           AND atomic_facts.workspace_id = graph_nodes.workspace_id
        LEFT JOIN reflections
            ON graph_nodes.source_table = 'reflections'
           AND graph_nodes.source_id = reflections.id
           AND reflections.workspace_id = graph_nodes.workspace_id
        LEFT JOIN foresight_records
            ON graph_nodes.source_table = 'foresight_records'
           AND graph_nodes.source_id = foresight_records.id
           AND foresight_records.workspace_id = graph_nodes.workspace_id
        WHERE graph_nodes.workspace_id = ?
          AND (
            (graph_nodes.source_table = 'atomic_facts'
             AND COALESCE(atomic_facts.status, 'missing') != 'active')
            OR
            (graph_nodes.source_table = 'reflections'
             AND COALESCE(reflections.status, 'missing') != 'active')
            OR
            (graph_nodes.source_table = 'foresight_records'
             AND COALESCE(foresight_records.status, 'missing') NOT IN ('pending', 'active'))
          )
        """,
        (workspace_id,),
    ).fetchall()
    return {str(row["id"]) for row in rows}


def _unsupported_entity_node_ids(connection: sqlite3.Connection, workspace_id: str) -> set[str]:
    rows = connection.execute(
        """
        SELECT graph_nodes.id
        FROM graph_nodes
        LEFT JOIN graph_edges
          ON graph_edges.workspace_id = graph_nodes.workspace_id
         AND graph_edges.invalidated_at IS NULL
         AND (
            graph_edges.source_node_id = graph_nodes.id
            OR graph_edges.target_node_id = graph_nodes.id
         )
        WHERE graph_nodes.workspace_id = ?
          AND graph_nodes.source_table = 'entities'
        GROUP BY graph_nodes.id
        HAVING COUNT(graph_edges.id) = 0
        """,
        (workspace_id,),
    ).fetchall()
    return {str(row["id"]) for row in rows}


def _community_summaries_touching_nodes(
    connection: sqlite3.Connection, node_ids: set[str], workspace_id: str
) -> list[str]:
    if not node_ids:
        return []
    rows = connection.execute(
        "SELECT id, member_nodes_json FROM community_summaries WHERE workspace_id = ?",
        (workspace_id,),
    ).fetchall()
    return [
        str(row["id"])
        for row in rows
        if _json_string_set(row["member_nodes_json"]).intersection(node_ids)
    ]


def _delete_community_summaries(connection: sqlite3.Connection, community_ids: list[str]) -> int:
    if not community_ids:
        return 0
    placeholders = ", ".join("?" for _ in community_ids)
    return _rowcount(
        connection.execute(
            f"DELETE FROM community_summaries WHERE id IN ({placeholders})",  # nosec B608
            tuple(sorted(community_ids)),
        )
    )


def _invalidate_graph_edges_touching_nodes(
    connection: sqlite3.Connection, node_ids: set[str], workspace_id: str, now: str
) -> int:
    if not node_ids:
        return 0
    placeholders = ", ".join("?" for _ in node_ids)
    parameters = (now, workspace_id, *sorted(node_ids), *sorted(node_ids))
    return _rowcount(
        connection.execute(
            f"""
            UPDATE graph_edges
            SET invalidated_at = ?
            WHERE workspace_id = ?
              AND invalidated_at IS NULL
              AND (
                source_node_id IN ({placeholders})
                OR target_node_id IN ({placeholders})
              )
            """,  # nosec B608
            parameters,
        )
    )


def _delete_graph_nodes(
    connection: sqlite3.Connection, node_ids: set[str], workspace_id: str
) -> int:
    if not node_ids:
        return 0
    placeholders = ", ".join("?" for _ in node_ids)
    connection.execute(
        f"""
        DELETE FROM graph_edges
        WHERE workspace_id = ?
          AND (
            source_node_id IN ({placeholders})
            OR target_node_id IN ({placeholders})
          )
        """,  # nosec B608
        (workspace_id, *sorted(node_ids), *sorted(node_ids)),
    )
    return _rowcount(
        connection.execute(
            f"""
            DELETE FROM graph_nodes
            WHERE workspace_id = ? AND id IN ({placeholders})
            """,  # nosec B608
            (workspace_id, *sorted(node_ids)),
        )
    )


def _delete_orphaned_entities(connection: sqlite3.Connection, workspace_id: str) -> int:
    return _rowcount(
        connection.execute(
            """
            DELETE FROM entities
            WHERE workspace_id = ?
              AND id NOT IN (
                SELECT source_id FROM graph_nodes
                WHERE workspace_id = ?
                  AND source_table = 'entities'
                  AND source_id IS NOT NULL
              )
            """,
            (workspace_id, workspace_id),
        )
    )


def _expire_orphaned_working_memory(
    connection: sqlite3.Connection, workspace_id: str, now: str
) -> int:
    return _rowcount(
        connection.execute(
            """
            UPDATE working_memory
            SET status = 'expired', updated_at = ?
            WHERE workspace_id = ? AND status = 'active'
              AND (
                (source_record_type = 'atomic_fact'
                 AND source_record_id IN (
                    SELECT id FROM atomic_facts
                    WHERE workspace_id = ? AND status IN ('rejected', 'expired')
                 ))
                OR
                (source_record_type = 'session_working_set'
                 AND source_record_id IN (
                    SELECT id FROM session_working_set
                    WHERE status IN ('expired', 'rejected', 'superseded')
                 ))
              )
            """,
            (now, workspace_id, workspace_id),
        )
    )


def _active_session_count(connection: sqlite3.Connection, workspace_id: str) -> int:
    row = connection.execute(
        "SELECT COUNT(*) AS count FROM sessions WHERE workspace_id = ? AND status != 'deleted'",
        (workspace_id,),
    ).fetchone()
    return int(row["count"]) if row is not None else 0


def _json_string_set(value: object) -> set[str]:
    if not isinstance(value, str):
        return set()
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return set()
    if not isinstance(decoded, list):
        return set()
    return {str(item) for item in decoded if item is not None}


def _rowcount(cursor: sqlite3.Cursor) -> int:
    return max(int(cursor.rowcount), 0)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()  # noqa: UP017
