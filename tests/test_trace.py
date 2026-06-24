from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from core import agent
from core.agent import handle_user_message
from core.db.repositories import (
    configure_database,
    create_answer_trace,
    create_session,
    get_answer_trace,
    list_answer_traces_by_observation,
    list_answer_traces_by_session,
    repository_connection,
)
from core.memory.trace import TraceBuilder


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    path = tmp_path / "mira.sqlite3"
    configure_database(path)
    yield path


class _CapturingQwen:
    def __init__(self, answer: str = "Acknowledged.") -> None:
        self.answer = answer
        self.prompts: list[str] = []

    def __call__(self, messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
        assert schema_name == "answer_generation"
        self.prompts.append(messages[0]["content"])
        return {"json": {"answer": self.answer, "used_memory_ids": []}}


@pytest.fixture
def fake_qwen(monkeypatch: pytest.MonkeyPatch) -> _CapturingQwen:
    fake = _CapturingQwen()
    monkeypatch.setattr(agent, "call_qwen_json", fake)
    return fake


# --- Repository-level tests ---


def _create_observation(session_id: str, content: str = "test content") -> str:
    from core.db.repositories import save_observation

    return save_observation(session_id, "user", content)


def test_create_and_get_answer_trace(database_path: Path) -> None:
    session_id = create_session("test-user")
    obs1 = _create_observation(session_id)
    obs2 = _create_observation(session_id, "assistant response")
    trace_id = create_answer_trace(
        {
            "session_id": session_id,
            "user_observation_id": obs1,
            "assistant_observation_id": obs2,
            "retrieval_mode": "quick",
            "retrieved_observation_ids_json": ["obs-a", "obs-b"],
            "retrieved_fact_ids_json": ["fact-1"],
            "session_item_ids_json": ["item-1"],
            "hot_memory_ids_json": [],
            "graph_path_ids_json": [],
            "community_summary_ids_json": [],
            "sufficiency_json": None,
            "prompt_sections_json": [{"section": "recent_turns", "source_ids": ["obs-1"]}],
            "hydration_ids_json": [],
            "retrieval_log_id": None,
            "prompt_log_id": None,
        }
    )
    assert trace_id

    fetched = get_answer_trace(trace_id)
    assert fetched is not None
    assert fetched["session_id"] == session_id
    assert fetched["retrieval_mode"] == "quick"
    assert fetched["retrieved_observation_ids_json"] == ["obs-a", "obs-b"]
    assert fetched["retrieved_fact_ids_json"] == ["fact-1"]
    assert fetched["session_item_ids_json"] == ["item-1"]
    assert fetched["prompt_sections_json"] == [{"section": "recent_turns", "source_ids": ["obs-1"]}]


def test_list_answer_traces_by_session(database_path: Path) -> None:
    session_id = create_session("test-user")
    obs1 = _create_observation(session_id)
    obs2 = _create_observation(session_id)
    obs3 = _create_observation(session_id)
    obs4 = _create_observation(session_id)
    id1 = create_answer_trace(
        {
            "session_id": session_id,
            "user_observation_id": obs1,
            "assistant_observation_id": obs2,
            "retrieval_mode": "quick",
        }
    )
    id2 = create_answer_trace(
        {
            "session_id": session_id,
            "user_observation_id": obs3,
            "assistant_observation_id": obs4,
            "retrieval_mode": "deep",
        }
    )

    traces = list_answer_traces_by_session(session_id)
    assert len(traces) == 2
    assert traces[0]["id"] == id2
    assert traces[1]["id"] == id1


def test_list_answer_traces_by_observation(database_path: Path) -> None:
    session_id = create_session("test-user")
    obs1 = _create_observation(session_id)
    obs2 = _create_observation(session_id)
    trace_id = create_answer_trace(
        {
            "session_id": session_id,
            "user_observation_id": obs1,
            "assistant_observation_id": obs2,
            "retrieval_mode": "quick",
        }
    )

    traces = list_answer_traces_by_observation(obs1)
    assert len(traces) == 1
    assert traces[0]["id"] == trace_id

    assert list_answer_traces_by_observation("nonexistent") == []


def test_answer_trace_rejects_missing_required_fields(database_path: Path) -> None:
    session_id = create_session("test-user")
    with pytest.raises(ValueError, match="Missing required field"):
        create_answer_trace({"session_id": session_id})


# --- TraceBuilder unit tests ---


class TestTraceBuilder:
    def test_builder_accumulates_and_builds(self, database_path: Path) -> None:
        session_id = create_session("test-user")
        user_obs = _create_observation(session_id, "user turn")
        assistant_obs = _create_observation(session_id, "assistant turn")
        builder = TraceBuilder(session_id, user_obs)
        builder.assistant_observation_id = assistant_obs
        builder.record_retrieval(
            "quick",
            [
                {"source": "observations", "source_id": "obs-1"},
                {"source": "atomic_facts", "source_id": "fact-1"},
                {"source": "observations", "source_id": "obs-2"},
            ],
        )
        builder.record_session_items([{"id": "si-1"}, {"id": "si-2"}])
        builder.record_hot_memory([{"id": "hm-1"}])
        builder.record_prompt_sections(
            [
                {"section": "recent_turns", "source_ids": ["obs-1"]},
                {"section": "session_working_set", "source_ids": ["si-1", "si-2"]},
            ]
        )
        builder.record_hydration(["hyd-1"])
        builder.link_retrieval_log("rl-1")
        builder.link_prompt_log("pl-1")

        trace_id = builder.build()
        assert trace_id

        fetched = get_answer_trace(trace_id)
        assert fetched is not None
        assert fetched["retrieval_mode"] == "quick"
        assert fetched["retrieved_observation_ids_json"] == ["obs-1", "obs-2"]
        assert fetched["retrieved_fact_ids_json"] == ["fact-1"]
        assert fetched["session_item_ids_json"] == ["si-1", "si-2"]
        assert fetched["hot_memory_ids_json"] == ["hm-1"]
        assert len(fetched["prompt_sections_json"]) == 2
        assert fetched["hydration_ids_json"] == ["hyd-1"]
        assert fetched["retrieval_log_id"] == "rl-1"
        assert fetched["prompt_log_id"] == "pl-1"

    def test_builder_classifies_sources(self, database_path: Path) -> None:
        session_id = create_session("test-user")
        user_obs = _create_observation(session_id)
        assistant_obs = _create_observation(session_id)
        builder = TraceBuilder(session_id, user_obs)
        builder.assistant_observation_id = assistant_obs

        builder.record_retrieval(
            "deep",
            [
                {"source": "community_summary", "source_id": "cs-1", "community_id": "c-1"},
                {"source": "reflection", "source_id": "ref-1"},
                {"source": "observation", "source_id": "obs-3"},
            ],
        )
        trace_id = builder.build()
        fetched = get_answer_trace(trace_id)
        assert fetched is not None
        assert fetched["community_summary_ids_json"] == ["cs-1"]
        assert fetched["graph_path_ids_json"] == []
        assert "obs-3" in fetched["retrieved_observation_ids_json"]

    def test_builder_graph_paths(self, database_path: Path) -> None:
        session_id = create_session("test-user")
        user_obs = _create_observation(session_id)
        assistant_obs = _create_observation(session_id)
        builder = TraceBuilder(session_id, user_obs)
        builder.assistant_observation_id = assistant_obs

        builder.record_retrieval(
            "relational",
            [
                {"source": "graph_edge", "source_id": "edge-1", "confidence": 0.9},
                {"source": "graph_edge", "source_id": "edge-2", "confidence": 0.8},
            ],
        )
        trace_id = builder.build()
        fetched = get_answer_trace(trace_id)
        assert fetched is not None
        assert fetched["graph_path_ids_json"] == ["edge-1", "edge-2"]

    def test_builder_empty_sources(self, database_path: Path) -> None:
        session_id = create_session("test-user")
        user_obs = _create_observation(session_id)
        assistant_obs = _create_observation(session_id)
        builder = TraceBuilder(session_id, user_obs)
        builder.assistant_observation_id = assistant_obs

        builder.record_retrieval("quick", [])
        builder.record_session_items([])
        builder.record_hot_memory([])
        builder.record_prompt_sections([])

        trace_id = builder.build()
        fetched = get_answer_trace(trace_id)
        assert fetched is not None
        assert fetched["retrieved_observation_ids_json"] == []
        assert fetched["session_item_ids_json"] == []

    def test_builder_sufficiency(self, database_path: Path) -> None:
        session_id = create_session("test-user")
        user_obs = _create_observation(session_id)
        assistant_obs = _create_observation(session_id)
        builder = TraceBuilder(session_id, user_obs)
        builder.assistant_observation_id = assistant_obs

        builder.record_sufficiency({"sufficient": False, "gaps": ["deadline info"]})
        builder.record_retrieval("quick", [{"source": "observations", "source_id": "obs-1"}])

        trace_id = builder.build()
        fetched = get_answer_trace(trace_id)
        assert fetched is not None
        assert fetched["sufficiency_json"] == {"sufficient": False, "gaps": ["deadline info"]}

    def test_builder_defaults(self, database_path: Path) -> None:
        session_id = create_session("test-user")
        user_obs = _create_observation(session_id)
        assistant_obs = _create_observation(session_id)
        builder = TraceBuilder(session_id, user_obs)
        builder.assistant_observation_id = assistant_obs

        trace_id = builder.build()
        fetched = get_answer_trace(trace_id)
        assert fetched is not None
        assert fetched["retrieval_mode"] == "quick"
        assert fetched["retrieved_observation_ids_json"] == []
        assert fetched["retrieved_fact_ids_json"] == []


# --- Integration tests: agent produces traces ---


def test_answer_trace_created_per_turn(database_path: Path, fake_qwen: _CapturingQwen) -> None:
    session_id = create_session("jerry")
    response = handle_user_message(session_id, "What is my deadline?")

    assert "trace_id" in response

    fetched = get_answer_trace(str(response["trace_id"]))
    assert fetched is not None
    assert fetched["session_id"] == session_id
    assert fetched["user_observation_id"] == response["user_observation_id"]
    assert fetched["assistant_observation_id"] == response["assistant_observation_id"]
    assert isinstance(fetched["retrieval_mode"], str)


def test_trace_id_in_response(database_path: Path, fake_qwen: _CapturingQwen) -> None:
    session_id = create_session("jerry")
    response = handle_user_message(session_id, "What is my deadline?")

    assert isinstance(response["trace_id"], str)
    assert len(response["trace_id"]) > 0


def test_trace_persisted_in_sqlite(database_path: Path, fake_qwen: _CapturingQwen) -> None:
    session_id = create_session("jerry")
    response = handle_user_message(session_id, "What is my deadline?")

    trace_id = str(response["trace_id"])
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT id FROM answer_traces WHERE id = ?", (trace_id,)
        ).fetchone()
    assert row is not None


def test_trace_queryable_by_session_id(database_path: Path, fake_qwen: _CapturingQwen) -> None:
    session_id = create_session("jerry")
    handle_user_message(session_id, "What is my deadline?")
    handle_user_message(session_id, "And my other deadlines?")

    traces = list_answer_traces_by_session(session_id)
    assert len(traces) == 2


def test_trace_queryable_by_observation_id(database_path: Path, fake_qwen: _CapturingQwen) -> None:
    session_id = create_session("jerry")
    response = handle_user_message(session_id, "What is my deadline?")

    traces = list_answer_traces_by_observation(str(response["user_observation_id"]))
    assert len(traces) == 1
    assert traces[0]["id"] == response["trace_id"]


def test_trace_contains_retrieval_mode(database_path: Path, fake_qwen: _CapturingQwen) -> None:
    session_id = create_session("jerry")
    response = handle_user_message(session_id, "What kind of developer am I?")

    fetched = get_answer_trace(str(response["trace_id"]))
    assert fetched is not None
    assert fetched["retrieval_mode"] == "deep"


def test_trace_contains_session_items(database_path: Path, fake_qwen: _CapturingQwen) -> None:
    session_id = create_session("jerry")
    response = handle_user_message(session_id, "Use 2026, not 2025.")

    fetched = get_answer_trace(str(response["trace_id"]))
    assert fetched is not None
    assert len(fetched["session_item_ids_json"]) > 0


def test_trace_contains_prompt_sections(database_path: Path, fake_qwen: _CapturingQwen) -> None:
    session_id = create_session("jerry")
    response = handle_user_message(session_id, "What is my deadline?")

    fetched = get_answer_trace(str(response["trace_id"]))
    assert fetched is not None
    sections = fetched["prompt_sections_json"]
    assert isinstance(sections, list)
    assert len(sections) > 0


def test_trace_links_to_retrieval_and_prompt_logs(
    database_path: Path, fake_qwen: _CapturingQwen
) -> None:
    session_id = create_session("jerry")
    response = handle_user_message(session_id, "What is my deadline?")

    fetched = get_answer_trace(str(response["trace_id"]))
    assert fetched is not None
    with repository_connection() as connection:
        if fetched.get("retrieval_log_id"):
            rl_row = connection.execute(
                "SELECT id FROM retrieval_logs WHERE id = ?",
                (str(fetched["retrieval_log_id"]),),
            ).fetchone()
            assert rl_row is not None
        if fetched.get("prompt_log_id"):
            pl_row = connection.execute(
                "SELECT id FROM prompt_logs WHERE id = ?",
                (str(fetched["prompt_log_id"]),),
            ).fetchone()
            assert pl_row is not None


def test_trace_sufficiency_is_null_when_unavailable(
    database_path: Path, fake_qwen: _CapturingQwen
) -> None:
    session_id = create_session("jerry")
    response = handle_user_message(session_id, "Simple question.")

    fetched = get_answer_trace(str(response["trace_id"]))
    assert fetched is not None
    assert fetched["sufficiency_json"] is None


def test_multiple_turns_produce_separate_traces(
    database_path: Path, fake_qwen: _CapturingQwen
) -> None:
    session_id = create_session("jerry")
    r1 = handle_user_message(session_id, "First message.")
    r2 = handle_user_message(session_id, "Second message.")
    r3 = handle_user_message(session_id, "Third message.")

    assert r1["trace_id"] != r2["trace_id"]
    assert r2["trace_id"] != r3["trace_id"]

    traces = list_answer_traces_by_session(session_id)
    assert len(traces) == 3
