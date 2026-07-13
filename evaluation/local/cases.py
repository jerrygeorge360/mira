"""Local evaluation harness for MIRA memory behavior.

Ownership: MIRA contributors.
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

from core.db.chroma import reset_vector_store
from core.db.repositories import (
    configure_database,
    current_database_path,
)
from evaluation.runtime.case_runner import (
    DebugRecord,
    ProgressReporter,
    isolate_case_state,
    isolation_base_path,
    json_dump,
    run_case_interactions,
)

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


def run_evaluation_cases(
    cases_path: str,
    progress: ProgressReporter | None = None,
    delay_s: float = 0.0,
    run_slow_path: bool = False,
    slow_path_batch_size: int = 20,
    debug_trace: bool = False,
    case_ids: list[str] | None = None,
    isolate_cases: bool = True,
    resume: bool = False,
) -> dict[str, object]:
    """Run every case, score it, persist results, and return a summary.

    By default each case runs against its own SQLite database and a cleared
    vector store, so a previous case's durable memory cannot leak into the next
    through retrieval. Pass ``isolate_cases=False`` for intentional multi-case
    continuity scenarios that share one database.

    Results are checkpointed to the results file after every case, so a run that
    dies partway (e.g. a provider outage) does not lose completed work. Pass
    ``resume=True`` to skip cases already recorded in that file and continue with
    the rest -- cases are isolated and independent, so resuming is exact.
    """
    if delay_s < 0:
        raise ValueError("delay_s must not be negative")
    if slow_path_batch_size < 1:
        raise ValueError("slow_path_batch_size must be a positive integer")
    all_cases = _filter_cases(load_evaluation_cases(cases_path), case_ids)
    total = len(all_cases)
    prior_results = _load_prior_results(cases_path) if resume else []
    done_ids = {str(result.get("id")) for result in prior_results}
    if resume and done_ids:
        _progress(
            progress,
            f"resume: {len(done_ids)} already done, {total - len(done_ids)} remaining",
        )
    interaction_counter = {"count": 0}
    debug_records: list[DebugRecord] = []
    _progress(progress, f"loaded cases={total} path={cases_path}")
    original_database = current_database_path()
    isolation_base = isolation_base_path(original_database) if isolate_cases else None
    results: list[CaseResult] = list(prior_results)
    try:
        for index, case in enumerate(all_cases, start=1):
            if str(case.get("id", "unnamed")) in done_ids:
                continue
            if isolation_base is not None:
                isolate_case_state(isolation_base, index, progress)
            results.append(
                _evaluate_case(
                    case,
                    index=index,
                    total=total,
                    progress=progress,
                    delay_s=delay_s,
                    interaction_counter=interaction_counter,
                    run_slow_path=run_slow_path,
                    slow_path_batch_size=slow_path_batch_size,
                    debug_records=debug_records if debug_trace else None,
                )
            )
            # Checkpoint after each case so a crash can resume from here.
            _save_results(cases_path, _summarize(results))
    finally:
        if isolate_cases and original_database is not None:
            configure_database(original_database)
            reset_vector_store()
    summary = _summarize(results)
    summary["results_path"] = _save_results(cases_path, summary)
    if debug_trace:
        summary["debug_trace_path"] = _save_debug_trace(cases_path, summary, debug_records)
    _progress(
        progress,
        f"complete passed={summary['passed']}/{summary['total']} results={summary['results_path']}",
    )
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
    if "min_retrieved_records" in expected:
        minimum = int(str(expected["min_retrieved_records"]))
        retrieved = _retrieved_records(actual)
        checks.append(
            _check(f"min_retrieved_records>={minimum}", len(retrieved) >= minimum, len(retrieved))
        )
    if "retrieved_sources_include" in expected:
        retrieved = _retrieved_records(actual)
        observed_sources = {
            str(record.get("source")) for record in retrieved if isinstance(record, dict)
        }
        for source in _as_list(expected.get("retrieved_sources_include")):
            source_text = str(source)
            checks.append(
                _check(
                    f"retrieved_sources_include:{source_text}",
                    source_text in observed_sources,
                    sorted(observed_sources),
                )
            )
    if "top_retrieved_source" in expected:
        # Ranking-order check: which source won the #1 slot. Structured-first weighting
        # ranks validated memory (atomic_facts/...) above the raw observation log, so this
        # discriminates the flat_memory ablation, which removes that weighting.
        retrieved = _retrieved_records(actual)
        observed_top = str(retrieved[0].get("source")) if retrieved else None
        expected_top = str(expected["top_retrieved_source"])
        checks.append(
            _check(
                f"top_retrieved_source=={expected_top}", observed_top == expected_top, observed_top
            )
        )
    if "slow_path_created_min" in expected:
        created_counts = _slow_path_created_counts(actual)
        raw_minimums = expected["slow_path_created_min"]
        minimums = raw_minimums if isinstance(raw_minimums, dict) else {}
        for bucket, minimum in minimums.items():
            observed = created_counts.get(str(bucket), 0)
            required = int(str(minimum))
            checks.append(
                _check(
                    f"slow_path_created_min:{bucket}>={required}", observed >= required, observed
                )
            )
    if "slow_path_created_edge_types_include" in expected:
        observed_edge_types = set(_slow_path_created_edge_types(actual))
        for edge_type in _as_list(expected.get("slow_path_created_edge_types_include")):
            edge_type_text = str(edge_type)
            checks.append(
                _check(
                    f"slow_path_created_edge_type:{edge_type_text}",
                    edge_type_text in observed_edge_types,
                    sorted(observed_edge_types),
                )
            )
    if "active_session_item_labels_include" in expected:
        observed_labels = _active_session_item_labels(actual)
        for label in _as_list(expected.get("active_session_item_labels_include")):
            label_text = str(label)
            checks.append(
                _check(
                    f"active_session_item_label:{label_text}",
                    label_text in observed_labels,
                    sorted(observed_labels),
                )
            )

    if not checks:
        checks.append(_check("no_expectations", True))

    passed_checks = sum(1 for check in checks if check["passed"])
    return {
        "passed": passed_checks == len(checks),
        "score": round(passed_checks / len(checks), 4),
        "checks": checks,
    }


def _evaluate_case(
    case: EvaluationCase,
    *,
    index: int,
    total: int,
    progress: ProgressReporter | None,
    delay_s: float,
    interaction_counter: dict[str, int],
    run_slow_path: bool,
    slow_path_batch_size: int,
    debug_records: list[DebugRecord] | None,
) -> CaseResult:
    case_id = str(case.get("id", "unnamed"))
    category = str(case.get("category", "uncategorized"))
    if category not in EVALUATION_CATEGORIES:
        LOGGER.warning("Case %s has unknown category %r", case_id, category)

    expected = case.get("expect")
    expected_dict = expected if isinstance(expected, dict) else {}
    case_debug_records: list[DebugRecord] = []
    _progress(progress, f"case {index}/{total} {case_id}: start category={category}")
    try:
        actual = run_case_interactions(
            case,
            case_id=case_id,
            session_user="evaluation",
            progress=progress,
            delay_s=delay_s,
            interaction_counter=interaction_counter,
            run_slow_path=run_slow_path,
            slow_path_batch_size=slow_path_batch_size,
            case_debug_records=case_debug_records,
            debug_records=debug_records,
        )
        error = None
    except (ValueError, KeyError) as failure:
        actual = {"answer": "", "error": str(failure)}
        error = str(failure)

    score = score_case(expected_dict, actual)
    _progress(
        progress,
        f"case {index}/{total} {case_id}: "
        f"{'passed' if bool(score['passed']) and error is None else 'failed'} "
        f"score={score['score']} mode={actual.get('retrieval_mode')}",
    )
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


def _filter_cases(cases: list[EvaluationCase], case_ids: list[str] | None) -> list[EvaluationCase]:
    if not case_ids:
        return cases
    wanted = set(case_ids)
    return [case for case in cases if str(case.get("id", "")) in wanted]


def _save_results(cases_path: str, summary: dict[str, object]) -> str:
    output_path = Path(cases_path).with_suffix(".results.json")
    output_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )
    return str(output_path)


def _load_prior_results(cases_path: str) -> list[CaseResult]:
    """Load previously checkpointed case results for a resumed run (empty if none)."""
    output_path = Path(cases_path).with_suffix(".results.json")
    if not output_path.is_file():
        return []
    try:
        data = json.loads(output_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    prior = data.get("results") if isinstance(data, dict) else None
    if not isinstance(prior, list):
        return []
    return [result for result in prior if isinstance(result, dict) and result.get("id")]


def _check(name: str, passed: bool, observed: object = None) -> dict[str, object]:
    return {"name": name, "passed": bool(passed), "observed": observed}


def _retrieved_records(actual: dict[str, object]) -> list[dict[str, object]]:
    trace = actual.get("retrieval_trace")
    if not isinstance(trace, dict):
        return []
    retrieved = trace.get("retrieved", [])
    if not isinstance(retrieved, list):
        return []
    return [record for record in retrieved if isinstance(record, dict)]


def _slow_path_created_counts(actual: dict[str, object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for observation in _slow_path_observations(actual):
        created = observation.get("created_record_ids", {})
        if not isinstance(created, dict):
            continue
        for bucket, ids in created.items():
            counts[str(bucket)] = counts.get(str(bucket), 0) + len(_as_list(ids))
    return counts


def _slow_path_created_edge_types(actual: dict[str, object]) -> list[str]:
    edge_types: list[str] = []
    for observation in _slow_path_observations(actual):
        for edge in _as_list(observation.get("created_graph_edges")):
            if isinstance(edge, dict) and edge.get("edge_type"):
                edge_types.append(str(edge["edge_type"]))
    return edge_types


def _active_session_item_labels(actual: dict[str, object]) -> set[str]:
    labels: set[str] = set()
    for record in _eval_debug_records(actual):
        items = record.get("active_session_items", [])
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            explicitness = item.get("explicitness_label")
            if item_type is not None:
                labels.add(f"type:{item_type}")
            if explicitness is not None:
                labels.add(f"explicitness_label:{explicitness}")
    return labels


def _slow_path_observations(actual: dict[str, object]) -> list[dict[str, object]]:
    observations: list[dict[str, object]] = []
    for record in _eval_debug_records(actual):
        slow_path = record.get("slow_path", [])
        if not isinstance(slow_path, list):
            continue
        for batch in slow_path:
            if not isinstance(batch, dict):
                continue
            batch_observations = batch.get("observations", [])
            if not isinstance(batch_observations, list):
                continue
            observations.extend(
                observation for observation in batch_observations if isinstance(observation, dict)
            )
    return observations


def _eval_debug_records(actual: dict[str, object]) -> list[dict[str, object]]:
    records = actual.get("_eval_debug_records", [])
    if not isinstance(records, list):
        return []
    return [record for record in records if isinstance(record, dict)]


def _as_list(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _progress(progress: ProgressReporter | None, message: str) -> None:
    if progress is not None:
        progress(message)


def _save_debug_trace(
    cases_path: str,
    summary: dict[str, object],
    debug_records: list[DebugRecord],
) -> str:
    output_path = Path(cases_path).with_suffix(".debug.md")
    output_path.write_text(_render_debug_markdown(summary, debug_records), encoding="utf-8")
    return str(output_path)


def _render_debug_markdown(
    summary: dict[str, object],
    records: list[DebugRecord],
) -> str:
    lines = [
        "# MIRA Local Eval Debug Trace",
        "",
        f"- Total: {summary.get('total')}",
        f"- Passed: {summary.get('passed')}",
        f"- Failed: {summary.get('failed')}",
        f"- Pass rate: {summary.get('pass_rate')}",
        "",
    ]
    for index, record in enumerate(records, start=1):
        lines.extend(_render_debug_record(index, record))
    return "\n".join(lines).rstrip() + "\n"


def _render_debug_record(index: int, record: DebugRecord) -> list[str]:
    lines = [
        f"## {index}. {record['case_id']} interaction {record['interaction']}",
        "",
        f"- Session: `{record['session_id']}`",
        f"- Trace: `{record['trace_id']}`",
        f"- Retrieval mode: `{record['retrieval_mode']}`",
        "",
        "### User",
        "",
        _code_block(str(record["message"])),
        "",
        "### Answer",
        "",
        _code_block(str(record["answer"])),
        "",
        "### Routing",
        "",
        _code_block(json_dump(record.get("routing_decision", {})), "json"),
        "",
        "### Retrieval Trace",
        "",
        _code_block(json_dump(record.get("retrieval_trace", {})), "json"),
        "",
        "### Active Session Items",
        "",
        _code_block(json_dump(record.get("active_session_items", [])), "json"),
        "",
        "### Prompt Sections",
        "",
        _code_block(json_dump(record.get("prompt_sections", [])), "json"),
        "",
        "### Slow Path",
        "",
        _code_block(json_dump(record.get("slow_path", [])), "json"),
        "",
    ]
    return lines


def _code_block(value: str, language: str = "") -> str:
    return f"```{language}\n{value}\n```"
