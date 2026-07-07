"""Verify structured internal functions for concrete agent workflows."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from core.db.repositories import configure_database, create_session
from core.llm.functions import (
    INSPECT_MEMORY_FUNCTION,
    inspect_memory,
    invoke_structured_function,
    maybe_structured_tool_call,
    tool_result_context_record,
)
from core.session.working_set import upsert_session_item


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    """Configure function tests to use an isolated database."""
    path = tmp_path / "mira.sqlite3"
    configure_database(path)
    yield path


def test_memory_inspection_tool_is_only_selected_for_explicit_workflow(
    database_path: Path,
) -> None:
    """General questions should not trigger structured function-calling."""
    session_id = create_session("jerry")

    assert maybe_structured_tool_call(session_id, "What is an apple?") is None

    result = maybe_structured_tool_call(session_id, "What do you remember about me?")

    assert result is not None
    assert result["tool"] == INSPECT_MEMORY_FUNCTION


def test_inspect_memory_returns_structured_snapshot(database_path: Path) -> None:
    """The memory inspection function returns typed runtime diagnostics."""
    session_id = create_session("jerry")
    upsert_session_item(
        session_id,
        {
            "type": "active_constraint",
            "content": "Jerry prefers concise technical answers.",
            "scope": "cross_session",
            "status": "active",
            "priority": 0.9,
            "explicitness_label": "direct_instruction",
            "source_observations": [],
        },
    )

    result = inspect_memory(session_id, query="memory status")

    assert result["tool"] == INSPECT_MEMORY_FUNCTION
    assert result["session_id"] == session_id
    assert isinstance(result["counts"], dict)
    assert result["session_working_set"]
    assert isinstance(result["vector_store"], dict)


def test_structured_function_dispatch_validates_name(database_path: Path) -> None:
    """Unsupported functions fail closed instead of silently no-oping."""
    session_id = create_session("jerry")

    with pytest.raises(ValueError, match="Unsupported structured function"):
        invoke_structured_function("future_tool", {"session_id": session_id})


def test_tool_result_context_record_is_prompt_ready(database_path: Path) -> None:
    """Tool results can enter the existing retrieval/context pipeline."""
    session_id = create_session("jerry")
    result = inspect_memory(session_id, query="show memory")

    record = tool_result_context_record(result)

    assert record["id"] == "tool:inspect_memory"
    assert record["source"] == "structured_tool"
    assert "Structured memory inspection result" in str(record["content"])
