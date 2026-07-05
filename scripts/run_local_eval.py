"""Run MIRA's small local memory regression suite."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any, cast

from dotenv import load_dotenv

from core.db.repositories import configure_database
from evaluation.cases import run_evaluation_cases


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = _parse_args(argv)
    _configure_database(args.db)
    summary = _run_cases(args)
    print(json.dumps(_summary_for_terminal(summary), indent=2, sort_keys=True, default=str))
    return 0 if int(str(summary.get("failed", 0))) == 0 else 1


def _configure_database(database_path: str | None) -> None:
    path = database_path or str(Path(tempfile.mkdtemp(prefix="mira-local-eval-")) / "eval.sqlite3")
    configure_database(path)


def _run_cases(args: argparse.Namespace) -> dict[str, object]:
    if args.live:
        return run_evaluation_cases(args.cases)

    from core import agent

    patchable_agent = cast(Any, agent)
    original_qwen = patchable_agent.call_qwen_json
    patchable_agent.call_qwen_json = _stub_llm
    try:
        summary = run_evaluation_cases(args.cases)
    finally:
        patchable_agent.call_qwen_json = original_qwen
    summary["llm_mode"] = "stub"
    return summary


def _summary_for_terminal(summary: dict[str, object]) -> dict[str, object]:
    return {
        "total": summary.get("total"),
        "passed": summary.get("passed"),
        "failed": summary.get("failed"),
        "pass_rate": summary.get("pass_rate"),
        "results_path": summary.get("results_path"),
        "by_category": summary.get("by_category", {}),
    }


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", default="evaluation/memory_cases.json")
    parser.add_argument("--db", default=None, help="SQLite path. Defaults to an isolated temp DB.")
    parser.add_argument("--live", action="store_true", help="Use the configured live LLM provider.")
    return parser.parse_args(argv)


def _stub_llm(
    messages: list[dict[str, str]],
    schema_name: str,
    timeout_s: int = 60,
) -> dict[str, object]:
    del timeout_s
    if schema_name != "answer_generation":
        return {"json": {}}
    prompt = messages[0]["content"] if messages else ""
    context = prompt.split("Prompt context:", 1)[1] if "Prompt context:" in prompt else prompt
    return {"json": {"answer": f"Based on the available memory: {' '.join(context.split())}"}}


if __name__ == "__main__":
    raise SystemExit(main())
