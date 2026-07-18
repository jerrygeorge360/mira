"""SQLite source-of-truth connection helpers.

Ownership: Kelechi.
Related issue: ISSUE-005.
Architecture area: slow path.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def connect_sqlite(database_path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection configured for MIRA source-of-truth access."""
    connection = sqlite3.connect(Path(database_path), timeout=30.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection
