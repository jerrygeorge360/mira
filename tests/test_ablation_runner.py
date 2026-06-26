"""Verify ISSUE-122 one-command ablation runner.

Ownership: MIRA contributors.
Related issue: ISSUE-122.
Architecture area: evaluation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import run_ablation

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _tiny_cases(tmp_path: Path) -> Path:
    cases = {
        "cases": [
            {
                "id": "fact",
                "category": "direct_fact_recall",
                "interactions": [{"message": "What is my deadline?"}],
                "expect": {"retrieval_mode": "quick"},
            },
            {
                "id": "deep",
                "category": "deep_mode_synthesis",
                "interactions": [{"message": "What kind of developer am I?"}],
                "expect": {"retrieval_mode": "deep"},
            },
        ]
    }
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(cases), encoding="utf-8")
    return path


def _args(tmp_path: Path, cases: Path, *, live: bool = False) -> list[str]:
    argv = [
        "--cases",
        str(cases),
        "--out",
        str(tmp_path / "results"),
        "--db",
        str(tmp_path / "ablation.sqlite3"),
    ]
    argv.append("--live" if live else "--stub")
    return argv


def test_runner_writes_output_files(tmp_path: Path) -> None:
    """The runner writes the JSON results and Markdown summary."""
    cases = _tiny_cases(tmp_path)

    exit_code = run_ablation.main(_args(tmp_path, cases))

    assert exit_code == 0
    results_dir = tmp_path / "results"
    json_path = results_dir / "ablation_results.json"
    md_path = results_dir / "ablation_summary.md"
    assert json_path.is_file()
    assert md_path.is_file()

    saved = json.loads(json_path.read_text(encoding="utf-8"))
    assert saved["llm_mode"] == "stub"
    assert saved["rows"], "expected ablation rows in the JSON output"
    assert md_path.read_text(encoding="utf-8").startswith("# MIRA Ablation Study")


def test_runner_prints_markdown_table(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The runner prints the Markdown comparison table to stdout."""
    cases = _tiny_cases(tmp_path)

    run_ablation.main(_args(tmp_path, cases))

    out = capsys.readouterr().out
    assert "| Config | Disabled | Cases | Passed | Pass rate | Note |" in out
    assert "full_system" in out


def test_stub_mode_does_not_require_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default stub mode runs without a DashScope API key."""
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    cases = _tiny_cases(tmp_path)

    assert run_ablation.main(_args(tmp_path, cases)) == 0


def test_live_mode_fails_clearly_without_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Live mode without a key fails with a clear error and non-zero exit."""
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    cases = _tiny_cases(tmp_path)

    exit_code = run_ablation.main(_args(tmp_path, cases, live=True))

    assert exit_code == 2
    err = capsys.readouterr().err
    assert "DASHSCOPE_API_KEY" in err
    assert not (tmp_path / "results" / "ablation_results.json").exists()


def test_missing_cases_file_fails_clearly(tmp_path: Path) -> None:
    """A missing cases file is reported as a clean error, not a traceback."""
    argv = ["--cases", str(tmp_path / "nope.json"), "--out", str(tmp_path / "results"), "--stub"]
    assert run_ablation.main(argv) == 2


def test_makefile_target_points_to_runner() -> None:
    """The Makefile exposes an ablation target wired to the runner."""
    makefile = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "ablation:" in makefile
    assert "scripts.run_ablation" in makefile
    assert "ablation   Run the ablation study and write results" in makefile
