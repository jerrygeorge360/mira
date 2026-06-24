"""Typed repository functions for MIRA's durable source of truth.

Ownership: Kelechi.
Related issue: ISSUE-005, ISSUE-006.
Architecture area: slow path.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from core.db.schema import initialize_database
from core.db.sqlite import connect_sqlite

RepositoryRecord = dict[str, object]

DATABASE_PATH_ENV = "MIRA_DB_PATH"
_DATABASE_PATH: Path | None = None

ENUM_VALUES: dict[str, frozenset[str]] = {
    "session_record_status": frozenset({"active", "ended", "archived"}),
    "observation_role": frozenset({"user", "assistant", "system", "tool"}),
    "observation_source": frozenset({"chat", "slack", "mcp", "seed", "import"}),
    "slow_path_queue_status": frozenset({"pending", "processing", "done", "failed", "dead_letter"}),
    "session_item_type": frozenset(
        {
            "current_goal",
            "active_constraint",
            "correction",
            "decision",
            "open_question",
            "resolution",
        }
    ),
    "session_scope": frozenset(
        {"current_response", "current_task", "current_session", "project", "cross_session"}
    ),
    "session_item_status": frozenset(
        {"provisional", "hydrated", "confirmed", "resolved", "expired", "rejected", "superseded"}
    ),
    "session_origin": frozenset({"micro_path", "cross_session_hydration", "manual", "slow_path"}),
    "explicitness_label": frozenset(
        {
            "direct_instruction",
            "direct_correction",
            "direct_decision",
            "explicit_preference",
            "inferred_preference",
            "agent_inference",
            "ambiguous",
        }
    ),
    "fact_status": frozenset({"active", "superseded", "contradicted", "expired", "rejected"}),
    "graph_node_type": frozenset(
        {"observation", "entity", "reflection", "community", "foresight", "atomic_fact"}
    ),
    "graph_edge_type": frozenset(
        {
            "MENTIONS",
            "DERIVED_FROM",
            "PREFERS",
            "DISLIKES",
            "WORKS_ON",
            "IS_EXPERT_IN",
            "SUPERSEDED_BY",
            "CONTRADICTS",
            "CAUSED_BY",
            "LEADS_TO",
            "PART_OF_COMMUNITY",
        }
    ),
    "reflection_type": frozenset({"user_knowledge", "world_knowledge", "self_knowledge"}),
    "reflection_status": frozenset({"active", "stale", "invalidated", "superseded"}),
    "foresight_status": frozenset({"pending", "active", "resolved", "expired", "cancelled"}),
    "working_memory_type": frozenset(
        {
            "project_constraint",
            "user_preference",
            "behavioral_instruction",
            "active_goal",
            "active_foresight",
            "confirmed_correction",
        }
    ),
    "working_memory_status": frozenset({"active", "demoted", "expired", "superseded"}),
    "retrieval_mode": frozenset({"quick", "deep", "relational", "auto"}),
}

JSON_COLUMNS: frozenset[str] = frozenset(
    {
        "metadata_json",
        "source_observations_json",
        "supersedes_json",
        "aliases_json",
        "member_nodes_json",
        "retrieved_records_json",
        "sufficiency_json",
        "included_session_items_json",
        "included_memory_items_json",
        "included_recent_turns_json",
        "token_budget_json",
    }
)

UPDATED_AT_TABLES: frozenset[str] = frozenset(
    {
        "sessions",
        "slow_path_queue",
        "session_working_set",
        "entities",
        "reflections",
        "foresight_records",
        "community_summaries",
        "working_memory",
    }
)

TABLE_COLUMNS: dict[str, frozenset[str]] = {
    "sessions": frozenset(
        {"id", "user_id", "title", "status", "created_at", "updated_at", "ended_at"}
    ),
    "observations": frozenset(
        {
            "id",
            "session_id",
            "role",
            "content",
            "source",
            "metadata_json",
            "created_at",
            "processed_at",
        }
    ),
    "slow_path_queue": frozenset(
        {
            "id",
            "observation_id",
            "status",
            "attempt_count",
            "last_error",
            "created_at",
            "updated_at",
        }
    ),
    "session_working_set": frozenset(
        {
            "id",
            "session_id",
            "type",
            "content",
            "scope",
            "status",
            "priority",
            "explicitness_label",
            "evidence_span",
            "source_observations_json",
            "supersedes_json",
            "origin",
            "created_at",
            "updated_at",
            "expires_at",
            "resolution_reason",
        }
    ),
    "atomic_facts": frozenset(
        {
            "id",
            "subject",
            "predicate",
            "object",
            "confidence",
            "status",
            "source_observation_id",
            "created_at",
            "valid_from",
            "valid_until",
        }
    ),
    "entities": frozenset(
        {"id", "name", "entity_type", "aliases_json", "created_at", "updated_at"}
    ),
    "graph_nodes": frozenset(
        {"id", "node_type", "source_table", "source_id", "label", "metadata_json", "created_at"}
    ),
    "graph_edges": frozenset(
        {
            "id",
            "source_node_id",
            "target_node_id",
            "edge_type",
            "confidence",
            "source_observations_json",
            "metadata_json",
            "valid_from",
            "valid_until",
            "created_at",
            "invalidated_at",
        }
    ),
    "reflections": frozenset(
        {
            "id",
            "reflection_type",
            "content",
            "confidence",
            "status",
            "created_at",
            "updated_at",
            "stale_reason",
        }
    ),
    "reflection_evidence": frozenset({"id", "reflection_id", "observation_id", "created_at"}),
    "foresight_records": frozenset(
        {
            "id",
            "content",
            "reason",
            "status",
            "source_observation_id",
            "valid_from",
            "valid_until",
            "always_inject",
            "resolved_by",
            "created_at",
            "updated_at",
        }
    ),
    "community_summaries": frozenset(
        {
            "id",
            "community_id",
            "title",
            "summary",
            "member_nodes_json",
            "created_at",
            "updated_at",
        }
    ),
    "working_memory": frozenset(
        {
            "id",
            "content",
            "memory_type",
            "scope",
            "priority",
            "status",
            "source_record_type",
            "source_record_id",
            "created_at",
            "updated_at",
        }
    ),
    "retrieval_logs": frozenset(
        {
            "id",
            "session_id",
            "query",
            "retrieval_mode",
            "retrieved_records_json",
            "sufficiency_json",
            "created_at",
        }
    ),
    "prompt_logs": frozenset(
        {
            "id",
            "session_id",
            "user_observation_id",
            "included_session_items_json",
            "included_memory_items_json",
            "included_recent_turns_json",
            "token_budget_json",
            "created_at",
        }
    ),
}


def configure_database(database_path: str | Path) -> None:
    """Set the SQLite database path used by repository functions."""
    global _DATABASE_PATH
    _DATABASE_PATH = Path(database_path)
    initialize_database(_DATABASE_PATH)


def validate_enum_value(enum_name: str, value: str) -> None:
    """Validate a repository enum-like value before it is written to SQLite."""
    allowed_values = ENUM_VALUES.get(enum_name)
    if allowed_values is None:
        raise KeyError(f"Unknown repository enum: {enum_name}")
    if value not in allowed_values:
        joined_values = ", ".join(sorted(allowed_values))
        raise ValueError(f"Invalid {enum_name}: {value!r}. Expected one of: {joined_values}")


def enum_values(enum_name: str) -> frozenset[str]:
    """Return allowed values for a repository enum-like field."""
    allowed_values = ENUM_VALUES.get(enum_name)
    if allowed_values is None:
        raise KeyError(f"Unknown repository enum: {enum_name}")
    return allowed_values


def create_session(user_id: str, title: str | None = None) -> str:
    """Create an active session record and return its identifier."""
    session_id = _new_id()
    now = _now()
    _execute_insert(
        "sessions",
        {
            "id": session_id,
            "user_id": user_id,
            "title": title,
            "status": "active",
            "created_at": now,
            "updated_at": now,
        },
    )
    return session_id


def end_session(session_id: str) -> None:
    """Mark a session as ended."""
    now = _now()
    _execute_write(
        """
        UPDATE sessions
        SET status = ?, updated_at = ?, ended_at = ?
        WHERE id = ?
        """,
        ("ended", now, now, session_id),
        missing_message=f"Session not found: {session_id}",
    )


def save_observation(
    session_id: str,
    role: str,
    content: str,
    source: str = "chat",
    metadata: dict[str, object] | None = None,
) -> str:
    """Persist a raw observation and return its identifier."""
    validate_enum_value("observation_role", role)
    validate_enum_value("observation_source", source)
    observation_id = _new_id()
    _execute_insert(
        "observations",
        {
            "id": observation_id,
            "session_id": session_id,
            "role": role,
            "content": content,
            "source": source,
            "metadata_json": metadata,
            "created_at": _now(),
        },
    )
    return observation_id


def list_observations(session_id: str, limit: int | None = None) -> list[RepositoryRecord]:
    """List observations for a session in creation order."""
    if limit is not None and limit < 1:
        raise ValueError("limit must be a positive integer")
    query = "SELECT * FROM observations WHERE session_id = ? ORDER BY created_at ASC"
    parameters: tuple[object, ...] = (session_id,)
    if limit is not None:
        query = f"{query} LIMIT ?"
        parameters = (session_id, limit)
    return _fetch_all(query, parameters)


def enqueue_observation(observation_id: str) -> str:
    """Add an observation to the slow-path queue and return the queue identifier."""
    queue_id = _new_id()
    now = _now()
    _execute_insert(
        "slow_path_queue",
        {
            "id": queue_id,
            "observation_id": observation_id,
            "status": "pending",
            "attempt_count": 0,
            "created_at": now,
            "updated_at": now,
        },
    )
    return queue_id


def claim_slow_path_batch(limit: int) -> list[str]:
    """Claim queue records and return identifiers for compatibility callers."""
    return [str(record["id"]) for record in claim_pending_batch(limit)]


def claim_pending_batch(limit: int) -> list[RepositoryRecord]:
    """Claim pending or failed slow-path jobs for durable asynchronous processing."""
    if limit < 1:
        raise ValueError("limit must be a positive integer")
    now = _now()
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM slow_path_queue
            WHERE status IN (?, ?)
            ORDER BY created_at ASC
            LIMIT ?
            """,
            ("pending", "failed", limit),
        ).fetchall()
        queue_ids = [str(row["id"]) for row in rows]
        if not queue_ids:
            return []
        connection.executemany(
            """
            UPDATE slow_path_queue
            SET status = ?,
                attempt_count = attempt_count + 1,
                last_error = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            [("processing", now, queue_id) for queue_id in queue_ids],
        )
        claimed_rows = connection.execute(
            f"""
            SELECT *
            FROM slow_path_queue
            WHERE id IN ({", ".join("?" for _ in queue_ids)})
            ORDER BY created_at ASC
            """,  # nosec B608
            tuple(queue_ids),
        ).fetchall()
    return [_row_to_record(row) for row in claimed_rows]


def mark_processing(queue_id: str) -> None:
    """Move a pending or failed queue job into processing and count an attempt."""
    now = _now()
    _execute_write(
        """
        UPDATE slow_path_queue
        SET status = ?,
            attempt_count = attempt_count + 1,
            last_error = NULL,
            updated_at = ?
        WHERE id = ? AND status IN (?, ?)
        """,
        ("processing", now, queue_id, "pending", "failed"),
        missing_message=f"Queue item not found or not claimable: {queue_id}",
    )


def mark_queue_done(queue_id: str) -> None:
    """Mark a slow-path queue item as processed."""
    mark_done(queue_id)


def mark_queue_failed(queue_id: str, error: str) -> None:
    """Mark a slow-path queue item as failed with a clear error message."""
    mark_failed(queue_id, error)


def mark_done(queue_id: str) -> None:
    """Move a processing queue job to done."""
    _transition_queue_status(
        queue_id,
        from_statuses={"processing"},
        to_status="done",
        error=None,
    )


def mark_failed(queue_id: str, error: str) -> None:
    """Move a processing queue job to failed with a retryable error."""
    if not error:
        raise ValueError("error must not be empty")
    _transition_queue_status(
        queue_id,
        from_statuses={"processing"},
        to_status="failed",
        error=error,
    )


def move_to_dead_letter(queue_id: str, error: str) -> None:
    """Move a failed queue job to dead-letter with its terminal error."""
    if not error:
        raise ValueError("error must not be empty")
    _transition_queue_status(
        queue_id,
        from_statuses={"failed"},
        to_status="dead_letter",
        error=error,
    )


def list_failed_jobs(limit: int) -> list[RepositoryRecord]:
    """List retryable failed slow-path jobs for debugging or repair."""
    if limit < 1:
        raise ValueError("limit must be a positive integer")
    return _fetch_all(
        """
        SELECT *
        FROM slow_path_queue
        WHERE status = ?
        ORDER BY updated_at ASC
        LIMIT ?
        """,
        ("failed", limit),
    )


def create_session_item(item: RepositoryRecord) -> str:
    """Create a Session Working Set item and return its identifier."""
    record = _prepare_record(item)
    _require_fields(
        "session_working_set",
        record,
        {
            "session_id",
            "type",
            "content",
            "scope",
            "status",
            "priority",
            "explicitness_label",
            "source_observations_json",
        },
    )
    _validate_record_enums(
        record,
        {
            "type": "session_item_type",
            "scope": "session_scope",
            "status": "session_item_status",
            "explicitness_label": "explicitness_label",
            "origin": "session_origin",
        },
    )
    record.setdefault("origin", "micro_path")
    return _insert_with_generated_id("session_working_set", record)


def update_session_item_status(item_id: str, status: str) -> None:
    """Update the status of a Session Working Set item."""
    validate_enum_value("session_item_status", status)
    _execute_write(
        """
        UPDATE session_working_set
        SET status = ?, updated_at = ?
        WHERE id = ?
        """,
        (status, _now(), item_id),
        missing_message=f"Session item not found: {item_id}",
    )


def list_active_session_items(session_id: str) -> list[RepositoryRecord]:
    """List current non-terminal Session Working Set items for a session."""
    return _fetch_all(
        """
        SELECT * FROM session_working_set
        WHERE session_id = ? AND status IN (?, ?, ?)
        ORDER BY priority DESC, created_at ASC
        """,
        (session_id, "provisional", "hydrated", "confirmed"),
    )


def list_session_items_by_status(session_id: str, status: str) -> list[RepositoryRecord]:
    """List Session Working Set items for a session by status."""
    validate_enum_value("session_item_status", status)
    return _fetch_all(
        """
        SELECT * FROM session_working_set
        WHERE session_id = ? AND status = ?
        ORDER BY priority DESC, created_at ASC
        """,
        (session_id, status),
    )


def create_atomic_fact(fact: RepositoryRecord) -> str:
    """Create an atomic fact and return its identifier."""
    record = _prepare_record(fact)
    record.setdefault("status", "active")
    _require_fields(
        "atomic_facts",
        record,
        {"subject", "predicate", "object", "confidence", "status", "source_observation_id"},
    )
    _validate_record_enums(record, {"status": "fact_status"})
    return _insert_with_generated_id("atomic_facts", record)


def create_entity(entity: RepositoryRecord) -> str:
    """Create an entity and return its identifier."""
    record = _prepare_record(entity)
    _require_fields("entities", record, {"name", "entity_type"})
    return _insert_with_generated_id("entities", record)


def create_graph_node(node: RepositoryRecord) -> str:
    """Create a graph node and return its identifier."""
    record = _prepare_record(node)
    _require_fields("graph_nodes", record, {"node_type", "label"})
    _validate_record_enums(record, {"node_type": "graph_node_type"})
    return _insert_with_generated_id("graph_nodes", record)


def create_graph_edge(edge: RepositoryRecord) -> str:
    """Create a graph edge and return its identifier."""
    record = _prepare_record(edge)
    _require_fields(
        "graph_edges",
        record,
        {"source_node_id", "target_node_id", "edge_type", "confidence", "source_observations_json"},
    )
    _validate_record_enums(record, {"edge_type": "graph_edge_type"})
    return _insert_with_generated_id("graph_edges", record)


def create_reflection(reflection: RepositoryRecord) -> str:
    """Create a reflection and return its identifier."""
    record = _prepare_record(reflection)
    _require_fields("reflections", record, {"reflection_type", "content", "confidence", "status"})
    _validate_record_enums(
        record, {"reflection_type": "reflection_type", "status": "reflection_status"}
    )
    return _insert_with_generated_id("reflections", record)


def link_reflection_evidence(reflection_id: str, observation_id: str) -> str:
    """Link a reflection to supporting observation evidence."""
    return _insert_with_generated_id(
        "reflection_evidence",
        {"reflection_id": reflection_id, "observation_id": observation_id},
    )


def create_foresight_record(record: RepositoryRecord) -> str:
    """Create a foresight record and return its identifier."""
    prepared_record = _prepare_record(record)
    _require_fields(
        "foresight_records",
        prepared_record,
        {"content", "status", "source_observation_id"},
    )
    _validate_record_enums(prepared_record, {"status": "foresight_status"})
    return _insert_with_generated_id("foresight_records", prepared_record)


def list_active_foresight(session_id: str | None = None) -> list[RepositoryRecord]:
    """List active foresight records, optionally scoped by source observation session."""
    if session_id is None:
        return _fetch_all(
            "SELECT * FROM foresight_records WHERE status = ? ORDER BY created_at ASC",
            ("active",),
        )
    return _fetch_all(
        """
        SELECT foresight_records.*
        FROM foresight_records
        JOIN observations ON observations.id = foresight_records.source_observation_id
        WHERE foresight_records.status = ? AND observations.session_id = ?
        ORDER BY foresight_records.created_at ASC
        """,
        ("active", session_id),
    )


def create_working_memory_item(item: RepositoryRecord) -> str:
    """Create a durable working-memory item and return its identifier."""
    record = _prepare_record(item)
    _require_fields(
        "working_memory",
        record,
        {"content", "memory_type", "scope", "priority", "status"},
    )
    _validate_record_enums(
        record, {"memory_type": "working_memory_type", "status": "working_memory_status"}
    )
    return _insert_with_generated_id("working_memory", record)


def create_community_summary(summary: RepositoryRecord) -> str:
    """Create a graph-derived community summary and return its identifier."""
    record = _prepare_record(summary)
    _require_fields(
        "community_summaries",
        record,
        {"community_id", "title", "summary", "member_nodes_json"},
    )
    return _insert_with_generated_id("community_summaries", record)


def create_retrieval_log(log: RepositoryRecord) -> str:
    """Create a retrieval log and return its identifier."""
    record = _prepare_record(log)
    _require_fields(
        "retrieval_logs",
        record,
        {"session_id", "query", "retrieval_mode", "retrieved_records_json"},
    )
    _validate_record_enums(record, {"retrieval_mode": "retrieval_mode"})
    return _insert_with_generated_id("retrieval_logs", record)


def create_prompt_log(log: RepositoryRecord) -> str:
    """Create a prompt-construction log and return its identifier."""
    record = _prepare_record(log)
    _require_fields("prompt_logs", record, {"session_id", "user_observation_id"})
    return _insert_with_generated_id("prompt_logs", record)


def _configured_database_path() -> Path:
    if _DATABASE_PATH is not None:
        return _DATABASE_PATH
    return Path(os.environ.get(DATABASE_PATH_ENV, "./mira.db"))


def _connect() -> sqlite3.Connection:
    database_path = _configured_database_path()
    initialize_database(database_path)
    return connect_sqlite(database_path)


def repository_connection() -> sqlite3.Connection:
    """Open a configured SQLite connection after ensuring the schema exists."""
    return _connect()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()  # noqa: UP017


def _new_id() -> str:
    return uuid.uuid4().hex


def _prepare_record(record: RepositoryRecord) -> RepositoryRecord:
    return dict(record)


def _insert_with_generated_id(table: str, record: RepositoryRecord) -> str:
    prepared = dict(record)
    record_id = str(prepared.setdefault("id", _new_id()))
    now = _now()
    prepared.setdefault("created_at", now)
    if table in UPDATED_AT_TABLES:
        prepared.setdefault("updated_at", now)
    _execute_insert(table, prepared)
    return record_id


def _execute_insert(table: str, record: RepositoryRecord) -> None:
    _validate_insert_identifiers(table, tuple(record))
    columns = tuple(record)
    if not columns:
        raise ValueError(f"No values provided for {table}")
    placeholders = ", ".join("?" for _ in columns)
    column_sql = ", ".join(columns)
    values = tuple(_to_database_value(column, record[column]) for column in columns)
    with _connect() as connection:
        try:
            connection.execute(
                f"INSERT INTO {table} ({column_sql}) VALUES ({placeholders})",  # nosec B608
                values,
            )
        except sqlite3.IntegrityError as error:
            raise ValueError(f"Could not insert into {table}: {error}") from error
        except sqlite3.OperationalError as error:
            raise ValueError(f"Invalid repository insert for {table}: {error}") from error


def _execute_write(
    statement: str,
    parameters: tuple[object, ...],
    *,
    missing_message: str,
) -> None:
    with _connect() as connection:
        cursor = connection.execute(statement, parameters)
        if cursor.rowcount == 0:
            raise ValueError(missing_message)


def _fetch_all(statement: str, parameters: tuple[object, ...]) -> list[RepositoryRecord]:
    with _connect() as connection:
        rows = connection.execute(statement, parameters).fetchall()
    return [_row_to_record(row) for row in rows]


def _transition_queue_status(
    queue_id: str,
    *,
    from_statuses: set[str],
    to_status: str,
    error: str | None,
) -> None:
    validate_enum_value("slow_path_queue_status", to_status)
    for status in from_statuses:
        validate_enum_value("slow_path_queue_status", status)
    placeholders = ", ".join("?" for _ in from_statuses)
    _execute_write(
        f"""
        UPDATE slow_path_queue
        SET status = ?, last_error = ?, updated_at = ?
        WHERE id = ? AND status IN ({placeholders})
        """,  # nosec B608
        (to_status, error, _now(), queue_id, *sorted(from_statuses)),
        missing_message=f"Invalid queue transition for item: {queue_id}",
    )


def _require_fields(table: str, record: RepositoryRecord, required_fields: set[str]) -> None:
    missing_fields = sorted(field for field in required_fields if field not in record)
    if missing_fields:
        joined_fields = ", ".join(missing_fields)
        raise ValueError(f"Missing required field(s) for {table}: {joined_fields}")


def _validate_insert_identifiers(table: str, columns: tuple[str, ...]) -> None:
    allowed_columns = TABLE_COLUMNS.get(table)
    if allowed_columns is None:
        raise ValueError(f"Unknown repository table: {table}")
    unknown_columns = sorted(column for column in columns if column not in allowed_columns)
    if unknown_columns:
        joined_columns = ", ".join(unknown_columns)
        raise ValueError(f"Unknown column(s) for {table}: {joined_columns}")


def _validate_record_enums(record: RepositoryRecord, enum_fields: dict[str, str]) -> None:
    for field_name, enum_name in enum_fields.items():
        value = record.get(field_name)
        if value is not None:
            validate_enum_value(enum_name, str(value))


def _to_database_value(column: str, value: object) -> object:
    if column in JSON_COLUMNS and value is not None:
        return json.dumps(value, sort_keys=True)
    return value


def _row_to_record(row: sqlite3.Row) -> RepositoryRecord:
    record: RepositoryRecord = {}
    for key in tuple(row.keys()):
        value = row[key]
        if key in JSON_COLUMNS and value is not None:
            record[key] = json.loads(str(value))
        else:
            record[key] = value
    return record
