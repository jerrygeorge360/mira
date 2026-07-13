"""Verify ISSUE-052 LongMemEval/LoCoMo-style adapter skeleton.

Ownership: MIRA contributors.
Related issue: ISSUE-052.
Architecture area: evaluation.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from core import agent
from core.db.repositories import configure_database
from evaluation.benchmarks.longmemeval import (
    default_scorer,
    import_conversations,
    iter_examples,
    load_benchmark_dataset,
    load_sessions,
    run_longmemeval,
    run_question,
    score_answer,
)


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    """Configure adapter tests to use an isolated database."""
    path = tmp_path / "mira.sqlite3"
    configure_database(path)
    yield path


@pytest.fixture
def fake_qwen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock the Qwen call with a deterministic answer."""

    def _call(messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
        return {"json": {"answer": "Your deadline is Friday.", "used_memory_ids": []}}

    monkeypatch.setattr(agent, "call_qwen_json", _call)


def _example() -> dict[str, object]:
    return {
        "question_id": "lme-1",
        "question_type": "multi-session",
        "question": "What is my deadline?",
        "answer": "Friday",
        "sessions": [
            {
                "session_id": "s1",
                "turns": [
                    {"role": "user", "content": "My deadline is Friday."},
                    {"role": "assistant", "content": "Noted."},
                ],
            },
            {
                "session_id": "s2",
                "turns": [{"role": "user", "content": "Unrelated chatter."}],
            },
        ],
    }


def _write_dataset(tmp_path: Path) -> Path:
    path = tmp_path / "bench.json"
    path.write_text(json.dumps({"name": "fake", "examples": [_example()]}), encoding="utf-8")
    return path


def test_adapter_interface_exists() -> None:
    """The five adapter stages are exposed as callables."""
    for stage in (
        load_benchmark_dataset,
        load_sessions,
        import_conversations,
        run_question,
        score_answer,
        run_longmemeval,
    ):
        assert callable(stage)


def test_fake_benchmark_file_loads(database_path: Path, tmp_path: Path) -> None:
    """A fake benchmark file loads and parses into sessions/turns."""
    dataset_path = _write_dataset(tmp_path)

    dataset = load_benchmark_dataset(str(dataset_path))
    examples = iter_examples(dataset)
    assert len(examples) == 1

    sessions = load_sessions(examples[0])
    assert [session.session_ref for session in sessions] == ["s1", "s2"]
    assert sessions[0].turns[0].role == "user"


def test_import_conversations_persists_turns(database_path: Path) -> None:
    """Importing replays sessions into MIRA and maps session refs."""
    result = import_conversations(_example())

    assert set(result.session_id_map) == {"s1", "s2"}
    assert result.imported_turns == 3


def test_questions_run_through_agent(database_path: Path, fake_qwen: None) -> None:
    """A benchmark question runs through the agent and captures an answer."""
    captured = run_question("What is my deadline?")

    assert captured["answer"] == "Your deadline is Friday."
    assert captured["retrieval_mode"] == "quick"


def test_run_longmemeval_is_labeled_prototype(
    database_path: Path, tmp_path: Path, fake_qwen: None
) -> None:
    """The orchestrator runs end to end and never claims official results."""
    dataset_path = _write_dataset(tmp_path)

    summary = run_longmemeval(str(dataset_path))

    assert summary["official"] is False
    assert summary["status"] == "prototype"
    assert summary["total"] == 1
    assert summary["matched"] == 1  # "Friday" appears in the mocked answer
    assert summary["results"][0]["question_id"] == "lme-1"


def test_default_scorer_containment_and_overlap() -> None:
    """The default scorer matches on containment and term overlap."""
    assert default_scorer("PostgreSQL", "I moved to PostgreSQL.")["match"] is True
    assert default_scorer("Kubernetes", "We use Postgres.")["match"] is False


def test_shipped_sample_dataset_loads() -> None:
    """The shipped prototype dataset is loadable with sessions."""
    sample = (
        Path(__file__).resolve().parents[1]
        / "evaluation"
        / "benchmarks"
        / "sample_longmemeval.json"
    )
    dataset = load_benchmark_dataset(str(sample))
    examples = iter_examples(dataset)
    assert len(examples) == 2
    assert load_sessions(examples[0])[0].turns
