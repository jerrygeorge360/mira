"""Verify safe parsing helpers for structured LLM output."""

from __future__ import annotations

import pytest

from core.llm.json_helpers import (
    StructuredJsonParseError,
    coerce_or_reject_json,
    parse_json_response,
    validate_required_keys,
)


def test_valid_json_parses() -> None:
    """Valid JSON objects and arrays of objects parse safely."""
    assert parse_json_response('{"answer": "yes"}') == {"answer": "yes"}
    assert parse_json_response('[{"answer": "yes"}]') == [{"answer": "yes"}]


def test_markdown_wrapped_json_is_handled_if_safe() -> None:
    """A single fenced JSON block is unwrapped and parsed."""
    payload = coerce_or_reject_json(
        """```json
        {"answer": "yes"}
        ```"""
    )

    assert payload == {"answer": "yes"}


def test_invalid_json_is_rejected() -> None:
    """Malformed JSON raises a structured parse error."""
    with pytest.raises(StructuredJsonParseError, match="not valid JSON"):
        parse_json_response("{answer: yes}")


def test_missing_required_keys_fail() -> None:
    """Required keys are checked explicitly before business-specific handling."""
    payload = {"answer": "yes"}

    assert validate_required_keys(payload, {"answer"}) is True
    assert validate_required_keys(payload, {"answer", "used_memory_ids"}) is False
