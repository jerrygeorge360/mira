from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from core.db.repositories import (
    configure_database,
    create_answer_trace,
    create_session,
)
from ui.trace_view import render_session_traces, render_trace


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    path = tmp_path / "mira.sqlite3"
    configure_database(path)
    yield path


def _create_observation(session_id: str, content: str = "test content") -> str:
    from core.db.repositories import save_observation

    return save_observation(session_id, "user", content)


def test_render_trace_returns_output(database_path: Path) -> None:
    session_id = create_session("test-user")
    obs1 = _create_observation(session_id)
    obs2 = _create_observation(session_id)
    trace_id = create_answer_trace(
        {
            "session_id": session_id,
            "user_observation_id": obs1,
            "assistant_observation_id": obs2,
            "retrieval_mode": "deep",
            "retrieved_observation_ids_json": ["obs-a", "obs-b"],
            "session_item_ids_json": ["si-1"],
            "hot_memory_ids_json": ["hm-1"],
            "community_summary_ids_json": ["cs-1"],
            "graph_path_ids_json": ["edge-1"],
            "hydration_ids_json": ["hyd-1"],
            "prompt_sections_json": [
                {"section": "recent_turns", "source_ids": ["obs-a"]},
                {"section": "session_working_set", "source_ids": ["si-1"]},
            ],
            "sufficiency_json": None,
        }
    )

    output = render_trace(trace_id)

    assert trace_id in output
    assert "deep" in output
    assert "obs-a" in output
    assert "obs-b" in output
    assert "si-1" in output
    assert "hm-1" in output
    assert "cs-1" in output
    assert "edge-1" in output
    assert "hyd-1" in output
    assert "recent_turns" in output
    assert "session_working_set" in output
    assert "(not evaluated)" in output


def test_render_trace_not_found(database_path: Path) -> None:
    output = render_trace("nonexistent-id")
    assert "not found" in output


def test_render_trace_linked_logs(database_path: Path) -> None:
    session_id = create_session("test-user")
    obs1 = _create_observation(session_id)
    obs2 = _create_observation(session_id)
    trace_id = create_answer_trace(
        {
            "session_id": session_id,
            "user_observation_id": obs1,
            "assistant_observation_id": obs2,
            "retrieval_mode": "quick",
            "retrieval_log_id": "rl-1",
            "prompt_log_id": "pl-1",
        }
    )

    output = render_trace(trace_id)
    assert "rl-1" in output
    assert "pl-1" in output


def test_render_session_traces(database_path: Path) -> None:
    session_id = create_session("test-user")
    obs1 = _create_observation(session_id)
    obs2 = _create_observation(session_id)
    create_answer_trace(
        {
            "session_id": session_id,
            "user_observation_id": obs1,
            "assistant_observation_id": obs2,
            "retrieval_mode": "quick",
        }
    )

    output = render_session_traces(session_id)
    assert "Answer Traces for Session" in output
    assert session_id in output


def test_render_session_traces_empty(database_path: Path) -> None:
    output = render_session_traces("nonexistent-session")
    assert "No traces found" in output


def test_render_trace_with_full_data(database_path: Path) -> None:
    session_id = create_session("test-user")
    obs1 = _create_observation(session_id)
    obs2 = _create_observation(session_id)
    trace_id = create_answer_trace(
        {
            "session_id": session_id,
            "user_observation_id": obs1,
            "assistant_observation_id": obs2,
            "retrieval_mode": "relational",
            "retrieved_observation_ids_json": ["obs-c", "obs-d", "obs-e"],
            "retrieved_fact_ids_json": ["fact-x", "fact-y"],
            "session_item_ids_json": ["si-a", "si-b"],
            "hot_memory_ids_json": ["hm-a"],
            "graph_path_ids_json": ["edge-a", "edge-b", "edge-c"],
            "community_summary_ids_json": ["cs-2"],
            "sufficiency_json": {"sufficient": True, "coverage": 0.8},
            "prompt_sections_json": [
                {"section": "current_user_message", "source_ids": []},
                {"section": "retrieved_records", "source_ids": ["obs-c", "obs-d"]},
                {"section": "ambient_context", "source_ids": []},
            ],
            "hydration_ids_json": ["hyd-a"],
            "retrieval_log_id": "rl-2",
            "prompt_log_id": "pl-2",
        }
    )

    output = render_trace(trace_id)
    assert "relational" in output
    assert "sufficient" in output or "True" in output
    assert "obs-c" in output
    assert "fact-x" in output
    assert "fact-y" in output
