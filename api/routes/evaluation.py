"""Evaluation-results routes for the MIRA API.

Ownership: Jerry.
Architecture area: API/server.

Serves the latest local-eval, ablation, and benchmark result files (written by the
evaluation harnesses) so the UI can render real numbers instead of static mock data.
Read-only and defensive: a missing or unreadable file yields a null section rather than
an error, so the dashboard degrades gracefully before the first run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter

router = APIRouter(tags=["evaluation"])

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_EVAL = _REPO_ROOT / "evaluation" / "local" / "memory_cases.results.json"
_ABLATION = _REPO_ROOT / "evaluation" / "results" / "ablation_results.json"
_BENCHMARK = _REPO_ROOT / "evaluation" / "results" / "benchmarks" / "benchmark_results.json"


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _local_eval_summary() -> dict[str, Any] | None:
    data = _read_json(_LOCAL_EVAL)
    if data is None:
        return None
    results = data.get("results", [])
    cases = [
        {
            "id": row.get("id"),
            "category": row.get("category"),
            "passed": bool(row.get("passed")),
            "retrieval_mode": row.get("retrieval_mode"),
        }
        for row in results
        if isinstance(row, dict)
    ]
    return {
        "passed": data.get("passed"),
        "total": data.get("total"),
        "pass_rate": data.get("pass_rate"),
        "by_category": data.get("by_category"),
        "generated_at": data.get("generated_at"),
        "cases": cases,
    }


def _ablation_summary() -> dict[str, Any] | None:
    data = _read_json(_ABLATION)
    if data is None:
        return None
    rows = [
        {
            "name": row.get("name"),
            "disabled": row.get("disabled", []),
            "passed": row.get("passed"),
            "total": row.get("total"),
            "pass_rate": row.get("pass_rate"),
            "lost": _lost_cases(data.get("rows", []), row),
        }
        for row in data.get("rows", [])
        if isinstance(row, dict)
    ]
    return {
        "cases_path": data.get("cases_path"),
        "run_slow_path": data.get("run_slow_path"),
        "table": data.get("table"),
        "rows": rows,
    }


def _lost_cases(all_rows: list[Any], row: dict[str, Any]) -> list[str]:
    """Cases this config fails that the full_system baseline passes (its attribution)."""
    baseline = next(
        (r for r in all_rows if isinstance(r, dict) and r.get("name") == "full_system"), None
    )
    if baseline is None or row.get("name") == "full_system":
        return []
    passed_in_baseline = {
        str(c.get("id"))
        for c in baseline.get("results", [])
        if isinstance(c, dict) and c.get("passed")
    }
    failed_here = {
        str(c.get("id"))
        for c in row.get("results", [])
        if isinstance(c, dict) and not c.get("passed")
    }
    return sorted(cid.replace("abl-", "") for cid in passed_in_baseline & failed_here)


def _benchmark_summary() -> dict[str, Any] | None:
    data = _read_json(_BENCHMARK)
    if data is None:
        return None
    return {
        "suite": data.get("suite"),
        "total_examples": data.get("total_examples") or data.get("total"),
        "llm_pass_rate": data.get("llm_judge_pass_rate") or data.get("llm_pass_rate"),
        "deterministic_match_rate": data.get("deterministic_match_rate"),
        "average_score": data.get("average_judge_score") or data.get("average_score"),
        "llm_mode": data.get("llm_mode"),
        "estimated_cost": data.get("estimated_cost"),
        "categories": data.get("category_breakdown") or data.get("categories"),
    }


@router.get("/evaluation/summary")
def evaluation_summary() -> dict[str, Any]:
    """Return the latest local-eval, ablation, and benchmark results for the dashboard."""
    return {
        "local_eval": _local_eval_summary(),
        "ablation": _ablation_summary(),
        "benchmark": _benchmark_summary(),
    }
