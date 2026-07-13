"""Disposable demo workspace issuance and controlled cleanup."""

from __future__ import annotations

import hashlib
import importlib
import os
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import cast

from core.db import chroma
from core.db.repositories import create_user, create_workspace, repository_connection

DEMO_SEED_WORKSPACE_ID = "workspace_demo_seed"
DEMO_SEED_SLUG = "mira-demo-seed"


def issue_demo_workspace(requester: str) -> tuple[str, str, datetime]:
    """Create one isolated, expiring demo identity after applying local limits."""
    cleanup_expired_demo_workspaces()
    ensure_demo_seed_workspace()
    now = datetime.now(timezone.utc)  # noqa: UP017
    ttl_minutes = _positive_env("MIRA_DEMO_TTL_MINUTES", 60)
    max_active = _positive_env("MIRA_DEMO_MAX_ACTIVE", 10)
    max_per_window = _positive_env("MIRA_DEMO_MAX_PER_WINDOW", 3)
    window_minutes = _positive_env("MIRA_DEMO_ISSUANCE_WINDOW_MINUTES", 60)
    requester_hash = hashlib.sha256(requester.encode("utf-8")).hexdigest()
    window_start = (now - timedelta(minutes=window_minutes)).isoformat()
    with repository_connection() as connection:
        active = int(
            connection.execute(
                "SELECT COUNT(*) FROM workspaces "
                "WHERE workspace_type = 'demo' AND status = 'active' AND expires_at > ?",
                (now.isoformat(),),
            ).fetchone()[0]
        )
        recent = int(
            connection.execute(
                "SELECT COUNT(*) FROM demo_issuances WHERE requester_hash = ? AND created_at >= ?",
                (requester_hash, window_start),
            ).fetchone()[0]
        )
    if active >= max_active:
        raise ValueError("demo capacity is currently full")
    if recent >= max_per_window:
        raise ValueError("demo issuance limit reached; try again later")

    expires_at = now + timedelta(minutes=ttl_minutes)
    suffix = secrets.token_hex(6)
    user_id = create_user(display_name="Demo visitor")
    workspace_id = create_workspace(
        "MIRA demo",
        f"demo-{suffix}",
        "demo",
        owner_user_id=user_id,
        expires_at=expires_at.isoformat(),
    )
    with repository_connection() as connection:
        connection.execute(
            """
            INSERT INTO demo_issuances (
                id, requester_hash, user_id, workspace_id, status, created_at, expires_at
            ) VALUES (?, ?, ?, ?, 'active', ?, ?)
            """,
            (
                secrets.token_hex(16),
                requester_hash,
                user_id,
                workspace_id,
                now.isoformat(),
                expires_at.isoformat(),
            ),
        )
    try:
        _seed_workspace(workspace_id)
    except Exception:
        with repository_connection() as connection:
            connection.execute(
                "UPDATE workspaces SET expires_at = ? WHERE id = ?",
                (now.isoformat(), workspace_id),
            )
        cleanup_expired_demo_workspaces()
        raise
    return user_id, workspace_id, expires_at


def ensure_demo_seed_workspace() -> str:
    """Maintain a canonical non-interactive seed workspace."""
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT id FROM workspaces WHERE id = ?", (DEMO_SEED_WORKSPACE_ID,)
        ).fetchone()
    if row is None:
        try:
            create_workspace(
                "MIRA canonical demo seed",
                DEMO_SEED_SLUG,
                "development",
                workspace_id=DEMO_SEED_WORKSPACE_ID,
            )
            _seed_workspace(DEMO_SEED_WORKSPACE_ID)
        except ValueError:
            with repository_connection() as connection:
                winner = connection.execute(
                    "SELECT id FROM workspaces WHERE id = ?", (DEMO_SEED_WORKSPACE_ID,)
                ).fetchone()
            if winner is None:
                raise
    return DEMO_SEED_WORKSPACE_ID


def cleanup_expired_demo_workspaces() -> int:
    """Expire sessions, clear vectors, then delete demo-owned canonical rows."""
    now = datetime.now(timezone.utc).isoformat()  # noqa: UP017
    with repository_connection() as connection:
        rows = connection.execute(
            "SELECT id, owner_user_id FROM workspaces "
            "WHERE workspace_type = 'demo' AND status != 'deleted' AND expires_at <= ?",
            (now,),
        ).fetchall()
    for row in rows:
        _cleanup_workspace(str(row["id"]), str(row["owner_user_id"] or ""), now)
    return len(rows)


def _seed_workspace(workspace_id: str) -> None:
    module = importlib.import_module("scripts.seed_demo")
    seed_demo_data = cast(Callable[..., dict[str, object]], module.seed_demo_data)
    seed_demo_data(os.environ.get("MIRA_DB_PATH", "./mira.db"), workspace_id, reset=False)


def _cleanup_workspace(workspace_id: str, user_id: str, now: str) -> None:
    with repository_connection() as connection:
        connection.execute(
            "UPDATE workspaces SET status = 'deleting', updated_at = ? WHERE id = ?",
            (now, workspace_id),
        )
        connection.execute(
            "UPDATE slow_path_queue SET status = 'quarantined', "
            "quarantine_reason = 'demo workspace expired', updated_at = ? "
            "WHERE workspace_id = ? AND status IN ('pending', 'processing', 'failed')",
            (now, workspace_id),
        )
    for collection in chroma.SUPPORTED_COLLECTIONS:
        chroma.delete_workspace_vectors(collection, workspace_id=workspace_id)
    with repository_connection() as connection:
        for table in ("answer_traces", "prompt_logs", "retrieval_logs"):
            connection.execute(
                f"DELETE FROM {table} WHERE workspace_id = ?",  # nosec B608
                (workspace_id,),
            )
        connection.execute(
            "DELETE FROM reflection_evidence WHERE reflection_id IN "
            "(SELECT id FROM reflections WHERE workspace_id = ?)",
            (workspace_id,),
        )
        for table in (
            "graph_edges",
            "slow_path_step_journal",
            "slow_path_queue",
            "session_working_set",
            "atomic_facts",
            "foresight_records",
            "community_summaries",
            "working_memory",
            "reflections",
            "graph_nodes",
            "entities",
            "observations",
            "sessions",
            "canonical_subjects",
            "canonical_predicates",
        ):
            if table == "session_working_set":
                connection.execute(
                    "DELETE FROM session_working_set WHERE session_id IN "
                    "(SELECT id FROM sessions WHERE workspace_id = ?)",
                    (workspace_id,),
                )
            else:
                connection.execute(
                    f"DELETE FROM {table} WHERE workspace_id = ?",  # nosec B608
                    (workspace_id,),
                )
        connection.execute("DELETE FROM auth_sessions WHERE workspace_id = ?", (workspace_id,))
        connection.execute("DELETE FROM workspace_members WHERE workspace_id = ?", (workspace_id,))
        connection.execute(
            "UPDATE demo_issuances SET status = 'cleaned', cleaned_at = ?, "
            "workspace_id = NULL, user_id = NULL WHERE workspace_id = ?",
            (now, workspace_id),
        )
        connection.execute("DELETE FROM workspaces WHERE id = ?", (workspace_id,))
        if user_id:
            connection.execute(
                "DELETE FROM users WHERE id = ? AND NOT EXISTS "
                "(SELECT 1 FROM workspace_members WHERE user_id = ?)",
                (user_id, user_id),
            )


def _positive_env(name: str, default: int) -> int:
    value = int(os.environ.get(name, str(default)))
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value
