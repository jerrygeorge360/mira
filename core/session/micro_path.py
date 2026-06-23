"""Orchestration for the complete session micro-path.

Ownership: Jerry.
Related issue: ISSUE-201.
Architecture area: session micro-path.

This wires the fast-path observation id, the rule-assisted extractor, the
deterministic validator, and the temporary Session Working Set store into one
synchronous step. It runs after raw persistence and before prompt construction
so corrections affect the next response without waiting for the slow path.
"""

from __future__ import annotations

import logging

from core.session.extractor import extract_session_operations
from core.session.validator import validate_session_operation
from core.session.working_set import (
    expire_session_item,
    list_active_session_items,
    resolve_session_item,
    supersede_session_item,
    upsert_session_item,
)

SessionOperation = dict[str, object]
SessionItem = dict[str, object]

LOGGER = logging.getLogger(__name__)


def run_session_micro_path(
    session_id: str,
    observation_id: str,
    current_message: str,
    recent_turns: list[str],
) -> list[str]:
    """Extract, validate, and apply provisional session state for a new turn.

    The observation is already persisted. This loads the current Session Working
    Set, extracts candidate operations, validates them structurally, applies the
    valid ones, logs the rejected ones for slow-path review, and returns the
    identifiers of the Session Working Set items that changed.
    """
    current_working_set = list_active_session_items(session_id)
    operations = extract_session_operations(
        observation_id,
        current_message,
        recent_turns,
        current_working_set,
    )

    known_observation_ids = {observation_id}
    known_working_set_ids = {
        str(item["id"]) for item in current_working_set if isinstance(item.get("id"), str)
    }

    changed_ids: list[str] = []
    for operation in operations:
        if validate_session_operation(operation, known_observation_ids, known_working_set_ids):
            changed_ids.extend(_apply_operation(session_id, operation))
        else:
            _log_rejected_operation(observation_id, operation)
    return _unique(changed_ids)


def _apply_operation(session_id: str, operation: SessionOperation) -> list[str]:
    op = operation.get("op")
    if op == "upsert":
        return _apply_upsert(session_id, operation)
    if op == "supersede":
        return _apply_supersede(session_id, operation)
    if op in {"resolve", "expire"}:
        return _apply_resolution(session_id, operation, str(op))
    # no_op and any unhandled-but-valid operation leave state untouched.
    return []


def _apply_upsert(session_id: str, operation: SessionOperation) -> list[str]:
    item = _operation_to_item(operation)
    new_id = upsert_session_item(session_id, item)
    changed = [new_id]
    for superseded_id in _string_list(operation.get("supersedes")):
        supersede_session_item(session_id, superseded_id, new_id)
        changed.append(superseded_id)
    return changed


def _apply_supersede(session_id: str, operation: SessionOperation) -> list[str]:
    item = _operation_to_item(operation)
    new_id = upsert_session_item(session_id, item)
    changed = [new_id]
    target_id = operation.get("target_id")
    if isinstance(target_id, str):
        supersede_session_item(session_id, target_id, new_id)
        changed.append(target_id)
    return changed


def _apply_resolution(session_id: str, operation: SessionOperation, op: str) -> list[str]:
    reason = _resolution_reason(operation)
    changed: list[str] = []
    for target_id in _string_list(operation.get("supersedes")):
        if op == "expire":
            expire_session_item(session_id, target_id, reason)
        else:
            resolve_session_item(session_id, target_id, reason)
        changed.append(target_id)
    return changed


def _operation_to_item(operation: SessionOperation) -> SessionItem:
    return {
        "type": operation["type"],
        "content": operation["content"],
        "scope": operation["scope"],
        "status": operation.get("status", "provisional"),
        "priority": operation["priority"],
        "explicitness_label": operation["explicitness_label"],
        "evidence_span": operation.get("evidence_span"),
        "source_observations": _string_list(operation.get("source_observations")),
        "supersedes": _string_list(operation.get("supersedes")),
    }


def _resolution_reason(operation: SessionOperation) -> str | None:
    for field_name in ("evidence_span", "content"):
        value = operation.get(field_name)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _log_rejected_operation(observation_id: str, operation: SessionOperation) -> None:
    LOGGER.warning(
        "Rejected micro-path operation for slow-path review: observation=%s op=%r type=%r",
        observation_id,
        operation.get("op"),
        operation.get("type"),
    )


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered
