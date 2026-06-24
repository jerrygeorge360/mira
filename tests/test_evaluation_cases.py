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
from core.db.repositories import configure_database
from evaluation.cases import load_evaluation_cases, run_evaluation_cases, score_case


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
    assert len(cases) == 8
    assert "direct_fact_recall" in categories
    assert "retrieval_sufficiency" in categories
