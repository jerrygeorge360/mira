"""Workspace data reset tests."""

from __future__ import annotations

from pathlib import Path

from core.db import chroma
from core.db.repositories import (
    WorkspaceContext,
    bind_workspace,
    configure_database,
    create_atomic_fact,
    create_workspace,
    get_workspace,
    repository_connection,
)
from core.workspace_data import delete_workspace_data


def test_delete_workspace_data_removes_records_and_vectors(
    tmp_path: Path,
    monkeypatch,
) -> None:
    configure_database(tmp_path / "workspace-reset.sqlite3")
    monkeypatch.setattr(chroma, "_load_chroma_client", lambda: None)
    workspace_a = create_workspace("A", "workspace-reset-a", "development")
    workspace_b = create_workspace("B", "workspace-reset-b", "development")
    repo_a = bind_workspace(WorkspaceContext(workspace_a))
    repo_b = bind_workspace(WorkspaceContext(workspace_b))
    session_a = repo_a.create_session("user-a")
    session_b = repo_b.create_session("user-b")
    observation_a = repo_a.save_observation(session_a, "user", "A uses PostgreSQL.")
    observation_b = repo_b.save_observation(session_b, "user", "B uses MongoDB.")
    create_atomic_fact(
        {
            "workspace_id": workspace_a,
            "subject": "A",
            "predicate": "uses",
            "object": "PostgreSQL",
            "confidence": 0.9,
            "source_observation_id": observation_a,
        }
    )
    chroma.add_embedding(
        "observations",
        "observations",
        observation_a,
        [1.0, 0.0],
        workspace_id=workspace_a,
    )
    chroma.add_embedding(
        "observations",
        "observations",
        observation_b,
        [0.0, 1.0],
        workspace_id=workspace_b,
    )

    deleted = delete_workspace_data(workspace_a)

    assert deleted["sessions"] == 1
    assert deleted["observations"] == 1
    assert deleted["atomic_facts"] == 1
    assert get_workspace(workspace_a) is not None
    with repository_connection() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sessions WHERE workspace_id = ?",
                (workspace_a,),
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM observations WHERE workspace_id = ?",
                (workspace_b,),
            ).fetchone()[0]
            == 1
        )
    assert chroma.query_embeddings("observations", [1.0, 0.0], 5, workspace_id=workspace_a) == []
    assert chroma.query_embeddings("observations", [0.0, 1.0], 5, workspace_id=workspace_b)
