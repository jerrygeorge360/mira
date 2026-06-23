"""SQLite schema definition for MIRA's canonical durable records.

Ownership: Kelechi.
Related issue: ISSUE-005.
Architecture area: slow path.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

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
)

_INDEX_STATEMENTS: tuple[str, ...] = (
    """
    CREATE INDEX IF NOT EXISTS idx_session_working_set_session_id
    ON session_working_set (session_id)
    """,
    "CREATE INDEX IF NOT EXISTS idx_session_working_set_status ON session_working_set (status)",
    "CREATE INDEX IF NOT EXISTS idx_session_working_set_scope ON session_working_set (scope)",
    "CREATE INDEX IF NOT EXISTS idx_session_working_set_priority ON session_working_set (priority)",
)


def schema_statements() -> list[str]:
    """Return idempotent SQLite DDL for the Session Working Set store."""
    return [*_TABLE_STATEMENTS, *_INDEX_STATEMENTS]


def initialize_database(database_path: str | Path) -> None:
    """Create or update a SQLite database file with required MIRA tables."""
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        for statement in schema_statements():
            connection.execute(statement)
