"""SQLite schema definition for MIRA's canonical durable records.

Ownership: Kelechi.
Related issue: ISSUE-005.
Architecture area: slow path.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

LEGACY_WORKSPACE_ID = "workspace_legacy_default"
LEGACY_WORKSPACE_SLUG = "legacy-default"
WORKSPACE_MIGRATION_ID = "0002_workspace_ownership"

# SQLite is the source of truth for ISSUE-005. Enum-like fields intentionally remain
# TEXT columns here; repository helpers validate allowed values before writes.
_TABLE_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        id TEXT PRIMARY KEY,
        applied_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS runtime_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        github_id TEXT UNIQUE,
        github_login TEXT,
        display_name TEXT,
        avatar_url TEXT,
        email TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        last_login_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS workspaces (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        slug TEXT NOT NULL UNIQUE,
        owner_user_id TEXT,
        workspace_type TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        expires_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (owner_user_id) REFERENCES users (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS workspace_members (
        workspace_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        role TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (workspace_id, user_id),
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id),
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS auth_sessions (
        id TEXT PRIMARY KEY,
        token_hash TEXT NOT NULL UNIQUE,
        csrf_token_hash TEXT NOT NULL,
        user_id TEXT NOT NULL,
        workspace_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        last_used_at TEXT,
        revoked_at TEXT,
        FOREIGN KEY (user_id) REFERENCES users (id),
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS oauth_states (
        id TEXT PRIMARY KEY,
        state_hash TEXT NOT NULL UNIQUE,
        redirect_uri TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        consumed_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS oauth_clients (
        client_id TEXT PRIMARY KEY,
        client_name TEXT NOT NULL,
        redirect_uris_json TEXT NOT NULL,
        scope TEXT NOT NULL,
        token_endpoint_auth_method TEXT NOT NULL DEFAULT 'none',
        client_type TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT,
        disabled_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS oauth_authorization_requests (
        id TEXT PRIMARY KEY,
        request_token_hash TEXT NOT NULL UNIQUE,
        code_hash TEXT UNIQUE,
        client_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        workspace_id TEXT NOT NULL,
        redirect_uri TEXT NOT NULL,
        scope TEXT NOT NULL,
        resource TEXT NOT NULL,
        state TEXT,
        code_challenge TEXT NOT NULL,
        code_challenge_method TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        code_expires_at TEXT,
        consumed_at TEXT,
        FOREIGN KEY (client_id) REFERENCES oauth_clients (client_id),
        FOREIGN KEY (user_id) REFERENCES users (id),
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS oauth_access_tokens (
        id TEXT PRIMARY KEY,
        token_hash TEXT NOT NULL UNIQUE,
        client_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        workspace_id TEXT NOT NULL,
        scope TEXT NOT NULL,
        resource TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        revoked_at TEXT,
        FOREIGN KEY (client_id) REFERENCES oauth_clients (client_id),
        FOREIGN KEY (user_id) REFERENCES users (id),
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS oauth_refresh_tokens (
        id TEXT PRIMARY KEY,
        token_hash TEXT NOT NULL UNIQUE,
        client_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        workspace_id TEXT NOT NULL,
        scope TEXT NOT NULL,
        resource TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        rotated_at TEXT,
        revoked_at TEXT,
        FOREIGN KEY (client_id) REFERENCES oauth_clients (client_id),
        FOREIGN KEY (user_id) REFERENCES users (id),
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS demo_issuances (
        id TEXT PRIMARY KEY,
        requester_hash TEXT NOT NULL,
        user_id TEXT,
        workspace_id TEXT,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        cleaned_at TEXT,
        FOREIGN KEY (user_id) REFERENCES users (id),
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        title TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        ended_at TEXT,
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS observations (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        session_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT 'chat',
        metadata_json TEXT,
        created_at TEXT NOT NULL,
        processed_at TEXT,
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id),
        FOREIGN KEY (session_id) REFERENCES sessions (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS slow_path_queue (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        observation_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        attempt_count INTEGER NOT NULL DEFAULT 0,
        last_error TEXT,
        quarantine_reason TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id),
        FOREIGN KEY (observation_id) REFERENCES observations (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS slow_path_step_journal (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        observation_id TEXT NOT NULL,
        step_name TEXT NOT NULL,
        status TEXT NOT NULL,
        last_error TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (workspace_id, observation_id, step_name),
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id),
        FOREIGN KEY (observation_id) REFERENCES observations (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS session_working_set (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        type TEXT NOT NULL,
        content TEXT NOT NULL,
        scope TEXT NOT NULL,
        status TEXT NOT NULL,
        priority REAL NOT NULL,
        explicitness_label TEXT NOT NULL,
        evidence_span TEXT,
        source_observations_json TEXT NOT NULL,
        supersedes_json TEXT,
        origin TEXT NOT NULL DEFAULT 'micro_path',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        expires_at TEXT,
        resolution_reason TEXT,
        FOREIGN KEY (session_id) REFERENCES sessions (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS canonical_subjects (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        canonical_form TEXT NOT NULL,
        aliases_json TEXT,
        confidence REAL NOT NULL DEFAULT 1.0,
        created_at TEXT NOT NULL,
        UNIQUE (workspace_id, canonical_form),
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS canonical_predicates (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        canonical_form TEXT NOT NULL,
        aliases_json TEXT,
        confidence REAL NOT NULL DEFAULT 1.0,
        created_at TEXT NOT NULL,
        UNIQUE (workspace_id, canonical_form),
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS atomic_facts (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        subject TEXT NOT NULL,
        predicate TEXT NOT NULL,
        object TEXT NOT NULL,
        confidence REAL NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        source_observation_id TEXT NOT NULL,
        canonical_subject_id TEXT,
        canonical_predicate_id TEXT,
        created_at TEXT NOT NULL,
        valid_from TEXT,
        valid_until TEXT,
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id),
        FOREIGN KEY (source_observation_id) REFERENCES observations (id),
        FOREIGN KEY (canonical_subject_id) REFERENCES canonical_subjects (id),
        FOREIGN KEY (canonical_predicate_id) REFERENCES canonical_predicates (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS entities (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        name TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        aliases_json TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_nodes (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        node_type TEXT NOT NULL,
        source_table TEXT,
        source_id TEXT,
        label TEXT NOT NULL,
        metadata_json TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_edges (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        source_node_id TEXT NOT NULL,
        target_node_id TEXT NOT NULL,
        edge_type TEXT NOT NULL,
        confidence REAL NOT NULL,
        source_observations_json TEXT NOT NULL,
        metadata_json TEXT,
        valid_from TEXT,
        valid_until TEXT,
        created_at TEXT NOT NULL,
        invalidated_at TEXT,
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id),
        FOREIGN KEY (source_node_id) REFERENCES graph_nodes (id),
        FOREIGN KEY (target_node_id) REFERENCES graph_nodes (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reflections (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        reflection_type TEXT NOT NULL,
        content TEXT NOT NULL,
        confidence REAL NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        stale_reason TEXT,
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reflection_evidence (
        id TEXT PRIMARY KEY,
        reflection_id TEXT NOT NULL,
        observation_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (reflection_id) REFERENCES reflections (id),
        FOREIGN KEY (observation_id) REFERENCES observations (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS foresight_records (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        content TEXT NOT NULL,
        reason TEXT,
        status TEXT NOT NULL,
        source_observation_id TEXT NOT NULL,
        valid_from TEXT,
        valid_until TEXT,
        always_inject INTEGER NOT NULL DEFAULT 0,
        resolved_by TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id),
        FOREIGN KEY (source_observation_id) REFERENCES observations (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS community_summaries (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        community_id TEXT NOT NULL,
        title TEXT NOT NULL,
        summary TEXT NOT NULL,
        member_nodes_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id),
        UNIQUE (workspace_id, community_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS working_memory (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        content TEXT NOT NULL,
        memory_type TEXT NOT NULL,
        scope TEXT NOT NULL,
        priority REAL NOT NULL,
        status TEXT NOT NULL,
        source_record_type TEXT,
        source_record_id TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS retrieval_logs (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        session_id TEXT NOT NULL,
        query TEXT NOT NULL,
        retrieval_mode TEXT NOT NULL,
        retrieved_records_json TEXT NOT NULL,
        sufficiency_json TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id),
        FOREIGN KEY (session_id) REFERENCES sessions (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS prompt_logs (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        session_id TEXT NOT NULL,
        user_observation_id TEXT NOT NULL,
        included_session_items_json TEXT,
        included_memory_items_json TEXT,
        included_recent_turns_json TEXT,
        token_budget_json TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id),
        FOREIGN KEY (session_id) REFERENCES sessions (id),
        FOREIGN KEY (user_observation_id) REFERENCES observations (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS answer_traces (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        session_id TEXT NOT NULL,
        user_observation_id TEXT NOT NULL,
        assistant_observation_id TEXT NOT NULL,
        retrieval_mode TEXT NOT NULL,
        retrieved_observation_ids_json TEXT,
        retrieved_fact_ids_json TEXT,
        session_item_ids_json TEXT,
        hot_memory_ids_json TEXT,
        graph_path_ids_json TEXT,
        community_summary_ids_json TEXT,
        sufficiency_json TEXT,
        prompt_sections_json TEXT,
        hydration_ids_json TEXT,
        retrieval_log_id TEXT,
        prompt_log_id TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id),
        FOREIGN KEY (session_id) REFERENCES sessions (id),
        FOREIGN KEY (user_observation_id) REFERENCES observations (id),
        FOREIGN KEY (assistant_observation_id) REFERENCES observations (id)
    )
    """,
)

_INDEX_STATEMENTS: tuple[str, ...] = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_personal_workspace_owner "
    "ON workspaces (owner_user_id) "
    "WHERE workspace_type = 'personal' AND owner_user_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_workspace_members_user ON workspace_members (user_id)",
    "CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions (user_id, expires_at)",
    "CREATE INDEX IF NOT EXISTS idx_oauth_authorization_client "
    "ON oauth_authorization_requests (client_id, status, expires_at)",
    "CREATE INDEX IF NOT EXISTS idx_oauth_access_workspace "
    "ON oauth_access_tokens (workspace_id, expires_at, revoked_at)",
    "CREATE INDEX IF NOT EXISTS idx_oauth_refresh_client "
    "ON oauth_refresh_tokens (client_id, expires_at, revoked_at)",
    "CREATE INDEX IF NOT EXISTS idx_demo_issuances_requester "
    "ON demo_issuances (requester_hash, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_workspace_updated "
    "ON sessions (workspace_id, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_observations_workspace_created "
    "ON observations (workspace_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_queue_workspace_status "
    "ON slow_path_queue (workspace_id, status, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_step_journal_workspace_observation "
    "ON slow_path_step_journal (workspace_id, observation_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_observations_session_id ON observations (session_id)",
    "CREATE INDEX IF NOT EXISTS idx_observations_created_at ON observations (created_at)",
    "CREATE INDEX IF NOT EXISTS idx_observations_processed_at ON observations (processed_at)",
    """
    CREATE INDEX IF NOT EXISTS idx_session_working_set_session_id
    ON session_working_set (session_id)
    """,
    "CREATE INDEX IF NOT EXISTS idx_session_working_set_status ON session_working_set (status)",
    "CREATE INDEX IF NOT EXISTS idx_session_working_set_scope ON session_working_set (scope)",
    "CREATE INDEX IF NOT EXISTS idx_session_working_set_priority ON session_working_set (priority)",
    "CREATE INDEX IF NOT EXISTS idx_answer_traces_sid ON answer_traces (session_id)",
    "CREATE INDEX IF NOT EXISTS idx_answer_traces_uid ON answer_traces (user_observation_id)",
    "CREATE INDEX IF NOT EXISTS idx_facts_workspace_status "
    "ON atomic_facts (workspace_id, status, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_graph_nodes_workspace_source "
    "ON graph_nodes (workspace_id, source_table, source_id)",
    "CREATE INDEX IF NOT EXISTS idx_graph_edges_workspace_source "
    "ON graph_edges (workspace_id, source_node_id)",
    "CREATE INDEX IF NOT EXISTS idx_graph_edges_workspace_target "
    "ON graph_edges (workspace_id, target_node_id)",
    "CREATE INDEX IF NOT EXISTS idx_reflections_workspace_status "
    "ON reflections (workspace_id, status, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_foresight_workspace_status "
    "ON foresight_records (workspace_id, status, valid_from, valid_until)",
    "CREATE INDEX IF NOT EXISTS idx_working_memory_workspace_status "
    "ON working_memory (workspace_id, status, priority)",
    "CREATE INDEX IF NOT EXISTS idx_traces_workspace_session "
    "ON answer_traces (workspace_id, session_id, created_at)",
    """
    CREATE INDEX IF NOT EXISTS idx_atomic_facts_canonical
    ON atomic_facts (canonical_subject_id, canonical_predicate_id)
    """,
)

_WORKSPACE_TABLES = (
    "sessions",
    "observations",
    "slow_path_queue",
    "slow_path_step_journal",
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
)

_OWNERSHIP_TRIGGER_STATEMENTS: tuple[str, ...] = tuple(
    statement
    for table in _WORKSPACE_TABLES
    for statement in (
        f"""
        CREATE TRIGGER IF NOT EXISTS trg_{table}_workspace_insert
        BEFORE INSERT ON {table}
        WHEN NEW.workspace_id IS NULL
        BEGIN
            SELECT RAISE(ABORT, 'workspace_id is required for {table}');
        END
        """,
        f"""
        CREATE TRIGGER IF NOT EXISTS trg_{table}_workspace_update
        BEFORE UPDATE OF workspace_id ON {table}
        WHEN NEW.workspace_id IS NULL OR NEW.workspace_id != OLD.workspace_id
        BEGIN
            SELECT RAISE(ABORT, 'workspace_id is immutable for {table}');
        END
        """,
    )
) + (
    """
    CREATE TRIGGER IF NOT EXISTS trg_observation_session_workspace
    BEFORE INSERT ON observations
    WHEN NOT EXISTS (
        SELECT 1 FROM sessions
        WHERE id = NEW.session_id AND workspace_id = NEW.workspace_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'observation workspace does not match session');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_queue_observation_workspace
    BEFORE INSERT ON slow_path_queue
    WHEN NOT EXISTS (
        SELECT 1 FROM observations
        WHERE id = NEW.observation_id AND workspace_id = NEW.workspace_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'queue workspace does not match observation');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_step_journal_observation_workspace
    BEFORE INSERT ON slow_path_step_journal
    WHEN NOT EXISTS (
        SELECT 1 FROM observations
        WHERE id = NEW.observation_id AND workspace_id = NEW.workspace_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'step journal workspace does not match observation');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_graph_edge_workspace
    BEFORE INSERT ON graph_edges
    WHEN NOT EXISTS (
        SELECT 1
        FROM graph_nodes AS source, graph_nodes AS target
        WHERE source.id = NEW.source_node_id
          AND target.id = NEW.target_node_id
          AND source.workspace_id = NEW.workspace_id
          AND target.workspace_id = NEW.workspace_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'graph edge endpoints must share its workspace');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_reflection_evidence_workspace
    BEFORE INSERT ON reflection_evidence
    WHEN NOT EXISTS (
        SELECT 1
        FROM reflections
        JOIN observations ON observations.id = NEW.observation_id
        WHERE reflections.id = NEW.reflection_id
          AND reflections.workspace_id = observations.workspace_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'reflection evidence must share one workspace');
    END
    """,
)

# Canonical registries seed the alias vocabulary that lets contradiction/supersession
# detection pair facts whose raw subject/predicate wording varies across extractions.
# Auto-created buckets (raw form, low confidence) cover anything not seeded here.
_SEED_CANONICAL_SUBJECTS: dict[str, tuple[str, ...]] = {
    "user": ("i", "me", "my", "myself", "speaker", "user", "you"),
    "assistant": ("assistant", "agent", "mira", "ai"),
}
_SEED_CANONICAL_PREDICATES: dict[str, tuple[str, ...]] = {
    "prefers": ("prefer", "prefers", "likes", "favorite"),
    "uses": ("use", "uses", "using", "is using", "is currently using"),
    "decided": ("decide", "decided", "chose", "choose"),
    "switched_from": ("switched from", "switched_from", "migrated from", "moved from"),
    "works_on": ("work on", "works on", "working on", "works_on"),
}


def schema_statements() -> list[str]:
    """Return idempotent SQLite DDL for MIRA's source-of-truth schema."""
    return [*_TABLE_STATEMENTS, *_INDEX_STATEMENTS, *_OWNERSHIP_TRIGGER_STATEMENTS]


def initialize_database(database_path: str | Path) -> None:
    """Create or update a SQLite database file with the canonical MIRA schema."""
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        # Canonical registry migration rebuilds two tables to replace their old global
        # uniqueness constraint. Foreign keys are validated before this function returns.
        connection.execute("PRAGMA foreign_keys = OFF")
        for statement in _TABLE_STATEMENTS:
            connection.execute(statement)
        _ensure_legacy_workspace(connection)
        _migrate_workspace_ownership(connection)
        _migrate_slow_path_runtime(connection)
        _migrate_atomic_facts_canonical(connection)
        _migrate_canonical_registry_uniqueness(connection)
        for statement in _INDEX_STATEMENTS:
            connection.execute(statement)
        _install_ownership_triggers(connection)
        _seed_canonical_registries(connection, LEGACY_WORKSPACE_ID)
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations (id, applied_at) VALUES (?, ?)",
            (WORKSPACE_MIGRATION_ID, _now()),
        )
        connection.commit()
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(f"workspace migration left foreign-key violations: {violations!r}")
    finally:
        connection.close()


def _ensure_legacy_workspace(connection: sqlite3.Connection) -> None:
    now = _now()
    connection.execute(
        """
        INSERT OR IGNORE INTO workspaces (
            id, name, slug, owner_user_id, workspace_type, status,
            expires_at, created_at, updated_at
        ) VALUES (?, ?, ?, NULL, 'legacy', 'active', NULL, ?, ?)
        """,
        (LEGACY_WORKSPACE_ID, "Legacy local workspace", LEGACY_WORKSPACE_SLUG, now, now),
    )


def _install_ownership_triggers(connection: sqlite3.Connection) -> None:
    """Replace ownership triggers so upgraded databases receive hardened definitions."""
    trigger_names = [
        *(f"trg_{table}_workspace_insert" for table in _WORKSPACE_TABLES),
        *(f"trg_{table}_workspace_update" for table in _WORKSPACE_TABLES),
        "trg_observation_session_workspace",
        "trg_queue_observation_workspace",
        "trg_step_journal_observation_workspace",
        "trg_graph_edge_workspace",
        "trg_reflection_evidence_workspace",
    ]
    for trigger_name in trigger_names:
        connection.execute(f"DROP TRIGGER IF EXISTS {trigger_name}")  # noqa: S608  # nosec B608
    for statement in _OWNERSHIP_TRIGGER_STATEMENTS:
        connection.execute(statement)


def _migrate_workspace_ownership(connection: sqlite3.Connection) -> None:
    """Add and backfill workspace ownership on databases created before workspaces."""
    for table in _WORKSPACE_TABLES:
        columns = _table_columns(connection, table)
        if "workspace_id" not in columns:
            connection.execute(
                f"ALTER TABLE {table} ADD COLUMN workspace_id TEXT "  # noqa: S608  # nosec B608
                "REFERENCES workspaces (id)"
            )
        connection.execute(
            f"UPDATE {table} SET workspace_id = ? WHERE workspace_id IS NULL",  # noqa: S608  # nosec B608
            (LEGACY_WORKSPACE_ID,),
        )


def _migrate_slow_path_runtime(connection: sqlite3.Connection) -> None:
    """Add retry-safety fields introduced after the workspace migration."""
    queue_columns = _table_columns(connection, "slow_path_queue")
    if "quarantine_reason" not in queue_columns:
        connection.execute("ALTER TABLE slow_path_queue ADD COLUMN quarantine_reason TEXT")


def _migrate_canonical_registry_uniqueness(connection: sqlite3.Connection) -> None:
    """Replace legacy global canonical uniqueness with per-workspace uniqueness."""
    for table in ("canonical_subjects", "canonical_predicates"):
        if not _has_global_canonical_unique_index(connection, table):
            continue
        replacement = f"{table}__workspace_v2"
        connection.execute(f"DROP TABLE IF EXISTS {replacement}")  # noqa: S608  # nosec B608
        connection.execute(
            f"""
            CREATE TABLE {replacement} (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                canonical_form TEXT NOT NULL,
                aliases_json TEXT,
                confidence REAL NOT NULL DEFAULT 1.0,
                created_at TEXT NOT NULL,
                UNIQUE (workspace_id, canonical_form),
                FOREIGN KEY (workspace_id) REFERENCES workspaces (id)
            )
            """  # noqa: S608  # nosec B608
        )
        connection.execute(
            f"""
            INSERT INTO {replacement} (
                id, workspace_id, canonical_form, aliases_json, confidence, created_at
            )
            SELECT id, workspace_id, canonical_form, aliases_json, confidence, created_at
            FROM {table}
            """  # noqa: S608  # nosec B608
        )
        connection.execute(f"DROP TABLE {table}")  # noqa: S608  # nosec B608
        connection.execute(
            f"ALTER TABLE {replacement} RENAME TO {table}"  # noqa: S608  # nosec B608
        )


def _has_global_canonical_unique_index(connection: sqlite3.Connection, table: str) -> bool:
    for index in connection.execute(f"PRAGMA index_list({table})"):  # noqa: S608  # nosec B608
        if not bool(index[2]):
            continue
        columns = [
            str(row[2])
            for row in connection.execute(f"PRAGMA index_info({index[1]})")  # noqa: S608  # nosec B608
        ]
        if columns == ["canonical_form"]:
            return True
    return False


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info({table})")  # noqa: S608  # nosec B608
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()  # noqa: UP017


def _migrate_atomic_facts_canonical(connection: sqlite3.Connection) -> None:
    """Add canonical FK columns to an atomic_facts table created before they existed.

    ``CREATE TABLE IF NOT EXISTS`` leaves a pre-existing table untouched, so databases
    created before this change keep the old shape. SQLite allows adding a nullable
    ``REFERENCES`` column to a populated table (existing rows get NULL, satisfying the
    foreign key), which lets legacy rows coexist without a backfill.
    """
    existing = {row[1] for row in connection.execute("PRAGMA table_info(atomic_facts)")}
    if "canonical_subject_id" not in existing:
        connection.execute(
            "ALTER TABLE atomic_facts "
            "ADD COLUMN canonical_subject_id TEXT REFERENCES canonical_subjects (id)"
        )
    if "canonical_predicate_id" not in existing:
        connection.execute(
            "ALTER TABLE atomic_facts "
            "ADD COLUMN canonical_predicate_id TEXT REFERENCES canonical_predicates (id)"
        )


def seed_workspace_canonical_registries(connection: sqlite3.Connection, workspace_id: str) -> None:
    """Idempotently seed canonical vocabulary for one workspace."""
    _seed_canonical_registries(connection, workspace_id)


def _seed_canonical_registries(connection: sqlite3.Connection, workspace_id: str) -> None:
    """Idempotently seed canonical vocabulary without sharing user-derived buckets."""
    now = _now()
    for table, seeds in (
        ("canonical_subjects", _SEED_CANONICAL_SUBJECTS),
        ("canonical_predicates", _SEED_CANONICAL_PREDICATES),
    ):
        for canonical_form, aliases in seeds.items():
            connection.execute(
                f"INSERT OR IGNORE INTO {table} "  # noqa: S608  # nosec B608
                "(id, workspace_id, canonical_form, aliases_json, confidence, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    uuid.uuid4().hex,
                    workspace_id,
                    canonical_form,
                    json.dumps(list(aliases)),
                    1.0,
                    now,
                ),
            )
