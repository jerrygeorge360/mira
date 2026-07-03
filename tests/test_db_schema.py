"""Verify the ISSUE-005 SQLite source-of-truth schema.

Ownership: MIRA contributors.
Related issue: ISSUE-005.
Architecture area: slow path.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from core.db.repositories import enum_values, validate_enum_value
from core.db.schema import initialize_database, schema_statements
from core.db.sqlite import connect_sqlite

REQUIRED_TABLES = {
    "sessions",
    "observations",
    "slow_path_queue",
    "session_working_set",
    "atomic_facts",
    "entities",
    "graph_nodes",
    "graph_edges",
    "reflections",
    "reflection_evidence",
    "foresight_records",
    "community_summaries",
    "working_memory",
    "retrieval_logs",
    "prompt_logs",
}

REQUIRED_INDEXES = {
    "idx_observations_session_id",
    "idx_observations_created_at",
    "idx_observations_processed_at",
    "idx_session_working_set_session_id",
    "idx_session_working_set_status",
    "idx_session_working_set_scope",
    "idx_session_working_set_priority",
}

REQUIRED_COLUMNS = {
    "sessions": {
        "id",
        "user_id",
        "title",
        "status",
        "created_at",
        "updated_at",
        "ended_at",
    },
    "observations": {
        "id",
        "session_id",
        "role",
        "content",
        "source",
        "metadata_json",
        "created_at",
        "processed_at",
    },
    "session_working_set": {
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
    },
    "slow_path_queue": {
        "id",
        "observation_id",
        "status",
        "attempt_count",
        "last_error",
        "created_at",
        "updated_at",
    },
    "atomic_facts": {
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
    },
    "entities": {
        "id",
        "name",
        "entity_type",
        "aliases_json",
        "created_at",
        "updated_at",
    },
    "graph_nodes": {
        "id",
        "node_type",
        "source_table",
        "source_id",
        "label",
        "metadata_json",
        "created_at",
    },
    "graph_edges": {
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
    },
    "reflections": {
        "id",
        "reflection_type",
        "content",
        "confidence",
        "status",
        "created_at",
        "updated_at",
        "stale_reason",
    },
    "reflection_evidence": {
        "id",
        "reflection_id",
        "observation_id",
        "created_at",
    },
    "foresight_records": {
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
    },
    "community_summaries": {
        "id",
        "community_id",
        "title",
        "summary",
        "member_nodes_json",
        "created_at",
        "updated_at",
    },
    "working_memory": {
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
    },
    "retrieval_logs": {
        "id",
        "session_id",
        "query",
        "retrieval_mode",
        "retrieved_records_json",
        "sufficiency_json",
        "created_at",
    },
    "prompt_logs": {
        "id",
        "session_id",
        "user_observation_id",
        "included_session_items_json",
        "included_memory_items_json",
        "included_recent_turns_json",
        "token_budget_json",
        "created_at",
    },
}


def _names(connection: sqlite3.Connection, object_type: str) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = ? AND name NOT LIKE 'sqlite_%'",
        (object_type,),
    ).fetchall()
    return {str(row[0]) for row in rows}


def _columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row[1]) for row in rows}


def test_database_initializes_from_clean_file(tmp_path: Path) -> None:
    """A clean SQLite file can be initialized with the source-of-truth schema."""
    database_path = tmp_path / "mira.sqlite3"

    initialize_database(database_path)

    assert database_path.is_file()
    with connect_sqlite(database_path) as connection:
        assert _names(connection, "table") >= REQUIRED_TABLES


def test_all_required_indexes_exist(tmp_path: Path) -> None:
    """Required query indexes are present after initialization."""
    database_path = tmp_path / "mira.sqlite3"
    initialize_database(database_path)

    with connect_sqlite(database_path) as connection:
        assert _names(connection, "index") >= REQUIRED_INDEXES


def test_schema_creation_is_idempotent(tmp_path: Path) -> None:
    """Running schema initialization repeatedly preserves the same table set."""
    database_path = tmp_path / "mira.sqlite3"

    initialize_database(database_path)
    initialize_database(database_path)

    with connect_sqlite(database_path) as connection:
        assert _names(connection, "table") >= REQUIRED_TABLES


def test_required_columns_exist(tmp_path: Path) -> None:
    """Table columns match the database contract."""
    database_path = tmp_path / "mira.sqlite3"
    initialize_database(database_path)

    with connect_sqlite(database_path) as connection:
        for table_name, expected_columns in REQUIRED_COLUMNS.items():
            assert expected_columns <= _columns(connection, table_name)


def test_schema_statements_are_idempotent() -> None:
    """Every DDL statement can safely run more than once."""
    statements = schema_statements()

    assert statements
    assert all("IF NOT EXISTS" in statement for statement in statements)


def test_repository_enum_helpers_validate_allowed_values() -> None:
    """Repository helpers accept only known enum-like values."""
    validate_enum_value("retrieval_mode", "quick")
    validate_enum_value("retrieval_mode", "general")

    with pytest.raises(ValueError):
        validate_enum_value("retrieval_mode", "slow")

    with pytest.raises(KeyError):
        enum_values("not_a_real_enum")
