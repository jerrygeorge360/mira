"""Workspace-scoped scheduling and observability for bounded memory sleep.

The lifecycle implementation remains authoritative for retention decisions.  This
module owns only scheduling, run coordination, snapshots, and compact operator
read models.
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from core.db.repositories import repository_connection, require_active_workspace
from core.db.schema import LEGACY_WORKSPACE_ID
from core.memory.lifecycle import (
    runtime_trust,
    sleep_run_context,
)

DEFAULT_SLEEP_INTERVAL_HOURS = 6.0
MIN_SLEEP_INTERVAL_HOURS = 1.0
MAX_SLEEP_INTERVAL_HOURS = 168.0
DEFAULT_STALE_RUN_HOURS = 24.0
SLEEP_TRIGGERS = frozenset({"manual", "automatic", "mcp"})

LifecycleRunner = Callable[..., dict[str, object]]


def get_sleep_config(
    workspace_id: str = LEGACY_WORKSPACE_ID,
    *,
    now: datetime | str | None = None,
) -> dict[str, object]:
    """Return durable scheduler settings, creating safe defaults when needed."""
    require_active_workspace(workspace_id)
    reference = _parse_time(now) if now is not None else datetime.now(UTC)
    with repository_connection() as connection:
        _recover_stale_run(connection, workspace_id, reference)
        row = connection.execute(
            "SELECT * FROM memory_sleep_schedule WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()
        if row is None:
            enabled, interval = _environment_defaults()
            next_sleep = _next_sleep_at(reference, interval) if enabled else None
            connection.execute(
                """
                INSERT INTO memory_sleep_schedule (
                    workspace_id, automatic_sleep_enabled, sleep_interval_hours,
                    last_sleep_at, next_sleep_at, updated_at
                ) VALUES (?, ?, ?, NULL, ?, ?)
                """,
                (workspace_id, int(enabled), interval, next_sleep, _now()),
            )
            row = connection.execute(
                "SELECT * FROM memory_sleep_schedule WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchone()
        active_run = connection.execute(
            """
            SELECT status FROM memory_sleep_runs
            WHERE workspace_id = ? AND status IN ('pending', 'running')
            ORDER BY started_at ASC, id ASC LIMIT 1
            """,
            (workspace_id,),
        ).fetchone()
    if row is None:
        raise RuntimeError("memory sleep schedule could not be created")
    config = _config_record(dict(row))
    config["status"] = str(active_run["status"]) if active_run is not None else "idle"
    return config


def update_sleep_config(
    workspace_id: str = LEGACY_WORKSPACE_ID,
    *,
    enabled: bool | None = None,
    interval_hours: float | None = None,
    now: datetime | str | None = None,
) -> dict[str, object]:
    """Update workspace scheduler settings and recalculate the next due time."""
    current = get_sleep_config(workspace_id, now=now)
    if enabled is not None and not isinstance(enabled, bool):
        raise ValueError("enabled must be a boolean")
    interval = (
        float(interval_hours) if interval_hours is not None else float(current["interval_hours"])
    )
    _validate_interval(interval)
    next_enabled = bool(current["enabled"] if enabled is None else enabled)
    reference = _parse_time(now) if now is not None else datetime.now(UTC)
    last_sleep_at = _optional_time(current.get("last_sleep_at"))
    next_sleep_at = None
    if next_enabled:
        next_sleep_at = _next_sleep_at(last_sleep_at or reference, interval)
    with repository_connection() as connection:
        connection.execute(
            """
            UPDATE memory_sleep_schedule
            SET automatic_sleep_enabled = ?, sleep_interval_hours = ?,
                next_sleep_at = ?, updated_at = ?
            WHERE workspace_id = ?
            """,
            (int(next_enabled), interval, next_sleep_at, _now(), workspace_id),
        )
    return get_sleep_config(workspace_id, now=now)


def list_active_sleep_workspaces() -> list[str]:
    """Return active workspace ids for the single shared worker."""
    with repository_connection() as connection:
        rows = connection.execute(
            "SELECT id FROM workspaces WHERE status = 'active' ORDER BY id"
        ).fetchall()
    return [str(row["id"]) for row in rows]


def maybe_run_scheduled_sleep(
    workspace_id: str,
    *,
    max_items: int = 50,
    now: datetime | str | None = None,
    lifecycle_runner: LifecycleRunner | None = None,
) -> dict[str, object]:
    """Run one automatic cycle only when the workspace schedule is due."""
    config = get_sleep_config(workspace_id, now=now)
    reference = _parse_time(now) if now is not None else datetime.now(UTC)
    next_sleep = _optional_time(config.get("next_sleep_at"))
    if not bool(config["enabled"]):
        return {"status": "disabled", "workspace_id": workspace_id, "config": config}
    if next_sleep is not None and next_sleep > reference:
        return {"status": "not_due", "workspace_id": workspace_id, "config": config}
    return run_scheduled_sleep(
        workspace_id,
        max_items=max_items,
        trigger="automatic",
        now=now,
        lifecycle_runner=lifecycle_runner,
    )


def run_scheduled_sleep(
    workspace_id: str = LEGACY_WORKSPACE_ID,
    *,
    max_items: int = 50,
    trigger: str = "manual",
    now: datetime | str | None = None,
    lifecycle_runner: LifecycleRunner | None = None,
) -> dict[str, object]:
    """Run one coordinated sleep cycle and persist operator-visible results."""
    if max_items < 1:
        raise ValueError("max_items must be a positive integer")
    if trigger not in SLEEP_TRIGGERS:
        raise ValueError(f"invalid sleep trigger: {trigger}")
    require_active_workspace(workspace_id)
    effective_now = _parse_time(now) if now is not None else datetime.now(UTC)
    config = get_sleep_config(workspace_id, now=effective_now)
    run = _begin_run(workspace_id, trigger, max_items, config, effective_now)
    if run["status"] == "already_running":
        return run

    before, before_states = capture_sleep_snapshot(workspace_id)
    errors: list[str] = []
    lifecycle: dict[str, object] = {}
    try:
        from core.memory import slow_path

        runner = lifecycle_runner or slow_path.run_memory_sleep
        with sleep_run_context(str(run["sleep_run_id"])):
            try:
                lifecycle = runner(workspace_id, max_items, now=effective_now.isoformat())
            except Exception as error:  # noqa: BLE001 - a maintenance run must be isolated
                errors.append(f"memory_sleep: {str(error) or error.__class__.__name__}")

            try:
                facts = slow_path._sleep_active_facts(workspace_id, max_items)
                changes_found, changes_applied, duplicates_consolidated, change_errors = (
                    slow_path._refresh_sleep_changes(workspace_id, facts)
                )
                errors.extend(change_errors)
                reflections = slow_path._sleep_active_reflections(workspace_id, max_items)
                reflections_updated, reflection_errors = slow_path._refresh_sleep_reflections(
                    reflections
                )
                errors.extend(reflection_errors)
            except Exception as error:  # noqa: BLE001 - report failure and keep worker alive
                changes_found = changes_applied = duplicates_consolidated = 0
                reflections_updated = 0
                errors.append(f"maintenance: {str(error) or error.__class__.__name__}")
                lifecycle.setdefault("errors", []).append(errors[-1])
    except Exception as error:  # noqa: BLE001 - scheduler failures are recorded, not raised
        changes_found = changes_applied = duplicates_consolidated = 0
        reflections_updated = 0
        errors.append(f"scheduler: {str(error) or error.__class__.__name__}")

    after, after_states = capture_sleep_snapshot(workspace_id)
    changes = build_sleep_changes(before_states, after_states, workspace_id)
    status = "failed" if errors else "completed"
    finished_at = _now()
    summary = {
        "reinforced": 0,
        "weakened": _int_value(lifecycle.get("weakened")),
        "archived": _int_value(lifecycle.get("archived")),
        "forgotten": _int_value(lifecycle.get("forgotten")),
        "consolidated": _int_value(lifecycle.get("consolidated")) or duplicates_consolidated,
        "permanently_deleted": 0,
        "changes_found": len(changes),
        "changes_applied": changes_applied,
        "reflections_updated": reflections_updated,
    }
    result = {
        "sleep_run_id": run["sleep_run_id"],
        "workspace_id": workspace_id,
        "trigger": trigger,
        "status": status,
        "started_at": run["started_at"],
        "finished_at": finished_at,
        "before": before,
        "after": after,
        "changes": changes,
        "summary": summary,
        "max_items": max_items,
        "reviewed": _int_value(lifecycle.get("reviewed_count"))
        or _int_value(lifecycle.get("reviewed")),
        "facts_reviewed": len(facts) if "facts" in locals() else 0,
        "reflections_reviewed": len(reflections) if "reflections" in locals() else 0,
        "changes_found": changes_found,
        "changes_applied": changes_applied,
        "duplicates_consolidated": duplicates_consolidated,
        "reflections_updated": reflections_updated,
        "lifecycle": lifecycle,
        "errors": errors,
    }
    _finish_run(
        workspace_id,
        str(run["sleep_run_id"]),
        status=status,
        finished_at=finished_at,
        result=result,
        before=before,
        after=after,
        changes=changes,
        config=config,
        error="; ".join(errors) if errors else None,
        schedule_at=effective_now,
    )
    return result


def list_sleep_runs(
    workspace_id: str = LEGACY_WORKSPACE_ID,
    *,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, object]:
    """List workspace sleep history with compact JSON fields decoded."""
    if limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")
    if offset < 0:
        raise ValueError("offset must not be negative")
    require_active_workspace(workspace_id)
    with repository_connection() as connection:
        rows = connection.execute(
            """
            SELECT * FROM memory_sleep_runs
            WHERE workspace_id = ?
            ORDER BY started_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (workspace_id, limit, offset),
        ).fetchall()
        total = connection.execute(
            "SELECT COUNT(*) AS count FROM memory_sleep_runs WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()["count"]
    return {
        "items": [_decode_run(dict(row)) for row in rows],
        "total": int(total),
        "limit": limit,
        "offset": offset,
    }


def get_sleep_run(
    sleep_run_id: str,
    workspace_id: str = LEGACY_WORKSPACE_ID,
) -> dict[str, object] | None:
    """Return one sleep run only when it belongs to the requested workspace."""
    require_active_workspace(workspace_id)
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT * FROM memory_sleep_runs WHERE id = ? AND workspace_id = ?",
            (sleep_run_id, workspace_id),
        ).fetchone()
    return None if row is None else _decode_run(dict(row))


def capture_sleep_snapshot(
    workspace_id: str,
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    """Capture summary metrics and the small in-process state map used for deltas."""
    require_active_workspace(workspace_id)
    with repository_connection() as connection:
        rows = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM memory_state WHERE workspace_id = ?", (workspace_id,)
            ).fetchall()
        ]
        hot = _count(
            connection,
            "SELECT COUNT(*) FROM working_memory WHERE workspace_id = ? AND status = 'active'",
            workspace_id,
        )
        warm = _count(
            connection,
            "SELECT COUNT(*) FROM reflections WHERE workspace_id = ? AND status = 'active'",
            workspace_id,
        )
        warm += _count(
            connection,
            "SELECT COUNT(*) FROM community_summaries WHERE workspace_id = ?",
            workspace_id,
        )
        cold = 0
        for table in ("observations", "atomic_facts", "graph_nodes", "graph_edges"):
            cold += _count(
                connection, f"SELECT COUNT(*) FROM {table} WHERE workspace_id = ?", workspace_id
            )  # noqa: S608

    status_counts = {status: 0 for status in ("active", "weakened", "archived", "forgotten")}
    retention_values: list[float] = []
    trust_values: list[float] = []
    state_map: dict[str, dict[str, object]] = {}
    for state in rows:
        lifecycle_status = str(state.get("lifecycle_status") or "active")
        status_counts[lifecycle_status] = status_counts.get(lifecycle_status, 0) + 1
        retention_values.append(float(state.get("retention_score") or 0.0))
        trust_values.append(runtime_trust(state))
        state_map[str(state["id"])] = {
            "id": state["id"],
            "source_type": state["source_type"],
            "source_id": state["source_id"],
            "lifecycle_status": lifecycle_status,
            "retention_score": float(state.get("retention_score") or 0.0),
            "pinned": bool(state.get("pinned")),
        }
    snapshot = {
        "active_memories": status_counts.get("active", 0),
        "weakening_memories": status_counts.get("weakened", 0),
        "archived_memories": status_counts.get("archived", 0),
        "forgotten_memories": status_counts.get("forgotten", 0),
        "pinned_memories": sum(1 for state in rows if bool(state.get("pinned"))),
        "average_retention_score": _average(retention_values),
        "average_trust": _average(trust_values),
        "hot_memory_count": hot,
        "warm_memory_count": warm,
        "cold_memory_count": cold,
    }
    return snapshot, state_map


def build_sleep_changes(
    before: dict[str, dict[str, object]],
    after: dict[str, dict[str, object]],
    workspace_id: str,
    *,
    limit: int = 100,
) -> list[dict[str, object]]:
    """Build a bounded delta without persisting a full memory copy."""
    changes: list[dict[str, object]] = []
    for memory_id in sorted(set(before) | set(after)):
        previous = before.get(memory_id)
        current = after.get(memory_id)
        if previous is None or current is None:
            continue
        old_status = str(previous["lifecycle_status"])
        new_status = str(current["lifecycle_status"])
        old_score = float(previous["retention_score"])
        new_score = float(current["retention_score"])
        if (
            old_status == new_status
            and math.isclose(old_score, new_score)
            and previous["pinned"] == current["pinned"]
        ):
            continue
        if old_status == "forgotten" and new_status != "forgotten":
            continue
        if new_status == "forgotten":
            change_type = "forgotten"
        elif new_status == "archived":
            change_type = "archived"
        elif new_status == "weakened" or new_score < old_score:
            change_type = "weakened"
        elif new_score > old_score:
            change_type = "reinforced"
        else:
            change_type = "changed"
        changes.append(
            {
                "memory_id": memory_id,
                "workspace_id": workspace_id,
                "source_type": current["source_type"],
                "source_id": current["source_id"],
                "change_type": change_type,
                "status_before": old_status,
                "status_after": new_status,
                "retention_before": old_score,
                "retention_after": new_score,
                "pinned": bool(current["pinned"]),
                "content": _source_label(
                    str(current["source_type"]), str(current["source_id"]), workspace_id
                ),
            }
        )
        if len(changes) >= limit:
            break
    return changes


def _begin_run(
    workspace_id: str,
    trigger: str,
    max_items: int,
    config: dict[str, object],
    started_at: datetime,
) -> dict[str, object]:
    run_id = uuid4().hex
    with repository_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        _recover_stale_run(connection, workspace_id, started_at)
        active = connection.execute(
            """
            SELECT id, status, trigger, started_at FROM memory_sleep_runs
            WHERE workspace_id = ? AND status IN ('pending', 'running')
            ORDER BY started_at ASC, id ASC LIMIT 1
            """,
            (workspace_id,),
        ).fetchone()
        if active is not None:
            return {
                "status": "already_running",
                "workspace_id": workspace_id,
                "sleep_run_id": str(active["id"]),
                "trigger": str(active["trigger"]),
                "started_at": str(active["started_at"]),
                "message": "sleep already running",
            }
        timestamp = started_at.isoformat()
        connection.execute(
            """
            INSERT INTO memory_sleep_runs (
                id, workspace_id, status, trigger, started_at, configuration_json
            ) VALUES (?, ?, 'pending', ?, ?, ?)
            """,
            (
                run_id,
                workspace_id,
                trigger,
                timestamp,
                json.dumps(
                    {
                        "enabled": bool(config["enabled"]),
                        "interval_hours": float(config["interval_hours"]),
                        "max_items": max_items,
                    },
                    sort_keys=True,
                ),
            ),
        )
        connection.execute(
            "UPDATE memory_sleep_runs SET status = 'running' WHERE id = ? AND workspace_id = ?",
            (run_id, workspace_id),
        )
    return {
        "status": "running",
        "workspace_id": workspace_id,
        "sleep_run_id": run_id,
        "trigger": trigger,
        "started_at": timestamp,
    }


def _finish_run(
    workspace_id: str,
    run_id: str,
    *,
    status: str,
    finished_at: str,
    result: dict[str, object],
    before: dict[str, object],
    after: dict[str, object],
    changes: list[dict[str, object]],
    config: dict[str, object],
    error: str | None,
    schedule_at: datetime,
) -> None:
    lifecycle = result.get("lifecycle")
    lifecycle = lifecycle if isinstance(lifecycle, dict) else {}
    with repository_connection() as connection:
        connection.execute(
            """
            UPDATE memory_sleep_runs
            SET status = ?, completed_at = CASE WHEN ? = 'completed' THEN ? ELSE NULL END,
                finished_at = ?, reviewed_count = ?, reinforced_count = ?, weakened_count = ?,
                consolidated_count = ?, archived_count = ?, forgotten_count = ?,
                before_snapshot_json = ?, after_snapshot_json = ?, changes_json = ?, error = ?,
                details = ?
            WHERE id = ? AND workspace_id = ?
            """,
            (
                status,
                status,
                finished_at,
                finished_at,
                _int_value(result.get("reviewed")),
                _int_value(result.get("summary", {}).get("reinforced"))
                if isinstance(result.get("summary"), dict)
                else 0,
                _int_value(lifecycle.get("weakened")),
                _int_value(result.get("duplicates_consolidated")),
                _int_value(lifecycle.get("archived")),
                _int_value(lifecycle.get("forgotten")),
                json.dumps(before, sort_keys=True),
                json.dumps(after, sort_keys=True),
                json.dumps(changes, sort_keys=True),
                error,
                json.dumps(
                    {"result": result, "configuration": config}, sort_keys=True, default=str
                ),
                run_id,
                workspace_id,
            ),
        )
        schedule = connection.execute(
            "SELECT automatic_sleep_enabled, sleep_interval_hours "
            "FROM memory_sleep_schedule WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()
        if schedule is not None:
            enabled = bool(schedule["automatic_sleep_enabled"])
            interval = float(schedule["sleep_interval_hours"])
            next_sleep = _next_sleep_at(schedule_at, interval) if enabled else None
            connection.execute(
                """
                UPDATE memory_sleep_schedule
                SET last_sleep_at = CASE WHEN ? = 'completed' THEN ? ELSE last_sleep_at END,
                    next_sleep_at = ?, updated_at = ?
                WHERE workspace_id = ?
                """,
                (status, schedule_at.isoformat(), next_sleep, _now(), workspace_id),
            )


def _decode_run(record: dict[str, object]) -> dict[str, object]:
    result = dict(record)
    result["sleep_run_id"] = result.get("id")
    for column, public_name in (
        ("configuration_json", "configuration"),
        ("before_snapshot_json", "before"),
        ("after_snapshot_json", "after"),
        ("changes_json", "changes"),
    ):
        result[public_name] = _decode_json(
            result.get(column), default={} if public_name != "changes" else []
        )
    if result.get("finished_at") is None:
        result["finished_at"] = result.get("completed_at")
    return result


def _config_record(row: dict[str, object]) -> dict[str, object]:
    interval = float(row["sleep_interval_hours"])
    return {
        "workspace_id": row["workspace_id"],
        "enabled": bool(row["automatic_sleep_enabled"]),
        "automatic_sleep_enabled": bool(row["automatic_sleep_enabled"]),
        "interval_hours": int(interval) if interval.is_integer() else interval,
        "sleep_interval_hours": interval,
        "last_sleep_at": row.get("last_sleep_at"),
        "next_sleep_at": row.get("next_sleep_at"),
        "updated_at": row.get("updated_at"),
    }


def _environment_defaults() -> tuple[bool, float]:
    raw = os.environ.get("MEMORY_SLEEP_INTERVAL_HOURS", str(int(DEFAULT_SLEEP_INTERVAL_HOURS)))
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = DEFAULT_SLEEP_INTERVAL_HOURS
    if not math.isfinite(value):
        value = DEFAULT_SLEEP_INTERVAL_HOURS
    if value == 0:
        return False, DEFAULT_SLEEP_INTERVAL_HOURS
    if value < MIN_SLEEP_INTERVAL_HOURS or value > MAX_SLEEP_INTERVAL_HOURS:
        value = DEFAULT_SLEEP_INTERVAL_HOURS
    return True, value


def _validate_interval(interval: float) -> None:
    if (
        not math.isfinite(interval)
        or interval < MIN_SLEEP_INTERVAL_HOURS
        or interval > MAX_SLEEP_INTERVAL_HOURS
    ):
        raise ValueError("interval_hours must be between 1 and 168")


def _recover_stale_run(connection: Any, workspace_id: str, reference: datetime) -> None:
    """Mark an abandoned worker run failed before another run can claim the workspace."""
    cutoff = reference - timedelta(hours=_stale_run_hours())
    connection.execute(
        """
        UPDATE memory_sleep_runs
        SET status = 'failed', finished_at = ?,
            error = COALESCE(error, 'sleep worker interrupted before completion')
        WHERE workspace_id = ? AND status IN ('pending', 'running') AND started_at < ?
        """,
        (reference.isoformat(), workspace_id, cutoff.isoformat()),
    )


def _stale_run_hours() -> float:
    raw = os.environ.get("MEMORY_SLEEP_STALE_RUN_HOURS", str(int(DEFAULT_STALE_RUN_HOURS)))
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = DEFAULT_STALE_RUN_HOURS
    if not math.isfinite(value) or value < 1.0 or value > MAX_SLEEP_INTERVAL_HOURS:
        return DEFAULT_STALE_RUN_HOURS
    return value


def _next_sleep_at(start: datetime, interval: float) -> str:
    return (start + timedelta(hours=interval)).isoformat()


def _parse_time(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("now must be an ISO-8601 datetime") from error
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _optional_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    return _parse_time(value)


def _source_label(source_type: str, source_id: str, workspace_id: str) -> str | None:
    columns = {
        "observations": ("observations", "content"),
        "atomic_facts": ("atomic_facts", "object"),
        "reflections": ("reflections", "content"),
        "foresight_records": ("foresight_records", "content"),
        "community_summaries": ("community_summaries", "summary"),
        "working_memory": ("working_memory", "content"),
        "graph_nodes": ("graph_nodes", "label"),
    }
    table_column = columns.get(source_type)
    if table_column is None:
        return None
    table, column = table_column
    with repository_connection() as connection:
        row = connection.execute(
            f"SELECT {column} FROM {table} WHERE id = ? AND workspace_id = ?",  # noqa: S608
            (source_id, workspace_id),
        ).fetchone()
    return None if row is None else str(row[column])


def _count(connection: Any, query: str, workspace_id: str) -> int:
    row = connection.execute(query, (workspace_id,)).fetchone()
    return int(row[0]) if row is not None else 0


def _average(values: list[float]) -> float:
    return round(sum(values) / len(values), 6) if values else 0.0


def _int_value(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _decode_json(value: object, *, default: object) -> object:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return default


def _now() -> str:
    return datetime.now(UTC).isoformat()
