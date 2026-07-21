"""Rule-assisted structured extraction for provisional session operations.

Ownership: Jerry.
Related issue: ISSUE-011.
Architecture area: session micro-path.
"""

from __future__ import annotations

import re

SessionOperation = dict[str, object]

ALLOWED_OPERATIONS = frozenset({"upsert", "supersede", "resolve", "expire", "no_op"})
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
PROJECT_SCOPE_MARKERS = frozenset({"mira", "project", "architecture", "schema", "database"})
AMBIGUOUS_MARKERS = frozenset({"maybe", "might", "possibly", "probably", "i guess", "later"})
SARCASM_MARKERS = frozenset({"yeah right", "as if", "/s", "sarcasm", "sure, jan"})
RESOLUTION_MARKERS = frozenset({"ignore that", "never mind", "nevermind", "drop that"})
EXPIRATION_MARKERS = frozenset({"for now", "temporary", "just this response", "next reply only"})
CORRECTION_PREFIX_RE = re.compile(r"^\s*(actually|correction)\b[:,-]?", re.IGNORECASE)
TRANSITION_RE = re.compile(
    r"\b(switched|switch|moved|move|migrated|migrate|changed|change)\s+from\b",
    re.IGNORECASE,
)
CORRECTION_NOT_RE = re.compile(
    r"\b(use|set|make|call|treat|store|prefer|reply|answer|assume)\b.+\bnot\b.+",
    re.IGNORECASE,
)


def extract_session_operations(
    observation_id: str,
    current_message: str,
    recent_turns: list[str],
    current_working_set: list[dict[str, object]],
) -> list[SessionOperation]:
    """Extract provisional session-state operations from a new user turn."""
    del recent_turns
    normalized_message = _normalize(current_message)
    if not normalized_message:
        return [_no_op(observation_id, current_message, "empty_message")]
    if _is_sarcastic(normalized_message):
        return [_no_op(observation_id, current_message, "sarcasm_or_irony")]
    if _is_low_confidence(normalized_message):
        return [_no_op(observation_id, current_message, "ambiguous_low_confidence")]
    if _is_resolution_or_expiration(normalized_message):
        return [
            _resolution_operation(
                observation_id,
                current_message,
                current_working_set,
                op="expire" if _should_expire(normalized_message) else "resolve",
            )
        ]
    correction = _extract_correction(observation_id, current_message, current_working_set)
    if correction is not None:
        return [correction]
    open_question = _extract_open_question(observation_id, current_message)
    if open_question is not None:
        return [open_question]
    decision = _extract_decision_or_constraint(observation_id, current_message)
    if decision is not None:
        return [decision]
    goal = _extract_current_goal(observation_id, current_message)
    if goal is not None:
        return [goal]
    return [_no_op(observation_id, current_message, "no_session_state_operation_detected")]


def _extract_correction(
    observation_id: str,
    message: str,
    current_working_set: list[dict[str, object]],
) -> SessionOperation | None:
    normalized_message = _normalize(message)
    if not _looks_like_correction(normalized_message, current_working_set):
        return None
    superseded_items = _matching_working_set_ids(normalized_message, current_working_set)
    return _operation(
        observation_id,
        message,
        op="upsert",
        item_type="correction",
        scope=_scope_for(message),
        priority=0.96,
        explicitness_label="direct_correction",
        supersedes=superseded_items,
    )


def _looks_like_correction(
    normalized_message: str,
    current_working_set: list[dict[str, object]],
) -> bool:
    """Require explicit correction structure, not incidental words like "not"."""
    if CORRECTION_PREFIX_RE.search(normalized_message):
        return True
    if TRANSITION_RE.search(normalized_message):
        return True
    if CORRECTION_NOT_RE.search(normalized_message):
        return True
    if " instead" in normalized_message or "instead " in normalized_message:
        return bool(current_working_set) or _contains_any(
            normalized_message,
            (" use ", " set ", " store ", " prefer ", " answer ", " reply "),
        )
    return False


def _extract_decision_or_constraint(
    observation_id: str,
    message: str,
) -> SessionOperation | None:
    normalized_message = _normalize(message)
    decision_markers = (
        " are different from ",
        " is different from ",
        "we decided",
        "the rule is",
        "must ",
        "should ",
    )
    if not any(marker in normalized_message for marker in decision_markers):
        return None
    item_type = (
        "active_constraint"
        if _contains_any(normalized_message, ("must ", "should "))
        else "decision"
    )
    explicitness = "direct_decision" if item_type == "decision" else "direct_instruction"
    return _operation(
        observation_id,
        message,
        op="upsert",
        item_type=item_type,
        scope=_scope_for(message),
        priority=0.86,
        explicitness_label=explicitness,
    )


def _extract_current_goal(observation_id: str, message: str) -> SessionOperation | None:
    normalized_message = _normalize(message)
    goal_markers = ("let's ", "lets ", "i want to ", "we need to ", "goal is")
    if not any(marker in normalized_message for marker in goal_markers):
        return None
    return _operation(
        observation_id,
        message,
        op="upsert",
        item_type="current_goal",
        scope="current_task",
        priority=0.82,
        explicitness_label="direct_instruction",
    )


def _extract_open_question(observation_id: str, message: str) -> SessionOperation | None:
    normalized_message = _normalize(message)
    explicit_open_markers = (
        "open question",
        "we need to decide",
        "we need to figure out",
        "we still need to",
        "we have not decided",
        "we haven't decided",
    )
    open_question_markers = (*explicit_open_markers, "should we ")
    if "?" not in message or not any(
        marker in normalized_message for marker in open_question_markers
    ):
        return None
    return _operation(
        observation_id,
        message,
        op="upsert",
        item_type="open_question",
        scope="current_task",
        priority=0.62,
        explicitness_label=(
            "direct_instruction"
            if any(marker in normalized_message for marker in explicit_open_markers)
            else "ambiguous"
        ),
    )


def _resolution_operation(
    observation_id: str,
    message: str,
    current_working_set: list[dict[str, object]],
    *,
    op: str,
) -> SessionOperation:
    target_ids = _candidate_target_ids(current_working_set)
    return _operation(
        observation_id,
        message,
        op=op,
        item_type="resolution",
        scope="current_task",
        priority=0.78,
        explicitness_label="direct_instruction",
        supersedes=target_ids,
    )


def _operation(
    observation_id: str,
    message: str,
    *,
    op: str,
    item_type: str,
    scope: str,
    priority: float,
    explicitness_label: str,
    supersedes: list[str] | None = None,
) -> SessionOperation:
    if op not in ALLOWED_OPERATIONS - {"no_op"}:
        raise ValueError(f"Unsupported operation: {op}")
    if item_type not in ALLOWED_ITEM_TYPES:
        raise ValueError(f"Unsupported item type: {item_type}")
    return {
        "op": op,
        "type": item_type,
        "content": message.strip(),
        "scope": scope,
        "priority": priority,
        "explicitness_label": explicitness_label,
        "evidence_span": _evidence_span(message),
        "source_observations": [observation_id],
        "supersedes": supersedes or [],
        "status": "provisional",
    }


def _no_op(observation_id: str, message: str, reason: str) -> SessionOperation:
    return {
        "op": "no_op",
        "reason": reason,
        "evidence_span": _evidence_span(message),
        "source_observations": [observation_id],
    }


def _matching_working_set_ids(
    normalized_message: str,
    current_working_set: list[dict[str, object]],
) -> list[str]:
    ids: list[str] = []
    for item in current_working_set:
        item_id = item.get("id")
        content = item.get("content")
        if isinstance(item_id, str) and isinstance(content, str):
            normalized_content = _normalize(content)
            if normalized_content and normalized_content in normalized_message:
                ids.append(item_id)
    return ids


def _candidate_target_ids(current_working_set: list[dict[str, object]]) -> list[str]:
    ids: list[str] = []
    for item in current_working_set:
        item_id = item.get("id")
        status = item.get("status", "provisional")
        if isinstance(item_id, str) and status not in {"resolved", "expired", "rejected"}:
            ids.append(item_id)
    return ids


def _scope_for(message: str) -> str:
    normalized_message = _normalize(message)
    if any(marker in normalized_message for marker in PROJECT_SCOPE_MARKERS):
        return "project"
    return "current_session"


def _evidence_span(message: str) -> str:
    return re.sub(r"\s+", " ", message).strip()


def _is_low_confidence(normalized_message: str) -> bool:
    return any(marker in normalized_message for marker in AMBIGUOUS_MARKERS)


def _is_sarcastic(normalized_message: str) -> bool:
    return any(marker in normalized_message for marker in SARCASM_MARKERS)


def _is_resolution_or_expiration(normalized_message: str) -> bool:
    return any(marker in normalized_message for marker in RESOLUTION_MARKERS | EXPIRATION_MARKERS)


def _should_expire(normalized_message: str) -> bool:
    return any(marker in normalized_message for marker in EXPIRATION_MARKERS | {"ignore that"})


def _contains_any(normalized_message: str, markers: tuple[str, ...]) -> bool:
    return any(marker in normalized_message for marker in markers)


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()
