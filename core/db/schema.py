"""SQLite schema definition for MIRA's canonical durable records.

Ownership: Kelechi.
Related issue: ISSUE-005.
Architecture area: slow path.
"""

from __future__ import annotations

import sqlite3
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
    CREATE TABLE IF NOT EXISTS atomic_facts (
        id TEXT PRIMARY KEY,
        subject TEXT NOT NULL,
        predicate TEXT NOT NULL,
        object TEXT NOT NULL,
        confidence REAL NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        source_observation_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        valid_from TEXT,
        valid_until TEXT,
        FOREIGN KEY (source_observation_id) REFERENCES observations (id)
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
)


def schema_statements() -> list[str]:
    """Return idempotent SQLite DDL for MIRA's source-of-truth schema."""
    return [*_TABLE_STATEMENTS, *_INDEX_STATEMENTS]


def initialize_database(database_path: str | Path) -> None:
    """Create or update a SQLite database file with the canonical MIRA schema."""
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        for statement in schema_statements():
            connection.execute(statement)
