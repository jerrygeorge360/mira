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

# SQLite is the source of truth for ISSUE-005. Enum-like fields intentionally remain
# TEXT columns here; repository helpers validate allowed values before writes.
_TABLE_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        title TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        ended_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS observations (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT 'chat',
        metadata_json TEXT,
        created_at TEXT NOT NULL,
        processed_at TEXT,
        FOREIGN KEY (session_id) REFERENCES sessions (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS slow_path_queue (
        id TEXT PRIMARY KEY,
        observation_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        attempt_count INTEGER NOT NULL DEFAULT 0,
        last_error TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
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
        canonical_form TEXT NOT NULL UNIQUE,
        aliases_json TEXT,
        confidence REAL NOT NULL DEFAULT 1.0,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS canonical_predicates (
        id TEXT PRIMARY KEY,
        canonical_form TEXT NOT NULL UNIQUE,
        aliases_json TEXT,
        confidence REAL NOT NULL DEFAULT 1.0,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS atomic_facts (
        id TEXT PRIMARY KEY,
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
        FOREIGN KEY (source_observation_id) REFERENCES observations (id),
        FOREIGN KEY (canonical_subject_id) REFERENCES canonical_subjects (id),
        FOREIGN KEY (canonical_predicate_id) REFERENCES canonical_predicates (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS entities (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        aliases_json TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_nodes (
        id TEXT PRIMARY KEY,
        node_type TEXT NOT NULL,
        source_table TEXT,
        source_id TEXT,
        label TEXT NOT NULL,
        metadata_json TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_edges (
        id TEXT PRIMARY KEY,
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
        FOREIGN KEY (source_node_id) REFERENCES graph_nodes (id),
        FOREIGN KEY (target_node_id) REFERENCES graph_nodes (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reflections (
        id TEXT PRIMARY KEY,
        reflection_type TEXT NOT NULL,
        content TEXT NOT NULL,
        confidence REAL NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        stale_reason TEXT
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
        FOREIGN KEY (source_observation_id) REFERENCES observations (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS community_summaries (
        id TEXT PRIMARY KEY,
        community_id TEXT NOT NULL,
        title TEXT NOT NULL,
        summary TEXT NOT NULL,
        member_nodes_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS working_memory (
        id TEXT PRIMARY KEY,
        content TEXT NOT NULL,
        memory_type TEXT NOT NULL,
        scope TEXT NOT NULL,
        priority REAL NOT NULL,
        status TEXT NOT NULL,
        source_record_type TEXT,
        source_record_id TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS retrieval_logs (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        query TEXT NOT NULL,
        retrieval_mode TEXT NOT NULL,
        retrieved_records_json TEXT NOT NULL,
        sufficiency_json TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES sessions (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS prompt_logs (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        user_observation_id TEXT NOT NULL,
        included_session_items_json TEXT,
        included_memory_items_json TEXT,
        included_recent_turns_json TEXT,
        token_budget_json TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES sessions (id),
        FOREIGN KEY (user_observation_id) REFERENCES observations (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS answer_traces (
        id TEXT PRIMARY KEY,
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
        FOREIGN KEY (session_id) REFERENCES sessions (id),
        FOREIGN KEY (user_observation_id) REFERENCES observations (id),
        FOREIGN KEY (assistant_observation_id) REFERENCES observations (id)
    )
    """,
)

_INDEX_STATEMENTS: tuple[str, ...] = (
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
    """
    CREATE INDEX IF NOT EXISTS idx_atomic_facts_canonical
    ON atomic_facts (canonical_subject_id, canonical_predicate_id)
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
    return [*_TABLE_STATEMENTS, *_INDEX_STATEMENTS]


def initialize_database(database_path: str | Path) -> None:
    """Create or update a SQLite database file with the canonical MIRA schema."""
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        for statement in _TABLE_STATEMENTS:
            connection.execute(statement)
        # Migrate before indexes so the canonical-column index can be created on a
        # pre-existing atomic_facts table that predates those columns.
        _migrate_atomic_facts_canonical(connection)
        for statement in _INDEX_STATEMENTS:
            connection.execute(statement)
        _seed_canonical_registries(connection)


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


def _seed_canonical_registries(connection: sqlite3.Connection) -> None:
    """Idempotently seed the canonical subject/predicate vocabulary and their aliases."""
    now = datetime.now(timezone.utc).isoformat()  # noqa: UP017
    for table, seeds in (
        ("canonical_subjects", _SEED_CANONICAL_SUBJECTS),
        ("canonical_predicates", _SEED_CANONICAL_PREDICATES),
    ):
        for canonical_form, aliases in seeds.items():
            connection.execute(
                f"INSERT OR IGNORE INTO {table} "  # noqa: S608  # nosec B608
                "(id, canonical_form, aliases_json, confidence, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (uuid.uuid4().hex, canonical_form, json.dumps(list(aliases)), 1.0, now),
            )
