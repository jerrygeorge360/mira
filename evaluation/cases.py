"""Local evaluation harness for MIRA memory behavior.

Ownership: Sarah.
Related issue: ISSUE-051.
Architecture area: evaluation.

This harness gives evidence the architecture works beyond a single hand-picked
demo. It loads declarative cases, replays each one's interactions through the
real agent runtime (it does not re-implement orchestration), scores the final
response against declared expectations, and writes a results file a dashboard
can consume. It is intentionally light: not a full benchmark adapter.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from core.agent import handle_user_message
from core.db.repositories import create_session

EvaluationCase = dict[str, object]
CaseResult = dict[str, object]
Score = dict[str, object]

LOGGER = logging.getLogger(__name__)

EVALUATION_CATEGORIES = frozenset(
    {
        "direct_fact_recall",
        "session_correction_handling",
        "cross_session_recall",
        "contradiction_handling",
        "supersession_handling",
        "foresight_activation",
        "deep_mode_synthesis",
        "retrieval_sufficiency",
        "routing_intent",
    }
)


def load_evaluation_cases(source: str) -> list[EvaluationCase]:
    """Load evaluation cases from a JSON file (a list, or an object with ``cases``)."""
    data = json.loads(Path(source).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        raw_cases = data.get("cases", [])
    elif isinstance(data, list):
        raw_cases = data
    else:
        raw_cases = []
    return [case for case in raw_cases if isinstance(case, dict)]


def run_evaluation_cases(cases_path: str) -> dict[str, object]:
    """Run every case, score it, persist results, and return a summary."""
    cases = load_evaluation_cases(cases_path)
    results = [_evaluate_case(case) for case in cases]
    summary = _summarize(results)
    summary["results_path"] = _save_results(cases_path, summary)
    LOGGER.info("Evaluation complete: %d/%d passed", summary["passed"], summary["total"])
    return summary


def score_case(expected: dict[str, object], actual: dict[str, object]) -> Score:
    """Score one actual response against declared expectations as pass/fail checks."""
    answer = str(actual.get("answer", ""))
    normalized_answer = answer.casefold()
    checks: list[dict[str, object]] = []

    for needle in _as_list(expected.get("answer_contains")):
        needle_text = str(needle)
        checks.append(
            _check(f"answer_contains:{needle_text}", needle_text.casefold() in normalized_answer)
        )
    for needle in _as_list(expected.get("answer_excludes")):
        needle_text = str(needle)
        checks.append(
            _check(
                f"answer_excludes:{needle_text}", needle_text.casefold() not in normalized_answer
            )
        )
    if "retrieval_mode" in expected:
        expected_mode = expected["retrieval_mode"]
        checks.append(
            _check(
                f"retrieval_mode=={expected_mode}",
                actual.get("retrieval_mode") == expected_mode,
                actual.get("retrieval_mode"),
            )
        )
    if "intent" in expected:
        decision = actual.get("routing_decision")
        observed = decision.get("intent") if isinstance(decision, dict) else None
        checks.append(
            _check(f"intent=={expected['intent']}", observed == expected["intent"], observed)
        )
    if "used_memory" in expected:
        trace = actual.get("retrieval_trace")
        observed = trace.get("used_memory") if isinstance(trace, dict) else None
        checks.append(_check("used_memory", observed == expected["used_memory"], observed))
    if "route" in expected:
        trace = actual.get("retrieval_trace")
        observed = trace.get("route") if isinstance(trace, dict) else None
        checks.append(
            _check(f"route=={expected['route']}", observed == expected["route"], observed)
        )
    if "used_session_items_nonempty" in expected:
        expected_nonempty = bool(expected["used_session_items_nonempty"])
        observed = bool(actual.get("used_session_items"))
        checks.append(
            _check("used_session_items_nonempty", observed == expected_nonempty, observed)
        )
    if "min_used_session_items" in expected:
        minimum = int(str(expected["min_used_session_items"]))
        observed_count = len(_as_list(actual.get("used_session_items")))
        checks.append(
            _check(f"min_used_session_items>={minimum}", observed_count >= minimum, observed_count)
        )
    if "min_used_memory_items" in expected:
        minimum = int(str(expected["min_used_memory_items"]))
        observed_count = len(_as_list(actual.get("used_memory_items")))
        checks.append(
            _check(f"min_used_memory_items>={minimum}", observed_count >= minimum, observed_count)
        )

    if not checks:
        checks.append(_check("no_expectations", True))

    passed_checks = sum(1 for check in checks if check["passed"])
    return {
        "passed": passed_checks == len(checks),
        "score": round(passed_checks / len(checks), 4),
        "checks": checks,
    }


def _evaluate_case(case: EvaluationCase) -> CaseResult:
    case_id = str(case.get("id", "unnamed"))
    category = str(case.get("category", "uncategorized"))
    if category not in EVALUATION_CATEGORIES:
        LOGGER.warning("Case %s has unknown category %r", case_id, category)

    expected = case.get("expect")
    expected_dict = expected if isinstance(expected, dict) else {}
    try:
        actual = _run_case_interactions(case)
        error = None
    except (ValueError, KeyError) as failure:
        actual = {"answer": "", "error": str(failure)}
        error = str(failure)

    score = score_case(expected_dict, actual)
    return {
        "id": case_id,
        "category": category,
        "passed": bool(score["passed"]) and error is None,
        "score": score["score"],
        "checks": score["checks"],
        "error": error,
        "answer": actual.get("answer", ""),
        "retrieval_mode": actual.get("retrieval_mode"),
    }


def _run_case_interactions(case: EvaluationCase) -> dict[str, object]:
    interactions = _as_list(case.get("interactions"))
    if not interactions:
        raise ValueError("case has no interactions")
    session_id = create_session("evaluation")
    last_response: dict[str, object] = {}
    for interaction in interactions:
        if not isinstance(interaction, dict):
            continue
        if interaction.get("reset_session"):
            session_id = create_session("evaluation")
        message = str(interaction.get("message", "")).strip()
        if not message:
            continue
        last_response = handle_user_message(session_id, message)
    if not last_response:
        raise ValueError("case produced no response")
    return last_response


def _summarize(results: list[CaseResult]) -> dict[str, object]:
    total = len(results)
    passed = sum(1 for result in results if result["passed"])
    by_category: dict[str, dict[str, int]] = {}
    for result in results:
        bucket = by_category.setdefault(str(result["category"]), {"total": 0, "passed": 0})
        bucket["total"] += 1
        if result["passed"]:
            bucket["passed"] += 1
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "by_category": by_category,
        "results": results,
        "generated_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017
    }


def _save_results(cases_path: str, summary: dict[str, object]) -> str:
    output_path = Path(cases_path).with_suffix(".results.json")
    output_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )
    return str(output_path)


def _check(name: str, passed: bool, observed: object = None) -> dict[str, object]:
    return {"name": name, "passed": bool(passed), "observed": observed}


def _as_list(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]
