"""Tests for MIRA API session routes."""

from __future__ import annotations

import json
from typing import Any, cast

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from api.auth import AuthenticatedWorkspace
from api.routes.sessions import (
    create_session_route,
    delete_session_route,
    get_session_route,
    get_working_set_route,
    list_sessions_route,
)
from api.schemas.sessions import CreateSessionRequest
from core.db import chroma
from core.db.repositories import (
    WorkspaceContext,
    configure_database,
    create_answer_trace,
    create_atomic_fact,
    create_community_summary,
    create_entity,
    create_foresight_record,
    create_graph_edge,
    create_graph_node,
    create_reflection,
    create_session,
    create_session_item,
    create_working_memory_item,
    create_workspace,
    link_reflection_evidence,
    repository_connection,
    save_observation,
)
from core.db.schema import LEGACY_WORKSPACE_ID
from core.memory.read_models import (
    get_memory_graph_read_model,
    get_memory_health_read_model,
    list_community_summaries_read_model,
    list_reflections_read_model,
)

AUTH = AuthenticatedWorkspace(WorkspaceContext(LEGACY_WORKSPACE_ID, auth_mode="development"))
REQUEST = Request({"type": "http", "method": "POST", "path": "/sessions", "headers": []})


def test_session_endpoint_creates_and_returns_session(tmp_path: Any, monkeypatch: Any) -> None:
    configure_database(tmp_path / "api-sessions.sqlite3")

    created = create_session_route(REQUEST, CreateSessionRequest(title="API Test"), AUTH)

    assert created.user_id == "development"
    assert created.title == "API Test"

    fetched = get_session_route(created.session_id, AUTH)
    assert fetched.session_id == created.session_id


def test_session_list_message_counts_are_workspace_scoped(
    tmp_path: Any, monkeypatch: Any
) -> None:
    configure_database(tmp_path / "api-session-counts.sqlite3")
    workspace_a = create_workspace("A", "session-counts-a", "development")
    workspace_b = create_workspace("B", "session-counts-b", "development")
    session_a = create_session("a", workspace_id=workspace_a)
    session_b = create_session("b", workspace_id=workspace_b)
    save_observation(session_a, "user", "A message")
    save_observation(session_b, "user", "B message")
    save_observation(session_b, "assistant", "B response")

    response = list_sessions_route(
        AuthenticatedWorkspace(WorkspaceContext(workspace_a, auth_mode="development"))
    )

    assert [(session.session_id, session.message_count) for session in response.sessions] == [
        (session_a, 1)
    ]


def test_working_set_endpoint_returns_grouped_shape(tmp_path: Any, monkeypatch: Any) -> None:
    configure_database(tmp_path / "api-working-set.sqlite3")
    session_id = create_session_route(REQUEST, CreateSessionRequest(), AUTH).session_id

    response = get_working_set_route(session_id, AUTH)

    assert response.session_id == session_id
    assert response.active_goals == []
    assert response.corrections == []
    assert response.constraints == []
    assert response.unresolved_questions == []
    assert response.provisional_decisions == []
    assert response.items == []


def test_working_set_endpoint_returns_enriched_inspection_fields(
    tmp_path: Any, monkeypatch: Any
) -> None:
    configure_database(tmp_path / "api-working-set-rich.sqlite3")
    session_id = create_session_route(REQUEST, CreateSessionRequest(), AUTH).session_id
    old_id = create_session_item(
        {
            "session_id": session_id,
            "type": "active_constraint",
            "content": "Prefer concise responses.",
            "scope": "current_session",
            "status": "superseded",
            "priority": 0.4,
            "explicitness_label": "direct_instruction",
            "source_observations_json": [],
        }
    )
    source_observation_id = save_observation(
        session_id,
        "user",
        "Actually, give me detailed responses.",
    )
    assistant_observation_id = save_observation(session_id, "assistant", "Understood.")
    correction_id = create_session_item(
        {
            "session_id": session_id,
            "type": "correction",
            "content": "Give detailed responses.",
            "scope": "project",
            "status": "confirmed",
            "priority": 0.9,
            "explicitness_label": "direct_correction",
            "evidence_span": "Actually, give me detailed responses.",
            "source_observations_json": [source_observation_id],
            "supersedes_json": [old_id],
        }
    )
    create_answer_trace(
        {
            "session_id": session_id,
            "user_observation_id": source_observation_id,
            "assistant_observation_id": assistant_observation_id,
            "retrieval_mode": "quick",
            "session_item_ids_json": [correction_id],
        }
    )
    create_working_memory_item(
        {
            "content": "Give detailed responses.",
            "memory_type": "confirmed_correction",
            "scope": "project",
            "priority": 0.9,
            "status": "active",
            "source_record_type": "session_working_set",
            "source_record_id": correction_id,
        }
    )

    response = get_working_set_route(session_id, AUTH)
    item = next(row for row in response.items if row["id"] == correction_id)
    source_messages = cast(list[dict[str, object]], item["source_messages"])
    superseded_items = cast(list[dict[str, object]], item["superseded_items"])

    assert source_messages[0]["message_index"] == 1
    assert item["usage_count"] == 1
    assert cast(int, item["token_cost"]) > 0
    assert item["promotion_status"] == "promoted"
    assert superseded_items[0]["content"] == "Prefer concise responses."


def test_delete_session_hides_chat_and_deactivates_derived_memory(
    tmp_path: Any, monkeypatch: Any
) -> None:
    configure_database(tmp_path / "api-delete-session.sqlite3")
    removed_vectors: list[str] = []
    monkeypatch.setattr(
        chroma,
        "remove_from_index",
        lambda record_id, *, workspace_id: removed_vectors.append(record_id),
    )
    session_id = create_session_route(
        REQUEST, CreateSessionRequest(title="Use PostgreSQL"), AUTH
    ).session_id
    keep_session_id = create_session_route(
        REQUEST, CreateSessionRequest(title="Keep this chat"), AUTH
    ).session_id
    observation_id = save_observation(session_id, "user", "We use PostgreSQL now.")
    fact_id = create_atomic_fact(
        {
            "subject": "project database",
            "predicate": "uses",
            "object": "PostgreSQL",
            "confidence": 0.95,
            "source_observation_id": observation_id,
        }
    )
    create_working_memory_item(
        {
            "content": "Project database uses PostgreSQL.",
            "memory_type": "project_constraint",
            "scope": "project",
            "priority": 0.8,
            "status": "active",
            "source_record_type": "atomic_fact",
            "source_record_id": fact_id,
        }
    )
    source = create_graph_node(
        {
            "node_type": "atomic_fact",
            "source_table": "atomic_facts",
            "source_id": fact_id,
            "label": "DB",
        }
    )
    target = create_graph_node({"node_type": "entity", "label": "PostgreSQL"})
    edge_id = create_graph_edge(
        {
            "source_node_id": source,
            "target_node_id": target,
            "edge_type": "MENTIONS",
            "confidence": 0.9,
            "source_observations_json": [observation_id],
        }
    )
    reflection_id = create_reflection(
        {
            "reflection_type": "user_knowledge",
            "content": "The project uses PostgreSQL.",
            "confidence": 0.8,
            "status": "active",
        }
    )
    link_reflection_evidence(reflection_id, observation_id)
    foresight_id = create_foresight_record(
        {
            "content": "Remember PostgreSQL for database questions.",
            "status": "active",
            "source_observation_id": observation_id,
        }
    )

    response = delete_session_route(REQUEST, session_id, AUTH)

    assert response["status"] == "deleted"
    assert observation_id in removed_vectors
    assert all(row.session_id != session_id for row in list_sessions_route(AUTH).sessions)
    assert any(row.session_id == keep_session_id for row in list_sessions_route(AUTH).sessions)
    with pytest.raises(HTTPException):
        get_session_route(session_id, AUTH)
    with repository_connection() as connection:
        session = connection.execute(
            "SELECT status FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        observation = connection.execute(
            "SELECT content, metadata_json FROM observations WHERE id = ?",
            (observation_id,),
        ).fetchone()
        fact = connection.execute(
            "SELECT status FROM atomic_facts WHERE id = ?",
            (fact_id,),
        ).fetchone()
        edge = connection.execute(
            "SELECT invalidated_at FROM graph_edges WHERE id = ?",
            (edge_id,),
        ).fetchone()
        reflection = connection.execute(
            "SELECT status, stale_reason FROM reflections WHERE id = ?",
            (reflection_id,),
        ).fetchone()
        foresight = connection.execute(
            "SELECT status FROM foresight_records WHERE id = ?",
            (foresight_id,),
        ).fetchone()
        working_memory = connection.execute("SELECT status FROM working_memory").fetchone()

    assert session["status"] == "deleted"
    assert observation["content"] == "[deleted by user]"
    assert '"deleted": true' in observation["metadata_json"]
    assert fact["status"] == "rejected"
    assert edge is None
    assert reflection["status"] == "stale"
    assert reflection["stale_reason"] == "source session deleted"
    assert foresight["status"] == "cancelled"
    assert working_memory["status"] == "expired"


def test_delete_session_prunes_shared_memory_provenance(tmp_path: Any, monkeypatch: Any) -> None:
    configure_database(tmp_path / "api-delete-shared-provenance.sqlite3")
    removed_vectors: list[str] = []
    monkeypatch.setattr(
        chroma,
        "remove_from_index",
        lambda record_id, *, workspace_id: removed_vectors.append(record_id),
    )
    deleted_session_id = create_session_route(
        REQUEST, CreateSessionRequest(title="Deleted source"), AUTH
    ).session_id
    retained_session_id = create_session_route(
        REQUEST, CreateSessionRequest(title="Retained source"), AUTH
    ).session_id
    deleted_observation_id = save_observation(
        deleted_session_id, "user", "I prefer detailed study help."
    )
    retained_observation_id = save_observation(
        retained_session_id, "user", "Please keep giving detailed study help."
    )
    reflection_id = create_reflection(
        {
            "reflection_type": "user_knowledge",
            "content": "The user prefers detailed study help.",
            "confidence": 0.85,
            "status": "active",
        }
    )
    link_reflection_evidence(reflection_id, deleted_observation_id)
    link_reflection_evidence(reflection_id, retained_observation_id)
    source = create_graph_node({"node_type": "entity", "label": "User"})
    target = create_graph_node({"node_type": "entity", "label": "Detailed study help"})
    edge_id = create_graph_edge(
        {
            "source_node_id": source,
            "target_node_id": target,
            "edge_type": "PREFERS",
            "confidence": 0.85,
            "source_observations_json": [deleted_observation_id, retained_observation_id],
        }
    )

    response = delete_session_route(REQUEST, deleted_session_id, AUTH)

    deleted = cast(dict[str, int], response["deleted"])
    assert deleted["reflection_provenance"] == 1
    assert deleted["graph_edges_pruned"] == 1
    assert reflection_id not in removed_vectors
    with repository_connection() as connection:
        reflection = connection.execute(
            "SELECT status FROM reflections WHERE id = ?",
            (reflection_id,),
        ).fetchone()
        evidence_ids = [
            str(row["observation_id"])
            for row in connection.execute(
                """
                SELECT observation_id FROM reflection_evidence
                WHERE reflection_id = ?
                ORDER BY observation_id
                """,
                (reflection_id,),
            ).fetchall()
        ]
        edge = connection.execute(
            "SELECT source_observations_json, invalidated_at FROM graph_edges WHERE id = ?",
            (edge_id,),
        ).fetchone()

    assert reflection["status"] == "active"
    assert evidence_ids == [retained_observation_id]
    assert json.loads(str(edge["source_observations_json"])) == [retained_observation_id]
    assert edge["invalidated_at"] is None


def test_delete_session_removes_unsupported_entities(tmp_path: Any, monkeypatch: Any) -> None:
    configure_database(tmp_path / "api-delete-session-entities.sqlite3")
    monkeypatch.setattr(chroma, "remove_from_index", lambda record_id, *, workspace_id: None)
    session_id = create_session_route(
        REQUEST, CreateSessionRequest(title="Entity source"), AUTH
    ).session_id
    keep_session_id = create_session_route(
        REQUEST, CreateSessionRequest(title="Keep workspace active"), AUTH
    ).session_id
    observation_id = save_observation(session_id, "user", "My name is Jerry.")
    entity_id = create_entity(
        {
            "name": "Jerry",
            "entity_type": "person",
            "aliases_json": [],
        }
    )
    observation_node_id = create_graph_node(
        {
            "node_type": "observation",
            "source_table": "observations",
            "source_id": observation_id,
            "label": "My name is Jerry.",
        }
    )
    entity_node_id = create_graph_node(
        {
            "node_type": "entity",
            "source_table": "entities",
            "source_id": entity_id,
            "label": "Jerry",
        }
    )
    create_graph_edge(
        {
            "source_node_id": observation_node_id,
            "target_node_id": entity_node_id,
            "edge_type": "MENTIONS",
            "confidence": 1.0,
            "source_observations_json": [observation_id],
        }
    )

    response = delete_session_route(REQUEST, session_id, AUTH)

    deleted = cast(dict[str, int], response["deleted"])
    assert deleted["entities"] == 1
    assert any(row.session_id == keep_session_id for row in list_sessions_route(AUTH).sessions)
    with repository_connection() as connection:
        entity = connection.execute("SELECT id FROM entities WHERE id = ?", (entity_id,)).fetchone()
        entity_node = connection.execute(
            "SELECT id FROM graph_nodes WHERE id = ?",
            (entity_node_id,),
        ).fetchone()

    assert entity is None
    assert entity_node is None


def test_deleting_last_session_resets_workspace_memory(tmp_path: Any, monkeypatch: Any) -> None:
    configure_database(tmp_path / "api-delete-last-session.sqlite3")
    deleted_collections: list[str] = []
    monkeypatch.setattr(
        chroma,
        "delete_workspace_vectors",
        lambda collection, *, workspace_id: deleted_collections.append(collection),
    )
    monkeypatch.setattr(chroma, "remove_from_index", lambda record_id, *, workspace_id: None)
    session_id = create_session_route(
        REQUEST, CreateSessionRequest(title="Exam memory"), AUTH
    ).session_id
    observation_id = save_observation(session_id, "user", "My exam is on July 20, 2026.")
    fact_id = create_atomic_fact(
        {
            "subject": "user exam",
            "predicate": "date",
            "object": "July 20, 2026",
            "confidence": 0.9,
            "source_observation_id": observation_id,
        }
    )
    create_working_memory_item(
        {
            "content": "User exam is on July 20, 2026.",
            "memory_type": "project_constraint",
            "scope": "project",
            "priority": 0.8,
            "status": "active",
            "source_record_type": "atomic_fact",
            "source_record_id": fact_id,
        }
    )
    node_id = create_graph_node(
        {
            "node_type": "atomic_fact",
            "source_table": "atomic_facts",
            "source_id": fact_id,
            "label": "Exam date",
        }
    )
    reflection_id = create_reflection(
        {
            "reflection_type": "user_knowledge",
            "content": "The user is preparing for an exam.",
            "confidence": 0.8,
            "status": "active",
        }
    )
    link_reflection_evidence(reflection_id, observation_id)
    create_community_summary(
        {
            "community_id": "community_exam",
            "title": "Exam planning",
            "summary": "Exam-related memory.",
            "member_nodes_json": [node_id],
        }
    )
    create_foresight_record(
        {
            "content": "Offer exam revision help before July 20.",
            "status": "active",
            "source_observation_id": observation_id,
        }
    )

    response = delete_session_route(REQUEST, session_id, AUTH)
    deleted = cast(dict[str, int], response["deleted"])

    assert response["status"] == "deleted"
    assert deleted["workspace_memory_reset"] == 1
    assert set(deleted_collections) == chroma.SUPPORTED_COLLECTIONS
    assert list_sessions_route(AUTH).sessions == []
    assert list_reflections_read_model(workspace_id=LEGACY_WORKSPACE_ID) == []
    assert list_community_summaries_read_model(workspace_id=LEGACY_WORKSPACE_ID) == []
    assert get_memory_graph_read_model(workspace_id=LEGACY_WORKSPACE_ID) == {
        "nodes": [],
        "edges": [],
    }
    health = get_memory_health_read_model(workspace_id=LEGACY_WORKSPACE_ID)
    tiers = cast(dict[str, dict[str, object]], health["tiers"])
    cold_components = cast(dict[str, int], tiers["cold"]["components"])
    warm_components = cast(dict[str, int], tiers["warm"]["components"])
    assert cold_components["observations"] == 0
    assert cold_components["atomic_facts"] == 0
    assert warm_components["community_summaries"] == 0
