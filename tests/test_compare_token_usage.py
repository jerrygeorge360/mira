"""Verify the controlled direct-versus-Paritok comparison report."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.llm.usage import prompt_fingerprint
from scripts import compare_token_usage


def test_comparison_writes_measured_savings_and_quality_checks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "cases.json"
    output_path = tmp_path / "report.json"
    input_path.write_text(
        json.dumps(
            [
                {
                    "id": "case-1",
                    "user_message": "Where is the frontend hosted?",
                    "context": [{"section": "retrieved_memory", "content": "Hosted on Vercel."}],
                    "expected_terms": ["Vercel"],
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MIRA_DB_PATH", str(tmp_path / "usage.sqlite3"))
    monkeypatch.setenv("LLM_PROFILE", "deepseek")
    monkeypatch.setattr(compare_token_usage, "_proxy_json", lambda path: {"status": "ok"})

    def fake_run(messages: list[dict[str, str]], gateway: str, model: str) -> dict[str, object]:
        del model
        return {
            "run_id": f"run-{gateway}",
            "answer": "The frontend is hosted on Vercel.",
            "usage_source": "provider",
            "input_tokens": 100 if gateway == "direct" else 40,
            "output_tokens": 10,
            "total_tokens": 110 if gateway == "direct" else 50,
            "latency_ms": 25,
            "estimated_cost_usd": None,
            "prompt_fingerprint": prompt_fingerprint(messages),
        }

    monkeypatch.setattr(compare_token_usage, "_run_call", fake_run)

    result = compare_token_usage.main(
        ["--input", str(input_path), "--out", str(output_path), "--limit", "1"]
    )

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert result == 0
    assert report["measurement_scope"] == "answer_generation"
    assert report["summary"]["input_tokens_saved"] == 60
    assert report["summary"]["input_reduction_percent"] == 60.0
    assert report["summary"]["direct_quality_passes"] == 1
    assert report["summary"]["paritok_quality_passes"] == 1


def test_comparison_refuses_estimated_tokens() -> None:
    with pytest.raises(RuntimeError, match="authoritative token usage"):
        compare_token_usage._required_input_tokens(
            {"usage_source": "estimated", "input_tokens": None},
            "direct",
        )
