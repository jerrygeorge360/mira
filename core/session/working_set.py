"""Temporary Session Working Set store, separate from durable memory tiers.

Ownership: Jerry.
Related issue: ISSUE-010.
Architecture area: session micro-path.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone

from core.db.repositories import repository_connection, validate_enum_value

SessionItem = dict[str, object]

PROMPT_STATUSES = frozenset({"active", "confirmed", "hydrated", "provisional"})
TERMINAL_STATUSES = frozenset({"resolved", "expired", "rejected", "superseded"})
JSON_FIELDS = frozenset({"source_observations_json", "supersedes_json"})

STATUS_RANK = {
    "active": 0,
    "confirmed": 1,
    "hydrated": 2,
    "provisional": 3,
}
TYPE_RANK = {
    "correction": 0,
    "active_constraint": 1,
    "current_goal": 2,
    "open_question": 3,
    "decision": 4,
    "resolution": 5,
}
SCOPE_RANK = {
    "current_response": 0,
    "current_task": 1,
    "current_session": 2,
    "project": 3,
    "cross_session": 4,
}


def upsert_session_item(session_id: str, item: SessionItem) -> str:
    """Insert or update a temporary Session Working Set item."""
    record = _to_database_record(session_id, item)
    item_id = str(record.setdefault("id", _new_id()))
    now = _now()
    record.setdefault("status", "provisional")
    record.setdefault("priority", 0.0)
    record.setdefault("origin", "micro_path")
    record.setdefault("source_observations_json", [])
    record.setdefault("supersedes_json", [])
    record.setdefault("created_at", now)
    record["updated_at"] = now
    _validate_item_record(record)

    with repository_connection() as connection:
        existing = connection.execute(
            "SELECT id FROM session_working_set WHERE id = ? AND session_id = ?",
            (item_id, session_id),
        ).fetchone()
        if existing is None:
            _insert_item(connection, record)
        else:
            _update_item(connection, record)
    return item_id


def supersede_session_item(session_id: str, item_id: str, superseded_by: str) -> None:
    """Mark a session item as superseded and link it to its replacement."""
    now = _now()
    with repository_connection() as connection:
        _ensure_item_exists(connection, session_id, item_id)
        _ensure_item_exists(connection, session_id, superseded_by)
        connection.execute(
            """
            UPDATE session_working_set
            SET status = ?, updated_at = ?, resolution_reason = ?
            WHERE id = ? AND session_id = ?
            """,
            ("superseded", now, f"superseded_by:{superseded_by}", item_id, session_id),
        )
        replacement = connection.execute(
            """
            SELECT supersedes_json FROM session_working_set
            WHERE id = ? AND session_id = ?
            """,
            (superseded_by, session_id),
        ).fetchone()
        supersedes = _json_list(replacement["supersedes_json"])
        if item_id not in supersedes:
            supersedes.append(item_id)
        connection.execute(
            """
            UPDATE session_working_set
            SET supersedes_json = ?, updated_at = ?
            WHERE id = ? AND session_id = ?
            """,
            (json.dumps(supersedes, sort_keys=True), now, superseded_by, session_id),
        )


def resolve_session_item(session_id: str, item_id: str, reason: str | None = None) -> None:
    """Resolve a current-session item that no longer needs prompt pressure."""
    _set_terminal_status(session_id, item_id, "resolved", reason)


def expire_session_item(session_id: str, item_id: str, reason: str | None = None) -> None:
    """Expire a temporary session item that is no longer relevant."""
    _set_terminal_status(session_id, item_id, "expired", reason)


def reject_session_item(session_id: str, item_id: str, reason: str) -> None:
    """Reject an invalid session item without deleting its history."""
    if not reason:
        raise ValueError("reason must not be empty")
    _set_terminal_status(session_id, item_id, "rejected", reason)


def list_active_session_items(session_id: str) -> list[SessionItem]:
    """List relevant non-terminal Session Working Set items for a session."""
    rows = _fetch_session_items(session_id)
    return [_to_public_item(row) for row in rows if _is_prompt_relevant(row)]


def export_prompt_ready_session_items(session_id: str, max_items: int) -> list[SessionItem]:
    """Export prompt-ready Session Working Set items in deterministic priority order."""
    if max_items < 1:
        raise ValueError("max_items must be a positive integer")
    items = list_active_session_items(session_id)
    return sorted(items, key=_prompt_sort_key)[:max_items]


def upsert_item(item: SessionItem) -> str:
    """Insert or update a Session Working Set item using its session identifier."""
    session_id = item.get("session_id")
    if not isinstance(session_id, str):
        raise ValueError("item must include session_id")
    return upsert_session_item(session_id, item)


def supersede_item(item_id: str, replacement_item_id: str) -> None:
    """Supersede one item using its replacement's session identifier."""
    session_id = _lookup_session_id(item_id)
    supersede_session_item(session_id, item_id, replacement_item_id)


def resolve_item(item_id: str, resolution: str) -> None:
    """Resolve a Session Working Set item."""
    resolve_session_item(_lookup_session_id(item_id), item_id, resolution)


def expire_item(item_id: str, reason: str) -> None:
    """Expire a Session Working Set item."""
    expire_session_item(_lookup_session_id(item_id), item_id, reason)


def list_active_items(session_id: str) -> list[SessionItem]:
    """List active Session Working Set items for a session."""
    return list_active_session_items(session_id)


def export_prompt_ready_items(session_id: str) -> list[SessionItem]:
    """Export prompt-ready Session Working Set items without an item cap."""
    return export_prompt_ready_session_items(session_id, 100)


def _to_database_record(session_id: str, item: SessionItem) -> SessionItem:
    record = dict(item)
    record["session_id"] = session_id
    if "source_observations" in record:
        record["source_observations_json"] = record.pop("source_observations")
    if "supersedes" in record:
        record["supersedes_json"] = record.pop("supersedes")
    return record


def _validate_item_record(record: SessionItem) -> None:
    required_fields = {
        "id",
        "session_id",
        "type",
        "content",
        "scope",
        "status",
        "priority",
        "explicitness_label",
        "source_observations_json",
        "origin",
        "created_at",
        "updated_at",
    }
    missing_fields = sorted(field for field in required_fields if field not in record)
    if missing_fields:
        raise ValueError(f"Missing session item field(s): {', '.join(missing_fields)}")
    validate_enum_value("session_item_type", str(record["type"]))
    validate_enum_value("session_scope", str(record["scope"]))
    _validate_session_status(str(record["status"]))
    validate_enum_value("explicitness_label", str(record["explicitness_label"]))
    validate_enum_value("session_origin", str(record["origin"]))


def _validate_session_status(status: str) -> None:
    if status == "active":
        return
    validate_enum_value("session_item_status", status)


def _insert_item(connection: sqlite3.Connection, record: SessionItem) -> None:
    connection.execute(
        """
        INSERT INTO session_working_set (
            id,
            session_id,
            type,
            content,
            scope,
            status,
            priority,
            explicitness_label,
            evidence_span,
            source_observations_json,
            supersedes_json,
            origin,
            created_at,
            updated_at,
            expires_at,
            resolution_reason
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        _item_values(record),
    )


def _update_item(connection: sqlite3.Connection, record: SessionItem) -> None:
    connection.execute(
        """
        UPDATE session_working_set
        SET type = ?,
            content = ?,
            scope = ?,
            status = ?,
            priority = ?,
            explicitness_label = ?,
            evidence_span = ?,
            source_observations_json = ?,
            supersedes_json = ?,
            origin = ?,
            updated_at = ?,
            expires_at = ?,
            resolution_reason = ?
        WHERE id = ? AND session_id = ?
        """,
        (
            record["type"],
            record["content"],
            record["scope"],
            record["status"],
            record["priority"],
            record["explicitness_label"],
            record.get("evidence_span"),
            _json_dump(record["source_observations_json"]),
            _json_dump(record.get("supersedes_json", [])),
            record["origin"],
            record["updated_at"],
            record.get("expires_at"),
            record.get("resolution_reason"),
            record["id"],
            record["session_id"],
        ),
    )


def _item_values(record: SessionItem) -> tuple[object, ...]:
    return (
        record["id"],
        record["session_id"],
        record["type"],
        record["content"],
        record["scope"],
        record["status"],
        record["priority"],
        record["explicitness_label"],
        record.get("evidence_span"),
        _json_dump(record["source_observations_json"]),
        _json_dump(record.get("supersedes_json", [])),
        record["origin"],
        record["created_at"],
        record["updated_at"],
        record.get("expires_at"),
        record.get("resolution_reason"),
    )


def _set_terminal_status(
    session_id: str,
    item_id: str,
    status: str,
    reason: str | None,
) -> None:
    if status not in TERMINAL_STATUSES:
        raise ValueError(f"Unsupported terminal status: {status}")
    with repository_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE session_working_set
            SET status = ?, updated_at = ?, resolution_reason = ?
            WHERE id = ? AND session_id = ?
            """,
            (status, _now(), reason, item_id, session_id),
        )
        if cursor.rowcount == 0:
            raise ValueError(f"Session item not found: {item_id}")


def _fetch_session_items(session_id: str) -> list[dict[str, object]]:
    with repository_connection() as connection:
        rows = connection.execute(
            """
            SELECT * FROM session_working_set
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _is_prompt_relevant(row: dict[str, object]) -> bool:
    status = str(row["status"])
    if status not in PROMPT_STATUSES:
        return False
    expires_at = row.get("expires_at")
    if expires_at is None:
        return True
    return _parse_time(str(expires_at)) > datetime.now(timezone.utc)  # noqa: UP017


def _to_public_item(row: dict[str, object]) -> SessionItem:
    item = dict(row)
    item["source_observations"] = _json_list(item.pop("source_observations_json"))
    item["supersedes"] = _json_list(item.pop("supersedes_json"))
    return item


def _prompt_sort_key(item: SessionItem) -> tuple[int, float, int, float, int]:
    status = str(item["status"])
    item_type = str(item["type"])
    scope = str(item["scope"])
    created_at = str(item["created_at"])
    priority = float(str(item["priority"]))
    return (
        STATUS_RANK.get(status, 99),
        -priority,
        TYPE_RANK.get(item_type, 99),
        -_parse_time(created_at).timestamp(),
        SCOPE_RANK.get(scope, 99),
    )


def _ensure_item_exists(connection: sqlite3.Connection, session_id: str, item_id: str) -> None:
    row = connection.execute(
        "SELECT id FROM session_working_set WHERE id = ? AND session_id = ?",
        (item_id, session_id),
    ).fetchone()
    if row is None:
        raise ValueError(f"Session item not found: {item_id}")


def _lookup_session_id(item_id: str) -> str:
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT session_id FROM session_working_set WHERE id = ?",
            (item_id,),
        ).fetchone()
    if row is None:
        raise ValueError(f"Session item not found: {item_id}")
    return str(row["session_id"])


def _json_dump(value: object) -> str:
    return json.dumps(value, sort_keys=True)


def _json_list(value: object) -> list[object]:
    if value is None:
        return []
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, list):
        raise ValueError("Expected JSON list for session item field")
    return decoded


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)  # noqa: UP017
    return parsed


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()  # noqa: UP017


def _new_id() -> str:
    return uuid.uuid4().hex
