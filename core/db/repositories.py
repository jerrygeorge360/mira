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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from core.db.schema import (
    LEGACY_WORKSPACE_ID,
    initialize_database,
    seed_workspace_canonical_registries,
)
from core.db.sqlite import connect_sqlite

RepositoryRecord = dict[str, object]

DATABASE_PATH_ENV = "MIRA_DB_PATH"
_DATABASE_PATH: Path | None = None
_INITIALIZED_DATABASE_PATHS: set[Path] = set()


@dataclass(frozen=True)
class WorkspaceContext:
    """Trusted workspace identity passed to workspace-bound repositories."""

    workspace_id: str
    user_id: str | None = None
    membership_role: str | None = None
    auth_mode: str = "internal"


ENUM_VALUES: dict[str, frozenset[str]] = {
    "workspace_type": frozenset({"personal", "demo", "legacy", "development"}),
    "workspace_status": frozenset({"active", "suspended", "expired", "deleting", "deleted"}),
    "workspace_role": frozenset({"owner", "admin", "member"}),
    "session_record_status": frozenset({"active", "ended", "archived", "deleted"}),
    "observation_role": frozenset({"user", "assistant", "system", "tool"}),
    "observation_source": frozenset({"chat", "slack", "mcp", "seed", "import"}),
    "slow_path_queue_status": frozenset(
        {"pending", "processing", "done", "failed", "dead_letter", "quarantined"}
    ),
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
    "retrieval_mode": frozenset({"quick", "deep", "relational", "auto", "general"}),
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
        "retrieved_observation_ids_json",
        "retrieved_fact_ids_json",
        "session_item_ids_json",
        "hot_memory_ids_json",
        "graph_path_ids_json",
        "community_summary_ids_json",
        "prompt_sections_json",
        "hydration_ids_json",
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
            "canonical_subject_id",
            "canonical_predicate_id",
            "created_at",
            "valid_from",
            "valid_until",
        }
    ),
    "canonical_subjects": frozenset(
        {"id", "canonical_form", "aliases_json", "confidence", "created_at"}
    ),
    "canonical_predicates": frozenset(
        {"id", "canonical_form", "aliases_json", "confidence", "created_at"}
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
    "answer_traces": frozenset(
        {
            "id",
            "session_id",
            "user_observation_id",
            "assistant_observation_id",
            "retrieval_mode",
            "retrieved_observation_ids_json",
            "retrieved_fact_ids_json",
            "session_item_ids_json",
            "hot_memory_ids_json",
            "graph_path_ids_json",
            "community_summary_ids_json",
            "sufficiency_json",
            "prompt_sections_json",
            "hydration_ids_json",
            "retrieval_log_id",
            "prompt_log_id",
            "created_at",
        }
    ),
}

_WORKSPACE_OWNED_TABLES = frozenset(
    {
        "sessions",
        "observations",
        "slow_path_queue",
        "canonical_subjects",
        "canonical_predicates",
        "atomic_facts",
        "entities",
        "graph_nodes",
        "graph_edges",
        "reflections",
        "foresight_records",
        "community_summaries",
        "working_memory",
        "retrieval_logs",
        "prompt_logs",
        "answer_traces",
    }
)
for _workspace_table in _WORKSPACE_OWNED_TABLES:
    TABLE_COLUMNS[_workspace_table] = frozenset({*TABLE_COLUMNS[_workspace_table], "workspace_id"})

TABLE_COLUMNS.update(
    {
        "users": frozenset(
            {
                "id",
                "github_id",
                "github_login",
                "display_name",
                "avatar_url",
                "email",
                "created_at",
                "updated_at",
                "last_login_at",
            }
        ),
        "workspaces": frozenset(
            {
                "id",
                "name",
                "slug",
                "owner_user_id",
                "workspace_type",
                "status",
                "expires_at",
                "created_at",
                "updated_at",
            }
        ),
        "workspace_members": frozenset({"workspace_id", "user_id", "role", "created_at"}),
    }
)


def configure_database(database_path: str | Path) -> None:
    """Set the SQLite database path used by repository functions."""
    global _DATABASE_PATH
    _DATABASE_PATH = Path(database_path)
    initialize_database(_DATABASE_PATH)
    _INITIALIZED_DATABASE_PATHS.add(_DATABASE_PATH.resolve())


def current_database_path() -> Path | None:
    """Return the database path set via ``configure_database``, or ``None`` if unset."""
    return _DATABASE_PATH


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


def create_user(
    *,
    github_id: str | None = None,
    github_login: str | None = None,
    display_name: str | None = None,
    avatar_url: str | None = None,
    email: str | None = None,
    user_id: str | None = None,
) -> str:
    """Create an internal user record; OAuth upsert behavior is added in slice 5."""
    identifier = user_id or _new_id()
    now = _now()
    _execute_insert(
        "users",
        {
            "id": identifier,
            "github_id": github_id,
            "github_login": github_login,
            "display_name": display_name,
            "avatar_url": avatar_url,
            "email": email,
            "created_at": now,
            "updated_at": now,
        },
    )
    return identifier


def add_workspace_member(workspace_id: str, user_id: str, role: str) -> None:
    """Add one user to a workspace with a validated role."""
    require_active_workspace(workspace_id)
    validate_enum_value("workspace_role", role)
    _execute_insert(
        "workspace_members",
        {
            "workspace_id": workspace_id,
            "user_id": user_id,
            "role": role,
            "created_at": _now(),
        },
    )


def create_workspace(
    name: str,
    slug: str,
    workspace_type: str,
    *,
    owner_user_id: str | None = None,
    status: str = "active",
    expires_at: str | None = None,
    workspace_id: str | None = None,
) -> str:
    """Create a workspace and seed its isolated canonical vocabulary."""
    if not name.strip() or not slug.strip():
        raise ValueError("workspace name and slug must not be empty")
    validate_enum_value("workspace_type", workspace_type)
    validate_enum_value("workspace_status", status)
    identifier = workspace_id or _new_id()
    now = _now()
    with _connect() as connection:
        try:
            connection.execute(
                """
                INSERT INTO workspaces (
                    id, name, slug, owner_user_id, workspace_type, status,
                    expires_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    identifier,
                    name.strip(),
                    slug.strip(),
                    owner_user_id,
                    workspace_type,
                    status,
                    expires_at,
                    now,
                    now,
                ),
            )
            if owner_user_id is not None:
                connection.execute(
                    """
                    INSERT INTO workspace_members (workspace_id, user_id, role, created_at)
                    VALUES (?, ?, 'owner', ?)
                    """,
                    (identifier, owner_user_id, now),
                )
            seed_workspace_canonical_registries(connection, identifier)
        except sqlite3.IntegrityError as error:
            raise ValueError(f"Could not create workspace: {error}") from error
    return identifier


def get_workspace(workspace_id: str) -> RepositoryRecord | None:
    """Fetch one workspace by immutable identifier."""
    rows = _fetch_all("SELECT * FROM workspaces WHERE id = ?", (workspace_id,))
    return rows[0] if rows else None


def require_active_workspace(workspace_id: str) -> RepositoryRecord:
    """Return an active workspace or fail closed."""
    workspace = get_workspace(workspace_id)
    if workspace is None:
        raise ValueError(f"Workspace not found: {workspace_id}")
    if workspace.get("status") != "active":
        raise ValueError(f"Workspace is not active: {workspace_id}")
    expires_at = workspace.get("expires_at")
    if isinstance(expires_at, str) and expires_at <= _now():
        with _connect() as connection:
            connection.execute(
                "UPDATE workspaces SET status = 'expired', updated_at = ? WHERE id = ?",
                (_now(), workspace_id),
            )
        raise ValueError(f"Workspace is not active: {workspace_id}")
    return workspace


def workspace_id_for_session(session_id: str) -> str:
    """Resolve and validate the active workspace that owns a session."""
    workspace_id = _workspace_id_for("sessions", session_id)
    require_active_workspace(workspace_id)
    return workspace_id


def workspace_id_for_observation(observation_id: str) -> str:
    """Resolve and validate the active workspace that owns an observation."""
    workspace_id = _workspace_id_for("observations", observation_id)
    require_active_workspace(workspace_id)
    return workspace_id


def bind_workspace(context: WorkspaceContext) -> WorkspaceRepository:
    """Validate a trusted context and return a repository bound to it."""
    require_active_workspace(context.workspace_id)
    if context.user_id is not None:
        with _connect() as connection:
            membership = connection.execute(
                """
                SELECT role FROM workspace_members
                WHERE workspace_id = ? AND user_id = ?
                """,
                (context.workspace_id, context.user_id),
            ).fetchone()
        if membership is None:
            raise ValueError("User is not a member of the workspace")
    return WorkspaceRepository(context)


def configured_workspace_context(
    env_name: str = "MIRA_WORKSPACE_ID", *, allow_development_fallback: bool = True
) -> WorkspaceContext:
    """Resolve an explicitly configured integration workspace or fail closed."""
    workspace_id = os.environ.get(env_name, "").strip()
    if (
        not workspace_id
        and allow_development_fallback
        and os.environ.get("MIRA_AUTH_MODE", "").casefold() == "development"
    ):
        workspace_id = os.environ.get("MIRA_DEVELOPMENT_WORKSPACE_ID", LEGACY_WORKSPACE_ID).strip()
    if not workspace_id:
        raise ValueError(f"{env_name} must bind this integration to one workspace")
    require_active_workspace(workspace_id)
    return WorkspaceContext(workspace_id, auth_mode="configured")


def ensure_workspace_session(
    context: WorkspaceContext, session_id: str, user_id: str, *, source: str
) -> str:
    """Create a deterministic integration session inside one verified workspace."""
    repository = bind_workspace(context)
    if repository.get_session(session_id) is not None:
        return session_id
    if source not in {"slack", "mcp", "streamlit"}:
        raise ValueError("source must identify a configured integration")
    now = _now()
    _execute_insert(
        "sessions",
        {
            "id": session_id,
            "workspace_id": context.workspace_id,
            "user_id": user_id,
            "status": "active",
            "created_at": now,
            "updated_at": now,
        },
    )
    return session_id


class WorkspaceRepository:
    """Small fail-closed repository facade for ownership-sensitive access."""

    def __init__(self, context: WorkspaceContext) -> None:
        self.context = context

    @property
    def workspace_id(self) -> str:
        return self.context.workspace_id

    def create_session(self, user_id: str, title: str | None = None) -> str:
        return create_session(user_id, title, workspace_id=self.workspace_id)

    def get_session(self, session_id: str) -> RepositoryRecord | None:
        rows = _fetch_all(
            "SELECT * FROM sessions WHERE id = ? AND workspace_id = ? AND status != 'deleted'",
            (session_id, self.workspace_id),
        )
        return rows[0] if rows else None

    def list_sessions(self, limit: int = 50) -> list[RepositoryRecord]:
        if limit < 1:
            raise ValueError("limit must be a positive integer")
        return _fetch_all(
            """
            SELECT * FROM sessions
            WHERE workspace_id = ? AND status != 'deleted'
            ORDER BY updated_at DESC LIMIT ?
            """,
            (self.workspace_id, limit),
        )

    def save_observation(
        self,
        session_id: str,
        role: str,
        content: str,
        source: str = "chat",
        metadata: dict[str, object] | None = None,
    ) -> str:
        if self.get_session(session_id) is None:
            raise ValueError(f"Session not found in workspace: {session_id}")
        return save_observation(session_id, role, content, source, metadata)

    def list_observations(
        self, session_id: str, limit: int | None = None
    ) -> list[RepositoryRecord]:
        if self.get_session(session_id) is None:
            raise ValueError(f"Session not found in workspace: {session_id}")
        return list_observations(session_id, limit)

    def get_atomic_fact(self, fact_id: str) -> RepositoryRecord | None:
        rows = _fetch_all(
            "SELECT * FROM atomic_facts WHERE id = ? AND workspace_id = ?",
            (fact_id, self.workspace_id),
        )
        return rows[0] if rows else None

    def get_graph_node(self, node_id: str) -> RepositoryRecord | None:
        rows = _fetch_all(
            "SELECT * FROM graph_nodes WHERE id = ? AND workspace_id = ?",
            (node_id, self.workspace_id),
        )
        return rows[0] if rows else None

    def get_answer_trace(self, trace_id: str) -> RepositoryRecord | None:
        rows = _fetch_all(
            "SELECT * FROM answer_traces WHERE id = ? AND workspace_id = ?",
            (trace_id, self.workspace_id),
        )
        return rows[0] if rows else None


def create_session(
    user_id: str,
    title: str | None = None,
    *,
    workspace_id: str = LEGACY_WORKSPACE_ID,
) -> str:
    """Create an active session record and return its identifier."""
    require_active_workspace(workspace_id)
    session_id = _new_id()
    now = _now()
    _execute_insert(
        "sessions",
        {
            "id": session_id,
            "workspace_id": workspace_id,
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
    workspace_id = _workspace_id_for("sessions", session_id)
    observation_id = _new_id()
    _execute_insert(
        "observations",
        {
            "id": observation_id,
            "workspace_id": workspace_id,
            "session_id": session_id,
            "role": role,
            "content": content,
            "source": source,
            "metadata_json": metadata,
            "created_at": _now(),
        },
    )
    return observation_id


def list_sessions(user_id: str | None = None, limit: int = 50) -> list[RepositoryRecord]:
    """List sessions, most recently updated first (optionally filtered by user)."""
    if limit < 1:
        raise ValueError("limit must be a positive integer")
    if user_id:
        return _fetch_all(
            """
            SELECT * FROM sessions
            WHERE user_id = ? AND status != 'deleted'
            ORDER BY updated_at DESC LIMIT ?
            """,
            (user_id, limit),
        )
    return _fetch_all(
        "SELECT * FROM sessions WHERE status != 'deleted' ORDER BY updated_at DESC LIMIT ?",
        (limit,),
    )


def message_counts_by_session(*, workspace_id: str | None = None) -> dict[str, int]:
    """Return {session_id: number of user/assistant turns} in one query (for the sidebar)."""
    workspace_filter = ""
    parameters: tuple[object, ...] = ()
    if workspace_id is not None:
        workspace_filter = "AND sessions.workspace_id = ?"
        parameters = (workspace_id,)
    with repository_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT observations.session_id, COUNT(*) AS n
            FROM observations
            JOIN sessions ON sessions.id = observations.session_id
            WHERE role IN ('user', 'assistant')
              AND sessions.status != 'deleted'
              {workspace_filter}
            GROUP BY observations.session_id
            """,  # nosec B608
            parameters,
        ).fetchall()
    return {str(row["session_id"]): int(row["n"]) for row in rows}


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
    workspace_id = _workspace_id_for("observations", observation_id)
    now = _now()
    _execute_insert(
        "slow_path_queue",
        {
            "id": queue_id,
            "workspace_id": workspace_id,
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


def claim_pending_batch(limit: int, *, workspace_id: str | None = None) -> list[RepositoryRecord]:
    """Claim pending or failed slow-path jobs for durable asynchronous processing."""
    if limit < 1:
        raise ValueError("limit must be a positive integer")
    if workspace_id is not None:
        require_active_workspace(workspace_id)
    now = _now()
    with _connect() as connection:
        if workspace_id is None:
            rows = connection.execute(
                """
                SELECT * FROM slow_path_queue
                WHERE status IN (?, ?)
                ORDER BY created_at ASC LIMIT ?
                """,
                ("pending", "failed", limit),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT * FROM slow_path_queue
                WHERE workspace_id = ? AND status IN (?, ?)
                ORDER BY created_at ASC LIMIT ?
                """,
                (workspace_id, "pending", "failed", limit),
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
                quarantine_reason = NULL,
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


def quarantine_queue_job(queue_id: str, reason: str) -> None:
    """Stop an ownership-invalid job without allowing automatic retries."""
    if not reason:
        raise ValueError("reason must not be empty")
    now = _now()
    _execute_write(
        """
        UPDATE slow_path_queue
        SET status = 'quarantined', last_error = ?, quarantine_reason = ?, updated_at = ?
        WHERE id = ? AND status = 'processing'
        """,
        (reason, reason, now, queue_id),
        missing_message=f"Queue item not found or not processing: {queue_id}",
    )


def slow_path_step_completed(workspace_id: str, observation_id: str, step_name: str) -> bool:
    """Return whether one observation step was durably completed."""
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT 1 FROM slow_path_step_journal
            WHERE workspace_id = ? AND observation_id = ? AND step_name = ?
              AND status = 'completed'
            """,
            (workspace_id, observation_id, step_name),
        ).fetchone()
    return row is not None


def mark_slow_path_step_started(workspace_id: str, observation_id: str, step_name: str) -> None:
    """Create or reset the journal row immediately before running a step."""
    require_active_workspace(workspace_id)
    now = _now()
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO slow_path_step_journal (
                id, workspace_id, observation_id, step_name, status,
                last_error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'running', NULL, ?, ?)
            ON CONFLICT(workspace_id, observation_id, step_name) DO UPDATE SET
                status = 'running', last_error = NULL, updated_at = excluded.updated_at
            """,
            (_new_id(), workspace_id, observation_id, step_name, now, now),
        )


def mark_slow_path_step_completed(workspace_id: str, observation_id: str, step_name: str) -> None:
    """Mark a journaled step complete only after its writes return successfully."""
    _update_slow_path_step(workspace_id, observation_id, step_name, "completed", None)


def mark_slow_path_step_failed(
    workspace_id: str, observation_id: str, step_name: str, error: str
) -> None:
    """Record a retryable step failure without losing the completed-step history."""
    _update_slow_path_step(workspace_id, observation_id, step_name, "failed", error)


def _update_slow_path_step(
    workspace_id: str,
    observation_id: str,
    step_name: str,
    status: str,
    error: str | None,
) -> None:
    _execute_write(
        """
        UPDATE slow_path_step_journal
        SET status = ?, last_error = ?, updated_at = ?
        WHERE workspace_id = ? AND observation_id = ? AND step_name = ?
        """,
        (status, error, _now(), workspace_id, observation_id, step_name),
        missing_message=f"Slow-path step was not started: {observation_id}/{step_name}",
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


CANONICAL_LOW_CONFIDENCE = 0.3


def create_atomic_fact(fact: RepositoryRecord) -> str:
    """Create an atomic fact and return its identifier.

    The raw extracted subject/predicate are stored verbatim for provenance, while
    canonical registry ids are resolved so downstream change detection can pair facts
    across inconsistent extraction wording.
    """
    record = _prepare_record(fact)
    record.setdefault("status", "active")
    _require_fields(
        "atomic_facts",
        record,
        {"subject", "predicate", "object", "confidence", "status", "source_observation_id"},
    )
    workspace_id = str(
        record.setdefault(
            "workspace_id",
            _workspace_id_for("observations", str(record["source_observation_id"])),
        )
    )
    _validate_record_enums(record, {"status": "fact_status"})
    record.setdefault(
        "canonical_subject_id",
        resolve_canonical_form(
            "canonical_subjects", str(record["subject"]), workspace_id=workspace_id
        ),
    )
    record.setdefault(
        "canonical_predicate_id",
        resolve_canonical_form(
            "canonical_predicates", str(record["predicate"]), workspace_id=workspace_id
        ),
    )
    return _insert_with_generated_id("atomic_facts", record)


def resolve_canonical_form(
    table: str,
    raw_value: str,
    *,
    workspace_id: str = LEGACY_WORKSPACE_ID,
) -> str | None:
    """Resolve a raw subject/predicate to a canonical registry id.

    Matches the normalized raw value against each registry row's canonical form and its
    aliases (case-insensitively). When nothing matches, a new low-confidence bucket is
    created from the raw form rather than failing silently, so unmapped wording is
    visible and reviewable instead of producing a silent zero-candidate outcome.
    """
    if table not in ("canonical_subjects", "canonical_predicates"):
        raise ValueError(f"Unknown canonical registry table: {table}")
    normalized = _normalize_canonical(raw_value)
    if not normalized:
        return None
    with _connect() as connection:
        rows = connection.execute(
            f"SELECT id, canonical_form, aliases_json FROM {table} "  # noqa: S608  # nosec B608
            "WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchall()
    for row in rows:
        if normalized == row["canonical_form"]:
            return str(row["id"])
        aliases = json.loads(row["aliases_json"]) if row["aliases_json"] else []
        if any(normalized == _normalize_canonical(str(alias)) for alias in aliases):
            return str(row["id"])
    return _insert_with_generated_id(
        table,
        {
            "workspace_id": workspace_id,
            "canonical_form": normalized,
            "aliases_json": [],
            "confidence": CANONICAL_LOW_CONFIDENCE,
        },
    )


def canonical_form_for_id(table: str, canonical_id: str | None) -> str | None:
    """Return the canonical_form string for a registry id, or None if absent."""
    if not canonical_id or table not in ("canonical_subjects", "canonical_predicates"):
        return None
    with _connect() as connection:
        row = connection.execute(
            f"SELECT canonical_form FROM {table} WHERE id = ?",  # noqa: S608  # nosec B608
            (canonical_id,),
        ).fetchone()
    return None if row is None else str(row["canonical_form"])


_CANONICAL_LEADING_DETERMINERS = frozenset(
    {"the", "a", "an", "my", "our", "your", "their", "his", "her", "its"}
)


def _normalize_canonical(value: str) -> str:
    """Normalize a raw subject/predicate for canonical matching.

    Case-folds, treats snake_case as spaces so ``prefers_language`` and
    ``prefers language`` share a bucket, and strips a single leading determiner so
    ``the speaker`` collapses onto the seeded ``speaker`` alias. Without this,
    trivial wording differences fork one entity into several canonical buckets and
    contradiction/supersession pairing (which requires a shared canonical subject)
    silently finds no candidates.
    """
    tokens = value.casefold().replace("_", " ").split()
    if len(tokens) > 1 and tokens[0] in _CANONICAL_LEADING_DETERMINERS:
        tokens = tokens[1:]
    return " ".join(tokens)


def create_entity(entity: RepositoryRecord) -> str:
    """Create an entity and return its identifier."""
    record = _prepare_record(entity)
    record.setdefault("workspace_id", LEGACY_WORKSPACE_ID)
    _require_fields("entities", record, {"name", "entity_type"})
    return _insert_with_generated_id("entities", record)


def create_graph_node(node: RepositoryRecord) -> str:
    """Create a graph node and return its identifier."""
    record = _prepare_record(node)
    record.setdefault("workspace_id", LEGACY_WORKSPACE_ID)
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
    record.setdefault(
        "workspace_id", _workspace_id_for("graph_nodes", str(record["source_node_id"]))
    )
    _validate_record_enums(record, {"edge_type": "graph_edge_type"})
    return _insert_with_generated_id("graph_edges", record)


def create_reflection(reflection: RepositoryRecord) -> str:
    """Create a reflection and return its identifier."""
    record = _prepare_record(reflection)
    record.setdefault("workspace_id", LEGACY_WORKSPACE_ID)
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
    prepared_record.setdefault(
        "workspace_id",
        _workspace_id_for("observations", str(prepared_record["source_observation_id"])),
    )
    _validate_record_enums(prepared_record, {"status": "foresight_status"})
    return _insert_with_generated_id("foresight_records", prepared_record)


def list_active_foresight(
    session_id: str | None = None, *, workspace_id: str = LEGACY_WORKSPACE_ID
) -> list[RepositoryRecord]:
    """List active foresight records, optionally scoped by source observation session."""
    if session_id is None:
        return _fetch_all(
            "SELECT * FROM foresight_records "
            "WHERE workspace_id = ? AND status = ? ORDER BY created_at ASC",
            (workspace_id, "active"),
        )
    return _fetch_all(
        """
        SELECT foresight_records.*
        FROM foresight_records
        JOIN observations ON observations.id = foresight_records.source_observation_id
        WHERE foresight_records.workspace_id = ? AND foresight_records.status = ?
          AND observations.session_id = ?
        ORDER BY foresight_records.created_at ASC
        """,
        (workspace_id, "active", session_id),
    )


def create_working_memory_item(item: RepositoryRecord) -> str:
    """Create a durable working-memory item and return its identifier."""
    record = _prepare_record(item)
    record.setdefault("workspace_id", LEGACY_WORKSPACE_ID)
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
    record.setdefault("workspace_id", LEGACY_WORKSPACE_ID)
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
    record.setdefault("workspace_id", _workspace_id_for("sessions", str(record["session_id"])))
    _validate_record_enums(record, {"retrieval_mode": "retrieval_mode"})
    return _insert_with_generated_id("retrieval_logs", record)


def create_prompt_log(log: RepositoryRecord) -> str:
    """Create a prompt-construction log and return its identifier."""
    record = _prepare_record(log)
    _require_fields("prompt_logs", record, {"session_id", "user_observation_id"})
    record.setdefault("workspace_id", _workspace_id_for("sessions", str(record["session_id"])))
    return _insert_with_generated_id("prompt_logs", record)


def create_answer_trace(trace: RepositoryRecord) -> str:
    """Create an answer trace and return its identifier."""
    record = _prepare_record(trace)
    _require_fields(
        "answer_traces",
        record,
        {
            "session_id",
            "user_observation_id",
            "assistant_observation_id",
            "retrieval_mode",
        },
    )
    record.setdefault("workspace_id", _workspace_id_for("sessions", str(record["session_id"])))
    return _insert_with_generated_id("answer_traces", record)


def get_answer_trace(trace_id: str) -> RepositoryRecord | None:
    """Fetch a single answer trace by its identifier."""
    rows = _fetch_all(
        "SELECT * FROM answer_traces WHERE id = ?",
        (trace_id,),
    )
    return rows[0] if rows else None


def list_answer_traces_by_session(session_id: str, limit: int = 20) -> list[RepositoryRecord]:
    """List answer traces for a session in reverse chronological order."""
    if limit < 1:
        raise ValueError("limit must be a positive integer")
    return _fetch_all(
        """
        SELECT * FROM answer_traces
        WHERE session_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (session_id, limit),
    )


def list_answer_traces_by_observation(
    user_observation_id: str,
) -> list[RepositoryRecord]:
    """List answer traces that reference a specific user observation."""
    return _fetch_all(
        """
        SELECT * FROM answer_traces
        WHERE user_observation_id = ?
        ORDER BY created_at DESC
        """,
        (user_observation_id,),
    )


def _configured_database_path() -> Path:
    if _DATABASE_PATH is not None:
        return _DATABASE_PATH
    return Path(os.environ.get(DATABASE_PATH_ENV, "./mira.db"))


def _connect() -> sqlite3.Connection:
    database_path = _configured_database_path()
    _ensure_database_initialized(database_path)
    return connect_sqlite(database_path)


def repository_connection() -> sqlite3.Connection:
    """Open a configured SQLite connection after ensuring the schema exists."""
    return _connect()


def _ensure_database_initialized(database_path: Path) -> None:
    resolved_path = database_path.resolve()
    if resolved_path in _INITIALIZED_DATABASE_PATHS and database_path.exists():
        return
    initialize_database(database_path)
    _INITIALIZED_DATABASE_PATHS.add(resolved_path)


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


def _workspace_id_for(table: str, record_id: str) -> str:
    """Resolve ownership from a canonical parent record and fail closed if absent."""
    if table not in _WORKSPACE_OWNED_TABLES:
        raise ValueError(f"Table is not workspace-owned: {table}")
    with _connect() as connection:
        row = connection.execute(
            f"SELECT workspace_id FROM {table} WHERE id = ?",  # noqa: S608  # nosec B608
            (record_id,),
        ).fetchone()
    if row is None or not row["workspace_id"]:
        raise ValueError(f"Workspace-owned {table} record not found: {record_id}")
    return str(row["workspace_id"])


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
