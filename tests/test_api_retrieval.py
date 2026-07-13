"""Tests for MIRA API retrieval trace routes."""

from __future__ import annotations

from typing import Any

from api.auth import AuthenticatedWorkspace
from api.routes.retrieval import get_retrieval_trace
from core.db.repositories import (
    WorkspaceContext,
    configure_database,
    create_answer_trace,
    create_retrieval_log,
    create_session,
    save_observation,
)
from core.db.schema import LEGACY_WORKSPACE_ID


def test_retrieval_trace_endpoint_returns_trace_shape(tmp_path: Any, monkeypatch: Any) -> None:
    db_path = tmp_path / "api-retrieval.sqlite3"
    monkeypatch.setenv("MIRA_DB_PATH", str(db_path))
    configure_database(db_path)
    session_id = create_session("jerry", "trace test")
    user_observation_id = save_observation(session_id, "user", "What changed?")
    assistant_observation_id = save_observation(session_id, "assistant", "MIRA changed.")
    retrieval_log_id = create_retrieval_log(
        {
            "session_id": session_id,
            "query": "What changed?",
            "retrieval_mode": "relational",
            "retrieved_records_json": [{"id": "edge_1", "source": "graph"}],
        }
    )
    trace_id = create_answer_trace(
        {
            "session_id": session_id,
            "user_observation_id": user_observation_id,
            "assistant_observation_id": assistant_observation_id,
            "retrieval_mode": "relational",
            "retrieval_log_id": retrieval_log_id,
            "retrieved_observation_ids_json": [user_observation_id],
            "retrieved_fact_ids_json": ["fact_1"],
            "session_item_ids_json": ["sws_1"],
            "hot_memory_ids_json": ["wm_1"],
            "graph_path_ids_json": ["edge_1"],
            "community_summary_ids_json": ["community_1"],
            "sufficiency_json": {"sufficient": True},
            "prompt_sections_json": [{"section": "retrieval", "source_ids": ["edge_1"]}],
            "hydration_ids_json": ["sws_hydrated"],
        }
    )

    response = get_retrieval_trace(
        trace_id,
        AuthenticatedWorkspace(WorkspaceContext(LEGACY_WORKSPACE_ID, auth_mode="development")),
    )

    assert response.trace_id == trace_id
    assert response.session_id == session_id
    assert response.user_observation_id == user_observation_id
    assert response.assistant_observation_id == assistant_observation_id
    assert response.query == "What changed?"
    assert response.retrieval_mode == "relational"
    assert response.retrieved_observation_ids == [user_observation_id]
    assert response.retrieved_fact_ids == ["fact_1"]
    assert response.session_item_ids == ["sws_1"]
    assert response.hot_memory_ids == ["wm_1"]
    assert response.graph_path_ids == ["edge_1"]
    assert response.community_summary_ids == ["community_1"]
    assert response.sufficiency == {"sufficient": True}
    assert response.prompt_sections == [{"section": "retrieval", "source_ids": ["edge_1"]}]
    assert response.hydration_ids == ["sws_hydrated"]
    assert response.retrieval_log_id == retrieval_log_id
    assert response.evidence
