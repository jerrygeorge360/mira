"""Generic, workspace-scoped lifecycle state for durable MIRA memories.

The existing source tables remain authoritative for content, provenance, validity,
and contradiction semantics. This sidecar records lifecycle signals only: access,
verification, reinforcement, trust inputs, and reversible archive/forget decisions.
"""

from __future__ import annotations

import json
import math
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from core.db.repositories import repository_connection, require_active_workspace
from core.db.schema import LEGACY_WORKSPACE_ID

LifecycleRecord = dict[str, object]

ACTIVE_LIFECYCLE_STATUSES = frozenset({"active", "weakened"})
INACTIVE_LIFECYCLE_STATUSES = frozenset({"archived", "forgotten"})
# Source tables retain historical rows with their own validity/status fields.  Keep
# those values in one policy so retrieval modes do not grow subtly different filters.
INACTIVE_SOURCE_STATUSES = frozenset(
    {
        "archived",
        "cancelled",
        "contradicted",
        "demoted",
        "expired",
        "forgotten",
        "invalidated",
        "rejected",
        "stale",
        "superseded",
    }
)
HISTORICAL_QUERY_MARKERS = frozenset(
    {
        "archived",
        "before",
        "forgotten",
        "historical",
        "history",
        "old version",
        "past",
        "previous",
        "prior",
        "superseded",
        "what used to",
        "formerly",
    }
)
DEFAULT_STABILITY_DAYS = 30.0
MIN_RETENTION_SCORE = 0.0
MAX_RETENTION_SCORE = 1.0

_CURRENT_SLEEP_RUN_ID: ContextVar[str | None] = ContextVar(
    "mira_current_sleep_run_id", default=None
)


@contextmanager
def sleep_run_context(run_id: str) -> Iterator[None]:
    """Bind an already-coordinated scheduler run to the lifecycle writer."""
    token = _CURRENT_SLEEP_RUN_ID.set(run_id)
    try:
        yield
    finally:
        _CURRENT_SLEEP_RUN_ID.reset(token)


SOURCE_ALIASES = {
    "session": "sessions",
    "observation": "observations",
    "atomic_fact": "atomic_facts",
    "reflection": "reflections",
    "foresight": "foresight_records",
    "community_summary": "community_summaries",
    "graph_node": "graph_nodes",
    "graph_edge": "graph_edges",
    "hot_memory": "working_memory",
}
SOURCE_AUTHORITY = {
    "observations": "direct_observation",
    "atomic_facts": "structured_derivation",
    "reflections": "synthesized_reflection",
    "foresight_records": "temporal_derivation",
    "community_summaries": "community_synthesis",
    "working_memory": "promoted_working_memory",
    "session_working_set": "session_context",
    "graph_nodes": "graph_derivation",
    "graph_edges": "graph_derivation",
}
SOURCE_TABLES = frozenset(
    {
        "sessions",
        "observations",
        "atomic_facts",
        "graph_nodes",
        "graph_edges",
        "reflections",
        "foresight_records",
        "community_summaries",
        "working_memory",
        "session_working_set",
    }
)


def is_historical_query(query: str | None = None, *, historical: bool = False) -> bool:
    """Return whether retrieval should include retained historical records.

    The explicit flag is the authoritative switch.  Marker detection is a small
    convenience for direct retrieval callers; it never changes workspace scope or
    relevance/trust scoring.
    """
    if historical:
        return True
    if not query:
        return False
    normalized = " ".join(query.casefold().split())
    return any(marker in normalized for marker in HISTORICAL_QUERY_MARKERS)


def retrieval_lifecycle_eligible(
    source_type: str,
    *,
    state: dict[str, object] | None = None,
    record: dict[str, object] | None = None,
    query: str | None = None,
    historical: bool = False,
    allow_superseded: bool = False,
) -> bool:
    """Apply the shared current-vs-historical lifecycle visibility policy.

    This intentionally answers only lifecycle eligibility.  It does not inspect
    relevance, confidence, or runtime trust; low-trust active records remain
    retrievable for the later verification gate.
    """
    include_historical = is_historical_query(query, historical=historical)
    lifecycle = state or {}
    source = record or {}
    lifecycle_status = str(lifecycle.get("lifecycle_status", "active")).casefold()
    source_status = str(source.get("status", "active")).casefold()
    if include_historical:
        return True
    if lifecycle_status in INACTIVE_SOURCE_STATUSES:
        return False
    if source_status in INACTIVE_SOURCE_STATUSES and not (
        allow_superseded and source_status == "superseded"
    ):
        return False
    return not (source_type == "graph_edges" and source.get("invalidated_at"))


def retrieval_source_type(source: str) -> str | None:
    """Map a retrieval label to the source table used by lifecycle state."""
    return {
        "observations": "observations",
        "recent_observations": "observations",
        "atomic_facts": "atomic_facts",
        "reflections": "reflections",
        "reflection": "reflections",
        "foresight_records": "foresight_records",
        "foresight": "foresight_records",
        "community_summary": "community_summaries",
        "community_summaries": "community_summaries",
        "working_memory": "working_memory",
        "graph_edge": "graph_edges",
        "graph_edges": "graph_edges",
        "graph_node": "graph_nodes",
        "graph_nodes": "graph_nodes",
    }.get(source)


def ensure_memory_state(
    source_type: str,
    source_id: str,
    workspace_id: str = LEGACY_WORKSPACE_ID,
    source_authority: str | None = None,
    *,
    created_at: str | None = None,
) -> LifecycleRecord:
    """Create or return one lifecycle row after checking source ownership."""
    source_type = _normalize_source_type(source_type)
    if not source_id.strip():
        raise ValueError("source_id must not be empty")
    require_active_workspace(workspace_id)
    now = _now()
    with repository_connection() as connection:
        _assert_source_workspace(connection, source_type, source_id, workspace_id)
        connection.execute(
            """
            INSERT OR IGNORE INTO memory_state (
                id, workspace_id, source_type, source_id, source_authority,
                retention_score, stability, pinned, lifecycle_status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 0.5, ?, 0, 'active', ?, ?)
            """,
            (
                uuid.uuid4().hex,
                workspace_id,
                source_type,
                source_id,
                source_authority or SOURCE_AUTHORITY.get(source_type, "unknown"),
                DEFAULT_STABILITY_DAYS,
                created_at or now,
                now,
            ),
        )
        row = connection.execute(
            """
            SELECT * FROM memory_state
            WHERE workspace_id = ? AND source_type = ? AND source_id = ?
            """,
            (workspace_id, source_type, source_id),
        ).fetchone()
    if row is None:
        raise RuntimeError("memory lifecycle state could not be created")
    return dict(row)


def get_memory_state(
    source_type: str,
    source_id: str,
    workspace_id: str = LEGACY_WORKSPACE_ID,
) -> LifecycleRecord | None:
    """Return lifecycle state for a workspace-owned source, if initialized."""
    source_type = _normalize_source_type(source_type)
    require_active_workspace(workspace_id)
    with repository_connection() as connection:
        _assert_source_workspace(connection, source_type, source_id, workspace_id)
        row = connection.execute(
            """
            SELECT * FROM memory_state
            WHERE workspace_id = ? AND source_type = ? AND source_id = ?
            """,
            (workspace_id, source_type, source_id),
        ).fetchone()
    return None if row is None else dict(row)


def get_memory_state_by_id(
    memory_id: str,
    workspace_id: str = LEGACY_WORKSPACE_ID,
) -> LifecycleRecord | None:
    """Return one lifecycle state by its public id within a workspace."""
    if not memory_id.strip():
        raise ValueError("memory_id must not be empty")
    require_active_workspace(workspace_id)
    with repository_connection() as connection:
        row = connection.execute(
            """
            SELECT * FROM memory_state
            WHERE id = ? AND workspace_id = ?
            """,
            (memory_id, workspace_id),
        ).fetchone()
    return None if row is None else dict(row)


def forget_memory_by_id(
    memory_id: str,
    workspace_id: str = LEGACY_WORKSPACE_ID,
    *,
    reason: str = "forgotten",
    now: datetime | str | None = None,
) -> LifecycleRecord:
    """Forget a public lifecycle id by delegating to :func:`forget_memory`."""
    state = get_memory_state_by_id(memory_id, workspace_id)
    if state is None:
        raise ValueError("memory_id not found")
    return forget_memory(
        str(state["source_type"]),
        str(state["source_id"]),
        workspace_id,
        reason=reason,
        now=now,
    )


def lifecycle_for_retrieval(
    source_type: str,
    source_id: str,
    workspace_id: str = LEGACY_WORKSPACE_ID,
    *,
    record: dict[str, object] | None = None,
    query: str | None = None,
    historical: bool = False,
    allow_superseded: bool = False,
) -> LifecycleRecord:
    """Return state plus freshness/trust metadata for one retrieval candidate."""
    state = ensure_memory_state(
        source_type,
        source_id,
        workspace_id,
        source_authority=_authority_for_record(source_type, record or {}),
        created_at=_timestamp_from_record(record or {}),
    )
    freshness = freshness_score(state, record=record)
    trust = runtime_trust(state, record=record, freshness=freshness)
    include_historical = is_historical_query(query, historical=historical)
    return {
        **state,
        "freshness_score": freshness,
        "trust_score": trust,
        "historical_query": include_historical,
        "eligible": retrieval_lifecycle_eligible(
            source_type,
            state=state,
            record=record,
            query=query,
            historical=historical,
            allow_superseded=allow_superseded,
        ),
    }


def record_retrieval(
    source_type: str,
    source_id: str,
    workspace_id: str = LEGACY_WORKSPACE_ID,
    *,
    trace_id: str | None = None,
    evidence: dict[str, object] | None = None,
) -> LifecycleRecord:
    """Record access without treating retrieval alone as successful use."""
    state = ensure_memory_state(source_type, source_id, workspace_id)
    now = _now()
    with repository_connection() as connection:
        connection.execute(
            "UPDATE memory_state SET last_accessed_at = ?, updated_at = ? WHERE id = ?",
            (now, now, state["id"]),
        )
        _insert_review(
            connection,
            state,
            event_type="retrieved",
            retrieved=1,
            trace_id=trace_id,
            evidence=evidence,
        )
        row = connection.execute(
            "SELECT * FROM memory_state WHERE id = ?", (state["id"],)
        ).fetchone()
    return dict(row) if row is not None else state


def record_feedback(
    source_type: str,
    source_id: str,
    workspace_id: str = LEGACY_WORKSPACE_ID,
    answer_correct: bool | None = None,
    verified: bool = False,
    refuted: bool = False,
    evidence: object = None,
    trace_id: str | None = None,
) -> LifecycleRecord:
    """Append answer feedback and update runtime trust/retention inputs."""
    if answer_correct is not None and not isinstance(answer_correct, bool):
        raise ValueError("answer_correct must be a boolean or None")
    if not isinstance(verified, bool) or not isinstance(refuted, bool):
        raise ValueError("verified and refuted must be booleans")
    if verified and refuted:
        raise ValueError("verified and refuted cannot both be true")
    if answer_correct is None and not verified and not refuted:
        raise ValueError("feedback must include correctness, verification, or refutation")
    state = ensure_memory_state(source_type, source_id, workspace_id)
    now = _now()
    success_delta = int(answer_correct is True)
    failure_delta = int(answer_correct is False)
    verification_delta = int(verified)
    refuted_delta = int(refuted)
    reinforced_delta = int(answer_correct is True or verified)
    retention_delta = (0.08 * success_delta) + (0.04 * verification_delta)
    retention_delta -= (0.2 * failure_delta) + (0.25 * refuted_delta)
    stability_multiplier = 1.08 if reinforced_delta else (0.8 if failure_delta or refuted else 1.0)
    with repository_connection() as connection:
        connection.execute(
            """
            UPDATE memory_state
            SET successful_uses = successful_uses + ?,
                failed_uses = failed_uses + ?,
                verification_count = verification_count + ?,
                refuted_count = refuted_count + ?,
                retention_score = MIN(1.0, MAX(0.0, retention_score + ?)),
                stability = MIN(365.0, MAX(1.0, stability * ?)),
                last_verified_at = CASE WHEN ? = 1 THEN ? ELSE last_verified_at END,
                lifecycle_status = CASE
                    WHEN ? = 1 AND lifecycle_status = 'active' THEN 'weakened'
                    ELSE lifecycle_status
                END,
                updated_at = ?
            WHERE id = ? AND workspace_id = ?
            """,
            (
                success_delta,
                failure_delta,
                verification_delta,
                refuted_delta,
                retention_delta,
                stability_multiplier,
                verification_delta,
                now,
                int(failure_delta or refuted_delta),
                now,
                state["id"],
                workspace_id,
            ),
        )
        _insert_review(
            connection,
            state,
            event_type="answer_feedback",
            answer_correct=answer_correct,
            answer_wrong=int(answer_correct is False),
            verified=verification_delta,
            refuted=refuted_delta,
            reinforced=reinforced_delta,
            trace_id=trace_id,
            evidence=evidence,
        )
        row = connection.execute(
            "SELECT * FROM memory_state WHERE id = ?", (state["id"],)
        ).fetchone()
    return dict(row) if row is not None else state


def archive_memory(
    source_type: str,
    source_id: str,
    workspace_id: str = LEGACY_WORKSPACE_ID,
    *,
    reason: str = "archived",
    now: datetime | str | None = None,
) -> LifecycleRecord:
    """Mark lifecycle state archived without deleting source or audit rows."""
    return _set_lifecycle_status(
        source_type,
        source_id,
        workspace_id,
        target_status="archived",
        event_type="archived",
        reason=reason,
        now=now,
    )


def forget_memory(
    source_type: str,
    source_id: str,
    workspace_id: str = LEGACY_WORKSPACE_ID,
    *,
    reason: str = "forgotten",
    now: datetime | str | None = None,
) -> LifecycleRecord:
    """Mark lifecycle state forgotten; this generic operation never hard-deletes."""
    return _set_lifecycle_status(
        source_type,
        source_id,
        workspace_id,
        target_status="forgotten",
        event_type="forgotten",
        reason=reason,
        now=now,
    )


def restore_memory(
    source_type: str,
    source_id: str,
    workspace_id: str = LEGACY_WORKSPACE_ID,
    *,
    reason: str = "restored",
    now: datetime | str | None = None,
) -> LifecycleRecord:
    """Restore archived state; forgotten state remains terminal."""
    source_type = _normalize_source_type(source_type)
    state = ensure_memory_state(source_type, source_id, workspace_id)
    if str(state["lifecycle_status"]) != "archived":
        return state
    return _set_lifecycle_status(
        source_type,
        source_id,
        workspace_id,
        target_status="active",
        event_type="restored",
        reason=reason,
        now=now,
    )


def is_lifecycle_status_visible(status: str, *, include_inactive: bool = False) -> bool:
    """Return whether a lifecycle status is eligible for a normal memory view."""
    if status in ACTIVE_LIFECYCLE_STATUSES:
        return True
    return include_inactive and status in INACTIVE_LIFECYCLE_STATUSES


def filter_memory_states(
    states: list[LifecycleRecord], *, include_inactive: bool = False
) -> list[LifecycleRecord]:
    """Filter state dictionaries without mutating source records or input rows."""
    return [
        dict(state)
        for state in states
        if is_lifecycle_status_visible(
            str(state.get("lifecycle_status", "")), include_inactive=include_inactive
        )
    ]


def _set_lifecycle_status(
    source_type: str,
    source_id: str,
    workspace_id: str,
    *,
    target_status: str,
    event_type: str,
    reason: str,
    now: datetime | str | None,
) -> LifecycleRecord:
    source_type = _normalize_source_type(source_type)
    require_active_workspace(workspace_id)
    state = ensure_memory_state(source_type, source_id, workspace_id)
    current_status = str(state["lifecycle_status"])
    if current_status == "forgotten" or current_status == target_status:
        return state
    if target_status == "active" and current_status != "archived":
        return state
    timestamp = _as_of_datetime(now).isoformat()
    with repository_connection() as connection:
        connection.execute(
            """
            UPDATE memory_state
            SET lifecycle_status = ?, updated_at = ?
            WHERE id = ? AND workspace_id = ?
            """,
            (target_status, timestamp, state["id"], workspace_id),
        )
        _insert_review(
            connection,
            state,
            event_type=event_type,
            evidence={
                "reason": reason,
                "status_before": current_status,
                "status_after": target_status,
            },
        )
        row = connection.execute(
            "SELECT * FROM memory_state WHERE id = ? AND workspace_id = ?",
            (state["id"], workspace_id),
        ).fetchone()
    return dict(row) if row is not None else state


def record_feedback_for_trace(
    trace_id: str,
    workspace_id: str = LEGACY_WORKSPACE_ID,
    *,
    answer_correct: bool | None = None,
    verified: bool = False,
    refuted: bool = False,
    evidence: object = None,
) -> list[LifecycleRecord]:
    """Apply one answer verdict to every memory item recorded by an answer trace."""
    require_active_workspace(workspace_id)
    with repository_connection() as connection:
        row = connection.execute(
            """
            SELECT retrieval_logs.retrieved_records_json
            FROM answer_traces
            JOIN retrieval_logs ON retrieval_logs.id = answer_traces.retrieval_log_id
            WHERE answer_traces.id = ? AND answer_traces.workspace_id = ?
            """,
            (trace_id, workspace_id),
        ).fetchone()
    if row is None:
        raise ValueError("trace_id not found in workspace")
    records = row["retrieved_records_json"]
    if not isinstance(records, list):
        return []
    results: list[LifecycleRecord] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        source_type = record.get("source")
        source_id = record.get("id") or record.get("source_id")
        if not isinstance(source_type, str) or not isinstance(source_id, str):
            continue
        if source_type not in SOURCE_TABLES and source_type not in SOURCE_ALIASES:
            continue
        results.append(
            record_feedback(
                source_type,
                source_id,
                workspace_id,
                answer_correct=answer_correct,
                verified=verified,
                refuted=refuted,
                evidence=evidence,
                trace_id=trace_id,
            )
        )
    return results


def run_memory_sleep(
    workspace_id: str = LEGACY_WORKSPACE_ID,
    max_items: int = 100,
    *,
    now: datetime | str | None = None,
) -> LifecycleRecord:
    """Run one bounded, append-audit sleep cycle without deleting source records."""
    if max_items < 1:
        raise ValueError("max_items must be a positive integer")
    require_active_workspace(workspace_id)
    as_of = _as_of_datetime(now)
    started_at = as_of.isoformat()
    run_id = _CURRENT_SLEEP_RUN_ID.get()
    owns_run = run_id is None
    run_id = run_id or uuid.uuid4().hex
    with repository_connection() as connection:
        if owns_run:
            previous = connection.execute(
                """
                SELECT * FROM memory_sleep_runs
                WHERE workspace_id = ? AND started_at = ? AND status = 'completed'
                ORDER BY completed_at DESC, id DESC
                LIMIT 1
                """,
                (workspace_id, started_at),
            ).fetchone()
            if previous is not None:
                return dict(previous)
            connection.execute(
                """
                INSERT INTO memory_sleep_runs (id, workspace_id, status, started_at)
                VALUES (?, ?, 'running', ?)
                """,
                (run_id, workspace_id, started_at),
            )
        else:
            run = connection.execute(
                "SELECT id FROM memory_sleep_runs WHERE id = ? AND workspace_id = ?",
                (run_id, workspace_id),
            ).fetchone()
            if run is None:
                raise ValueError("coordinated sleep run not found")
        rows = connection.execute(
            """
            SELECT * FROM memory_state
            WHERE workspace_id = ? AND lifecycle_status IN ('active', 'weakened')
            ORDER BY updated_at ASC, id ASC
            LIMIT ?
            """,
            (workspace_id, max_items),
        ).fetchall()

    reviewed = weakened = archived = forgotten = 0
    for row in rows:
        state = dict(row)
        reviewed += 1
        old_score = float(state["retention_score"])
        new_score = _sleep_score(state, as_of)
        status = str(state["lifecycle_status"])
        has_negative_evidence = (
            int(state["failed_uses"]) > int(state["successful_uses"])
            or int(state["refuted_count"]) > 0
        )
        if not int(state["pinned"]):
            if has_negative_evidence and new_score <= 0.05:
                status = "forgotten"
                forgotten += 1
            elif has_negative_evidence and new_score <= 0.2:
                status = "archived"
                archived += 1
            elif new_score < old_score:
                status = "weakened"
                weakened += 1
        with repository_connection() as connection:
            connection.execute(
                """
                UPDATE memory_state
                SET retention_score = ?, lifecycle_status = ?, updated_at = ?
                WHERE id = ? AND workspace_id = ?
                """,
                (new_score, status, as_of.isoformat(), state["id"], workspace_id),
            )
            _insert_review(
                connection,
                state,
                event_type="sleep_review",
                evidence={"score_before": old_score, "score_after": new_score, "status": status},
            )

    consolidated = _consolidate_duplicate_states(workspace_id, max_items=max_items)
    refreshed = _refresh_reflections(workspace_id, max_items=max_items)
    details = {
        "max_items": max_items,
        "reflection_refreshes": refreshed,
        "as_of": as_of.isoformat(),
    }
    completed_at = _now()
    with repository_connection() as connection:
        connection.execute(
            """
            UPDATE memory_sleep_runs
            SET status = 'completed', completed_at = ?, reviewed_count = ?, weakened_count = ?,
                consolidated_count = ?, archived_count = ?, forgotten_count = ?, details = ?
            WHERE id = ? AND workspace_id = ?
            """,
            (
                completed_at,
                reviewed,
                weakened,
                consolidated,
                archived,
                forgotten,
                json.dumps(details, sort_keys=True),
                run_id,
                workspace_id,
            ),
        )
        row = connection.execute(
            "SELECT * FROM memory_sleep_runs WHERE id = ?", (run_id,)
        ).fetchone()
    return dict(row) if row is not None else {"id": run_id, "status": "completed"}


def list_memory_states(
    workspace_id: str = LEGACY_WORKSPACE_ID,
    *,
    limit: int = 100,
    include_inactive: bool = True,
) -> list[LifecycleRecord]:
    """List lifecycle state for the authenticated workspace."""
    if limit < 1:
        raise ValueError("limit must be a positive integer")
    require_active_workspace(workspace_id)
    status_filter = "" if include_inactive else "AND lifecycle_status IN ('active', 'weakened')"
    with repository_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT * FROM memory_state
            WHERE workspace_id = ? {status_filter}
            ORDER BY updated_at DESC, id DESC LIMIT ?
            """,  # nosec B608
            (workspace_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def freshness_score(
    state: dict[str, object],
    *,
    record: dict[str, object] | None = None,
    as_of: datetime | None = None,
) -> float:
    """Calculate freshness independently of relevance and source authority."""
    raw = (
        state.get("last_verified_at") or (record or {}).get("updated_at") or state.get("created_at")
    )
    timestamp = _parse_time(raw)
    if timestamp is None:
        return 0.0
    reference = as_of or datetime.now(UTC)
    stability_days = max(1.0, _as_float(state.get("stability"), DEFAULT_STABILITY_DAYS))
    age_seconds = max(0.0, (reference - timestamp).total_seconds())
    return max(0.0, min(1.0, math.exp(-math.log(2.0) * age_seconds / (stability_days * 86400.0))))


def runtime_trust(
    state: dict[str, object],
    *,
    record: dict[str, object] | None = None,
    freshness: float | None = None,
) -> float:
    """Return a runtime trust estimate; it is never used as relevance score."""
    success = _as_int(state.get("successful_uses"))
    failure = _as_int(state.get("failed_uses"))
    verification = _as_int(state.get("verification_count"))
    total = success + failure
    outcome = (success / total) if total else 0.5
    verification_signal = min(1.0, verification / 3.0)
    authority_signal = _authority_score(str(state.get("source_authority") or "unknown"))
    fresh = freshness if freshness is not None else freshness_score(state, record=record)
    retention = max(0.0, min(1.0, _as_float(state.get("retention_score"))))
    if str(state.get("lifecycle_status")) in INACTIVE_LIFECYCLE_STATUSES:
        return 0.0
    return round(
        max(
            0.0,
            min(
                1.0,
                0.30 * authority_signal
                + 0.20 * fresh
                + 0.20 * outcome
                + 0.15 * verification_signal
                + 0.15 * retention,
            ),
        ),
        6,
    )


def _sleep_score(state: dict[str, object], as_of: datetime) -> float:
    if _as_int(state.get("successful_uses")) + _as_int(state.get("failed_uses")) == 0:
        return max(0.0, min(1.0, _as_float(state.get("retention_score"))))
    fresh = freshness_score(state, as_of=as_of)
    success = _as_int(state.get("successful_uses"))
    failure = _as_int(state.get("failed_uses"))
    verification = _as_int(state.get("verification_count"))
    evidence = (success + 0.5 * verification) / max(1.0, success + failure + verification)
    old = _as_float(state.get("retention_score"))
    # Sleep inspection must not become implicit positive feedback.  Any increase
    # requires genuine usage/verification through the normal feedback path.
    proposed = round(0.45 * old + 0.30 * fresh + 0.25 * evidence, 6)
    return max(0.0, min(old, proposed))


def _consolidate_duplicate_states(workspace_id: str, *, max_items: int) -> int:
    consolidated = 0
    for source_type, table, content_column in (
        ("observations", "observations", "content"),
        ("reflections", "reflections", "content"),
        ("foresight_records", "foresight_records", "content"),
    ):
        with repository_connection() as connection:
            rows = connection.execute(
                f"""
                SELECT memory_state.id, memory_state.source_id, {table}.{content_column} AS content
                FROM memory_state JOIN {table} ON {table}.id = memory_state.source_id
                WHERE memory_state.workspace_id = ?
                  AND memory_state.source_type = ?
                  AND memory_state.lifecycle_status IN ('active', 'weakened')
                ORDER BY memory_state.created_at ASC, memory_state.id ASC
                LIMIT ?
                """,  # nosec B608
                (workspace_id, source_type, max_items * 4),
            ).fetchall()
        groups: dict[str, list[dict[str, object]]] = {}
        for row in rows:
            key = " ".join(str(row["content"]).casefold().split())
            if key:
                groups.setdefault(key, []).append(dict(row))
        for group in groups.values():
            for duplicate in group[1:]:
                with repository_connection() as connection:
                    cursor = connection.execute(
                        """
                        UPDATE memory_state
                        SET lifecycle_status = 'archived',
                            retention_score = MIN(retention_score, 0.2), updated_at = ?
                        WHERE id = ? AND workspace_id = ? AND pinned = 0
                        """,
                        (_now(), duplicate["id"], workspace_id),
                    )
                    if cursor.rowcount:
                        state = dict(
                            connection.execute(
                                "SELECT * FROM memory_state WHERE id = ?", (duplicate["id"],)
                            ).fetchone()
                        )
                        _insert_review(
                            connection,
                            state,
                            event_type="duplicate_consolidated",
                            evidence={"canonical_source_id": group[0]["source_id"]},
                        )
                        consolidated += 1
                        if consolidated >= max_items:
                            return consolidated
    return consolidated


def _refresh_reflections(workspace_id: str, *, max_items: int) -> int:
    from core.memory.reflection import invalidate_reflection_if_unsupported

    with repository_connection() as connection:
        rows = connection.execute(
            """
            SELECT id FROM reflections
            WHERE workspace_id = ? AND status = 'active'
            ORDER BY updated_at ASC LIMIT ?
            """,
            (workspace_id, max_items),
        ).fetchall()
    refreshed = 0
    for row in rows:
        try:
            invalidate_reflection_if_unsupported(str(row["id"]))
            refreshed += 1
        except (ValueError, KeyError):
            continue
    return refreshed


def _insert_review(
    connection: Any,
    state: dict[str, object],
    *,
    event_type: str,
    trace_id: str | None = None,
    retrieved: int = 0,
    answer_correct: bool | None = None,
    answer_wrong: int = 0,
    verified: int = 0,
    refuted: int = 0,
    reinforced: int = 0,
    evidence: object = None,
) -> None:
    connection.execute(
        """
        INSERT INTO memory_reviews (
            id, workspace_id, memory_state_id, trace_id, event_type, retrieved,
            answer_correct, answer_wrong, verified, refuted, reinforced, evidence, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid.uuid4().hex,
            state["workspace_id"],
            state["id"],
            trace_id,
            event_type,
            retrieved,
            None if answer_correct is None else int(answer_correct),
            answer_wrong,
            verified,
            refuted,
            reinforced,
            json.dumps(evidence, sort_keys=True, default=str) if evidence is not None else None,
            _now(),
        ),
    )


def _assert_source_workspace(
    connection: Any, source_type: str, source_id: str, workspace_id: str
) -> None:
    if source_type not in SOURCE_TABLES:
        return
    if source_type == "session_working_set":
        row = connection.execute(
            """
            SELECT sessions.workspace_id FROM session_working_set
            JOIN sessions ON sessions.id = session_working_set.session_id
            WHERE session_working_set.id = ?
            """,
            (source_id,),
        ).fetchone()
    else:
        row = connection.execute(
            f"SELECT workspace_id FROM {source_type} WHERE id = ?",  # nosec B608
            (source_id,),
        ).fetchone()
    if row is None:
        raise ValueError(f"memory source not found: {source_type}/{source_id}")
    if str(row["workspace_id"]) != workspace_id:
        raise ValueError("memory source does not belong to the requested workspace")


def _normalize_source_type(source_type: str) -> str:
    normalized = SOURCE_ALIASES.get(source_type, source_type)
    if not normalized.strip():
        raise ValueError("source_type must not be empty")
    return normalized


def _authority_for_record(source_type: str, record: dict[str, object]) -> str:
    if source_type in {"observation", "observations"}:
        role = str(record.get("role", "user"))
        if role == "user":
            return "direct_observation"
        return "untrusted_observation"
    return SOURCE_AUTHORITY.get(_normalize_source_type(source_type), "unknown")


def _authority_score(authority: str) -> float:
    return {
        "direct_observation": 0.95,
        "structured_derivation": 0.82,
        "temporal_derivation": 0.78,
        "synthesized_reflection": 0.68,
        "community_synthesis": 0.62,
        "promoted_working_memory": 0.72,
        "session_context": 0.7,
        "untrusted_observation": 0.25,
        "unknown": 0.4,
    }.get(authority, 0.4)


def _timestamp_from_record(record: dict[str, object]) -> str | None:
    value = record.get("updated_at") or record.get("created_at")
    return value if isinstance(value, str) else None


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _as_of_datetime(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed_time = _parse_time(value)
        if parsed_time is None:
            raise ValueError("now must be an ISO-8601 datetime")
        parsed = parsed_time
    else:
        raise ValueError("now must be a datetime, ISO-8601 string, or None")
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _as_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _as_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default
