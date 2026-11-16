"""Source-aware graph provenance and conservative document change semantics."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.db.evidence import (
    create_document_fact,
    list_active_evidence,
    register_source,
    retract_document_sources,
)
from core.db.repositories import configure_database, repository_connection
from core.memory.change import apply_contradiction, apply_supersession, detect_memory_change
from core.memory.graph import create_graph_edge, create_graph_node, find_edges_by_type

NOW = "2026-09-01T00:00:00+00:00"


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "source-graph.sqlite"
    configure_database(path)
    with repository_connection() as db:
        for workspace in ("one", "two"):
            db.execute(
                "INSERT INTO workspaces (id, name, slug, workspace_type, created_at, updated_at) "
                "VALUES (?, ?, ?, 'development', ?, ?)",
                (workspace, workspace, workspace, NOW, NOW),
            )
            for suffix in ("a", "b"):
                kb_id = f"kb-{workspace}-{suffix}"
                db.execute(
                    "INSERT INTO knowledge_bases "
                    "(id, workspace_id, name, status, created_at, updated_at) "
                    "VALUES (?, ?, ?, 'active', ?, ?)",
                    (kb_id, workspace, kb_id, NOW, NOW),
                )
    return path


def _document_source(
    workspace: str,
    suffix: str,
    content: str,
    *,
    kb_suffix: str = "a",
    authority: float = 1.0,
) -> str:
    document_id = f"document-{workspace}-{suffix}"
    chunk_id = f"chunk-{workspace}-{suffix}"
    kb_id = f"kb-{workspace}-{kb_suffix}"
    with repository_connection() as db:
        db.execute(
            "INSERT INTO documents (id, workspace_id, knowledge_base_id, filename, mime_type, "
            "size_bytes, s3_bucket, s3_key, checksum_sha256, status, created_at, updated_at) "
            "VALUES (?, ?, ?, 'policy.txt', 'text/plain', ?, 'bucket', ?, 'digest', "
            "'ready', ?, ?)",
            (document_id, workspace, kb_id, len(content), document_id, NOW, NOW),
        )
        db.execute(
            "INSERT INTO document_chunks (id, workspace_id, knowledge_base_id, document_id, "
            "chunk_index, content, created_at) VALUES (?, ?, ?, ?, 0, ?, ?)",
            (chunk_id, workspace, kb_id, document_id, content, NOW),
        )
    return register_source("document_chunk", chunk_id, workspace_id=workspace, authority=authority)


def _fact(
    source_id: str,
    value: str,
    *,
    workspace: str = "one",
    valid_from: str | None = None,
    valid_until: str | None = None,
) -> str:
    return create_document_fact(
        workspace,
        source_id,
        "Refund period",
        "lasts",
        value,
        0.9,
        valid_from=valid_from,
        valid_until=valid_until,
    )


def test_document_edge_has_normalized_provenance_without_fake_observation(database: Path) -> None:
    source = _document_source("one", "policy", "Refund period is 30 days.")
    left = create_graph_node("entity", "Refund period", workspace_id="one")
    right = create_graph_node("entity", "30 days", workspace_id="one")

    edge_id = create_graph_edge(
        left, right, "DERIVED_FROM", 0.8, workspace_id="one", evidence_source_ids=[source]
    )

    edge = find_edges_by_type("DERIVED_FROM", workspace_id="one")[0]
    assert edge["id"] == edge_id
    assert edge["source_observations"] == []
    assert edge["evidence_source_ids"] == [source]
    links = list_active_evidence("graph_edge", edge_id, workspace_id="one")
    assert [link["source"]["source_type"] for link in links] == ["document_chunk"]


def test_edge_rejects_cross_workspace_and_cross_kb_sources(database: Path) -> None:
    first = _document_source("one", "first", "Refund period is 30 days.")
    other_kb = _document_source("one", "other-kb", "Refund period is 14 days.", kb_suffix="b")
    other_workspace = _document_source("two", "other", "Refund period is 14 days.")
    left = create_graph_node("entity", "Refund period", workspace_id="one")
    right = create_graph_node("entity", "14 days", workspace_id="one")

    with pytest.raises(ValueError, match="knowledge bases"):
        create_graph_edge(
            left,
            right,
            "DERIVED_FROM",
            0.8,
            workspace_id="one",
            evidence_source_ids=[first, other_kb],
        )
    with pytest.raises(ValueError, match="workspace"):
        create_graph_edge(
            left,
            right,
            "DERIVED_FROM",
            0.8,
            workspace_id="one",
            evidence_source_ids=[other_workspace],
        )
    assert find_edges_by_type("DERIVED_FROM", workspace_id="one") == []


def test_document_conflict_stays_unresolved_even_when_uploaded_later(database: Path) -> None:
    old_source = _document_source("one", "old", "Refund period is 30 days.")
    new_source = _document_source("one", "new", "Refund period is 14 days.")
    old_fact = _fact(old_source, "30 days")
    new_fact = _fact(new_source, "14 days")

    changes = detect_memory_change(new_fact, [old_fact])
    assert len(changes) == 1
    assert changes[0]["relation"] == "CONTRADICTS"
    assert changes[0]["evidence"] == []
    assert changes[0]["evidence_source_ids"] == [old_source, new_source]
    with pytest.raises(ValueError, match="explicit transition"):
        apply_supersession(old_fact, new_fact, [])
    edge_id = apply_contradiction(old_fact, new_fact, [])
    assert len(list_active_evidence("graph_edge", edge_id, workspace_id="one")) == 2
    with repository_connection() as db:
        statuses = db.execute(
            "SELECT status FROM atomic_facts WHERE id IN (?, ?)", (old_fact, new_fact)
        ).fetchall()
    assert [row[0] for row in statuses] == ["active", "active"]


def test_retracting_contradiction_evidence_restores_confidence(database: Path) -> None:
    old_source = _document_source("one", "old", "Refund period is 30 days.")
    new_source = _document_source("one", "new", "Refund period is 14 days.")
    old_fact = _fact(old_source, "30 days")
    new_fact = _fact(new_source, "14 days")
    with repository_connection() as db:
        baseline = db.execute(
            "SELECT confidence FROM atomic_facts WHERE id = ?", (old_fact,)
        ).fetchone()[0]

    edge_id = apply_contradiction(old_fact, new_fact, [])
    with repository_connection() as db:
        reduced = db.execute(
            "SELECT confidence FROM atomic_facts WHERE id = ?", (old_fact,)
        ).fetchone()[0]
    assert reduced < baseline

    retract_document_sources("document-one-new", workspace_id="one")

    with repository_connection() as db:
        restored = db.execute(
            "SELECT confidence FROM atomic_facts WHERE id = ?", (old_fact,)
        ).fetchone()[0]
        invalidated_at = db.execute(
            "SELECT invalidated_at FROM graph_edges WHERE id = ?", (edge_id,)
        ).fetchone()[0]
    assert restored == pytest.approx(baseline)
    assert invalidated_at is not None


def test_explicit_document_transition_preserves_old_fact(database: Path) -> None:
    old_source = _document_source("one", "old", "Refund period was 30 days.")
    new_source = _document_source("one", "new", "Refund period changed from 30 days to 14 days.")
    old_fact = _fact(old_source, "30 days")
    new_fact = _fact(new_source, "14 days")

    changes = detect_memory_change(new_fact, [old_fact])
    assert [change["relation"] for change in changes] == ["SUPERSEDED_BY"]
    edge_id = apply_supersession(old_fact, new_fact, [])
    assert len(list_active_evidence("graph_edge", edge_id, workspace_id="one")) == 2
    with repository_connection() as db:
        old = db.execute(
            "SELECT status, valid_until FROM atomic_facts WHERE id = ?", (old_fact,)
        ).fetchone()
    assert old["status"] == "superseded"
    # Upload time does not establish the historical effective end of a policy.
    assert old["valid_until"] is None


def test_retracting_transition_source_reopens_old_fact_and_invalidates_relation(
    database: Path,
) -> None:
    old_source = _document_source("one", "old", "Refund period was 30 days.")
    new_source = _document_source("one", "new", "Refund period changed from 30 days to 14 days.")
    old_fact = _fact(old_source, "30 days")
    new_fact = _fact(new_source, "14 days")
    edge_id = apply_supersession(old_fact, new_fact, [])

    retract_document_sources("document-one-new", workspace_id="one")

    with repository_connection() as db:
        old = db.execute(
            "SELECT status, valid_until FROM atomic_facts WHERE id = ?", (old_fact,)
        ).fetchone()
        edge = db.execute(
            "SELECT invalidated_at FROM graph_edges WHERE id = ?", (edge_id,)
        ).fetchone()
    assert tuple(old) == ("active", None)
    assert edge["invalidated_at"] is not None


def test_lower_authority_document_cannot_supersede(database: Path) -> None:
    old_source = _document_source("one", "old", "Refund period was 30 days.", authority=1)
    new_source = _document_source(
        "one", "new", "Refund period changed from 30 days to 14 days.", authority=0.2
    )
    old_fact = _fact(old_source, "30 days")
    new_fact = _fact(new_source, "14 days")

    assert [change["relation"] for change in detect_memory_change(new_fact, [old_fact])] == [
        "CONTRADICTS"
    ]
    with pytest.raises(ValueError, match="explicit transition"):
        apply_supersession(old_fact, new_fact, [])


def test_document_claims_in_different_kbs_are_not_compared(database: Path) -> None:
    old_source = _document_source("one", "old", "Refund period is 30 days.")
    new_source = _document_source("one", "new", "Refund period is 14 days.", kb_suffix="b")
    old_fact = _fact(old_source, "30 days")
    new_fact = _fact(new_source, "14 days")

    assert detect_memory_change(new_fact, [old_fact]) == []
    with pytest.raises(ValueError, match="compatible claims"):
        apply_contradiction(old_fact, new_fact, [])


def test_distinct_validity_periods_do_not_imply_conflict(database: Path) -> None:
    old_source = _document_source("one", "old", "Refund period is 30 days in 2025.")
    new_source = _document_source("one", "new", "Refund period is 14 days in 2026.")
    old_fact = _fact(old_source, "30 days", valid_until="2025-12-31")
    new_fact = _fact(new_source, "14 days", valid_from="2026-01-01")

    assert detect_memory_change(new_fact, [old_fact]) == []
