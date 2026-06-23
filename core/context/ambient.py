"""Sensa-style ambient context provider for temporal and optional prompt signals.

Ownership: Jerry.
Related issue: ISSUE-018.
Architecture area: context.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core.db.repositories import repository_connection

AmbientContext = dict[str, object]

DEFAULT_TIMEZONE = "UTC"
TIMEZONE_ENV = "MIRA_USER_TIMEZONE"
COARSE_LOCATION_ENV = "MIRA_COARSE_LOCATION"


def build_ambient_context(
    session_id: str,
    user_timezone: str | None = None,
) -> AmbientContext:
    """Build stable temporal prompt context for one session."""
    timezone_name = _resolve_timezone_name(user_timezone)
    now = datetime.now(timezone.utc).astimezone(_zoneinfo(timezone_name))  # noqa: UP017
    return {
        "kind": "ambient_context",
        "ambient_context_role": "prompt_signal",
        "memory_tier": None,
        "retrieval_mode": None,
        "current_date": now.date().isoformat(),
        "current_time": now.isoformat(timespec="seconds"),
        "timezone": timezone_name,
        "session_gap": calculate_session_gap(session_id),
        "coarse_location": os.getenv(COARSE_LOCATION_ENV),
        "weather_context": None,
    }


def calculate_session_gap(session_id: str) -> AmbientContext:
    """Calculate elapsed time since the session's latest persisted activity."""
    session = _fetch_session(session_id)
    latest_observation_at = _latest_observation_at(session_id)
    latest_activity_at = latest_observation_at or _session_activity_at(session)
    now = datetime.now(timezone.utc)  # noqa: UP017
    started_at = _parse_datetime(str(session["created_at"]))
    latest_at = _parse_datetime(latest_activity_at)
    since_latest_seconds = max(0, int((now - latest_at).total_seconds()))
    since_start_seconds = max(0, int((now - started_at).total_seconds()))
    return {
        "session_id": session_id,
        "basis": "latest_observation" if latest_observation_at else "session_record",
        "latest_activity_at": latest_at.isoformat(),
        "session_started_at": started_at.isoformat(),
        "seconds_since_latest_activity": since_latest_seconds,
        "seconds_since_session_start": since_start_seconds,
        "human_gap": _human_gap(since_latest_seconds),
    }


def get_ambient_context(
    timezone_name: str,
    previous_session_at: str | None = None,
    include_optional_signals: bool = False,
) -> dict[str, object]:
    """Provide legacy ambient context for compatibility callers."""
    timezone_value = _resolve_timezone_name(timezone_name)
    now = datetime.now(timezone.utc).astimezone(_zoneinfo(timezone_value))  # noqa: UP017
    previous_at = _parse_datetime(previous_session_at) if previous_session_at else None
    gap_seconds = None if previous_at is None else max(0, int((now - previous_at).total_seconds()))
    context: AmbientContext = {
        "kind": "ambient_context",
        "ambient_context_role": "prompt_signal",
        "memory_tier": None,
        "retrieval_mode": None,
        "current_date": now.date().isoformat(),
        "current_time": now.isoformat(timespec="seconds"),
        "timezone": timezone_value,
        "session_gap": {
            "previous_session_at": previous_at.isoformat() if previous_at else None,
            "seconds_since_previous_session": gap_seconds,
            "human_gap": None if gap_seconds is None else _human_gap(gap_seconds),
        },
    }
    if include_optional_signals:
        context["coarse_location"] = os.getenv(COARSE_LOCATION_ENV)
        context["weather_context"] = None
    return context


def _fetch_session(session_id: str) -> AmbientContext:
    with repository_connection() as connection:
        row = connection.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None:
        raise ValueError(f"Session not found: {session_id}")
    return dict(row)


def _latest_observation_at(session_id: str) -> str | None:
    with repository_connection() as connection:
        row = connection.execute(
            """
            SELECT created_at
            FROM observations
            WHERE session_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()
    return None if row is None else str(row["created_at"])


def _session_activity_at(session: AmbientContext) -> str:
    for field_name in ("ended_at", "updated_at", "created_at"):
        value = session.get(field_name)
        if isinstance(value, str) and value:
            return value
    raise ValueError("Session has no temporal activity fields")


def _resolve_timezone_name(user_timezone: str | None) -> str:
    timezone_name = user_timezone or os.getenv(TIMEZONE_ENV) or DEFAULT_TIMEZONE
    _zoneinfo(timezone_name)
    return timezone_name


def _zoneinfo(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as error:
        raise ValueError(f"Unknown timezone: {timezone_name}") from error


def _parse_datetime(value: str | None) -> datetime:
    if value is None or not value:
        raise ValueError("datetime value must not be empty")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)  # noqa: UP017
    return parsed.astimezone(timezone.utc)  # noqa: UP017


def _human_gap(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} seconds"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minutes"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hours"
    days = hours // 24
    return f"{days} days"
