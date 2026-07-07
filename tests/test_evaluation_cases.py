"""Verify ISSUE-051 local evaluation harness.

Ownership: MIRA contributors.
Related issue: ISSUE-051.
Architecture area: evaluation.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from core import agent
from core.db.repositories import configure_database, repository_connection
from evaluation.cases import load_evaluation_cases, run_evaluation_cases, score_case


def _observation_count() -> int:
    with repository_connection() as connection:
        return int(connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0])


def _two_case_suite(tmp_path: Path) -> Path:
    cases = {
        "cases": [
            {
                "id": "first",
                "category": "direct_fact_recall",
                "interactions": [{"message": "My deadline is Friday."}],
                "expect": {},
            },
            {
                "id": "second",
                "category": "direct_fact_recall",
                "interactions": [{"message": "Anything else?"}],
                "expect": {},
            },
        ]
    }
    path = tmp_path / "isolation.json"
    path.write_text(json.dumps(cases), encoding="utf-8")
    return path


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    """Configure evaluation tests to use an isolated database."""
    path = tmp_path / "mira.sqlite3"
    configure_database(path)
    yield path


@pytest.fixture
def fake_qwen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock the Qwen call with a deterministic answer mentioning the deadline."""

    def _call(messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
        return {"json": {"answer": "Your deadline is Friday.", "used_memory_ids": []}}

    monkeypatch.setattr(agent, "call_qwen_json", _call)


def _write_cases(tmp_path: Path) -> Path:
    cases = {
        "cases": [
            {
                "id": "fact-recall",
                "category": "direct_fact_recall",
                "interactions": [
                    {"message": "My deadline is Friday."},
                    {"message": "What is my deadline?"},
                ],
                "expect": {"retrieval_mode": "quick", "answer_contains": ["Friday"]},
            },
            {
                "id": "correction",
                "category": "session_correction_handling",
                "interactions": [{"message": "Use 2026, not 2025."}],
                "expect": {"used_session_items_nonempty": True},
            },
            {
                "id": "deep-route",
                "category": "deep_mode_synthesis",
                "interactions": [{"message": "What kind of developer am I?"}],
                "expect": {"retrieval_mode": "deep"},
            },
        ]
    }
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(cases), encoding="utf-8")
    return path


def test_score_case_basic_pass_and_fail() -> None:
    """Pass/fail scoring evaluates declared expectations."""
    passing = score_case({"answer_contains": ["Friday"]}, {"answer": "It is Friday."})
    failing = score_case({"retrieval_mode": "quick"}, {"retrieval_mode": "deep"})

    assert passing["passed"] is True
    assert passing["score"] == 1.0
    assert failing["passed"] is False
    assert failing["score"] == 0.0


def test_score_case_checks_mechanism_trace_fields() -> None:
    """Mechanism checks fail when the right answer lacks architectural evidence."""
    actual = {
        "answer": "PostgreSQL",
        "retrieval_trace": {
            "retrieved": [{"source": "graph_edge", "id": "edge-1"}],
            "used_memory": True,
        },
        "_eval_debug_records": [
            {
                "active_session_items": [
                    {"type": "correction", "explicitness_label": "direct_correction"}
                ],
                "slow_path": [
                    {
                        "observations": [
                            {
                                "created_record_ids": {"graph_edges": ["edge-1"]},
                                "created_graph_edges": [{"edge_type": "SUPERSEDED_BY"}],
                            }
                        ]
                    }
                ],
            }
        ],
    }

    passing = score_case(
        {
            "min_retrieved_records": 1,
            "retrieved_sources_include": ["graph_edge"],
            "slow_path_created_min": {"graph_edges": 1},
            "slow_path_created_edge_types_include": ["SUPERSEDED_BY"],
            "active_session_item_labels_include": [
                "type:correction",
                "explicitness_label:direct_correction",
            ],
        },
        actual,
    )
    failing = score_case(
        {
            "retrieved_sources_include": ["community_summary"],
            "slow_path_created_edge_types_include": ["CONTRADICTS"],
        },
        actual,
    )

    assert passing["passed"] is True
    assert failing["passed"] is False


def test_load_evaluation_cases(database_path: Path, tmp_path: Path) -> None:
    """Cases load from a JSON object with a cases array."""
    cases_path = _write_cases(tmp_path)
    cases = load_evaluation_cases(str(cases_path))
    assert [case["id"] for case in cases] == ["fact-recall", "correction", "deep-route"]


def test_evaluation_cases_run_and_results_saved(
    database_path: Path, tmp_path: Path, fake_qwen: None
) -> None:
    """Cases run end to end, scoring passes, and results are persisted."""
    cases_path = _write_cases(tmp_path)

    summary = run_evaluation_cases(str(cases_path))

    assert summary["total"] == 3
    assert summary["passed"] == 3
    assert summary["pass_rate"] == 1.0
    assert summary["by_category"]["direct_fact_recall"] == {"total": 1, "passed": 1}

    results_path = Path(str(summary["results_path"]))
    assert results_path.exists()
    saved = json.loads(results_path.read_text(encoding="utf-8"))
    assert saved["total"] == 3
    assert {result["id"] for result in saved["results"]} == {
        "fact-recall",
        "correction",
        "deep-route",
    }


def test_evaluation_cases_can_filter_by_case_id(
    database_path: Path, tmp_path: Path, fake_qwen: None
) -> None:
    """A focused run can execute only selected cases."""
    cases_path = _write_cases(tmp_path)

    summary = run_evaluation_cases(str(cases_path), case_ids=["correction"])

    assert summary["total"] == 1
    assert summary["results"][0]["id"] == "correction"


def test_evaluation_cases_report_progress(
    database_path: Path, tmp_path: Path, fake_qwen: None
) -> None:
    """Case execution can report human-readable progress for live runs."""
    cases_path = _write_cases(tmp_path)
    messages: list[str] = []

    summary = run_evaluation_cases(str(cases_path), progress=messages.append)

    assert summary["passed"] == 3
    assert messages[0].startswith("loaded cases=3")
    assert any(message.startswith("case 1/3 fact-recall: start") for message in messages)
    assert "case fact-recall: interaction 1/2 answering" in messages
    assert any(message.startswith("complete passed=3/3") for message in messages)


def test_evaluation_cases_can_drain_slow_path(
    database_path: Path,
    tmp_path: Path,
    fake_qwen: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Local eval can run the worker queue inline between interactions."""
    import core.memory.slow_path as slow_path

    cases_path = _write_cases(tmp_path)
    messages: list[str] = []
    calls = {"count": 0}

    def _fake_batch(batch_size: int) -> list[dict[str, object]]:
        calls["count"] += 1
        assert batch_size == 7
        if calls["count"] % 2 == 1:
            return [{"observation_id": f"obs-{calls['count']}", "succeeded": True}]
        return []

    monkeypatch.setattr(slow_path, "run_slow_path_batch", _fake_batch)

    summary = run_evaluation_cases(
        str(cases_path),
        progress=messages.append,
        run_slow_path=True,
        slow_path_batch_size=7,
    )

    assert summary["passed"] == 3
    assert calls["count"] >= 2
    assert any("slow path batch processed=1 failed=0" in message for message in messages)
    assert any("slow path idle processed=1 failed=0" in message for message in messages)


def test_evaluation_cases_can_write_debug_trace(
    database_path: Path, tmp_path: Path, fake_qwen: None
) -> None:
    """Debug trace writes a readable per-interaction forensic report."""
    cases_path = _write_cases(tmp_path)

    summary = run_evaluation_cases(str(cases_path), debug_trace=True)

    debug_path = Path(str(summary["debug_trace_path"]))
    assert debug_path.exists()
    debug_text = debug_path.read_text(encoding="utf-8")
    assert "# MIRA Local Eval Debug Trace" in debug_text
    assert "### Routing" in debug_text
    assert "### Prompt Sections" in debug_text
    assert "fact-recall" in debug_text


def test_cases_are_isolated_by_default(
    database_path: Path, tmp_path: Path, fake_qwen: None
) -> None:
    """Each case runs in its own database, so durable state cannot leak forward."""
    cases_path = _two_case_suite(tmp_path)

    summary = run_evaluation_cases(str(cases_path))

    assert summary["total"] == 2
    # Cases ran against isolated per-case databases; the configured base DB is
    # restored afterward and holds none of their observations.
    assert _observation_count() == 0


def test_shared_db_preserves_state_across_cases(
    database_path: Path, tmp_path: Path, fake_qwen: None
) -> None:
    """The opt-out shares one database so intentional continuity scenarios work."""
    cases_path = _two_case_suite(tmp_path)

    summary = run_evaluation_cases(str(cases_path), isolate_cases=False)

    assert summary["total"] == 2
    # Both cases wrote their user and assistant turns into the one shared DB.
    assert _observation_count() >= 4


def test_failing_expectation_is_reported(
    database_path: Path, tmp_path: Path, fake_qwen: None
) -> None:
    """A case whose expectation is not met is scored as failed."""
    cases = {
        "cases": [
            {
                "id": "wrong-mode",
                "category": "direct_fact_recall",
                "interactions": [{"message": "What is my deadline?"}],
                "expect": {"retrieval_mode": "deep"},
            }
        ]
    }
    cases_path = tmp_path / "failing.json"
    cases_path.write_text(json.dumps(cases), encoding="utf-8")

    summary = run_evaluation_cases(str(cases_path))

    assert summary["passed"] == 0
    assert summary["failed"] == 1
    assert summary["results"][0]["passed"] is False


def test_shipped_memory_cases_suite_is_loadable() -> None:
    """The shipped sample suite covers the evaluation categories and loads."""
    suite_path = Path(__file__).resolve().parents[1] / "evaluation" / "memory_cases.json"
    cases = load_evaluation_cases(str(suite_path))
    categories = {str(case["category"]) for case in cases}
    assert len(cases) == 10
    assert "direct_fact_recall" in categories
    assert "retrieval_sufficiency" in categories
    assert "routing_intent" in categories
