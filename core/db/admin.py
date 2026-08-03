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


def get_llm_usage_overview(days: int = 7, limit: int = 30) -> dict[str, object]:
    """Aggregate measured LLM consumption without exposing prompt content."""
    if days < 1 or days > 365:
        raise ValueError("days must be between 1 and 365")
    if limit < 1 or limit > 200:
        raise ValueError("limit must be between 1 and 200")
    now = datetime.now(timezone.utc)  # noqa: UP017
    since = (now - timedelta(days=days)).isoformat()
    with repository_connection() as connection:
        totals_row = connection.execute(
            """
            SELECT
                COUNT(*) AS calls,
                COALESCE(SUM(CASE WHEN status = 'succeeded' THEN 1 ELSE 0 END), 0)
                    AS successful_calls,
                COALESCE(SUM(CASE WHEN usage_source = 'provider' THEN 1 ELSE 0 END), 0)
                    AS provider_measured_calls,
                COALESCE(SUM(input_tokens), 0) AS input_tokens,
                COALESCE(SUM(output_tokens), 0) AS output_tokens,
                COALESCE(SUM(total_tokens), 0) AS total_tokens,
                COALESCE(SUM(estimated_input_tokens), 0) AS estimated_input_tokens,
                COALESCE(SUM(estimated_cost_usd), 0.0) AS estimated_cost_usd
            FROM llm_usage_events
            WHERE created_at >= ?
            """,
            (since,),
        ).fetchone()
        by_gateway = _usage_groups(connection, "gateway", since)
        by_provider = _usage_groups(connection, "provider", since)
        recent = [
            dict(row)
            for row in connection.execute(
                """
                SELECT
                    run_id, component, operation, provider, model, gateway, status,
                    usage_source, input_tokens, output_tokens, total_tokens,
                    estimated_input_tokens, latency_ms, estimated_cost_usd, created_at
                FROM llm_usage_events
                WHERE created_at >= ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (since, limit),
            ).fetchall()
        ]
    totals = dict(totals_row) if totals_row is not None else {}
    totals["fully_measured"] = bool(totals.get("calls")) and totals.get("calls") == totals.get(
        "provider_measured_calls"
    )
    return {
        "generated_at": now.isoformat(),
        "period_days": days,
        "totals": totals,
        "by_gateway": by_gateway,
        "by_provider": by_provider,
        "recent_calls": recent,
    }


def _count(connection: sqlite3.Connection, query: str, params: tuple[object, ...] = ()) -> int:
    row = connection.execute(query, params).fetchone()
    return int(row[0]) if row is not None else 0


def _group_counts(connection: sqlite3.Connection, query: str, key: str) -> dict[str, int]:
    rows = connection.execute(query).fetchall()
    return {str(row[key]): int(row["count"]) for row in rows}


def _usage_groups(
    connection: sqlite3.Connection,
    column: str,
    since: str,
) -> list[dict[str, object]]:
    if column not in {"gateway", "provider"}:
        raise ValueError("unsupported usage grouping")
    rows = connection.execute(
        f"""
        SELECT
            {column} AS name,
            COUNT(*) AS calls,
            COALESCE(SUM(input_tokens), 0) AS input_tokens,
            COALESCE(SUM(output_tokens), 0) AS output_tokens,
            COALESCE(SUM(total_tokens), 0) AS total_tokens,
            COALESCE(SUM(estimated_input_tokens), 0) AS estimated_input_tokens,
            COALESCE(AVG(latency_ms), 0) AS average_latency_ms
        FROM llm_usage_events
        WHERE created_at >= ?
        GROUP BY {column}
        ORDER BY calls DESC
        """,  # nosec B608 - column is validated against a fixed allowlist
        (since,),
    ).fetchall()
    return [dict(row) for row in rows]
