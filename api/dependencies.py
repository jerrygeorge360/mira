"""Shared FastAPI dependencies and SQLite helpers.

Ownership: Jerry.
Related issue: ISSUE-134.
Architecture area: API/server.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from typing import Any

from core.db.repositories import configure_database, repository_connection

DATABASE_PATH_ENV = "MIRA_DB_PATH"


def configure_runtime_database() -> None:
    """Configure the repository database from environment defaults."""
    configure_database(os.environ.get(DATABASE_PATH_ENV, "./mira.db"))


def fetch_one(query: str, params: Iterable[object] = ()) -> dict[str, object] | None:
    """Return one SQLite row as a plain dictionary."""
    with repository_connection() as connection:
        row = connection.execute(query, tuple(params)).fetchone()
    return _row_to_api_record(row) if row is not None else None


def fetch_all(query: str, params: Iterable[object] = ()) -> list[dict[str, object]]:
    """Return all SQLite rows as plain dictionaries."""
    with repository_connection() as connection:
        rows = connection.execute(query, tuple(params)).fetchall()
    return [_row_to_api_record(row) for row in rows]


def row_value(row: dict[str, object], key: str, default: Any = None) -> Any:
    """Read a row value with a small typed boundary for API serialization."""
    return row.get(key, default)


def _row_to_api_record(row: Any) -> dict[str, object]:
    """Convert a SQLite row into the repository-style API record shape."""
    record: dict[str, object] = {}
    for key in tuple(row.keys()):
        value = row[key]
        if key.endswith("_json") and value is not None:
            try:
                record[key] = json.loads(str(value))
            except json.JSONDecodeError:
                record[key] = value
        else:
            record[key] = value
    return record
