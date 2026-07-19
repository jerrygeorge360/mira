import json
from pathlib import Path

from api.routes import evaluation


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_local_eval_summary_falls_back_to_published_snapshot(
    monkeypatch,
    tmp_path: Path,
) -> None:
    cases_path = tmp_path / "memory_cases.json"
    generated_path = tmp_path / "missing.results.json"
    snapshot_path = tmp_path / "published_summary.json"
    _write_json(
        cases_path,
        {
            "cases": [
                {
                    "id": "case-1",
                    "interactions": [{"message": "Remember that MIRA has evals."}],
                    "expect": {"answer_contains": ["MIRA"]},
                }
            ]
        },
    )
    _write_json(
        snapshot_path,
        {
            "passed": 1,
            "total": 1,
            "pass_rate": 1.0,
            "by_category": {"direct_fact_recall": {"passed": 1, "total": 1}},
            "results": [
                {
                    "id": "case-1",
                    "category": "direct_fact_recall",
                    "passed": True,
                    "retrieval_mode": "quick",
                    "checks": [{"name": "answer_contains:MIRA", "passed": True}],
                    "answer": "MIRA has evals.",
                }
            ],
        },
    )
    monkeypatch.setattr(evaluation, "_LOCAL_CASES", cases_path)
    monkeypatch.setattr(evaluation, "_LOCAL_EVAL", generated_path)
    monkeypatch.setattr(evaluation, "_LOCAL_EVAL_SNAPSHOT", snapshot_path)

    summary = evaluation._local_eval_summary()

    assert summary is not None
    assert summary["passed"] == 1
    assert summary["total"] == 1
    assert summary["cases"][0]["interactions"] == [{"message": "Remember that MIRA has evals."}]


def test_local_eval_summary_prefers_generated_results(
    monkeypatch,
    tmp_path: Path,
) -> None:
    cases_path = tmp_path / "memory_cases.json"
    generated_path = tmp_path / "memory_cases.results.json"
    snapshot_path = tmp_path / "published_summary.json"
    _write_json(cases_path, {"cases": []})
    _write_json(snapshot_path, {"passed": 13, "total": 13, "results": []})
    _write_json(generated_path, {"passed": 2, "total": 2, "results": []})
    monkeypatch.setattr(evaluation, "_LOCAL_CASES", cases_path)
    monkeypatch.setattr(evaluation, "_LOCAL_EVAL", generated_path)
    monkeypatch.setattr(evaluation, "_LOCAL_EVAL_SNAPSHOT", snapshot_path)

    summary = evaluation._local_eval_summary()

    assert summary is not None
    assert summary["passed"] == 2
    assert summary["total"] == 2
