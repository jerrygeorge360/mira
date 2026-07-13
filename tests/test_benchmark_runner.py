"""Verify ISSUE-123 official-capable benchmark runner.

Ownership: MIRA contributors.
Related issue: ISSUE-123.
Architecture area: evaluation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import run_benchmark

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GOLD_MARKER = "gold-only-marker-xyz"


def _dataset(tmp_path: Path, count: int = 2) -> Path:
    examples = [
        {
            "question_id": f"q{i}",
            "question_type": "knowledge_update",
            "category": "knowledge_update",
            "question": "What database do we use?",
            "answer": f"PostgreSQL ({GOLD_MARKER})",
            "sessions": [
                {
                    "session_id": "s1",
                    "turns": [
                        {"role": "user", "content": "We switched to PostgreSQL."},
                        {"role": "assistant", "content": "Noted."},
                    ],
                }
            ],
        }
        for i in range(count)
    ]
    path = tmp_path / "bench.json"
    path.write_text(json.dumps({"name": "fixture", "examples": examples}), encoding="utf-8")
    return path


def _args(tmp_path: Path, dataset: Path, *extra: str) -> list[str]:
    return [
        "--suite",
        "longmemeval",
        "--dataset",
        str(dataset),
        "--out",
        str(tmp_path / "out"),
        "--db",
        str(tmp_path / "bench.sqlite3"),
        "--stub",
        *extra,
    ]


def _results(tmp_path: Path) -> dict[str, object]:
    return json.loads((tmp_path / "out" / "benchmark_results.json").read_text(encoding="utf-8"))


def test_runner_loads_dataset_and_writes_outputs(tmp_path: Path) -> None:
    """The runner loads a fixture dataset and writes all three output files."""
    dataset = _dataset(tmp_path)

    code = run_benchmark.main(_args(tmp_path, dataset, "--judge", "hybrid"))

    assert code == 0
    out = tmp_path / "out"
    assert (out / "benchmark_results.json").is_file()
    assert (out / "benchmark_summary.md").is_file()
    assert (out / "benchmark_cost_ledger.json").is_file()
    results = _results(tmp_path)
    assert results["total"] == 2
    assert results["llm_mode"] == "stub"
    summary_md = (out / "benchmark_summary.md").read_text(encoding="utf-8")
    assert summary_md.startswith("# MIRA Benchmark Summary")


def test_default_run_is_labeled_prototype(tmp_path: Path) -> None:
    """Without --official the run is honestly labeled prototype."""
    run_benchmark.main(_args(tmp_path, _dataset(tmp_path, 1)))

    results = _results(tmp_path)
    assert results["official"] is False
    assert results["status"] == "prototype"


def test_official_subset_is_labeled_subset(tmp_path: Path) -> None:
    """An --official --limit run is labeled an official-protocol subset."""
    run_benchmark.main(_args(tmp_path, _dataset(tmp_path, 2), "--official", "--limit", "1"))

    results = _results(tmp_path)
    assert results["official"] is True
    assert results["status"] == "official_protocol_subset"
    assert results["limit"] == 1
    assert results["total"] == 1


def test_stub_mode_does_not_require_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stub mode runs offline without a provider key."""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    assert run_benchmark.main(_args(tmp_path, _dataset(tmp_path, 1), "--judge", "hybrid")) == 0


def test_live_mode_fails_clearly_without_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Live mode without a key fails clearly and writes nothing."""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    dataset = _dataset(tmp_path, 1)
    argv = [
        "--suite",
        "longmemeval",
        "--dataset",
        str(dataset),
        "--out",
        str(tmp_path / "out"),
        "--live",
    ]

    code = run_benchmark.main(argv)

    assert code == 2
    err = capsys.readouterr().err
    assert "LLM_API_KEY" in err
    assert "DASHSCOPE_API_KEY" in err


def test_live_mode_installs_requested_model_temporarily(monkeypatch: pytest.MonkeyPatch) -> None:
    """Live benchmarks route agent calls through the requested OpenAI-compatible model."""
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "original-model")
    args = run_benchmark._parse_args(["--live", "--model", "deepseek-chat"])

    restore = run_benchmark._install_llm_mode(args)

    assert run_benchmark.os.environ["LLM_MODEL"] == "deepseek-chat"
    restore()
    assert run_benchmark.os.environ["LLM_MODEL"] == "original-model"


def test_slow_path_runs_after_import(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Slow-path processing is invoked after importing each conversation."""
    import core.memory.slow_path as sp

    calls = {"n": 0}
    real = sp.run_slow_path_for_observation

    def _counting(observation_id: str) -> object:
        calls["n"] += 1
        return real(observation_id)

    monkeypatch.setattr(sp, "run_slow_path_for_observation", _counting)
    run_benchmark.main(_args(tmp_path, _dataset(tmp_path, 2)))

    assert calls["n"] >= 2  # at least once per imported example


def test_runner_prints_progress_to_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Benchmark runs emit progress logs without mixing them into stdout."""
    code = run_benchmark.main(_args(tmp_path, _dataset(tmp_path, 1), "--judge", "hybrid"))

    captured = capsys.readouterr()
    assert code == 0
    assert "[benchmark] loaded suite=longmemeval" in captured.err
    assert "example 1/1 q0: running slow path" in captured.err
    assert "slow path 1/" in captured.err
    assert captured.out.startswith("# MIRA Benchmark Summary")


def test_quiet_suppresses_progress_logs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """--quiet preserves the old no-progress stderr behavior for automation."""
    code = run_benchmark.main(_args(tmp_path, _dataset(tmp_path, 1), "--quiet"))

    captured = capsys.readouterr()
    assert code == 0
    assert "[benchmark]" not in captured.err


def test_gold_answer_not_leaked_into_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gold answer is never passed to MIRA's answer generation."""
    import evaluation.benchmarks.longmemeval as lme

    seen_questions: list[str] = []

    def _spy(
        question: str,
        session_id: str | None = None,
        *,
        workspace_id: str | None = None,
    ) -> dict[str, object]:
        seen_questions.append(question)
        assert workspace_id is not None
        return {"answer": "stub answer", "retrieval_mode": "quick", "used_memory_items": []}

    monkeypatch.setattr(lme, "run_question", _spy)
    run_benchmark.main(_args(tmp_path, _dataset(tmp_path, 2)))

    assert seen_questions
    assert all(GOLD_MARKER not in question for question in seen_questions)


def test_cache_prevents_duplicate_judge_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With --cache, a repeated run reuses cached judge output (no new judge calls)."""
    calls = {"n": 0}
    real = run_benchmark._stub_judge_call

    def _counting(messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
        calls["n"] += 1
        return real(messages, schema_name)

    monkeypatch.setattr(run_benchmark, "_stub_judge_call", _counting)
    argv = _args(tmp_path, _dataset(tmp_path, 1), "--judge", "llm", "--cache")

    run_benchmark.main(argv)
    after_first = calls["n"]
    assert after_first >= 1

    run_benchmark.main(argv)  # same --out: cache hit
    assert calls["n"] == after_first


def test_budget_cap_blocks_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A budget smaller than the estimate refuses to start and writes nothing."""
    dataset = _dataset(tmp_path, 2)

    code = run_benchmark.main(_args(tmp_path, dataset, "--judge", "hybrid", "--budget-usd", "0"))

    assert code == 3
    assert "Refusing to start" in capsys.readouterr().err
    assert not (tmp_path / "out" / "benchmark_results.json").exists()


def test_dry_run_cost_estimates_without_running(tmp_path: Path) -> None:
    """--dry-run-cost prints an estimate and does not run the benchmark."""
    code = run_benchmark.main(
        _args(
            tmp_path, _dataset(tmp_path, 2), "--official", "--dry-run-cost", "--budget-usd", "100"
        )
    )

    assert code == 0
    assert not (tmp_path / "out" / "benchmark_results.json").exists()


def test_makefile_targets_point_to_runner() -> None:
    """The Makefile exposes the three benchmark targets wired to the runner."""
    makefile = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")
    for target in ("benchmark:", "benchmark-cost:", "benchmark-subset:"):
        assert target in makefile
    assert "scripts.run_benchmark" in makefile
    assert "--dataset $(LONGMEMEVAL_DATASET)" in makefile
    assert "LONGMEMEVAL_DATASET ?= data/benchmarks/longmemeval.json" in makefile
