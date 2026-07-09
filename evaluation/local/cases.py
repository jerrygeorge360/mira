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
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from core.agent import handle_user_message
from core.db.chroma import reset_vector_store
from core.db.repositories import (
    configure_database,
    create_session,
    current_database_path,
    get_answer_trace,
    repository_connection,
)
from core.session.working_set import list_active_session_items

EvaluationCase = dict[str, object]
CaseResult = dict[str, object]
Score = dict[str, object]
DebugRecord = dict[str, object]


class ProgressReporter(Protocol):
    """Receives human-readable local-eval progress messages."""

    def __call__(self, message: str) -> None: ...


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
) -> dict[str, object]:
    """Run every case, score it, persist results, and return a summary.

    By default each case runs against its own SQLite database and a cleared
    vector store, so a previous case's durable memory cannot leak into the next
    through retrieval. Pass ``isolate_cases=False`` for intentional multi-case
    continuity scenarios that share one database.
    """
    if delay_s < 0:
        raise ValueError("delay_s must not be negative")
    if slow_path_batch_size < 1:
        raise ValueError("slow_path_batch_size must be a positive integer")
    cases = _filter_cases(load_evaluation_cases(cases_path), case_ids)
    total = len(cases)
    interaction_counter = {"count": 0}
    debug_records: list[DebugRecord] = []
    _progress(progress, f"loaded cases={total} path={cases_path}")
    original_database = current_database_path()
    isolation_base = _isolation_base_path(original_database) if isolate_cases else None
    results: list[CaseResult] = []
    try:
        for index, case in enumerate(cases, start=1):
            if isolation_base is not None:
                _isolate_case_state(isolation_base, index, progress)
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
        actual = _run_case_interactions(
            case,
            case_id=case_id,
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


def _run_case_interactions(
    case: EvaluationCase,
    *,
    case_id: str,
    progress: ProgressReporter | None,
    delay_s: float,
    interaction_counter: dict[str, int],
    run_slow_path: bool,
    slow_path_batch_size: int,
    case_debug_records: list[DebugRecord],
    debug_records: list[DebugRecord] | None,
) -> dict[str, object]:
    interactions = _as_list(case.get("interactions"))
    if not interactions:
        raise ValueError("case has no interactions")
    session_id = create_session("evaluation")
    last_response: dict[str, object] = {}
    total_interactions = len(interactions)
    for interaction_index, interaction in enumerate(interactions, start=1):
        if not isinstance(interaction, dict):
            continue
        if interaction.get("reset_session"):
            session_id = create_session("evaluation")
            _progress(progress, f"case {case_id}: reset session")
        message = str(interaction.get("message", "")).strip()
        if not message:
            continue
        _progress(
            progress,
            f"case {case_id}: interaction {interaction_index}/{total_interactions} answering",
        )
        _throttle_between_interactions(progress, delay_s, interaction_counter["count"])
        last_response = handle_user_message(session_id, message)
        interaction_counter["count"] += 1
        _progress(
            progress,
            f"case {case_id}: interaction {interaction_index}/{total_interactions} "
            f"done mode={last_response.get('retrieval_mode')} "
            f"trace={last_response.get('trace_id')}",
        )
        slow_path_debug: list[DebugRecord] = []
        if run_slow_path:
            slow_path_debug = _drain_slow_path(progress, case_id, slow_path_batch_size)
        debug_record = _interaction_debug_record(
            case_id=case_id,
            session_id=session_id,
            interaction_index=interaction_index,
            total_interactions=total_interactions,
            message=message,
            response=last_response,
            slow_path=slow_path_debug,
        )
        case_debug_records.append(debug_record)
        if debug_records is not None:
            debug_records.append(debug_record)
    if not last_response:
        raise ValueError("case produced no response")
    last_response["_eval_debug_records"] = case_debug_records
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


def _isolation_base_path(configured: Path | None) -> Path:
    """Return the base path that per-case isolated databases derive from."""
    if configured is not None:
        return configured
    return Path(tempfile.mkdtemp(prefix="mira-eval-cases-")) / "eval.sqlite3"


def _isolate_case_state(base: Path, index: int, progress: ProgressReporter | None) -> None:
    """Point durable state at a fresh per-case database and empty the vector store."""
    suffix = base.suffix or ".sqlite3"
    case_path = base.with_name(f"{base.stem}.case-{index}{suffix}")
    configure_database(case_path)
    reset_vector_store()
    _progress(progress, f"case {index}: isolated db={case_path}")


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


def _throttle_between_interactions(
    progress: ProgressReporter | None,
    delay_s: float,
    completed_interactions: int,
) -> None:
    if delay_s <= 0 or completed_interactions == 0:
        return
    _progress(progress, f"throttle: sleeping {delay_s:g}s before next live call")
    time.sleep(delay_s)


def _drain_slow_path(
    progress: ProgressReporter | None,
    case_id: str,
    batch_size: int,
) -> list[DebugRecord]:
    from core.memory.slow_path import run_slow_path_batch

    total_processed = 0
    total_failed = 0
    debug_batches: list[DebugRecord] = []
    while True:
        _progress(progress, f"case {case_id}: slow path claiming up to {batch_size}")
        results = run_slow_path_batch(batch_size)
        if not results:
            _progress(
                progress,
                f"case {case_id}: slow path idle processed={total_processed} failed={total_failed}",
            )
            return debug_batches
        processed = len(results)
        failed = sum(1 for result in results if not result.get("succeeded"))
        total_processed += processed
        total_failed += failed
        debug_batches.append(
            {
                "processed": processed,
                "failed": failed,
                "observations": [_slow_path_result_debug(result) for result in results],
            }
        )
        _progress(
            progress,
            f"case {case_id}: slow path batch processed={processed} failed={failed}",
        )


def _interaction_debug_record(
    *,
    case_id: str,
    session_id: str,
    interaction_index: int,
    total_interactions: int,
    message: str,
    response: dict[str, object],
    slow_path: list[DebugRecord],
) -> DebugRecord:
    trace_id = str(response.get("trace_id", ""))
    trace = get_answer_trace(trace_id) if trace_id else None
    return {
        "case_id": case_id,
        "session_id": session_id,
        "interaction": f"{interaction_index}/{total_interactions}",
        "message": message,
        "answer": response.get("answer", ""),
        "retrieval_mode": response.get("retrieval_mode"),
        "routing_decision": response.get("routing_decision", {}),
        "retrieval_trace": response.get("retrieval_trace", {}),
        "used_session_items": response.get("used_session_items", []),
        "used_memory_items": response.get("used_memory_items", []),
        "active_session_items": _compact_session_items(list_active_session_items(session_id)),
        "trace_id": trace_id,
        "prompt_sections": trace.get("prompt_sections_json", []) if trace else [],
        "hydration_ids": trace.get("hydration_ids_json", []) if trace else [],
        "slow_path": slow_path,
    }


def _slow_path_result_debug(result: dict[str, object]) -> DebugRecord:
    raw_steps = result.get("steps", [])
    steps = raw_steps if isinstance(raw_steps, list) else []
    created = result.get("created_record_ids", {})
    created_ids = created if isinstance(created, dict) else {}
    graph_edge_ids = [str(edge_id) for edge_id in _as_list(created_ids.get("graph_edges"))]
    return {
        "observation_id": result.get("observation_id"),
        "succeeded": result.get("succeeded"),
        "error_message": result.get("error_message"),
        "created_record_ids": created_ids,
        "created_graph_edges": _graph_edge_details(graph_edge_ids),
        "steps": [
            {
                "step": step.get("step_name"),
                "succeeded": step.get("succeeded"),
                "created": step.get("created_record_ids", []),
                "error": step.get("error_message"),
            }
            for step in steps
            if isinstance(step, dict)
        ],
    }


def _compact_session_items(items: list[dict[str, object]]) -> list[DebugRecord]:
    keys = ("id", "type", "content", "scope", "status", "priority", "explicitness_label")
    return [{key: item.get(key) for key in keys if item.get(key) is not None} for item in items]


def _graph_edge_details(edge_ids: list[str]) -> list[DebugRecord]:
    if not edge_ids:
        return []
    placeholders = ", ".join("?" for _ in edge_ids)
    with repository_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT graph_edges.id,
                   graph_edges.edge_type,
                   graph_edges.confidence,
                   source.label AS source_label,
                   target.label AS target_label
            FROM graph_edges
            JOIN graph_nodes AS source ON source.id = graph_edges.source_node_id
            JOIN graph_nodes AS target ON target.id = graph_edges.target_node_id
            WHERE graph_edges.id IN ({placeholders})
            ORDER BY graph_edges.created_at ASC
            """,  # nosec B608
            tuple(edge_ids),
        ).fetchall()
    return [dict(row) for row in rows]


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
        _code_block(_json_dump(record.get("routing_decision", {})), "json"),
        "",
        "### Retrieval Trace",
        "",
        _code_block(_json_dump(record.get("retrieval_trace", {})), "json"),
        "",
        "### Active Session Items",
        "",
        _code_block(_json_dump(record.get("active_session_items", [])), "json"),
        "",
        "### Prompt Sections",
        "",
        _code_block(_json_dump(record.get("prompt_sections", [])), "json"),
        "",
        "### Slow Path",
        "",
        _code_block(_json_dump(record.get("slow_path", [])), "json"),
        "",
    ]
    return lines


def _json_dump(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, default=str)


def _code_block(value: str, language: str = "") -> str:
    return f"```{language}\n{value}\n```"
