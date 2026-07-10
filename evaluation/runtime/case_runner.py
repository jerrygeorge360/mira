"""Shared case execution runtime for local eval and ablation.

Ownership: MIRA contributors.
Related issue: ISSUE-051, ISSUE-053.
Architecture area: evaluation.

This module owns the common mechanics of replaying a declarative memory case
through the real MIRA agent: sessions, reset markers, optional throttling,
optional inline slow-path draining, and trace/debug capture. Reporting remains
with the caller: local eval writes local summaries, while ablation compares
component configurations.
"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from typing import Protocol

from core.agent import handle_user_message
from core.db.chroma import reset_vector_store
from core.db.repositories import (
    configure_database,
    create_session,
    get_answer_trace,
    repository_connection,
)
from core.session.working_set import list_active_session_items

EvaluationCase = dict[str, object]
DebugRecord = dict[str, object]


class ProgressReporter(Protocol):
    """Receives human-readable evaluation progress messages."""

    def __call__(self, message: str) -> None: ...


def run_case_interactions(
    case: EvaluationCase,
    *,
    case_id: str,
    session_user: str,
    progress: ProgressReporter | None = None,
    delay_s: float = 0.0,
    interaction_counter: dict[str, int] | None = None,
    run_slow_path: bool = False,
    slow_path_batch_size: int = 20,
    case_debug_records: list[DebugRecord] | None = None,
    debug_records: list[DebugRecord] | None = None,
) -> dict[str, object]:
    """Replay a case through the real agent and return the final response."""
    interactions = _as_list(case.get("interactions"))
    if not interactions:
        raise ValueError("case has no interactions")
    if delay_s < 0:
        raise ValueError("delay_s must not be negative")
    if slow_path_batch_size < 1:
        raise ValueError("slow_path_batch_size must be a positive integer")

    counter = interaction_counter if interaction_counter is not None else {"count": 0}
    case_records = case_debug_records if case_debug_records is not None else []
    session_id = create_session(session_user)
    last_response: dict[str, object] = {}
    total_interactions = len(interactions)
    for interaction_index, interaction in enumerate(interactions, start=1):
        if not isinstance(interaction, dict):
            continue
        if interaction.get("reset_session"):
            session_id = create_session(session_user)
            _progress(progress, f"case {case_id}: reset session")
        message = str(interaction.get("message", "")).strip()
        if not message:
            continue
        _progress(
            progress,
            f"case {case_id}: interaction {interaction_index}/{total_interactions} answering",
        )
        _throttle_between_interactions(progress, delay_s, counter["count"])
        last_response = handle_user_message(session_id, message)
        counter["count"] += 1
        _progress(
            progress,
            f"case {case_id}: interaction {interaction_index}/{total_interactions} "
            f"done mode={last_response.get('retrieval_mode')} "
            f"trace={last_response.get('trace_id')}",
        )
        slow_path_debug: list[DebugRecord] = []
        if run_slow_path:
            slow_path_debug = drain_slow_path(progress, case_id, slow_path_batch_size)
        debug_record = _interaction_debug_record(
            case_id=case_id,
            session_id=session_id,
            interaction_index=interaction_index,
            total_interactions=total_interactions,
            message=message,
            response=last_response,
            slow_path=slow_path_debug,
        )
        case_records.append(debug_record)
        if debug_records is not None:
            debug_records.append(debug_record)
    if not last_response:
        raise ValueError("case produced no response")
    last_response["_eval_debug_records"] = case_records
    return last_response


def isolation_base_path(configured: Path | None) -> Path:
    """Return the base path that isolated evaluation databases derive from."""
    if configured is not None:
        return configured
    return Path(tempfile.mkdtemp(prefix="mira-eval-cases-")) / "eval.sqlite3"


def isolate_case_state(
    base: Path,
    label: str | int,
    progress: ProgressReporter | None = None,
    *,
    progress_prefix: str = "case",
) -> Path:
    """Point durable state at a fresh database and empty the vector store."""
    suffix = base.suffix or ".sqlite3"
    case_path = base.with_name(f"{base.stem}.{progress_prefix}-{label}{suffix}")
    configure_database(case_path)
    reset_vector_store()
    _progress(progress, f"{progress_prefix} {label}: isolated db={case_path}")
    return case_path


def drain_slow_path(
    progress: ProgressReporter | None,
    case_id: str,
    batch_size: int,
) -> list[DebugRecord]:
    """Drain queued slow-path work and return compact debug records."""
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


def _throttle_between_interactions(
    progress: ProgressReporter | None,
    delay_s: float,
    completed_interactions: int,
) -> None:
    if delay_s <= 0 or completed_interactions == 0:
        return
    _progress(progress, f"throttle: sleeping {delay_s:g}s before next live call")
    time.sleep(delay_s)


def _as_list(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _progress(progress: ProgressReporter | None, message: str) -> None:
    if progress is not None:
        progress(message)


def json_dump(value: object) -> str:
    """Return stable pretty JSON for debug renderers."""
    return json.dumps(value, indent=2, sort_keys=True, default=str)
