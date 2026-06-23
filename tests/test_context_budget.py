"""Verify the ISSUE-016 prompt budget manager.

Ownership: MIRA contributors.
Related issue: ISSUE-016.
Architecture area: context.
"""

from __future__ import annotations

import pytest

from core.context.budget import (
    allocate_prompt_budget,
    estimate_tokens,
    trim_context_sections,
)


def _section(name: str, tokens: int, content: str | None = None) -> dict[str, object]:
    return {
        "section": name,
        "token_count": tokens,
        "content": content if content is not None else name,
    }


def test_estimate_tokens_is_deterministic_and_nonzero_for_text() -> None:
    """Token estimates are stable without importing a tokenizer package."""
    assert estimate_tokens("") == 0
    assert estimate_tokens("Use 2026, not 2025.") == estimate_tokens("Use 2026, not 2025.")
    assert estimate_tokens("Use 2026, not 2025.") >= 1


def test_response_reserve_is_respected() -> None:
    """Prompt allocations never consume the reserved response budget."""
    allocation = allocate_prompt_budget(total_budget=1_000, response_reserve=250)
    prompt_keys = [
        "system_developer_constraints",
        "current_user_message",
        "session_working_set",
        "hot_memory",
        "retrieved_memories",
        "recent_turns",
        "warm_cold_memories",
        "diagnostics",
    ]

    assert allocation["response_reserve"] == 250
    assert allocation["prompt_budget"] == 750
    assert sum(allocation[key] for key in prompt_keys) == 750
    assert allocation["hot_memory"] < allocation["prompt_budget"]


def test_invalid_response_reserve_is_rejected() -> None:
    """A response reserve cannot consume the entire context window."""
    with pytest.raises(ValueError, match="response_reserve"):
        allocate_prompt_budget(total_budget=100, response_reserve=100)


def test_low_priority_sections_are_trimmed_first() -> None:
    """Diagnostics and warm/cold context lose space before core prompt sections."""
    sections = [
        _section("system_developer_constraints", 20),
        _section("current_user_message", 20),
        _section("session_working_set", 20),
        _section("diagnostics", 20),
        _section("warm_cold_memories", 20),
    ]

    trimmed = trim_context_sections(sections, total_budget=60)

    assert [section["section"] for section in trimmed] == [
        "system_developer_constraints",
        "current_user_message",
        "session_working_set",
    ]


def test_session_working_set_survives_before_recent_old_turns() -> None:
    """Session Working Set pressure outranks older recent turns."""
    sections = [
        _section("recent_turns", 40, "old turn"),
        _section("session_working_set", 40, "current correction"),
        _section("retrieved_memories", 40, "retrieved fact"),
    ]

    trimmed = trim_context_sections(sections, total_budget=80)

    assert [section["content"] for section in trimmed] == [
        "current correction",
        "retrieved fact",
    ]


def test_input_order_is_preserved_after_priority_trimming() -> None:
    """Selected sections keep their original order for prompt-builder assembly."""
    sections = [
        _section("system_developer_constraints", 10),
        _section("current_user_message", 10),
        _section("diagnostics", 50),
        _section("session_working_set", 10),
    ]

    trimmed = trim_context_sections(sections, total_budget=30)

    assert [section["section"] for section in trimmed] == [
        "system_developer_constraints",
        "current_user_message",
        "session_working_set",
    ]
