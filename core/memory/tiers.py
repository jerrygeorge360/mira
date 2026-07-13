"""Cold/warm/hot durable-memory promotion and demotion policy.

Ownership: Jerry.
Related issue: ISSUE-031.
Architecture area: slow path.

External durable memory can be far larger than the LLM context, so promotion and
demotion decide what *competes for prompt injection*, not what exists. Cold
history is never deleted; the hot tier is the bounded working_memory pool that
the prompt builder reads. A record (confirmed session item, atomic fact,
reflection, or foresight) is scored on importance, scope, validity, confidence,
user explicitness, and foresight urgency, promoted into the hot pool when it
clears the bar, and demoted when it goes stale, resolved, expired, superseded,
irrelevant, or when the hot tier exceeds its capacity.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from core.db.repositories import (
    create_working_memory_item,
    repository_connection,
    validate_enum_value,
    workspace_id_for_session,
)
from core.db.schema import LEGACY_WORKSPACE_ID

Candidate = dict[str, object]
HotMemoryItem = dict[str, object]

LOGGER = logging.getLogger(__name__)

# Bounded hot tier: the maximum number of active items that may compete for
# prompt injection at once. Module-level so policy/tests can tune it.
HOT_TIER_MAX = 50
PROMOTION_THRESHOLD = 0.5

SUPPORTED_RECORD_TYPES = frozenset(
    {"session_working_set", "reflections", "foresight_records", "atomic_facts"}
)

SESSION_TERMINAL_STATUSES = frozenset({"resolved", "expired", "rejected", "superseded"})
SESSION_TYPE_TO_MEMORY = {
    "correction": "confirmed_correction",
    "active_constraint": "project_constraint",
    "decision": "behavioral_instruction",
    "current_goal": "active_goal",
}
REFLECTION_TYPE_TO_MEMORY = {
    "user_knowledge": "user_preference",
    "self_knowledge": "behavioral_instruction",
    "world_knowledge": "behavioral_instruction",
}

SCOPE_WEIGHT = {
    "current_response": 0.2,
    "current_task": 0.5,
    "current_session": 0.6,
    "project": 0.85,
    "cross_session": 1.0,
}
EXPLICITNESS_SCORE = {
    "direct_instruction": 1.0,
    "direct_correction": 1.0,
    "direct_decision": 1.0,
    "explicit_preference": 0.8,
    "inferred_preference": 0.5,
    "agent_inference": 0.4,
    "ambiguous": 0.3,
}

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_'-]+")
STOPWORDS = frozenset(
    {"a", "an", "the", "is", "are", "do", "did", "i", "my", "me", "to", "of", "for", "on", "when"}
)


def evaluate_promotion_candidate(record_type: str, record_id: str) -> Candidate:
    """Score a durable record for hot-memory promotion against the policy factors."""
    if record_type not in SUPPORTED_RECORD_TYPES:
        raise ValueError(f"unsupported record_type: {record_type!r}")
    record = _fetch_source_record(record_type, record_id)
    if record is None:
        return _candidate(record_type, record_id, eligible=False, reason="source record not found")

    if record_type == "session_working_set":
        return _evaluate_session_item(record_id, record)
    if record_type == "reflections":
        return _evaluate_reflection(record_id, record)
    if record_type == "foresight_records":
        return _evaluate_foresight(record_id, record)
    return _evaluate_atomic_fact(record_id, record)


def promote_to_hot_memory(candidate: Candidate) -> str:
    """Promote an eligible candidate into the bounded hot working-memory pool."""
    if not candidate.get("eligible"):
        raise ValueError(f"candidate is not eligible: {candidate.get('reason')}")
    record_type = _string(candidate.get("record_type"))
    record_id = _string(candidate.get("record_id"))
    memory_type = _string(candidate.get("memory_type"))
    content = _string(candidate.get("content"))
    scope = _string(candidate.get("scope")) or "cross_session"
    priority = _float(candidate.get("promotion_score"))
    workspace_id = _string(candidate.get("workspace_id")) or LEGACY_WORKSPACE_ID
    if not content or not memory_type:
        raise ValueError("candidate is missing content or memory_type")

    existing = _existing_hot_item(record_type, record_id, workspace_id)
    if existing is not None:
        _update_hot_priority(str(existing["id"]), priority, content)
        return str(existing["id"])

    _enforce_capacity(workspace_id)
    item_id = create_working_memory_item(
        {
            "workspace_id": workspace_id,
            "content": content,
            "memory_type": memory_type,
            "scope": scope,
            "priority": priority,
            "status": "active",
            "source_record_type": record_type,
            "source_record_id": record_id,
        }
    )
    LOGGER.info("Promoted %s %s to hot memory %s", record_type, record_id, item_id)
    return item_id


def demote_hot_memory_item(item_id: str, reason: str) -> None:
    """Demote a hot-memory item out of injection eligibility, preserving history."""
    if not reason:
        raise ValueError("reason must not be empty")
    status = _demotion_status(reason)
    _set_hot_status(item_id, status)
    LOGGER.info("Demoted hot memory %s (%s) -> %s", item_id, reason, status)


def list_hot_memory_for_context(
    session_id: str | None,
    query: str,
    limit: int,
) -> list[HotMemoryItem]:
    """List active, still-valid hot memory ranked for prompt injection."""
    if limit < 1:
        raise ValueError("limit must be a positive integer")
    workspace_id = (
        workspace_id_for_session(session_id) if session_id is not None else LEGACY_WORKSPACE_ID
    )

    query_tokens = _tokens(query)
    items: list[HotMemoryItem] = []
    for row in _active_hot_items(workspace_id):
        if not _source_still_valid(row):
            continue
        priority = _float(row.get("priority"))
        relevance = _relevance(query_tokens, row)
        item = dict(row)
        item["relevance"] = relevance
        item["score"] = (0.6 * priority) + (0.4 * relevance)
        items.append(item)
    items.sort(key=_context_key)
    return items[:limit]


def _evaluate_session_item(record_id: str, record: dict[str, object]) -> Candidate:
    status = str(record["status"])
    if status in SESSION_TERMINAL_STATUSES:
        return _candidate(
            "session_working_set", record_id, eligible=False, reason=f"session item is {status}"
        )
    memory_type = SESSION_TYPE_TO_MEMORY.get(str(record["type"]))
    if memory_type is None:
        return _candidate(
            "session_working_set",
            record_id,
            eligible=False,
            reason=f"session item type {record['type']!r} is not promotable",
        )
    scope = str(record["scope"])
    priority = _float(record.get("priority"))
    explicitness = EXPLICITNESS_SCORE.get(str(record["explicitness_label"]), 0.5)
    importance = 0.9 if str(record["type"]) == "correction" else 0.75
    score = _promotion_score(
        importance=importance,
        scope=scope,
        confidence=priority,
        explicitness=explicitness,
        urgency=0.0,
    )
    return _candidate(
        "session_working_set",
        record_id,
        eligible=score >= PROMOTION_THRESHOLD,
        promotion_score=score,
        memory_type=memory_type,
        content=str(record["content"]),
        scope=scope,
        reason="passes promotion policy" if score >= PROMOTION_THRESHOLD else "below threshold",
    )


def _evaluate_reflection(record_id: str, record: dict[str, object]) -> Candidate:
    if str(record["status"]) != "active":
        return _candidate(
            "reflections",
            record_id,
            eligible=False,
            reason=f"reflection is {record['status']}",
        )
    memory_type = REFLECTION_TYPE_TO_MEMORY.get(
        str(record["reflection_type"]), "behavioral_instruction"
    )
    confidence = _float(record.get("confidence"))
    score = _promotion_score(
        importance=0.7,
        scope="cross_session",
        confidence=confidence,
        explicitness=0.7,
        urgency=0.0,
    )
    return _candidate(
        "reflections",
        record_id,
        eligible=score >= PROMOTION_THRESHOLD,
        promotion_score=score,
        memory_type=memory_type,
        content=str(record["content"]),
        scope="cross_session",
        reason="passes promotion policy" if score >= PROMOTION_THRESHOLD else "below threshold",
    )


def _evaluate_foresight(record_id: str, record: dict[str, object]) -> Candidate:
    status = str(record["status"])
    if status not in {"active", "pending"}:
        return _candidate(
            "foresight_records", record_id, eligible=False, reason=f"foresight is {status}"
        )
    always_inject = bool(record.get("always_inject"))
    urgency = 1.0 if always_inject else (0.8 if status == "active" else 0.5)
    score = _promotion_score(
        importance=0.8,
        scope="project",
        confidence=0.9,
        explicitness=0.8,
        urgency=urgency,
    )
    return _candidate(
        "foresight_records",
        record_id,
        eligible=score >= PROMOTION_THRESHOLD,
        promotion_score=score,
        memory_type="active_foresight",
        content=str(record["content"]),
        scope="project",
        reason="passes promotion policy" if score >= PROMOTION_THRESHOLD else "below threshold",
    )


def _evaluate_atomic_fact(record_id: str, record: dict[str, object]) -> Candidate:
    if str(record["status"]) != "active":
        return _candidate(
            "atomic_facts", record_id, eligible=False, reason=f"fact is {record['status']}"
        )
    confidence = _float(record.get("confidence"))
    predicate = str(record.get("predicate", "")).upper()
    memory_type = (
        "user_preference" if predicate in {"PREFERS", "DISLIKES"} else "behavioral_instruction"
    )
    score = _promotion_score(
        importance=0.6,
        scope="cross_session",
        confidence=confidence,
        explicitness=0.7,
        urgency=0.0,
    )
    content = f"{record['subject']} {record['predicate']} {record['object']}"
    return _candidate(
        "atomic_facts",
        record_id,
        eligible=score >= PROMOTION_THRESHOLD,
        promotion_score=score,
        memory_type=memory_type,
        content=content,
        scope="cross_session",
        reason="passes promotion policy" if score >= PROMOTION_THRESHOLD else "below threshold",
    )


def _promotion_score(
    *,
    importance: float,
    scope: str,
    confidence: float,
    explicitness: float,
    urgency: float,
) -> float:
    scope_weight = SCOPE_WEIGHT.get(scope, 0.5)
    raw = (
        (0.30 * _clamp(importance))
        + (0.20 * scope_weight)
        + (0.20 * _clamp(confidence))
        + (0.15 * _clamp(explicitness))
        + (0.15 * _clamp(urgency))
    )
    return round(_clamp(raw), 6)


def _candidate(
    record_type: str,
    record_id: str,
    *,
    eligible: bool,
    reason: str,
    promotion_score: float = 0.0,
    memory_type: str | None = None,
    content: str = "",
    scope: str = "",
) -> Candidate:
    record = _fetch_source_record(record_type, record_id)
    return {
        "record_type": record_type,
        "record_id": record_id,
        "eligible": eligible,
        "promotion_score": promotion_score,
        "memory_type": memory_type,
        "content": content,
        "scope": scope,
        "reason": reason,
        "workspace_id": (
            str(record.get("workspace_id"))
            if record is not None and record.get("workspace_id")
            else LEGACY_WORKSPACE_ID
        ),
    }


def _fetch_source_record(record_type: str, record_id: str) -> dict[str, object] | None:
    with repository_connection() as connection:
        if record_type == "session_working_set":
            row = connection.execute(
                """
                SELECT session_working_set.*, sessions.workspace_id
                FROM session_working_set
                JOIN sessions ON sessions.id = session_working_set.session_id
                WHERE session_working_set.id = ?
                """,
                (record_id,),
            ).fetchone()
        else:
            row = connection.execute(
                f"SELECT * FROM {record_type} WHERE id = ?",  # nosec B608
                (record_id,),
            ).fetchone()
    return None if row is None else dict(row)


def _existing_hot_item(
    record_type: str, record_id: str, workspace_id: str
) -> dict[str, object] | None:
    with repository_connection() as connection:
        row = connection.execute(
            """
            SELECT * FROM working_memory
            WHERE workspace_id = ? AND source_record_type = ?
              AND source_record_id = ? AND status = ?
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (workspace_id, record_type, record_id, "active"),
        ).fetchone()
    return None if row is None else dict(row)


def _active_hot_items(workspace_id: str) -> list[dict[str, object]]:
    with repository_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM working_memory WHERE workspace_id = ? AND status = ? "
            "ORDER BY priority DESC, created_at ASC",
            (workspace_id, "active"),
        ).fetchall()
    return [dict(row) for row in rows]


def _enforce_capacity(workspace_id: str) -> None:
    active = _active_hot_items(workspace_id)
    overflow = len(active) - HOT_TIER_MAX + 1
    if overflow <= 0:
        return
    # Demote the lowest-priority active items to make room for the new promotion.
    for row in sorted(
        active, key=lambda item: (_float(item.get("priority")), str(item["created_at"]))
    )[:overflow]:
        demote_hot_memory_item(str(row["id"]), "hot_tier_capacity_exceeded")


def _update_hot_priority(item_id: str, priority: float, content: str) -> None:
    with repository_connection() as connection:
        connection.execute(
            "UPDATE working_memory SET priority = ?, content = ?, updated_at = ? WHERE id = ?",
            (priority, content, _now(), item_id),
        )


def _set_hot_status(item_id: str, status: str) -> None:
    validate_enum_value("working_memory_status", status)
    with repository_connection() as connection:
        cursor = connection.execute(
            "UPDATE working_memory SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now(), item_id),
        )
        if cursor.rowcount == 0:
            raise ValueError(f"Hot memory item not found: {item_id}")


def _source_still_valid(row: dict[str, object]) -> bool:
    record_type = _string(row.get("source_record_type"))
    record_id = _string(row.get("source_record_id"))
    if record_type not in SUPPORTED_RECORD_TYPES or not record_id:
        return True
    record = _fetch_source_record(record_type, record_id)
    if record is None:
        return False
    status = str(record.get("status", "active"))
    if record_type == "session_working_set":
        return status not in SESSION_TERMINAL_STATUSES
    if record_type == "foresight_records":
        return status in {"active", "pending"}
    return status == "active"


def _demotion_status(reason: str) -> str:
    normalized = reason.casefold()
    if "supersed" in normalized:
        return "superseded"
    if "expir" in normalized:
        return "expired"
    return "demoted"


def _relevance(query_tokens: set[str], row: dict[str, object]) -> float:
    if not query_tokens:
        return 0.0
    content_tokens = _tokens(str(row.get("content", "")))
    if not content_tokens:
        return 0.0
    return len(query_tokens & content_tokens) / len(query_tokens)


def _context_key(item: HotMemoryItem) -> tuple[float, float, float]:
    return (
        -_float(item.get("score")),
        -_float(item.get("priority")),
        -_timestamp(item.get("created_at")),
    )


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in TOKEN_PATTERN.findall(value.casefold())
        if len(token) > 1 and token not in STOPWORDS
    }


def _timestamp(value: object) -> float:
    if not isinstance(value, str) or not value.strip():
        return 0.0
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)  # noqa: UP017
    return parsed.timestamp()


def _string(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _float(value: object, default: float = 0.0) -> float:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()  # noqa: UP017
