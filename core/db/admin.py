"""Read-only platform administration aggregates over canonical SQLite records."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from core.db.repositories import repository_connection


def get_admin_overview() -> dict[str, object]:
    """Return cross-workspace operational counts without user memory content."""
    now = datetime.now(timezone.utc)  # noqa: UP017
    now_iso = now.isoformat()
    seven_days_ago = (now - timedelta(days=7)).isoformat()
    thirty_days_ago = (now - timedelta(days=30)).isoformat()

    with repository_connection() as connection:
        users = {
            "registered": _count(
                connection,
                "SELECT COUNT(*) FROM users WHERE github_id IS NOT NULL",
            ),
            "new_last_7_days": _count(
                connection,
                "SELECT COUNT(*) FROM users WHERE github_id IS NOT NULL AND created_at >= ?",
                (seven_days_ago,),
            ),
            "new_last_30_days": _count(
                connection,
                "SELECT COUNT(*) FROM users WHERE github_id IS NOT NULL AND created_at >= ?",
                (thirty_days_ago,),
            ),
            "active_last_7_days": _count(
                connection,
                "SELECT COUNT(*) FROM users WHERE github_id IS NOT NULL AND last_login_at >= ?",
                (seven_days_ago,),
            ),
        }
        workspaces = _group_counts(
            connection,
            "SELECT workspace_type, COUNT(*) AS count FROM workspaces "
            "WHERE status = 'active' GROUP BY workspace_type",
            "workspace_type",
        )
        queue = _group_counts(
            connection,
            "SELECT status, COUNT(*) AS count FROM slow_path_queue GROUP BY status",
            "status",
        )
        activity = {
            "active_web_sessions": _count(
                connection,
                "SELECT COUNT(*) FROM auth_sessions WHERE revoked_at IS NULL AND expires_at > ?",
                (now_iso,),
            ),
            "conversations": _count(
                connection,
                "SELECT COUNT(*) FROM sessions WHERE status != 'deleted'",
            ),
            "observations": _count(connection, "SELECT COUNT(*) FROM observations"),
            "retrieval_traces": _count(connection, "SELECT COUNT(*) FROM retrieval_logs"),
        }
        oauth = {
            "registered_clients": _count(
                connection,
                "SELECT COUNT(*) FROM oauth_clients "
                "WHERE disabled_at IS NULL AND (expires_at IS NULL OR expires_at > ?)",
                (now_iso,),
            ),
            "active_access_tokens": _count(
                connection,
                "SELECT COUNT(*) FROM oauth_access_tokens "
                "WHERE revoked_at IS NULL AND expires_at > ?",
                (now_iso,),
            ),
        }
        registrations = [
            {"date": str(row["day"]), "count": int(row["count"])}
            for row in connection.execute(
                "SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS count "
                "FROM users WHERE github_id IS NOT NULL AND created_at >= ? "
                "GROUP BY day ORDER BY day",
                (thirty_days_ago,),
            ).fetchall()
        ]

    return {
        "generated_at": now_iso,
        "users": users,
        "workspaces": workspaces,
        "activity": activity,
        "queue": queue,
        "oauth": oauth,
        "registrations_last_30_days": registrations,
    }


def _count(connection: sqlite3.Connection, query: str, params: tuple[object, ...] = ()) -> int:
    row = connection.execute(query, params).fetchone()
    return int(row[0]) if row is not None else 0


def _group_counts(connection: sqlite3.Connection, query: str, key: str) -> dict[str, int]:
    rows = connection.execute(query).fetchall()
    return {str(row[key]): int(row["count"]) for row in rows}
