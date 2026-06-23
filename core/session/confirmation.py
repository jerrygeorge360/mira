"""Lifecycle gate that decides the fate of provisional session items.

Ownership: Jerry.
Related issue: ISSUE-205.
Architecture area: session micro-path.

Provisional Session Working Set items are immediately useful inside a session
but must not be allowed to poison durable cross-session memory. This module is
the safety bridge: it confirms, rejects, narrows the scope of, retires
(forward-only), or promotes an item to a durable-memory candidate.

Forward-only rule: when a later review rejects, downgrades, or retires an item
that already influenced earlier responses, only future prompt injection changes.
Prior turns are never retroactively rewritten -- raw observations are immutable.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from core.db.repositories import (
    create_working_memory_item,
    enum_values,
    repository_connection,
    validate_enum_value,
)
from core.session.working_set import SCOPE_RANK

LOGGER = logging.getLogger(__name__)

SessionItem = dict[str, object]

TERMINAL_STATUSES = frozenset({"resolved", "expired", "rejected", "superseded"})
DIRECT_EXPLICITNESS = frozenset(
    {"direct_instruction", "direct_correction", "direct_decision", "explicit_preference"}
)
DURABLE_SCOPES = frozenset({"project", "cross_session"})
SESSION_TYPE_TO_WORKING_MEMORY = {
    "correction": "confirmed_correction",
    "active_constraint": "project_constraint",
    "decision": "behavioral_instruction",
    "current_goal": "active_goal",
}


def confirm_session_item(item_id: str, confirmed_by: str) -> None:
    """Confirm a provisional item if it clears the confirmation gate, else reject it.

    The gate re-verifies source grounding, explicitness, and scope validity, and
    requires the item to not already be cancelled, contradicted, or resolved. An
    item that fails the gate is deterministically rejected rather than confirmed,
    so it can never reach durable memory.
    """
    if not confirmed_by:
        raise ValueError("confirmed_by must not be empty")
    item = _require_item(item_id)
    _ensure_not_terminal(item_id, item)

    failure = _confirmation_gate_failure(item)
    if failure is not None:
        _set_status(item_id, "rejected", f"confirmation_failed:{failure}")
        LOGGER.warning("Rejected session item %s during confirmation: %s", item_id, failure)
        return

    _set_status(item_id, "confirmed", f"confirmed_by:{confirmed_by}")
    LOGGER.info("Confirmed session item %s by %s", item_id, confirmed_by)


def reject_session_item_after_review(item_id: str, reason: str) -> None:
    """Reject a provisional item that slow-path review found unsupported.

    Forward-only: the item stops being injected from now on, but earlier turns
    that already used it are left intact.
    """
    if not reason:
        raise ValueError("reason must not be empty")
    _require_item(item_id)
    _set_status(item_id, "rejected", reason)
    LOGGER.info("Rejected session item %s after review: %s", item_id, reason)


def downgrade_session_item_scope(item_id: str, new_scope: str, reason: str) -> None:
    """Narrow a session item's scope without rewriting prior turns.

    Only a strictly narrower scope is allowed; widening must go through explicit
    promotion. The change applies forward-only to future prompt injection.
    """
    if not reason:
        raise ValueError("reason must not be empty")
    validate_enum_value("session_scope", new_scope)
    item = _require_item(item_id)
    _ensure_not_terminal(item_id, item)

    current_scope = str(item["scope"])
    if SCOPE_RANK[new_scope] >= SCOPE_RANK[current_scope]:
        raise ValueError(f"new_scope must narrow {current_scope!r}; got {new_scope!r}")

    now = _now()
    with repository_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE session_working_set
            SET scope = ?, resolution_reason = ?, updated_at = ?
            WHERE id = ?
            """,
            (new_scope, f"scope_downgraded:{reason}", now, item_id),
        )
        if cursor.rowcount == 0:
            raise ValueError(f"Session item not found: {item_id}")
    LOGGER.info(
        "Downgraded session item %s scope %s -> %s: %s",
        item_id,
        current_scope,
        new_scope,
        reason,
    )


def mark_session_item_forward_only(item_id: str, reason: str) -> None:
    """Retire an item from future prompts while preserving the turns it shaped.

    Used when an item already influenced responses but should no longer be
    injected. It is expired going forward; prior turns are not rewritten.
    """
    if not reason:
        raise ValueError("reason must not be empty")
    item = _require_item(item_id)
    _ensure_not_terminal(item_id, item)
    _set_status(item_id, "expired", f"forward_only:{reason}")
    LOGGER.info("Retired session item %s forward-only: %s", item_id, reason)


def promote_session_item_to_durable_candidate(item_id: str) -> str:
    """Produce a durable-memory candidate from a project/cross-session item.

    Promotion requires a durable scope and a passing confirmation gate. It writes
    a working-memory candidate record and marks the session item confirmed. This
    only produces a candidate; tier placement is left to the slow-path tier
    manager.
    """
    item = _require_item(item_id)
    _ensure_not_terminal(item_id, item)

    scope = str(item["scope"])
    if scope not in DURABLE_SCOPES:
        raise ValueError(
            f"durable promotion requires project or cross_session scope; got {scope!r}"
        )

    failure = _confirmation_gate_failure(item)
    if failure is not None:
        raise ValueError(f"cannot promote session item {item_id}: {failure}")

    memory_type = SESSION_TYPE_TO_WORKING_MEMORY.get(str(item["type"]))
    if memory_type is None:
        raise ValueError(f"session item type {item['type']!r} is not promotable to durable memory")

    candidate_id = create_working_memory_item(
        {
            "content": item["content"],
            "memory_type": memory_type,
            "scope": scope,
            "priority": item["priority"],
            "status": "active",
            "source_record_type": "session_working_set",
            "source_record_id": item_id,
        }
    )
    _set_status(item_id, "confirmed", f"promoted_to_durable_candidate:{candidate_id}")
    LOGGER.info("Promoted session item %s to durable candidate %s", item_id, candidate_id)
    return candidate_id


def _confirmation_gate_failure(item: SessionItem) -> str | None:
    source_ids = _json_list(item.get("source_observations_json"))
    if not source_ids:
        return "missing_source_grounding"
    observation_contents = _observation_contents(source_ids)
    if not observation_contents:
        return "ungrounded_source_observations"

    if str(item["scope"]) not in enum_values("session_scope"):
        return "invalid_scope"

    if str(item["explicitness_label"]) not in DIRECT_EXPLICITNESS:
        return "ambiguous_explicitness"

    evidence_span = item.get("evidence_span")
    if not (isinstance(evidence_span, str) and evidence_span.strip()):
        return "missing_evidence_span"
    if not _evidence_grounded(evidence_span, observation_contents):
        return "evidence_not_grounded"
    return None


def _observation_contents(observation_ids: list[str]) -> list[str]:
    placeholders = ", ".join("?" for _ in observation_ids)
    with repository_connection() as connection:
        rows = connection.execute(
            f"SELECT content FROM observations WHERE id IN ({placeholders})",  # nosec B608
            tuple(observation_ids),
        ).fetchall()
    return [str(row["content"]) for row in rows]


def _evidence_grounded(evidence_span: str, observation_contents: list[str]) -> bool:
    normalized_evidence = _normalize(evidence_span)
    if not normalized_evidence:
        return False
    return any(normalized_evidence in _normalize(content) for content in observation_contents)


def _set_status(item_id: str, status: str, reason: str) -> None:
    validate_enum_value("session_item_status", status)
    with repository_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE session_working_set
            SET status = ?, resolution_reason = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, reason, _now(), item_id),
        )
        if cursor.rowcount == 0:
            raise ValueError(f"Session item not found: {item_id}")


def _require_item(item_id: str) -> SessionItem:
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT * FROM session_working_set WHERE id = ?",
            (item_id,),
        ).fetchone()
    if row is None:
        raise ValueError(f"Session item not found: {item_id}")
    return dict(row)


def _ensure_not_terminal(item_id: str, item: SessionItem) -> None:
    status = str(item["status"])
    if status in TERMINAL_STATUSES:
        raise ValueError(f"cannot transition terminal session item {item_id} (status={status})")


def _json_list(value: object) -> list[str]:
    if value is None:
        return []
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, list):
        return []
    return [item for item in decoded if isinstance(item, str)]


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()  # noqa: UP017
