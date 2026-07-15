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
from core.memory.tiers import HOT_TIER_MAX

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
    """Return community summaries with overlap/review annotations."""
    rows = _fetch_all(
        "SELECT * FROM community_summaries WHERE workspace_id = ? ORDER BY created_at DESC LIMIT ?",
        (workspace_id, limit),
    )
    return _annotate_community_overlap(rows)


def list_memory_lifecycle_read_model(
    session_id: str | None = None,
    limit: int = 20,
    *,
    workspace_id: str = LEGACY_WORKSPACE_ID,
) -> list[MemoryRecord]:
    """Return recent observations with fast-path and slow-path lifecycle evidence."""
    if limit < 1:
        raise ValueError("limit must be a positive integer")

    where = "WHERE observations.workspace_id = ?"
    params: list[object] = [workspace_id]
    if session_id:
        where += " AND observations.session_id = ?"
        params.append(session_id)

    rows = _fetch_all(
        f"""
        SELECT
            observations.id,
            observations.session_id,
            observations.role,
            observations.content,
            observations.source,
            observations.created_at,
            observations.processed_at,
            slow_path_queue.id AS queue_id,
            slow_path_queue.status AS queue_status,
            slow_path_queue.attempt_count AS queue_attempt_count,
            slow_path_queue.last_error AS queue_last_error,
            slow_path_queue.quarantine_reason AS queue_quarantine_reason,
            slow_path_queue.created_at AS queue_created_at,
            slow_path_queue.updated_at AS queue_updated_at
        FROM observations
        LEFT JOIN slow_path_queue
            ON slow_path_queue.observation_id = observations.id
           AND slow_path_queue.workspace_id = observations.workspace_id
        {where}
        ORDER BY observations.created_at DESC
        LIMIT ?
        """,  # nosec B608
        (*params, limit),
    )
    if not rows:
        return []

    observation_ids = [str(row["id"]) for row in rows]
    steps_by_observation = _slow_path_steps_by_observation(observation_ids, workspace_id)
    session_items_by_observation = _session_items_by_observation(observation_ids, workspace_id)
    artifact_counts_by_observation = _artifact_counts_by_observation(observation_ids, workspace_id)

    lifecycle: list[MemoryRecord] = []
    for row in rows:
        observation_id = str(row["id"])
        session_items = session_items_by_observation.get(observation_id, [])
        artifacts = artifact_counts_by_observation.get(observation_id, {})
        lifecycle.append(
            {
                "observation": {
                    "id": observation_id,
                    "session_id": row["session_id"],
                    "role": row["role"],
                    "source": row["source"],
                    "content": row["content"],
                    "created_at": row["created_at"],
                    "processed_at": row["processed_at"],
                },
                "fast_path": {
                    "status": "completed",
                    "persisted_at": row["created_at"],
                    "queued": bool(row.get("queue_id")),
                },
                "session_extraction": {
                    "status": _session_extraction_status(session_items),
                    "counts": _count_by_key(session_items, "type"),
                    "items": session_items,
                },
                "slow_path": {
                    "queue": {
                        "id": row.get("queue_id"),
                        "status": row.get("queue_status") or "not_queued",
                        "attempt_count": row.get("queue_attempt_count") or 0,
                        "last_error": row.get("queue_last_error"),
                        "quarantine_reason": row.get("queue_quarantine_reason"),
                        "created_at": row.get("queue_created_at"),
                        "updated_at": row.get("queue_updated_at"),
                    },
                    "steps": steps_by_observation.get(observation_id, []),
                    "status": _slow_path_status(row, steps_by_observation.get(observation_id, [])),
                },
                "artifacts": _artifact_counts(artifacts),
                "artifact_ids": artifacts,
                "rejections": _rejections(row, steps_by_observation.get(observation_id, [])),
            }
        )
    return lifecycle


def get_memory_health_read_model(*, workspace_id: str = LEGACY_WORKSPACE_ID) -> MemoryRecord:
    """Return persisted memory tier counts and retention state.

    This view only reports signals the current architecture records. It does not
    invent decay, access-reinforcement, or summarization events.
    """
    with repository_connection() as connection:
        hot_statuses = _status_counts(
            connection,
            "SELECT status, COUNT(*) AS count FROM working_memory "
            "WHERE workspace_id = ? GROUP BY status",
            (workspace_id,),
        )
        session_statuses = _status_counts(
            connection,
            """
            SELECT session_working_set.status, COUNT(*) AS count
            FROM session_working_set
            JOIN sessions ON sessions.id = session_working_set.session_id
            WHERE sessions.workspace_id = ?
            GROUP BY session_working_set.status
            """,
            (workspace_id,),
        )
        reflection_statuses = _status_counts(
            connection,
            "SELECT status, COUNT(*) AS count FROM reflections "
            "WHERE workspace_id = ? GROUP BY status",
            (workspace_id,),
        )
        foresight_statuses = _status_counts(
            connection,
            "SELECT status, COUNT(*) AS count FROM foresight_records "
            "WHERE workspace_id = ? GROUP BY status",
            (workspace_id,),
        )
        durable_counts = {
            "observations": _scalar_count(
                connection,
                "SELECT COUNT(*) FROM observations WHERE workspace_id = ?",
                (workspace_id,),
            ),
            "atomic_facts": _scalar_count(
                connection,
                "SELECT COUNT(*) FROM atomic_facts WHERE workspace_id = ?",
                (workspace_id,),
            ),
            "graph_nodes": _scalar_count(
                connection,
                "SELECT COUNT(*) FROM graph_nodes WHERE workspace_id = ?",
                (workspace_id,),
            ),
            "graph_edges": _scalar_count(
                connection,
                "SELECT COUNT(*) FROM graph_edges WHERE workspace_id = ?",
                (workspace_id,),
            ),
        }
        warm_components = {
            "active_reflections": reflection_statuses.get("active", 0),
            "community_summaries": _scalar_count(
                connection,
                "SELECT COUNT(*) FROM community_summaries WHERE workspace_id = ?",
                (workspace_id,),
            ),
        }
        recent_movements = _recent_memory_movements(connection, workspace_id, limit=10)

    hot_active = hot_statuses.get("active", 0)
    session_active = sum(
        session_statuses.get(status, 0) for status in ("provisional", "hydrated", "confirmed")
    )
    session_terminal = sum(
        session_statuses.get(status, 0)
        for status in ("resolved", "expired", "rejected", "superseded")
    )
    cold_count = sum(durable_counts.values())
    warm_count = sum(warm_components.values())
    foresight_count = sum(foresight_statuses.values())

    return {
        "workspace_id": workspace_id,
        "tiers": {
            "hot": {
                "label": "Hot memory",
                "count": hot_active,
                "capacity": HOT_TIER_MAX,
                "pressure": round(hot_active / HOT_TIER_MAX, 3) if HOT_TIER_MAX else 0.0,
                "statuses": hot_statuses,
                "description": (
                    "Active working_memory rows eligible to compete for prompt injection."
                ),
            },
            "warm": {
                "label": "Warm patterns",
                "count": warm_count,
                "components": warm_components,
                "statuses": {"reflections": reflection_statuses},
                "description": (
                    "Reusable reflection and community summaries kept for retrieval context."
                ),
            },
            "cold": {
                "label": "Cold durable store",
                "count": cold_count,
                "components": durable_counts,
                "description": (
                    "Persisted observations, facts, and graph records retained outside the prompt."
                ),
            },
            "time_bound": {
                "label": "Time-bound foresight",
                "count": foresight_count,
                "statuses": foresight_statuses,
                "description": "Foresight records with their persisted lifecycle status.",
            },
        },
        "working_set": {
            "active_count": session_active,
            "terminal_count": session_terminal,
            "statuses": session_statuses,
            "pressure_note": (
                "No hard Session Working Set cap is configured; prompt assembly and hot-tier "
                "promotion decide what competes for context."
            ),
        },
        "retention": {
            "hot_capacity": HOT_TIER_MAX,
            "hot_pressure": round(hot_active / HOT_TIER_MAX, 3) if HOT_TIER_MAX else 0.0,
            "forgetting_signals": {
                "demoted_hot": hot_statuses.get("demoted", 0),
                "expired_hot": hot_statuses.get("expired", 0),
                "superseded_hot": hot_statuses.get("superseded", 0),
                "resolved_session_items": session_statuses.get("resolved", 0),
                "expired_session_items": session_statuses.get("expired", 0),
                "rejected_session_items": session_statuses.get("rejected", 0),
                "superseded_session_items": session_statuses.get("superseded", 0),
                "stale_reflections": reflection_statuses.get("stale", 0),
                "invalidated_reflections": reflection_statuses.get("invalidated", 0),
                "superseded_reflections": reflection_statuses.get("superseded", 0),
                "resolved_foresight": foresight_statuses.get("resolved", 0),
                "expired_foresight": foresight_statuses.get("expired", 0),
                "cancelled_foresight": foresight_statuses.get("cancelled", 0),
            },
        },
        "recent_movements": recent_movements,
        "instrumentation": {
            "persisted": [
                "hot memory capacity and statuses",
                "Session Working Set statuses",
                "reflection statuses",
                "foresight statuses",
                "durable observations, atomic facts, graph nodes, and graph edges",
            ],
            "not_persisted_yet": [
                "per-record decay factors",
                "retrieval access reinforcement",
                "recursive summarization events",
                "warm-to-cold archival movement history",
            ],
        },
    }


def _fetch_all(query: str, params: Iterable[object]) -> list[MemoryRecord]:
    with repository_connection() as connection:
        rows = connection.execute(query, tuple(params)).fetchall()
    return [_row_to_record(row) for row in rows]


def _scalar_count(connection: sqlite3.Connection, query: str, params: Iterable[object]) -> int:
    return int(connection.execute(query, tuple(params)).fetchone()[0])


def _status_counts(
    connection: sqlite3.Connection, query: str, params: Iterable[object]
) -> dict[str, int]:
    return {
        str(row["status"]): int(row["count"])
        for row in connection.execute(query, tuple(params)).fetchall()
    }


def _recent_memory_movements(
    connection: sqlite3.Connection, workspace_id: str, limit: int
) -> list[MemoryRecord]:
    movements: list[MemoryRecord] = []
    for row in connection.execute(
        """
        SELECT id, content, status, source_record_type, source_record_id, updated_at
        FROM working_memory
        WHERE workspace_id = ? AND status != ?
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (workspace_id, "active", limit),
    ).fetchall():
        movements.append(
            {
                "source": "working_memory",
                "id": row["id"],
                "title": row["content"],
                "from": "hot",
                "to": str(row["status"]),
                "reason": _movement_reason("working_memory", str(row["status"])),
                "updated_at": row["updated_at"],
                "source_record_type": row["source_record_type"],
                "source_record_id": row["source_record_id"],
            }
        )

    for row in connection.execute(
        """
        SELECT session_working_set.id, session_working_set.content, session_working_set.status,
               session_working_set.resolution_reason, session_working_set.updated_at
        FROM session_working_set
        JOIN sessions ON sessions.id = session_working_set.session_id
        WHERE sessions.workspace_id = ?
          AND session_working_set.status IN (?, ?, ?, ?)
        ORDER BY session_working_set.updated_at DESC
        LIMIT ?
        """,
        (workspace_id, "resolved", "expired", "rejected", "superseded", limit),
    ).fetchall():
        movements.append(
            {
                "source": "session_working_set",
                "id": row["id"],
                "title": row["content"],
                "from": "session working set",
                "to": str(row["status"]),
                "reason": row["resolution_reason"]
                or _movement_reason("session_working_set", str(row["status"])),
                "updated_at": row["updated_at"],
            }
        )

    for row in connection.execute(
        """
        SELECT id, content, status, stale_reason, updated_at
        FROM reflections
        WHERE workspace_id = ? AND status != ?
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (workspace_id, "active", limit),
    ).fetchall():
        movements.append(
            {
                "source": "reflections",
                "id": row["id"],
                "title": row["content"],
                "from": "warm reflection",
                "to": str(row["status"]),
                "reason": row["stale_reason"]
                or _movement_reason("reflections", str(row["status"])),
                "updated_at": row["updated_at"],
            }
        )

    for row in connection.execute(
        """
        SELECT id, content, status, resolved_by, updated_at
        FROM foresight_records
        WHERE workspace_id = ? AND status IN (?, ?, ?)
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (workspace_id, "resolved", "expired", "cancelled", limit),
    ).fetchall():
        movements.append(
            {
                "source": "foresight_records",
                "id": row["id"],
                "title": row["content"],
                "from": "time-bound foresight",
                "to": str(row["status"]),
                "reason": row["resolved_by"]
                or _movement_reason("foresight_records", str(row["status"])),
                "updated_at": row["updated_at"],
            }
        )

    return sorted(movements, key=lambda item: str(item.get("updated_at") or ""), reverse=True)[
        :limit
    ]


def _movement_reason(source: str, status: str) -> str:
    reasons = {
        ("working_memory", "demoted"): "No longer eligible for hot prompt injection.",
        ("working_memory", "expired"): "Source validity expired.",
        ("working_memory", "superseded"): "A newer memory replaced this item.",
        ("session_working_set", "resolved"): "Session item was resolved.",
        ("session_working_set", "expired"): "Session item passed its validity window.",
        ("session_working_set", "rejected"): "Session extraction rejected the item.",
        ("session_working_set", "superseded"): "A newer session item superseded this one.",
        ("reflections", "stale"): "Reflection was marked stale.",
        ("reflections", "invalidated"): "Reflection was invalidated by newer evidence.",
        ("reflections", "superseded"): "Reflection was replaced by a newer synthesis.",
        ("foresight_records", "resolved"): "Foresight item was resolved.",
        ("foresight_records", "expired"): "Foresight item expired.",
        ("foresight_records", "cancelled"): "Foresight item was cancelled.",
    }
    return reasons.get((source, status), f"Stored status changed to {status}.")


def _annotate_community_overlap(rows: list[MemoryRecord]) -> list[MemoryRecord]:
    annotated: list[MemoryRecord] = []
    member_sets = {
        str(row["id"]): set(_json_list(row.get("member_nodes_json")))
        for row in rows
        if row.get("id") is not None
    }
    titles = {str(row["id"]): _title_tokens(str(row.get("title") or "")) for row in rows}
    for row in rows:
        row_id = str(row.get("id") or "")
        members = member_sets.get(row_id, set())
        overlaps: list[MemoryRecord] = []
        for other in rows:
            other_id = str(other.get("id") or "")
            if not row_id or other_id == row_id:
                continue
            other_members = member_sets.get(other_id, set())
            shared = members & other_members
            member_overlap = _overlap_ratio(members, other_members)
            title_overlap = _overlap_ratio(titles.get(row_id, set()), titles.get(other_id, set()))
            if shared or title_overlap >= 0.6:
                overlaps.append(
                    {
                        "id": other_id,
                        "community_id": other.get("community_id"),
                        "title": other.get("title"),
                        "shared_member_count": len(shared),
                        "member_overlap_ratio": round(member_overlap, 3),
                        "title_overlap_ratio": round(title_overlap, 3),
                    }
                )
        strongest_overlap = max(
            (_number(record["member_overlap_ratio"]) for record in overlaps),
            default=0.0,
        )
        title_duplicate = any(_number(record["title_overlap_ratio"]) >= 0.8 for record in overlaps)
        recommendation = (
            "review_possible_duplicate"
            if strongest_overlap >= 0.5 or title_duplicate
            else "preserve_for_context"
        )
        enriched = dict(row)
        enriched["member_count"] = len(members)
        enriched["cohesion_score"] = _cohesion_score(members, strongest_overlap)
        enriched["overlapping_communities"] = sorted(
            overlaps,
            key=lambda record: (
                -_number(record["member_overlap_ratio"]),
                -_number(record["title_overlap_ratio"]),
                str(record.get("title") or ""),
            ),
        )[:5]
        enriched["merge_recommendation"] = recommendation
        enriched["community_explanation"] = (
            "These memories share graph edges and are cached as a warm retrieval context."
            if recommendation == "preserve_for_context"
            else (
                "This community overlaps another summary; review whether both support "
                "distinct retrieval contexts."
            )
        )
        annotated.append(enriched)
    return annotated


def _overlap_ratio(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _number(value: object) -> float:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _cohesion_score(members: set[str], strongest_overlap: float) -> float:
    if not members:
        return 0.0
    size_signal = min(1.0, len(members) / 8)
    distinctness = 1.0 - min(1.0, strongest_overlap)
    return round((0.7 * size_signal) + (0.3 * distinctness), 3)


def _title_tokens(title: str) -> set[str]:
    stopwords = {"and", "or", "the", "a", "an", "for", "of", "to", "in"}
    return {
        token
        for token in title.casefold().replace("-", " ").split()
        if len(token) > 2 and token not in stopwords
    }


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


def _slow_path_steps_by_observation(
    observation_ids: list[str], workspace_id: str
) -> dict[str, list[MemoryRecord]]:
    rows = _fetch_by_observation_ids(
        """
        SELECT observation_id, step_name, status, last_error, created_at, updated_at
        FROM slow_path_step_journal
        WHERE workspace_id = ? AND observation_id IN ({placeholders})
        ORDER BY created_at ASC
        """,
        observation_ids,
        workspace_id,
    )
    grouped: dict[str, list[MemoryRecord]] = {}
    for row in rows:
        grouped.setdefault(str(row["observation_id"]), []).append(row)
    return grouped


def _session_items_by_observation(
    observation_ids: list[str], workspace_id: str
) -> dict[str, list[MemoryRecord]]:
    rows = _fetch_all(
        """
        SELECT session_working_set.*
        FROM session_working_set
        JOIN sessions ON sessions.id = session_working_set.session_id
        WHERE sessions.workspace_id = ?
        ORDER BY session_working_set.created_at ASC
        """,
        (workspace_id,),
    )
    grouped: dict[str, list[MemoryRecord]] = {
        observation_id: [] for observation_id in observation_ids
    }
    known_ids = set(observation_ids)
    for row in rows:
        for source_id in _json_list(row.get("source_observations_json")):
            if source_id in known_ids:
                grouped[source_id].append(row)
    return grouped


def _artifact_counts_by_observation(
    observation_ids: list[str], workspace_id: str
) -> dict[str, dict[str, list[str]]]:
    artifacts: dict[str, dict[str, list[str]]] = {
        observation_id: {
            "atomic_facts": [],
            "entities": [],
            "graph_edges": [],
            "foresight_records": [],
            "reflections": [],
            "working_memory": [],
        }
        for observation_id in observation_ids
    }
    known_ids = set(observation_ids)

    for row in _fetch_by_observation_ids(
        """
        SELECT id, source_observation_id AS observation_id
        FROM atomic_facts
        WHERE workspace_id = ? AND source_observation_id IN ({placeholders})
        """,
        observation_ids,
        workspace_id,
    ):
        artifacts[str(row["observation_id"])]["atomic_facts"].append(str(row["id"]))

    for row in _fetch_all(
        "SELECT id, source_observations_json FROM graph_edges WHERE workspace_id = ?",
        (workspace_id,),
    ):
        for source_id in _json_list(row.get("source_observations_json")):
            if source_id in known_ids:
                artifacts[source_id]["graph_edges"].append(str(row["id"]))

    for row in _fetch_all(
        """
        SELECT graph_edges.source_observations_json, graph_nodes.source_id AS entity_id
        FROM graph_edges
        JOIN graph_nodes ON graph_nodes.id = graph_edges.target_node_id
        WHERE graph_edges.workspace_id = ?
          AND graph_edges.edge_type = 'MENTIONS'
          AND graph_nodes.source_table = 'entities'
          AND graph_nodes.source_id IS NOT NULL
        """,
        (workspace_id,),
    ):
        for source_id in _json_list(row.get("source_observations_json")):
            entity_id = row.get("entity_id")
            if source_id in known_ids and entity_id:
                artifacts[source_id]["entities"].append(str(entity_id))

    for row in _fetch_by_observation_ids(
        """
        SELECT id, source_observation_id AS observation_id
        FROM foresight_records
        WHERE workspace_id = ? AND source_observation_id IN ({placeholders})
        """,
        observation_ids,
        workspace_id,
    ):
        artifacts[str(row["observation_id"])]["foresight_records"].append(str(row["id"]))

    for row in _fetch_by_observation_ids(
        """
        SELECT reflections.id, reflection_evidence.observation_id
        FROM reflection_evidence
        JOIN reflections ON reflections.id = reflection_evidence.reflection_id
        WHERE reflections.workspace_id = ?
          AND reflection_evidence.observation_id IN ({placeholders})
        """,
        observation_ids,
        workspace_id,
    ):
        artifacts[str(row["observation_id"])]["reflections"].append(str(row["id"]))

    session_items_by_observation = _session_items_by_observation(observation_ids, workspace_id)
    session_item_ids_by_observation = {
        observation_id: [str(item["id"]) for item in items]
        for observation_id, items in session_items_by_observation.items()
    }
    fact_ids_by_observation = {
        observation_id: set(ids["atomic_facts"]) for observation_id, ids in artifacts.items()
    }
    session_item_ids = {
        item_id for item_ids in session_item_ids_by_observation.values() for item_id in item_ids
    }
    fact_ids = {fact_id for item_ids in fact_ids_by_observation.values() for fact_id in item_ids}
    for row in _fetch_all(
        """
        SELECT id, source_record_type, source_record_id
        FROM working_memory
        WHERE workspace_id = ?
        """,
        (workspace_id,),
    ):
        source_type = str(row.get("source_record_type") or "")
        source_id = str(row.get("source_record_id") or "")
        for observation_id in observation_ids:
            if (
                source_type == "session_working_set"
                and source_id in session_item_ids
                and source_id in session_item_ids_by_observation[observation_id]
            ):
                artifacts[observation_id]["working_memory"].append(str(row["id"]))
            if (
                source_type == "atomic_facts"
                and source_id in fact_ids
                and source_id in fact_ids_by_observation[observation_id]
            ):
                artifacts[observation_id]["working_memory"].append(str(row["id"]))

    return {
        observation_id: {key: sorted(set(value)) for key, value in counts.items()}
        for observation_id, counts in artifacts.items()
    }


def _fetch_by_observation_ids(
    query_template: str, observation_ids: list[str], workspace_id: str
) -> list[MemoryRecord]:
    if not observation_ids:
        return []
    placeholders = ", ".join("?" for _ in observation_ids)
    query = query_template.format(placeholders=placeholders)
    return _fetch_all(query, (workspace_id, *observation_ids))


def _count_by_key(records: list[MemoryRecord], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        value = str(record.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _artifact_counts(artifacts: dict[str, list[str]]) -> dict[str, int]:
    return {key: len(set(value)) for key, value in artifacts.items()}


def _session_extraction_status(session_items: list[MemoryRecord]) -> str:
    if not session_items:
        return "no_session_items"
    if any(str(item.get("status")) == "rejected" for item in session_items):
        return "has_rejections"
    return "completed"


def _slow_path_status(row: MemoryRecord, steps: list[MemoryRecord]) -> str:
    queue_status = str(row.get("queue_status") or "")
    if queue_status in {"failed", "dead_letter", "quarantined"}:
        return queue_status
    if any(str(step.get("status")) == "failed" for step in steps):
        return "step_failed"
    if row.get("processed_at"):
        return "completed"
    if queue_status:
        return queue_status
    return "not_queued"


def _rejections(row: MemoryRecord, steps: list[MemoryRecord]) -> list[MemoryRecord]:
    rejected: list[MemoryRecord] = []
    if row.get("queue_last_error") or row.get("queue_quarantine_reason"):
        rejected.append(
            {
                "stage": "slow_path_queue",
                "reason": row.get("queue_last_error") or row.get("queue_quarantine_reason"),
            }
        )
    for step in steps:
        if step.get("last_error"):
            rejected.append(
                {
                    "stage": step.get("step_name"),
                    "reason": step.get("last_error"),
                }
            )
    return rejected


def _json_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    if not isinstance(value, str) or not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, list):
        return [str(item) for item in parsed if item is not None]
    return []
