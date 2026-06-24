"""Safe helpers for parsing structured LLM outputs.

Ownership: Jerry.
Related issue: ISSUE-021.
Architecture area: llm.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable

LOGGER = logging.getLogger(__name__)

StructuredJsonPayload = dict[str, object] | list[dict[str, object]]


class StructuredJsonError(ValueError):
    """Base error for structured-JSON parsing failures."""

    def __init__(self, message: str, raw_text: str) -> None:
        super().__init__(message)
        self.message = message
        self.raw_text = raw_text

    def __str__(self) -> str:
        preview = _preview(self.raw_text)
        return f"{self.message}: {preview}"


class StructuredJsonParseError(StructuredJsonError):
    """Raised when model output cannot be parsed as safe structured JSON."""


class StructuredJsonValidationError(StructuredJsonError):
    """Raised when parsed structured JSON is missing required top-level keys."""

    def __init__(self, message: str, raw_text: str, missing_keys: Iterable[str]) -> None:
        super().__init__(message, raw_text)
        self.missing_keys = tuple(sorted(missing_keys))


def parse_json_response(raw_text: str) -> StructuredJsonPayload:
    """Parse raw model output as strict JSON."""
    return _parse_json_response(raw_text)


def validate_required_keys(payload: dict[str, object], required_keys: set[str]) -> bool:
    """Return True when all required keys are present in a parsed JSON object."""
    missing_keys = sorted(key for key in required_keys if key not in payload)
    if missing_keys:
        LOGGER.warning(
            "Structured JSON payload missing required keys: %s",
            ", ".join(missing_keys),
        )
        return False
    return True


def coerce_or_reject_json(raw_text: str) -> StructuredJsonPayload:
    """Parse strict JSON, safely unwrapping a single Markdown code fence if present."""
    try:
        return _parse_json_response(raw_text)
    except StructuredJsonParseError as first_error:
        markdown_payload = _unwrap_markdown_json(raw_text)
        if markdown_payload is None:
            raise first_error
        try:
            return _parse_json_response(markdown_payload)
        except StructuredJsonParseError:
            raise


def _parse_json_response(raw_text: str) -> StructuredJsonPayload:
    stripped = raw_text.strip()
    if not stripped:
        error = StructuredJsonParseError("Structured JSON response was empty", raw_text)
        _log_failure(error)
        raise error
    try:
        decoded = json.loads(stripped)
    except json.JSONDecodeError as error:
        structured_error = StructuredJsonParseError(
            f"Structured JSON response was not valid JSON: {error.msg}",
            raw_text,
        )
        _log_failure(structured_error)
        raise structured_error from error
    if isinstance(decoded, dict):
        return dict(decoded)
    if isinstance(decoded, list):
        if not all(isinstance(item, dict) for item in decoded):
            structured_error = StructuredJsonParseError(
                "Structured JSON array must contain only objects",
                raw_text,
            )
            _log_failure(structured_error)
            raise structured_error
        return [dict(item) for item in decoded]
    structured_error = StructuredJsonParseError(
        (
            "Structured JSON response must be an object or array of objects, "
            f"got {type(decoded).__name__}"
        ),
        raw_text,
    )
    _log_failure(structured_error)
    raise structured_error


def _unwrap_markdown_json(raw_text: str) -> str | None:
    stripped = raw_text.strip()
    if not stripped.startswith("```") or not stripped.endswith("```"):
        return None
    first_newline = stripped.find("\n")
    if first_newline == -1:
        return None
    language = stripped[3:first_newline].strip().casefold()
    if language not in {"", "json"}:
        return None
    payload = stripped[first_newline + 1 : -3].strip()
    if not payload:
        return None
    return payload


def _log_failure(error: StructuredJsonError) -> None:
    LOGGER.warning("%s", error)


def _preview(raw_text: str, limit: int = 160) -> str:
    compact = " ".join(raw_text.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 3]}..."
