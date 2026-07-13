"""Retrieval trace routes for the MIRA API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.auth import WorkspaceAuth
from api.dependencies import fetch_one
from api.schemas.retrieval import RetrievalTraceResponse
from core.db.repositories import bind_workspace

router = APIRouter(prefix="/retrieval", tags=["retrieval"])


@router.get("/traces/{trace_id}", response_model=RetrievalTraceResponse)
def get_retrieval_trace(
    trace_id: str,
    auth: WorkspaceAuth,
) -> RetrievalTraceResponse:
    """Return one answer trace and its retrieval evidence."""
    trace = bind_workspace(auth.context).get_answer_trace(trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="trace_id not found")
    retrieval_log = None
    if trace.get("retrieval_log_id"):
        retrieval_log = fetch_one(
            "SELECT * FROM retrieval_logs WHERE id = ? AND workspace_id = ?",
            (str(trace["retrieval_log_id"]), auth.context.workspace_id),
        )
    return RetrievalTraceResponse(
        trace_id=trace_id,
        session_id=str(trace["session_id"]),
        user_observation_id=str(trace["user_observation_id"]),
        assistant_observation_id=str(trace["assistant_observation_id"]),
        retrieval_mode=str(trace["retrieval_mode"]),
        query=str(retrieval_log["query"]) if retrieval_log and retrieval_log.get("query") else None,
        retrieved_observation_ids=_string_list(trace.get("retrieved_observation_ids_json")),
        retrieved_fact_ids=_string_list(trace.get("retrieved_fact_ids_json")),
        session_item_ids=_string_list(trace.get("session_item_ids_json")),
        hot_memory_ids=_string_list(trace.get("hot_memory_ids_json")),
        graph_path_ids=_string_list(trace.get("graph_path_ids_json")),
        community_summary_ids=_string_list(trace.get("community_summary_ids_json")),
        sufficiency=_dict_or_none(trace.get("sufficiency_json")),
        prompt_sections=_dict_list(trace.get("prompt_sections_json")),
        hydration_ids=_string_list(trace.get("hydration_ids_json")),
        retrieval_log_id=(
            str(trace["retrieval_log_id"]) if trace.get("retrieval_log_id") else None
        ),
        prompt_log_id=str(trace["prompt_log_id"]) if trace.get("prompt_log_id") else None,
        created_at=str(trace["created_at"]) if trace.get("created_at") else None,
        evidence=_trace_evidence(trace, retrieval_log),
    )


def _trace_evidence(
    trace: dict[str, object],
    retrieval_log: dict[str, object] | None,
) -> list[dict[str, object]]:
    evidence: list[dict[str, object]] = []
    if retrieval_log:
        for item in _object_list(retrieval_log.get("retrieved_records_json")):
            evidence.append({"source": "retrieval_log", "record": item})
    for key, source in (
        ("retrieved_observation_ids_json", "observation"),
        ("retrieved_fact_ids_json", "atomic_fact"),
        ("session_item_ids_json", "session_item"),
        ("hot_memory_ids_json", "working_memory"),
        ("graph_path_ids_json", "graph_path"),
        ("community_summary_ids_json", "community_summary"),
    ):
        for item_id in _string_list(trace.get(key)):
            evidence.append({"source": source, "id": str(item_id)})
    return evidence


def _object_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _string_list(value: object) -> list[str]:
    return [str(item) for item in _object_list(value)]


def _dict_list(value: object) -> list[dict[str, object]]:
    return [item for item in _object_list(value) if isinstance(item, dict)]


def _dict_or_none(value: object) -> dict[str, object] | None:
    return value if isinstance(value, dict) else None
