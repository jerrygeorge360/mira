"""Future-relevant constraints and time-sensitive memory records.

Ownership: Jerry.
Related issue: ISSUE-030.
Architecture area: slow path.

Foresight lets MIRA track deadlines, temporary constraints, travel, medication,
project windows, and other future-relevant state without permanently injecting
everything. Records move through an explicit, evidence-backed lifecycle:

    pending -> active -> resolved
    pending -> active -> expired
    pending / active -> cancelled

Time-driven transitions (activation, expiration) are computed from an ambient
"now" against ``valid_from`` / ``valid_until``. Resolution and cancellation are
explicit, evidence-backed actions, so they have dedicated entry points.
"""

from __future__ import annotations

import logging
import math
import re
from datetime import datetime, timezone

from core.db.repositories import (
    create_foresight_record,
    repository_connection,
    validate_enum_value,
)
from core.db.schema import LEGACY_WORKSPACE_ID
from core.llm.embeddings import embed_text
from core.llm.prompts import render_prompt
from core.llm.qwen import LLMClientError, call_qwen_json

ForesightRecord = dict[str, object]

LOGGER = logging.getLogger(__name__)

DETECTABLE_STATUSES = frozenset({"pending", "active"})
TERMINAL_STATUSES = frozenset({"resolved", "expired", "cancelled"})
FORESIGHT_RECONCILIATION_CONFIDENCE = 0.85
FORESIGHT_CANDIDATE_LLM_LIMIT = 8
FORESIGHT_RECENT_TURN_LIMIT = 6

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_'-]+")
DATE_PATTERN = re.compile(r"\b(?:20\d{2}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?)\b")
STOPWORDS = frozenset(
    {"a", "an", "the", "is", "are", "do", "did", "i", "my", "me", "to", "of", "for", "on", "when"}
)
FUTURE_MARKERS = frozenset(
    {
        "after",
        "before",
        "by",
        "deadline",
        "due",
        "event",
        "exam",
        "later",
        "next",
        "remind",
        "schedule",
        "scheduled",
        "soon",
        "submit",
        "today",
        "tomorrow",
        "upcoming",
        "until",
        "week",
        "month",
        "quarter",
    }
)
NON_FORESIGHT_MARKERS = frozenset(
    {
        "prefer",
        "prefers",
        "preference",
        "detailed responses",
        "concise responses",
        "answer in",
        "respond in",
        "use detailed",
    }
)
CANCELLATION_PATTERN = re.compile(
    r"\b(?:cancel|canceled|cancelled|cancled|cacelled|canceling|cancelling|drop|remove)\b|"
    r"\b(?:do not|don't|dont|no longer)\s+(?:have\s+)?|"
    r"\b(?:does not|doesn't|doesnt)\s+(?:apply|exist)\b|"
    r"\bnot\b.+\banymore\b",
    re.IGNORECASE,
)
CANCELLATION_STOPWORDS = frozenset(
    {
        "anymore",
        "apply",
        "cancel",
        "canceled",
        "cancelled",
        "cancled",
        "cacelled",
        "canceling",
        "cancelling",
        "doesn't",
        "doesnt",
        "don't",
        "dont",
        "drop",
        "exist",
        "have",
        "longer",
        "no",
        "not",
        "remove",
        "alright",
        "it",
        "that",
        "this",
        "was",
    }
)
REFERENCE_STOPWORDS = CANCELLATION_STOPWORDS | frozenset(
    {
        "about",
        "has",
        "remind",
        "scheduled",
        "their",
        "today",
        "tomorrow",
        "user",
        "you",
    }
)


def detect_foresight(
    observation_id: str,
    content: str,
    ambient_context: dict[str, object],
) -> list[ForesightRecord]:
    """Detect future-relevant foresight candidates from one observation."""
    if not observation_id:
        raise ValueError("observation_id must not be empty")
    if not content.strip():
        return []

    valid_from = _ambient_now(ambient_context)
    prompt = render_prompt(
        "foresight_detection",
        {"evidence": _evidence_with_ambient(content, ambient_context)},
    )
    response = call_qwen_json(
        [{"role": "user", "content": prompt}],
        schema_name="foresight_detection",
    )
    payload = response.get("json", {})
    raw_records = payload.get("foresight") if isinstance(payload, dict) else None
    if not isinstance(raw_records, list):
        return []

    records: list[ForesightRecord] = []
    for raw_record in raw_records:
        if not isinstance(raw_record, dict):
            continue
        record = _normalize_detected(raw_record, observation_id, valid_from)
        if record is not None:
            records.append(record)
    return records


def create_foresight(record: ForesightRecord) -> str:
    """Persist a foresight record and return its identifier."""
    content = _string(record.get("content"))
    status = _string(record.get("status")) or "pending"
    source_observation_id = _string(record.get("source_observation_id"))
    if not content:
        raise ValueError("foresight content must not be empty")
    if not source_observation_id:
        raise ValueError("foresight must reference a source observation")
    validate_enum_value("foresight_status", status)

    return create_foresight_record(
        {
            "content": content,
            "reason": _optional_string(record.get("reason")),
            "status": status,
            "source_observation_id": source_observation_id,
            "valid_from": _optional_string(record.get("valid_from")),
            "valid_until": _optional_string(record.get("valid_until")),
            "always_inject": int(bool(record.get("always_inject", False))),
            "resolved_by": _optional_string(record.get("resolved_by")),
        }
    )


def update_foresight_status(record_id: str, now: str) -> None:
    """Advance a record's time-driven lifecycle (activation, expiration) at ``now``."""
    record = _require_record(record_id)
    status = str(record["status"])
    if status in TERMINAL_STATUSES:
        return

    now_dt = _parse(now)
    valid_from_dt = _parse(record.get("valid_from"))
    valid_until_dt = _parse(record.get("valid_until"))

    new_status = status
    if valid_until_dt is not None and now_dt is not None and now_dt > valid_until_dt:
        new_status = "expired"
    elif status == "pending" and (
        valid_from_dt is None or now_dt is None or now_dt >= valid_from_dt
    ):
        new_status = "active"

    if new_status != status:
        _write_status(record_id, new_status)
        LOGGER.info("Foresight %s transitioned %s -> %s", record_id, status, new_status)


def refresh_foresight_lifecycle(
    now: str | None = None,
    *,
    workspace_id: str | None = None,
) -> dict[str, int]:
    """Advance every non-terminal foresight record whose time boundary has passed."""
    effective_now = now or _now()
    where = "WHERE status IN ('pending', 'active')"
    params: tuple[object, ...] = ()
    if workspace_id is not None:
        where += " AND workspace_id = ?"
        params = (workspace_id,)
    with repository_connection() as connection:
        rows = connection.execute(
            f"SELECT id, status FROM foresight_records {where}",  # nosec B608
            params,
        ).fetchall()

    activated = 0
    expired = 0
    for row in rows:
        record_id = str(row["id"])
        prior_status = str(row["status"])
        update_foresight_status(record_id, effective_now)
        current_status = str(_require_record(record_id)["status"])
        if prior_status != current_status:
            activated += int(current_status == "active")
            expired += int(current_status == "expired")
    return {"examined": len(rows), "activated": activated, "expired": expired}


def resolve_foresight(record_id: str, resolved_by: str) -> None:
    """Resolve a foresight record early, citing the observation that fulfilled it."""
    if not resolved_by:
        raise ValueError("resolved_by must not be empty")
    record = _require_record(record_id)
    status = str(record["status"])
    if status in TERMINAL_STATUSES:
        raise ValueError(f"cannot resolve foresight in terminal status {status!r}")
    _write_status(record_id, "resolved", resolved_by=resolved_by)
    LOGGER.info("Foresight %s resolved by %s", record_id, resolved_by)


def cancel_foresight(record_id: str, cancelled_by: str | None = None) -> None:
    """Cancel a foresight record that no longer applies."""
    record = _require_record(record_id)
    status = str(record["status"])
    if status in TERMINAL_STATUSES:
        raise ValueError(f"cannot cancel foresight in terminal status {status!r}")
    _write_status(record_id, "cancelled", resolved_by=cancelled_by)
    LOGGER.info("Foresight %s cancelled", record_id)


def cancel_matching_foresight(
    observation_id: str,
    content: str,
    *,
    workspace_id: str = LEGACY_WORKSPACE_ID,
    reference_text: str | None = None,
) -> list[str]:
    """Cancel active foresight explicitly withdrawn by a new user observation."""
    normalized = _normalize_text(content)
    if not CANCELLATION_PATTERN.search(normalized):
        return []
    target_tokens = _cancellation_tokens(normalized) - CANCELLATION_STOPWORDS
    if not target_tokens and reference_text:
        target_tokens = _cancellation_tokens(_normalize_text(reference_text)) - REFERENCE_STOPWORDS
    if not target_tokens:
        return []

    with repository_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM foresight_records "
            "WHERE workspace_id = ? AND status IN ('pending', 'active')",
            (workspace_id,),
        ).fetchall()

    cancelled: list[str] = []
    for row in rows:
        record = dict(row)
        record_tokens = _cancellation_tokens(
            f"{record.get('content', '')} {record.get('reason') or ''}"
        )
        if not target_tokens & record_tokens:
            continue
        record_id = str(record["id"])
        cancel_foresight(record_id, cancelled_by=observation_id)
        cancelled.append(record_id)
    return cancelled


def reconcile_foresight_lifecycle(
    observation_id: str,
    content: str,
    *,
    workspace_id: str = LEGACY_WORKSPACE_ID,
    session_id: str | None = None,
    reference_text: str | None = None,
    current_time: str | None = None,
) -> dict[str, object]:
    """Resolve a user update against workspace Foresight using bounded semantic context.

    Embeddings rank candidates but never mutate lifecycle state. A structured LLM verdict
    must reference supplied record IDs and clear a confidence gate. Provider failure falls
    back to the conservative explicit-cancellation matcher and otherwise leaves state alone.
    """
    candidates = _active_foresight_candidates(workspace_id)
    if not candidates:
        return _empty_reconciliation_result()
    shortlisted = _shortlist_foresight_candidates(content, candidates, reference_text)
    prompt = render_prompt(
        "foresight_reconciliation",
        {
            "current_time": current_time or _now(),
            "recent_turns": _recent_session_turns(session_id, observation_id),
            "reference_text": reference_text,
            "latest_statement": content,
            "candidates": shortlisted,
        },
    )
    try:
        response = call_qwen_json(
            [{"role": "user", "content": prompt}],
            schema_name="foresight_reconciliation",
        )
    except LLMClientError as error:
        LOGGER.warning(
            "Foresight semantic reconciliation failed; using conservative fallback: %s",
            error,
        )
        cancelled = cancel_matching_foresight(
            observation_id,
            content,
            workspace_id=workspace_id,
            reference_text=reference_text,
        )
        result = _empty_reconciliation_result()
        result["cancelled"] = cancelled
        result["fallback_used"] = True
        return result
    return _apply_foresight_decisions(
        observation_id,
        response.get("json"),
        shortlisted,
    )


def _active_foresight_candidates(workspace_id: str) -> list[ForesightRecord]:
    with repository_connection() as connection:
        rows = connection.execute(
            """
            SELECT foresight_records.*,
                   observations.content AS source_content,
                   observations.session_id AS source_session_id,
                   observations.created_at AS source_created_at
            FROM foresight_records
            JOIN observations
              ON observations.id = foresight_records.source_observation_id
            WHERE foresight_records.workspace_id = ?
              AND foresight_records.status IN ('pending', 'active')
            ORDER BY foresight_records.created_at DESC
            """,
            (workspace_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _shortlist_foresight_candidates(
    content: str,
    candidates: list[ForesightRecord],
    reference_text: str | None,
) -> list[ForesightRecord]:
    query_text = "\n".join(text for text in (content, reference_text) if text)
    try:
        query_embedding = embed_text(query_text)
        scored = [
            (
                _cosine_similarity(
                    query_embedding,
                    embed_text(_foresight_candidate_text(candidate)),
                ),
                candidate,
            )
            for candidate in candidates
        ]
        scored.sort(key=lambda pair: (-pair[0], -_timestamp(pair[1].get("created_at"))))
    except (LLMClientError, ValueError) as error:
        LOGGER.warning("Foresight candidate embedding failed; using recent candidates: %s", error)
        scored = [(0.0, candidate) for candidate in candidates]

    shortlisted: list[ForesightRecord] = []
    for similarity, candidate in scored[:FORESIGHT_CANDIDATE_LLM_LIMIT]:
        public_candidate: ForesightRecord = {
            "id": str(candidate["id"]),
            "content": str(candidate["content"]),
            "reason": _optional_string(candidate.get("reason")),
            "status": str(candidate["status"]),
            "valid_from": _optional_string(candidate.get("valid_from")),
            "valid_until": _optional_string(candidate.get("valid_until")),
            "source_statement": _optional_string(candidate.get("source_content")),
            "source_session_id": _optional_string(candidate.get("source_session_id")),
            "source_created_at": _optional_string(candidate.get("source_created_at")),
            "similarity": round(similarity, 4),
        }
        shortlisted.append(public_candidate)
    return shortlisted


def _apply_foresight_decisions(
    observation_id: str,
    payload: object,
    candidates: list[ForesightRecord],
) -> dict[str, object]:
    result = _empty_reconciliation_result()
    if not isinstance(payload, dict):
        return result
    valid_ids = {str(candidate["id"]) for candidate in candidates}
    decisions = payload.get("decisions")
    if not isinstance(decisions, list):
        return result
    needs_clarification = payload.get("needs_clarification") is True
    result["needs_clarification"] = needs_clarification
    clarification = payload.get("clarification")
    result["clarification"] = clarification.strip() if isinstance(clarification, str) else None
    if needs_clarification:
        return result
    applied_ids: set[str] = set()
    replacements: set[tuple[str, str | None]] = set()

    for decision in decisions:
        if not isinstance(decision, dict):
            continue
        target_id = _string(decision.get("target_id"))
        action = _string(decision.get("action")).casefold()
        confidence = _confidence(decision.get("confidence"))
        if (
            target_id not in valid_ids
            or target_id in applied_ids
            or confidence < FORESIGHT_RECONCILIATION_CONFIDENCE
        ):
            continue
        if action == "retain":
            _result_ids(result, "retained").append(target_id)
            applied_ids.add(target_id)
            continue
        if action == "unrelated":
            continue
        try:
            if action == "cancel":
                cancel_foresight(target_id, cancelled_by=observation_id)
                _result_ids(result, "cancelled").append(target_id)
            elif action == "resolve":
                resolve_foresight(target_id, observation_id)
                _result_ids(result, "resolved").append(target_id)
            elif action == "modify":
                replacement_content = _string(decision.get("replacement_content"))
                if not replacement_content:
                    continue
                replacement_valid_until = _normalize_valid_until(
                    decision.get("replacement_valid_until")
                )
                cancel_foresight(target_id, cancelled_by=observation_id)
                _result_ids(result, "cancelled").append(target_id)
                replacement_key = (replacement_content.casefold(), replacement_valid_until)
                if replacement_key not in replacements:
                    replacement_id = create_foresight(
                        {
                            "content": replacement_content,
                            "reason": _string(decision.get("reason")),
                            "status": "active",
                            "source_observation_id": observation_id,
                            "valid_from": _now(),
                            "valid_until": replacement_valid_until,
                            "always_inject": False,
                        }
                    )
                    _result_ids(result, "created").append(replacement_id)
                    replacements.add(replacement_key)
            else:
                continue
        except ValueError as error:
            LOGGER.warning("Ignoring invalid Foresight lifecycle decision: %s", error)
            continue
        applied_ids.add(target_id)
    return result


def _empty_reconciliation_result() -> dict[str, object]:
    return {
        "cancelled": [],
        "resolved": [],
        "created": [],
        "retained": [],
        "needs_clarification": False,
        "clarification": None,
        "fallback_used": False,
    }


def _result_ids(result: dict[str, object], key: str) -> list[str]:
    value = result.get(key)
    return value if isinstance(value, list) else []


def _recent_session_turns(session_id: str | None, observation_id: str) -> list[dict[str, str]]:
    if not session_id:
        return []
    with repository_connection() as connection:
        rows = connection.execute(
            """
            SELECT role, content, created_at
            FROM observations
            WHERE session_id = ? AND id != ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (session_id, observation_id, FORESIGHT_RECENT_TURN_LIMIT),
        ).fetchall()
    return [
        {
            "role": str(row["role"]),
            "content": str(row["content"]),
            "created_at": str(row["created_at"]),
        }
        for row in reversed(rows)
    ]


def _foresight_candidate_text(candidate: ForesightRecord) -> str:
    return " ".join(
        text
        for text in (
            _optional_string(candidate.get("content")),
            _optional_string(candidate.get("reason")),
            _optional_string(candidate.get("source_content")),
        )
        if text
    )


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)


def _confidence(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    return max(0.0, min(float(value), 1.0))


def list_relevant_foresight(
    query: str, now: str, *, workspace_id: str = LEGACY_WORKSPACE_ID
) -> list[ForesightRecord]:
    """List active foresight that is temporally valid and relevant at ``now``."""
    refresh_foresight_lifecycle(now, workspace_id=workspace_id)
    now_dt = _parse(now)
    query_tokens = _tokens(query)
    relevant: list[ForesightRecord] = []
    for row in _fetch_by_status("active", workspace_id=workspace_id):
        if not _temporally_valid(row, now_dt):
            continue
        always_inject = bool(row["always_inject"])
        relevance = _relevance(query_tokens, row)
        if always_inject or relevance > 0.0:
            relevant.append(_public_record(row, relevance, always_inject))
    relevant.sort(key=_relevance_key)
    return relevant


def _normalize_detected(
    raw_record: dict[object, object],
    observation_id: str,
    valid_from: str | None,
) -> ForesightRecord | None:
    content = _string(raw_record.get("content"))
    if not content:
        return None
    reason = _string(raw_record.get("reason"))
    if not _is_future_relevant(content, reason):
        LOGGER.info("Rejected non-future foresight candidate: %s", content)
        return None
    status = _string(raw_record.get("status"))
    if status not in DETECTABLE_STATUSES:
        status = "pending"
    return {
        "content": content,
        "reason": reason,
        "status": status,
        "always_inject": bool(raw_record.get("always_inject")),
        "source_observation_id": observation_id,
        "valid_from": valid_from,
        "valid_until": _normalize_valid_until(raw_record.get("valid_until")),
        "resolved_by": None,
    }


def _require_record(record_id: str) -> ForesightRecord:
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT * FROM foresight_records WHERE id = ?",
            (record_id,),
        ).fetchone()
    if row is None:
        raise ValueError(f"Foresight record not found: {record_id}")
    return dict(row)


def _write_status(record_id: str, status: str, resolved_by: str | None = None) -> None:
    validate_enum_value("foresight_status", status)
    now = _now()
    with repository_connection() as connection:
        if resolved_by is not None:
            cursor = connection.execute(
                """
                UPDATE foresight_records
                SET status = ?, resolved_by = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, resolved_by, now, record_id),
            )
        else:
            cursor = connection.execute(
                "UPDATE foresight_records SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, record_id),
            )
        if cursor.rowcount == 0:
            raise ValueError(f"Foresight record not found: {record_id}")
        if status in TERMINAL_STATUSES:
            hot_status = "expired" if status == "expired" else "demoted"
            connection.execute(
                """
                UPDATE working_memory
                SET status = ?, updated_at = ?
                WHERE source_record_type = 'foresight_records'
                  AND source_record_id = ? AND status = 'active'
                """,
                (hot_status, now, record_id),
            )


def _fetch_by_status(
    status: str, *, workspace_id: str = LEGACY_WORKSPACE_ID
) -> list[ForesightRecord]:
    with repository_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM foresight_records WHERE workspace_id = ? AND status = ? "
            "ORDER BY created_at DESC",
            (workspace_id, status),
        ).fetchall()
    return [dict(row) for row in rows]


def _temporally_valid(row: ForesightRecord, now_dt: datetime | None) -> bool:
    if now_dt is None:
        return True
    valid_from = _parse(row.get("valid_from"))
    valid_until = _parse(row.get("valid_until"))
    if valid_from is not None and now_dt < valid_from:
        return False
    return not (valid_until is not None and now_dt > valid_until)


def _relevance(query_tokens: set[str], row: ForesightRecord) -> float:
    if not query_tokens:
        return 0.0
    text = f"{row.get('content', '')} {row.get('reason') or ''}"
    content_tokens = _tokens(text)
    if not content_tokens:
        return 0.0
    return len(query_tokens & content_tokens) / len(query_tokens)


def _public_record(row: ForesightRecord, relevance: float, always_inject: bool) -> ForesightRecord:
    record = dict(row)
    record["always_inject"] = always_inject
    record["relevance"] = relevance
    return record


def _relevance_key(record: ForesightRecord) -> tuple[int, float, float]:
    always_inject = bool(record.get("always_inject"))
    raw_relevance = record.get("relevance", 0.0)
    relevance = float(raw_relevance) if isinstance(raw_relevance, int | float) else 0.0
    return (0 if always_inject else 1, -relevance, -_timestamp(record.get("created_at")))


def _ambient_now(ambient_context: dict[str, object]) -> str | None:
    for key in ("current_time", "current_date"):
        value = ambient_context.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _evidence_with_ambient(content: str, ambient_context: dict[str, object]) -> str:
    ambient_now = _ambient_now(ambient_context)
    if ambient_now is None:
        return content
    return f"{content}\n\n(Current date/time: {ambient_now})"


def _is_future_relevant(content: str, reason: str) -> bool:
    text = _normalize_text(f"{content} {reason}")
    if any(marker in text for marker in NON_FORESIGHT_MARKERS) and not _has_future_trigger(text):
        return False
    return _has_future_trigger(text)


def _has_future_trigger(text: str) -> bool:
    tokens = _tokens(text)
    phrase_markers = {marker for marker in FUTURE_MARKERS if " " in marker}
    word_markers = FUTURE_MARKERS - phrase_markers
    return (
        DATE_PATTERN.search(text) is not None
        or bool(tokens & word_markers)
        or any(marker in text for marker in phrase_markers)
    )


def _parse(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)  # noqa: UP017
    return parsed


def _timestamp(value: object) -> float:
    parsed = _parse(value)
    return 0.0 if parsed is None else parsed.timestamp()


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in TOKEN_PATTERN.findall(value.casefold())
        if len(token) > 1 and token not in STOPWORDS
    }


def _cancellation_tokens(value: str) -> set[str]:
    """Include conservative verb stems when matching an event withdrawal."""
    tokens = _tokens(value)
    expanded = set(tokens)
    for token in tokens:
        if token.endswith("ing") and len(token) > 5:
            stem = token[:-3]
            expanded.add(stem)
            if len(stem) > 2 and stem[-1] == stem[-2]:
                expanded.add(stem[:-1])
    return expanded


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _string(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _optional_string(value: object) -> str | None:
    text = _string(value)
    return text or None


def _normalize_valid_until(value: object) -> str | None:
    text = _optional_string(value)
    if text is None:
        return None
    if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", text):
        text = f"{text}T23:59:59+00:00"
    parsed = _parse(text)
    if parsed is None:
        LOGGER.warning("Ignoring invalid foresight valid_until value: %s", text)
        return None
    return parsed.isoformat()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()  # noqa: UP017
