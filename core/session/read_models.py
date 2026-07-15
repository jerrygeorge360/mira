"""Read models for Session Working Set inspection surfaces."""

from __future__ import annotations

import json
import sqlite3

from core.context.budget import estimate_tokens
from core.db.repositories import repository_connection
from core.db.schema import LEGACY_WORKSPACE_ID

SessionRecord = dict[str, object]

ACTIVE_STATUSES = frozenset({"provisional", "hydrated", "confirmed"})
DURABLE_SCOPES = frozenset({"project", "cross_session"})


def list_session_working_set_read_model(
    session_id: str,
    *,
    workspace_id: str = LEGACY_WORKSPACE_ID,
) -> list[SessionRecord]:
    """Return enriched Session Working Set items for UI inspection."""
    with repository_connection() as connection:
        rows = connection.execute(
            """
            SELECT session_working_set.*
            FROM session_working_set
            JOIN sessions ON sessions.id = session_working_set.session_id
            WHERE session_working_set.session_id = ? AND sessions.workspace_id = ?
            ORDER BY
                CASE session_working_set.status
                    WHEN 'confirmed' THEN 0
                    WHEN 'hydrated' THEN 1
                    WHEN 'provisional' THEN 2
                    ELSE 3
                END,
                session_working_set.priority DESC,
                session_working_set.updated_at DESC
            """,
            (session_id, workspace_id),
        ).fetchall()
        items = [_row_to_record(row) for row in rows]
        if not items:
            return []
        observations = _observations_by_id(connection, session_id, workspace_id)
        usage = _usage_by_item_id(connection, session_id, workspace_id)
        durable = _durable_by_source_item_id(connection, workspace_id)
        superseded = _items_by_id(connection, [item_id for item in items for item_id in _ids(item)])

    return [
        _enrich_item(
            item,
            observations=observations,
            usage=usage,
            durable=durable,
            superseded=superseded,
        )
        for item in items
    ]


def active_session_items(items: list[SessionRecord]) -> list[SessionRecord]:
    """Return prompt-active working-set items from an enriched item list."""
    return [item for item in items if str(item.get("status")) in ACTIVE_STATUSES]


def _enrich_item(
    item: SessionRecord,
    *,
    observations: dict[str, SessionRecord],
    usage: dict[str, list[SessionRecord]],
    durable: dict[str, list[SessionRecord]],
    superseded: dict[str, SessionRecord],
) -> SessionRecord:
    item_id = str(item["id"])
    content = str(item.get("content") or "")
    source_ids = _json_list(item.get("source_observations_json"))
    supersedes_ids = _json_list(item.get("supersedes_json"))
    used_in = usage.get(item_id, [])
    durable_records = durable.get(item_id, [])
    enriched = dict(item)
    enriched["source_observations"] = source_ids
    enriched["source_messages"] = [
        observations[source_id] for source_id in source_ids if source_id in observations
    ]
    enriched["supersedes"] = supersedes_ids
    enriched["superseded_items"] = [
        superseded[item_id] for item_id in supersedes_ids if item_id in superseded
    ]
    enriched["usage_count"] = len(used_in)
    enriched["used_in_responses"] = used_in
    enriched["token_cost"] = estimate_tokens(content)
    enriched["durable_memory"] = durable_records
    enriched["promotion_status"] = _promotion_status(enriched, durable_records)
    enriched["active"] = str(item.get("status")) in ACTIVE_STATUSES
    return enriched


def _observations_by_id(
    connection: sqlite3.Connection, session_id: str, workspace_id: str
) -> dict[str, SessionRecord]:
    rows = connection.execute(
        """
        SELECT id, role, content, created_at
        FROM observations
        WHERE session_id = ? AND workspace_id = ?
        ORDER BY created_at ASC
        """,
        (session_id, workspace_id),
    ).fetchall()
    observations: dict[str, SessionRecord] = {}
    for index, row in enumerate(rows, start=1):
        record = _row_to_record(row)
        record["message_index"] = index
        observations[str(record["id"])] = record
    return observations


def _usage_by_item_id(
    connection: sqlite3.Connection, session_id: str, workspace_id: str
) -> dict[str, list[SessionRecord]]:
    rows = connection.execute(
        """
        SELECT id, user_observation_id, assistant_observation_id, created_at, session_item_ids_json
        FROM answer_traces
        WHERE session_id = ? AND workspace_id = ?
        ORDER BY created_at DESC
        """,
        (session_id, workspace_id),
    ).fetchall()
    usage: dict[str, list[SessionRecord]] = {}
    for row in rows:
        record = _row_to_record(row)
        trace = {
            "trace_id": record["id"],
            "user_observation_id": record["user_observation_id"],
            "assistant_observation_id": record["assistant_observation_id"],
            "created_at": record["created_at"],
        }
        for item_id in _json_list(record.get("session_item_ids_json")):
            usage.setdefault(item_id, []).append(trace)
    return usage


def _durable_by_source_item_id(
    connection: sqlite3.Connection, workspace_id: str
) -> dict[str, list[SessionRecord]]:
    rows = connection.execute(
        """
        SELECT
            id, content, memory_type, scope, priority, status,
            source_record_id, created_at, updated_at
        FROM working_memory
        WHERE workspace_id = ? AND source_record_type = 'session_working_set'
        ORDER BY updated_at DESC
        """,
        (workspace_id,),
    ).fetchall()
    durable: dict[str, list[SessionRecord]] = {}
    for row in rows:
        record = _row_to_record(row)
        durable.setdefault(str(record["source_record_id"]), []).append(record)
    return durable


def _items_by_id(connection: sqlite3.Connection, item_ids: list[str]) -> dict[str, SessionRecord]:
    if not item_ids:
        return {}
    placeholders = ", ".join("?" for _ in item_ids)
    rows = connection.execute(
        f"""
        SELECT
            id, type, content, scope, status, priority,
            explicitness_label, created_at, updated_at
        FROM session_working_set
        WHERE id IN ({placeholders})
        """,  # nosec B608
        tuple(item_ids),
    ).fetchall()
    return {str(row["id"]): _row_to_record(row) for row in rows}


def _promotion_status(item: SessionRecord, durable_records: list[SessionRecord]) -> str:
    if durable_records:
        return "promoted"
    if str(item.get("status")) == "confirmed" and str(item.get("scope")) in DURABLE_SCOPES:
        return "eligible"
    if str(item.get("status")) == "provisional" and str(item.get("scope")) in DURABLE_SCOPES:
        return "pending_confirmation"
    return "session_only"


def _ids(item: SessionRecord) -> list[str]:
    return _json_list(item.get("supersedes_json"))


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


def _row_to_record(row: sqlite3.Row) -> SessionRecord:
    record: SessionRecord = {}
    for key in tuple(row.keys()):
        value = row[key]
        if key.endswith("_json") and value is not None:
            record[key] = _json_value(value)
        else:
            record[key] = value
    return record


def _json_value(value: object) -> object:
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return value
