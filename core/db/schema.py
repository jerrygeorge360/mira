"""SQLite schema and connection management for MIRA.

Defines and migrates the relational schema backing observations, consolidated
memories, and the knowledge graph (nodes and edges), and hands out connections
to the rest of the system.

ISSUE-014: SQLite schema.
"""

from __future__ import annotations

import sqlite3


def connect(db_path: str) -> sqlite3.Connection:
    """Open a connection to the MIRA SQLite database.

    Args:
        db_path: Filesystem path to the SQLite database file.

    Returns:
        An open SQLite connection.
    """
    raise NotImplementedError


def initialise_schema(connection: sqlite3.Connection) -> None:
    """Create all MIRA tables and indexes if they do not already exist.

    Args:
        connection: An open connection to the target database.
    """
    raise NotImplementedError
