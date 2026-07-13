"""Verify workspace schema migration and fail-closed repository ownership."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.db.repositories import (
    WorkspaceContext,
    bind_workspace,
    configure_database,
    create_atomic_fact,
    create_graph_edge,
    create_graph_node,
    create_session,
    create_user,
    create_workspace,
    enqueue_observation,
    repository_connection,
    resolve_canonical_form,
    save_observation,
)
from core.db.schema import LEGACY_WORKSPACE_ID, WORKSPACE_MIGRATION_ID, initialize_database
from core.memory import slow_path
from core.retrieval.keyword import keyword_search_observations
from core.retrieval.relational import relational_retrieve


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()  # noqa: UP017


def test_legacy_rows_are_backfilled_idempotently(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL, title TEXT,
                status TEXT NOT NULL, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, ended_at TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO sessions VALUES ('session-old', 'local', NULL, 'active', ?, ?, NULL)",
            (_now(), _now()),
        )

    initialize_database(path)
    initialize_database(path)

    with sqlite3.connect(path) as connection:
        workspace_id = connection.execute(
            "SELECT workspace_id FROM sessions WHERE id = 'session-old'"
        ).fetchone()[0]
        migration_count = connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE id = ?",
            (WORKSPACE_MIGRATION_ID,),
        ).fetchone()[0]
        legacy_count = connection.execute(
            "SELECT COUNT(*) FROM workspaces WHERE id = ?",
            (LEGACY_WORKSPACE_ID,),
        ).fetchone()[0]

    assert workspace_id == LEGACY_WORKSPACE_ID
    assert migration_count == 1
    assert legacy_count == 1


def test_workspace_repository_hides_other_workspace_records(tmp_path: Path) -> None:
    configure_database(tmp_path / "ownership.sqlite3")
    workspace_a = create_workspace("A", "a", "development")
    workspace_b = create_workspace("B", "b", "development")
    repo_a = bind_workspace(WorkspaceContext(workspace_a))
    repo_b = bind_workspace(WorkspaceContext(workspace_b))

    session_a = repo_a.create_session("user-a")
    session_b = repo_b.create_session("user-b")
    observation_b = repo_b.save_observation(session_b, "user", "I use PostgreSQL.")
    fact_b = create_atomic_fact(
        {
            "subject": "user",
            "predicate": "uses",
            "object": "PostgreSQL",
            "confidence": 1.0,
            "source_observation_id": observation_b,
        }
    )

    assert repo_a.get_session(session_b) is None
    assert repo_a.get_atomic_fact(fact_b) is None
    assert repo_b.get_atomic_fact(fact_b) is not None
    with pytest.raises(ValueError, match="Session not found in workspace"):
        repo_a.save_observation(session_b, "user", "cross-workspace write")
    assert repo_a.get_session(session_a) is not None


def test_canonical_vocabulary_is_independent_per_workspace(tmp_path: Path) -> None:
    configure_database(tmp_path / "canonical.sqlite3")
    workspace_a = create_workspace("A", "canonical-a", "development")
    workspace_b = create_workspace("B", "canonical-b", "development")

    canonical_a = resolve_canonical_form(
        "canonical_subjects", "private project", workspace_id=workspace_a
    )
    canonical_b = resolve_canonical_form(
        "canonical_subjects", "private project", workspace_id=workspace_b
    )

    assert canonical_a is not None
    assert canonical_b is not None
    assert canonical_a != canonical_b


def test_database_rejects_cross_workspace_queue_and_graph_links(tmp_path: Path) -> None:
    configure_database(tmp_path / "boundaries.sqlite3")
    workspace_a = create_workspace("A", "boundary-a", "development")
    workspace_b = create_workspace("B", "boundary-b", "development")
    repo_a = bind_workspace(WorkspaceContext(workspace_a))
    repo_b = bind_workspace(WorkspaceContext(workspace_b))
    session_a = repo_a.create_session("a")
    session_b = repo_b.create_session("b")
    observation_a = repo_a.save_observation(session_a, "user", "A")
    observation_b = repo_b.save_observation(session_b, "user", "B")
    enqueue_observation(observation_a)

    with (
        repository_connection() as connection,
        pytest.raises(sqlite3.IntegrityError, match="queue workspace"),
    ):
        connection.execute(
            """
            INSERT INTO slow_path_queue (
                id, workspace_id, observation_id, status, attempt_count, created_at, updated_at
            ) VALUES ('bad-job', ?, ?, 'pending', 0, ?, ?)
            """,
            (workspace_a, observation_b, _now(), _now()),
        )

    node_a = create_graph_node({"workspace_id": workspace_a, "node_type": "entity", "label": "A"})
    node_b = create_graph_node({"workspace_id": workspace_b, "node_type": "entity", "label": "B"})
    with (
        repository_connection() as connection,
        pytest.raises(sqlite3.IntegrityError, match="workspace_id is immutable"),
    ):
        connection.execute(
            "UPDATE graph_nodes SET workspace_id = ? WHERE id = ?",
            (workspace_b, node_a),
        )
    with pytest.raises(ValueError, match="graph edge endpoints"):
        create_graph_edge(
            {
                "workspace_id": workspace_a,
                "source_node_id": node_a,
                "target_node_id": node_b,
                "edge_type": "MENTIONS",
                "confidence": 1.0,
                "source_observations_json": [observation_a],
            }
        )


def test_relational_retrieval_cannot_cross_workspace(tmp_path: Path) -> None:
    configure_database(tmp_path / "relational-isolation.sqlite3")
    workspace_a = create_workspace("A", "relational-a", "development")
    workspace_b = create_workspace("B", "relational-b", "development")
    node_a = create_graph_node({"workspace_id": workspace_a, "node_type": "entity", "label": "A"})
    node_b = create_graph_node({"workspace_id": workspace_b, "node_type": "entity", "label": "B"})
    target_b = create_graph_node(
        {"workspace_id": workspace_b, "node_type": "entity", "label": "B target"}
    )
    create_graph_edge(
        {
            "workspace_id": workspace_b,
            "source_node_id": node_b,
            "target_node_id": target_b,
            "edge_type": "LEADS_TO",
            "confidence": 1.0,
            "source_observations_json": [],
        }
    )

    assert relational_retrieve([node_a, node_b], {"LEADS_TO"}, workspace_id=workspace_a) == []


def test_keyword_retrieval_crosses_sessions_but_not_workspaces(tmp_path: Path) -> None:
    configure_database(tmp_path / "keyword-isolation.sqlite3")
    workspace_a = create_workspace("A", "keyword-a", "development")
    workspace_b = create_workspace("B", "keyword-b", "development")
    repo_a = bind_workspace(WorkspaceContext(workspace_a))
    repo_b = bind_workspace(WorkspaceContext(workspace_b))
    repo_a.save_observation(repo_a.create_session("a1"), "user", "Project uses PostgreSQL")
    repo_b.save_observation(repo_b.create_session("b1"), "user", "Project uses MongoDB")
    query_session = repo_a.create_session("a2")

    results = keyword_search_observations(
        "Which database does the project use?", limit=10, workspace_id=workspace_a
    )

    assert any(row["content"] == "Project uses PostgreSQL" for row in results)
    assert all(row["content"] != "Project uses MongoDB" for row in results)
    assert query_session


def test_slow_path_semantic_passes_run_per_claimed_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [
        {"id": "queue-a", "observation_id": "obs-a", "workspace_id": "workspace-a"},
        {"id": "queue-b", "observation_id": "obs-b", "workspace_id": "workspace-b"},
    ]
    semantic_workspaces: list[str] = []
    monkeypatch.setattr(slow_path, "claim_pending_batch", lambda batch_size: records)
    monkeypatch.setattr(
        slow_path, "_validate_queue_workspace", lambda record: str(record["workspace_id"])
    )
    monkeypatch.setattr(
        slow_path,
        "run_slow_path_for_observation",
        lambda observation_id, config=None: {
            "observation_id": observation_id,
            "succeeded": True,
        },
    )
    monkeypatch.setattr(slow_path, "mark_done", lambda queue_id: None)
    monkeypatch.setattr(
        slow_path,
        "run_semantic_passes",
        lambda config=None, *, workspace_id: semantic_workspaces.append(workspace_id) or [],
    )

    slow_path.run_slow_path_batch(2)

    assert semantic_workspaces == ["workspace-a", "workspace-b"]


def test_worker_quarantines_ownership_validation_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_database(tmp_path / "quarantine.sqlite3")
    session_id = create_session("user")
    observation_id = save_observation(session_id, "user", "invalid ownership")
    queue_id = enqueue_observation(observation_id)
    monkeypatch.setattr(
        slow_path,
        "_validate_queue_workspace",
        lambda record: (_ for _ in ()).throw(ValueError("workspace mismatch")),
    )

    results = slow_path.run_slow_path_batch(1)

    with repository_connection() as connection:
        row = connection.execute(
            "SELECT status, quarantine_reason FROM slow_path_queue WHERE id = ?", (queue_id,)
        ).fetchone()
    assert results[0]["succeeded"] is False
    assert row["status"] == "quarantined"
    assert row["quarantine_reason"] == "workspace mismatch"


def test_worker_retry_skips_completed_observation_steps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_database(tmp_path / "step-journal.sqlite3")
    session_id = create_session("user")
    observation_id = save_observation(session_id, "user", "retry safely")
    calls = {"embedding": 0, "graph": 0}

    def embedding(*args: object, **kwargs: object) -> dict[str, list[str]]:
        calls["embedding"] += 1
        return {}

    def graph(*args: object, **kwargs: object) -> dict[str, list[str]]:
        calls["graph"] += 1
        if calls["graph"] == 1:
            raise RuntimeError("temporary graph failure")
        return {}

    monkeypatch.setattr(slow_path, "_step_embedding_index", embedding)
    monkeypatch.setattr(slow_path, "_step_atomic_facts", lambda *args, **kwargs: {})
    monkeypatch.setattr(slow_path, "_step_entities", graph)
    monkeypatch.setattr(slow_path, "_step_changes", lambda *args, **kwargs: {})
    monkeypatch.setattr(slow_path, "_step_reflection_invalidation", lambda *args, **kwargs: {})
    monkeypatch.setattr(slow_path, "_step_tiers", lambda *args, **kwargs: {})
    monkeypatch.setattr(slow_path, "_step_foresight", lambda *args, **kwargs: {})

    first = slow_path.run_slow_path_for_observation(observation_id)
    second = slow_path.run_slow_path_for_observation(observation_id)

    assert first["succeeded"] is False
    assert second["succeeded"] is True
    assert calls == {"embedding": 1, "graph": 2}


def test_inactive_workspace_cannot_be_bound(tmp_path: Path) -> None:
    configure_database(tmp_path / "inactive.sqlite3")
    workspace_id = create_workspace("Expired", "expired", "demo", status="expired")

    with pytest.raises(ValueError, match="not active"):
        bind_workspace(WorkspaceContext(workspace_id))


def test_personal_workspace_is_unique_per_owner_and_membership_is_checked(
    tmp_path: Path,
) -> None:
    configure_database(tmp_path / "membership.sqlite3")
    owner_id = create_user(github_id="123", github_login="owner")
    outsider_id = create_user(github_id="456", github_login="outsider")
    workspace_id = create_workspace(
        "Owner workspace",
        "owner-workspace",
        "personal",
        owner_user_id=owner_id,
    )

    repository = bind_workspace(WorkspaceContext(workspace_id, user_id=owner_id))
    assert repository.workspace_id == workspace_id
    with pytest.raises(ValueError, match="not a member"):
        bind_workspace(WorkspaceContext(workspace_id, user_id=outsider_id))
    with pytest.raises(ValueError, match="Could not create workspace"):
        create_workspace(
            "Duplicate personal workspace",
            "owner-workspace-two",
            "personal",
            owner_user_id=owner_id,
        )
