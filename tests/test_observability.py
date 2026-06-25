"""Verify ISSUE-056 structured logging and secret redaction.

Ownership: MIRA contributors.
Related issue: ISSUE-056.
Architecture area: infra.
"""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator

import pytest

from core import observability
from core.observability import (
    configure_logging,
    log_event,
    log_observation_saved,
    log_qwen_error,
    log_retrieval_route,
    log_validator_rejection,
)


@pytest.fixture
def log_stream() -> Iterator[io.StringIO]:
    """Capture structured logs into an in-memory stream."""
    stream = io.StringIO()
    configure_logging(level=logging.DEBUG, stream=stream)
    yield stream
    logging.getLogger(observability.LOGGER_NAME).handlers.clear()


def _records(stream: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]


def test_logs_are_structured(log_stream: io.StringIO) -> None:
    """Each log line is JSON with event/level/logger/message fields."""
    log_observation_saved("sess_1", "obs_1", "user")

    records = _records(log_stream)
    assert len(records) == 1
    record = records[0]
    assert record["event"] == "observation_saved"
    assert record["level"] == "INFO"
    assert record["logger"] == "mira"
    assert record["session_id"] == "sess_1"
    assert record["observation_id"] == "obs_1"
    assert record["role"] == "user"
    assert "time" in record


def test_errors_include_session_and_observation_ids(log_stream: io.StringIO) -> None:
    """Error events carry the session and observation ids for diagnosis."""
    log_qwen_error(
        RuntimeError("upstream timeout"),
        session_id="sess_42",
        observation_id="obs_42",
    )

    record = _records(log_stream)[0]
    assert record["event"] == "qwen_error"
    assert record["level"] == "ERROR"
    assert record["session_id"] == "sess_42"
    assert record["observation_id"] == "obs_42"
    assert record["error_type"] == "RuntimeError"


def test_secrets_in_fields_are_redacted(log_stream: io.StringIO) -> None:
    """Secret-named fields are never written in the clear."""
    log_event(
        "test_event",
        "configured client",
        api_key="sk-supersecretkey1234567890",
        dashscope_api_key="sk-anothersecret9999999999",
        session_id="sess_1",
    )

    record = _records(log_stream)[0]
    assert record["api_key"] == "[REDACTED]"
    assert record["dashscope_api_key"] == "[REDACTED]"
    assert record["session_id"] == "sess_1"
    assert "supersecret" not in log_stream.getvalue()


def test_secrets_in_messages_are_redacted(log_stream: io.StringIO) -> None:
    """Token-shaped strings inside messages and errors are scrubbed."""
    log_qwen_error(RuntimeError("auth failed for Bearer abcd1234efgh5678 token"))
    log_validator_rejection("sess_1", "obs_1", "leaked xoxb-99999999-secrettoken value")

    output = log_stream.getvalue()
    assert "abcd1234efgh5678" not in output
    assert "xoxb-99999999-secrettoken" not in output
    assert output.count("[REDACTED]") >= 2


def test_retrieval_route_event_records_mode_and_reason(log_stream: io.StringIO) -> None:
    """The retrieval-route event shows which path ran and why."""
    log_retrieval_route("sess_1", "relational", "entity-centered change question")

    record = _records(log_stream)[0]
    assert record["event"] == "retrieval_route"
    assert record["mode"] == "relational"
    assert record["reason"] == "entity-centered change question"


def test_reserved_field_names_do_not_crash(log_stream: io.StringIO) -> None:
    """Passing a reserved LogRecord field name is dropped, not fatal."""
    log_event("safe", "ok", name="should-be-ignored", session_id="sess_1")

    record = _records(log_stream)[0]
    assert record["logger"] == "mira"  # 'name' did not overwrite the logger name
    assert record["session_id"] == "sess_1"
