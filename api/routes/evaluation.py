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

from api.auth import WorkspaceAuth

router = APIRouter(tags=["evaluation"])

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_CASES = _REPO_ROOT / "evaluation" / "local" / "memory_cases.json"
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
    definitions = _local_case_definitions()
    results = data.get("results", [])
    cases = [
        _local_case_summary(row, definitions.get(str(row.get("id"))))
        for row in results
        if isinstance(row, dict)
    ]
    by_mode = _count_cases_by_field(cases, "retrieval_mode")
    return {
        "passed": data.get("passed"),
        "total": data.get("total"),
        "pass_rate": data.get("pass_rate"),
        "by_category": data.get("by_category"),
        "by_retrieval_mode": by_mode,
        "failed_cases": [case for case in cases if not case["passed"]],
        "generated_at": data.get("generated_at"),
        "cases": cases,
    }


def _local_case_definitions() -> dict[str, dict[str, Any]]:
    data = _read_json(_LOCAL_CASES)
    if data is None:
        return {}
    return {
        str(case.get("id")): case
        for case in data.get("cases", [])
        if isinstance(case, dict) and case.get("id") is not None
    }


def _local_case_summary(row: dict[str, Any], definition: dict[str, Any] | None) -> dict[str, Any]:
    definition = definition or {}
    checks = [check for check in row.get("checks", []) if isinstance(check, dict)]
    failed_checks = [check for check in checks if not check.get("passed")]
    return {
        "id": row.get("id"),
        "category": row.get("category"),
        "passed": bool(row.get("passed")),
        "score": row.get("score"),
        "retrieval_mode": row.get("retrieval_mode"),
        "answer": row.get("answer"),
        "error": row.get("error"),
        "checks": checks,
        "failed_checks": failed_checks,
        "interactions": definition.get("interactions", []),
        "expect": definition.get("expect", {}),
    }


def _ablation_summary() -> dict[str, Any] | None:
    data = _read_json(_ABLATION)
    if data is None:
        return None
    all_rows = data.get("rows", [])
    full_system = next(
        (row for row in all_rows if isinstance(row, dict) and row.get("name") == "full_system"),
        None,
    )
    full_pass_rate = (
        _number(full_system.get("pass_rate")) if isinstance(full_system, dict) else None
    )
    rows = [
        {
            "name": row.get("name"),
            "disabled": row.get("disabled", []),
            "applied": row.get("applied", []),
            "passed": row.get("passed"),
            "total": row.get("total"),
            "pass_rate": row.get("pass_rate"),
            "drop_from_full": (
                round(full_pass_rate - _number(row.get("pass_rate")), 4)
                if full_pass_rate is not None
                else None
            ),
            "lost": _lost_cases(all_rows, row),
            "results": [case for case in row.get("results", []) if isinstance(case, dict)],
            "note": row.get("note"),
        }
        for row in all_rows
        if isinstance(row, dict)
    ]
    return {
        "cases_path": data.get("cases_path"),
        "run_slow_path": data.get("run_slow_path"),
        "llm_mode": data.get("llm_mode"),
        "parallel": data.get("parallel"),
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


def _count_cases_by_field(cases: list[dict[str, Any]], field: str) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for case in cases:
        key = str(case.get(field) or "unknown")
        bucket = counts.setdefault(key, {"passed": 0, "total": 0})
        bucket["total"] += 1
        if case.get("passed"):
            bucket["passed"] += 1
    return counts


def _number(value: Any) -> float:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


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
def evaluation_summary(auth: WorkspaceAuth) -> dict[str, Any]:
    """Return the latest local-eval, ablation, and benchmark results for the dashboard."""
    _ = auth
    return {
        "local_eval": _local_eval_summary(),
        "ablation": _ablation_summary(),
        "benchmark": _benchmark_summary(),
    }
