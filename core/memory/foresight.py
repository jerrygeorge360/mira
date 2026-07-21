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
import re
from datetime import datetime, timezone

from core.db.repositories import (
    create_foresight_record,
    repository_connection,
    validate_enum_value,
)
from core.db.schema import LEGACY_WORKSPACE_ID
from core.llm.prompts import render_prompt
from core.llm.qwen import call_qwen_json

ForesightRecord = dict[str, object]

LOGGER = logging.getLogger(__name__)

DETECTABLE_STATUSES = frozenset({"pending", "active"})
TERMINAL_STATUSES = frozenset({"resolved", "expired", "cancelled"})

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


def cancel_foresight(record_id: str) -> None:
    """Cancel a foresight record that no longer applies."""
    record = _require_record(record_id)
    status = str(record["status"])
    if status in TERMINAL_STATUSES:
        raise ValueError(f"cannot cancel foresight in terminal status {status!r}")
    _write_status(record_id, "cancelled")
    LOGGER.info("Foresight %s cancelled", record_id)


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
