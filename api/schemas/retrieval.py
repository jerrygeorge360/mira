"""Retrieval trace schemas for the MIRA API."""

from __future__ import annotations

from pydantic import BaseModel


class RetrievalTraceResponse(BaseModel):
    """Trace details for an answer/retrieval event."""

    trace_id: str
    session_id: str
    user_observation_id: str
    assistant_observation_id: str
    retrieval_mode: str
    query: str | None = None
    retrieved_observation_ids: list[str]
    retrieved_fact_ids: list[str]
    session_item_ids: list[str]
    hot_memory_ids: list[str]
    graph_path_ids: list[str]
    community_summary_ids: list[str]
    sufficiency: dict[str, object] | None = None
    prompt_sections: list[dict[str, object]]
    hydration_ids: list[str]
    retrieval_log_id: str | None = None
    prompt_log_id: str | None = None
    created_at: str | None = None
    evidence: list[dict[str, object]]
