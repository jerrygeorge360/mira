"""Repository helpers and enum validation for MIRA's durable source of truth.

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


def configure_database(database_path: str | Path) -> None:
    """Set the SQLite database path used by repository and session functions."""
    global _DATABASE_PATH
    _DATABASE_PATH = Path(database_path)
    initialize_database(_DATABASE_PATH)


def database_path() -> Path:
    """Return the configured repository database path."""
    if _DATABASE_PATH is not None:
        return _DATABASE_PATH
    return Path(os.environ.get(DATABASE_PATH_ENV, "./mira.db"))


def repository_connection() -> sqlite3.Connection:
    """Open a configured SQLite connection after ensuring the schema exists."""
    path = database_path()
    initialize_database(path)
    return connect_sqlite(path)


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
    with repository_connection() as connection:
        connection.execute(
            """
            INSERT INTO sessions (id, user_id, title, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, user_id, title, "active", now, now),
        )
    return session_id


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
    metadata_json = json.dumps(metadata, sort_keys=True) if metadata is not None else None
    with repository_connection() as connection:
        connection.execute(
            """
            INSERT INTO observations
                (id, session_id, role, content, source, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (observation_id, session_id, role, content, source, metadata_json, _now()),
        )
    return observation_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()  # noqa: UP017


def _new_id() -> str:
    return uuid.uuid4().hex
