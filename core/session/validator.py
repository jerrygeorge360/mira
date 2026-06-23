"""Deterministic structural validation for extractor operations.

Ownership: Jerry.
Related issue: ISSUE-012.
Architecture area: session micro-path.
"""

from __future__ import annotations

import logging

SessionOperation = dict[str, object]

LOGGER = logging.getLogger(__name__)

ALLOWED_OPERATIONS = frozenset({"upsert", "supersede", "resolve", "expire", "no_op"})
ALLOWED_SCOPES = frozenset(
    {"current_response", "current_task", "current_session", "project", "cross_session"}
)
ALLOWED_ITEM_TYPES = frozenset(
    {
        "current_goal",
        "active_constraint",
        "correction",
        "decision",
        "open_question",
        "resolution",
    }
)
TERMINAL_STATUSES = frozenset({"expired", "rejected", "resolved"})
EVIDENCE_REQUIRED_TYPES = frozenset({"correction", "decision", "active_constraint"})
PROTECTED_RULE_MARKERS = frozenset(
    {
        "system rule",
        "system prompt",
        "developer message",
        "developer instruction",
        "safety rule",
        "ignore safety",
        "bypass safety",
        "override policy",
    }
)


def validate_session_operation(
    operation: SessionOperation,
    known_observation_ids: set[str],
    known_working_set_ids: set[str],
) -> bool:
    """Validate that a session operation is structurally safe before applying it."""
    reason = _rejection_reason(operation, known_observation_ids, known_working_set_ids)
    if reason is not None:
        LOGGER.warning("Rejected session operation: %s", reason)
        return False
    return True


def _rejection_reason(
    operation: SessionOperation,
    known_observation_ids: set[str],
    known_working_set_ids: set[str],
) -> str | None:
    op = operation.get("op")
    if op not in ALLOWED_OPERATIONS:
        return "invalid operation"
    if op == "no_op":
        return None
    if _attempts_protected_rule_change(operation):
        return "attempted protected rule change"
    sources = operation.get("source_observations")
    if not _is_non_empty_string_list(sources):
        return "missing source observations"
    source_ids = _string_list(sources)
    if not set(source_ids) <= known_observation_ids:
        return "unknown source observation"
    scope = operation.get("scope")
    if scope not in ALLOWED_SCOPES:
        return "invalid scope"
    item_type = operation.get("type")
    if item_type not in ALLOWED_ITEM_TYPES:
        return "invalid item type"
    priority = operation.get("priority")
    if not _is_valid_priority(priority):
        return "invalid priority"
    if item_type in EVIDENCE_REQUIRED_TYPES and not _non_empty_string(
        operation.get("evidence_span")
    ):
        return "missing evidence span"
    if not _validate_referenced_working_set_items(operation, known_working_set_ids):
        return "invalid working-set reference"
    return None


def _validate_referenced_working_set_items(
    operation: SessionOperation,
    known_working_set_ids: set[str],
) -> bool:
    op = operation.get("op")
    supersedes = operation.get("supersedes", [])
    if supersedes is None:
        supersedes = []
    if not isinstance(supersedes, list) or not all(isinstance(item, str) for item in supersedes):
        return False
    if not set(supersedes) <= known_working_set_ids:
        return False
    target_id = operation.get("target_id")
    if op == "supersede":
        if not isinstance(target_id, str):
            return False
        if target_id not in known_working_set_ids:
            return False
    target_status = operation.get("target_status")
    return not (isinstance(target_status, str) and target_status in TERMINAL_STATUSES)


def _attempts_protected_rule_change(operation: SessionOperation) -> bool:
    text_parts: list[str] = []
    for field_name in ("content", "evidence_span"):
        value = operation.get(field_name)
        if isinstance(value, str):
            text_parts.append(value.casefold())
    text = " ".join(text_parts)
    return any(marker in text for marker in PROTECTED_RULE_MARKERS)


def _is_non_empty_string_list(value: object) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(item, str) for item in value)


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_valid_priority(value: object) -> bool:
    if not isinstance(value, int | float):
        return False
    return 0 <= float(value) <= 1
