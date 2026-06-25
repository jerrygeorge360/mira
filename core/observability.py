"""Structured logging and secret redaction for runtime and demo debugging.

Ownership: Kelechi.
Related issue: ISSUE-056.
Architecture area: infra.

Memory systems fail silently without good traces. This module emits structured
(JSON line) logs that show which path ran and why, with a helper per runtime
event, and redacts secrets (API keys, Slack tokens, bearer tokens) from both
messages and structured fields. It deliberately stays dependency-free -- no heavy
observability service -- so the demo's failures are diagnosable from the logs.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import IO

LOGGER_NAME = "mira"
LOGGER = logging.getLogger(LOGGER_NAME)

REDACTED = "[REDACTED]"

# Field names whose values are always secrets.
SECRET_FIELD_NAMES = frozenset(
    {
        "api_key",
        "dashscope_api_key",
        "token",
        "slack_bot_token",
        "slack_app_token",
        "authorization",
        "password",
        "secret",
    }
)

# Token shapes to scrub from free-text messages.
_SECRET_PATTERNS = (
    re.compile(r"xox[baprs]-[A-Za-z0-9-]+"),
    re.compile(r"xapp-[A-Za-z0-9-]+"),
    re.compile(r"sk-[A-Za-z0-9]{12,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{8,}"),
)

# Standard LogRecord attributes we must not treat as structured extras.
_RESERVED = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime", "event"}


class StructuredFormatter(logging.Formatter):
    """Render log records as single-line JSON with redacted secrets."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "time": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),  # noqa: UP017
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event", record.module),
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED:
                payload[key] = value
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)
        return _to_json(_redact_value("", payload))


def configure_logging(level: int = logging.INFO, stream: IO[str] | None = None) -> logging.Logger:
    """Configure the ``mira`` logger to emit structured, redacted JSON lines."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(StructuredFormatter())
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def log_event(
    event: str,
    message: str,
    *,
    level: int = logging.INFO,
    exc_info: BaseException | bool | None = None,
    **fields: object,
) -> None:
    """Emit one structured event with arbitrary safe extra fields."""
    extra = {"event": event, **_safe_fields(fields)}
    LOGGER.log(level, message, exc_info=exc_info, extra=extra)


# --- One helper per contracted runtime event --------------------------------


def log_observation_saved(session_id: str, observation_id: str, role: str) -> None:
    """Log that a raw observation was persisted on the fast path."""
    log_event(
        "observation_saved",
        "observation saved",
        session_id=session_id,
        observation_id=observation_id,
        role=role,
    )


def log_session_extraction(
    session_id: str,
    observation_id: str,
    applied: int,
    rejected: int,
) -> None:
    """Log the result of session micro-path extraction for a turn."""
    log_event(
        "session_extraction",
        "session extraction result",
        session_id=session_id,
        observation_id=observation_id,
        applied=applied,
        rejected=rejected,
    )


def log_validator_rejection(session_id: str, observation_id: str, reason: str) -> None:
    """Log a rejected session operation with its reason."""
    log_event(
        "validator_rejection",
        "session operation rejected",
        level=logging.WARNING,
        session_id=session_id,
        observation_id=observation_id,
        reason=reason,
    )


def log_session_hydration(session_id: str, hydrated_ids: list[str]) -> None:
    """Log how many durable items were hydrated into a session."""
    log_event(
        "session_hydration",
        "session hydration",
        session_id=session_id,
        hydrated_count=len(hydrated_ids),
        hydrated_ids=list(hydrated_ids),
    )


def log_retrieval_route(session_id: str, mode: str, reason: str) -> None:
    """Log the routed retrieval mode and why it was chosen."""
    log_event(
        "retrieval_route",
        "retrieval route selected",
        session_id=session_id,
        mode=mode,
        reason=reason,
    )


def log_prompt_budget_trim(
    session_id: str,
    dropped_sections: int,
    kept_sections: int,
    token_budget: int,
) -> None:
    """Log how prompt context was trimmed to fit the token budget."""
    log_event(
        "prompt_budget_trim",
        "prompt budget trim",
        session_id=session_id,
        dropped_sections=dropped_sections,
        kept_sections=kept_sections,
        token_budget=token_budget,
    )


def log_slow_path_step(
    observation_id: str,
    step: str,
    status: str,
    detail: str | None = None,
) -> None:
    """Log the result of one asynchronous slow-path step."""
    log_event(
        "slow_path_step",
        "slow-path step result",
        observation_id=observation_id,
        step=step,
        status=status,
        detail=detail,
    )


def log_qwen_error(
    error: BaseException,
    *,
    session_id: str | None = None,
    observation_id: str | None = None,
) -> None:
    """Log a Qwen call failure with session/observation context."""
    log_event(
        "qwen_error",
        f"Qwen call failed: {error}",
        level=logging.ERROR,
        session_id=session_id,
        observation_id=observation_id,
        error_type=type(error).__name__,
    )


def log_slack_error(error: BaseException, *, channel: str | None = None) -> None:
    """Log a Slack integration failure."""
    log_event(
        "slack_error",
        f"Slack error: {error}",
        level=logging.ERROR,
        channel=channel,
        error_type=type(error).__name__,
    )


def log_ui_error(error: BaseException, *, view: str | None = None) -> None:
    """Log a UI failure."""
    log_event(
        "ui_error",
        f"UI error: {error}",
        level=logging.ERROR,
        view=view,
        error_type=type(error).__name__,
    )


def _safe_fields(fields: Mapping[str, object]) -> dict[str, object]:
    return {key: value for key, value in fields.items() if key not in _RESERVED}


def _redact_value(key: str, value: object) -> object:
    if key.lower() in SECRET_FIELD_NAMES:
        return REDACTED if value not in (None, "") else value
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, Mapping):
        return {str(k): _redact_value(str(k), v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_redact_value(key, item) for item in value]
    return value


def _redact_text(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def _to_json(payload: object) -> str:
    import json

    return json.dumps(payload, default=str, sort_keys=True)
