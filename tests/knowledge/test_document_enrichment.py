"""Document upload, durable enrichment, and source retraction integration."""

from __future__ import annotations

import sqlite3

from core.db import chroma, repositories
from core.db.evidence import list_active_evidence
from core.db.repositories import create_knowledge_base, create_workspace
from core.knowledge.documents import delete_document, ingest_document
from core.knowledge.enrichment import run_document_enrichment_batch
from core.memory import graph
from core.retrieval.quick import _provenance_for_candidate
from core.retrieval.trust import assess_evidence, assess_provenance_completeness


class MemoryStorage:
    bucket = "test-documents"

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def upload(
        self, key: str, content: bytes, *, content_type: str, metadata: dict[str, str]
    ) -> None:
        self.objects[key] = content

    def download(self, key: str) -> bytes:
        return self.objects[key]

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)


def test_ready_document_enriches_then_retracts_without_fake_observation(
    tmp_path, monkeypatch
) -> None:
    database = tmp_path / "enrichment.sqlite"
    monkeypatch.setattr(repositories, "_DATABASE_PATH", database)
    monkeypatch.setattr(repositories, "_INITIALIZED_DATABASE_PATHS", set())
    monkeypatch.setattr(chroma, "_load_chroma_client", lambda: None)
    workspace_id = create_workspace("Project", "project-enrichment", "development")
    knowledge_base_id = create_knowledge_base("Project docs", workspace_id=workspace_id)
    monkeypatch.setenv("MIRA_DOCUMENT_ENRICHMENT_ENABLED", "true")
    monkeypatch.setenv("MIRA_DOCUMENT_ENRICHMENT_WORKSPACE_IDS", workspace_id)
    monkeypatch.setattr(
        "core.memory.atomic_fact.call_qwen_json",
        lambda *_args, **_kwargs: {
            "json": {
                "facts": [
                    {
                        "subject": "Prep AI",
                        "predicate": "uses",
                        "object": "PostgreSQL",
                        "evidence_span": "Prep AI uses PostgreSQL.",
                        "confidence": 0.9,
                    }
                ]
            }
        },
    )
    monkeypatch.setattr(
        graph,
        "extract_entities_from_source",
        lambda _text, *, workspace_id: [
            {
                "id": graph.canonicalize_entity("PostgreSQL", workspace_id=workspace_id),
                "name": "PostgreSQL",
            }
        ],
    )
    storage = MemoryStorage()
    document = ingest_document(
        workspace_id=workspace_id,
        knowledge_base_id=knowledge_base_id,
        filename="architecture.txt",
        content=b"Prep AI uses PostgreSQL.",
        storage=storage,
        embedder=lambda _text: [1.0, 0.0, 0.0],
    )
    document_id = str(document.document["id"])
    assert document.document["status"] == "ready"
    with sqlite3.connect(database) as connection:
        assert (
            connection.execute(
                "SELECT status FROM document_enrichment_jobs WHERE document_id = ?", (document_id,)
            ).fetchone()[0]
            == "pending"
        )

    assert run_document_enrichment_batch(limit=1)["processed"] == 1
    with sqlite3.connect(database) as connection:
        fact_id, observation_id = connection.execute(
            "SELECT id, source_observation_id FROM atomic_facts WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()
        assert observation_id is None
        assert (
            connection.execute(
                "SELECT status FROM document_enrichment_jobs WHERE document_id = ?", (document_id,)
            ).fetchone()[0]
            == "done"
        )
    evidence = list_active_evidence("atomic_fact", fact_id, workspace_id=workspace_id)
    assert len(evidence) == 1
    assert evidence[0]["source"]["provenance"]["document_id"] == document_id
    source_id = str(evidence[0]["source_id"])
    provenance = _provenance_for_candidate(
        "atomic_facts",
        {
            "source_id": fact_id,
            "record": {"workspace_id": workspace_id, "source_observation_id": None},
        },
    )
    assert provenance["evidence_source_ids"] == [source_id]
    assert provenance["sources"][0]["knowledge_base_id"] == knowledge_base_id
    assert "content" not in provenance["sources"][0]
    with sqlite3.connect(database) as connection:
        source_node = connection.execute(
            "SELECT id FROM graph_nodes WHERE workspace_id = ? "
            "AND source_table = 'document_chunks' AND source_id IN "
            "(SELECT id FROM document_chunks WHERE document_id = ?)",
            (workspace_id, document_id),
        ).fetchone()[0]
        entity_node = connection.execute(
            "SELECT id FROM graph_nodes WHERE workspace_id = ? AND source_table = 'entities' "
            "AND source_id IN (SELECT id FROM entities WHERE lower(name) = 'postgresql')",
            (workspace_id,),
        ).fetchone()[0]
        fact_node = connection.execute(
            "SELECT id FROM graph_nodes WHERE workspace_id = ? AND source_table = 'atomic_facts' "
            "AND source_id = ?",
            (workspace_id, fact_id),
        ).fetchone()[0]
        assert connection.execute(
            "SELECT 1 FROM graph_edges WHERE workspace_id = ? AND edge_type = 'MENTIONS' "
            "AND source_node_id = ? AND target_node_id = ? AND invalidated_at IS NULL",
            (workspace_id, source_node, entity_node),
        ).fetchone()
        derived_edge = connection.execute(
            "SELECT id FROM graph_edges WHERE workspace_id = ? AND edge_type = 'DERIVED_FROM' "
            "AND source_node_id = ? AND target_node_id = ? AND invalidated_at IS NULL",
            (workspace_id, fact_node, source_node),
        ).fetchone()
        assert derived_edge
    assert len(list_active_evidence("graph_edge", derived_edge[0], workspace_id=workspace_id)) == 1
    assert (
        list_active_evidence("graph_edge", derived_edge[0], workspace_id=workspace_id)[0][
            "source_id"
        ]
        == source_id
    )
    fact_record = {
        "id": fact_id,
        "workspace_id": workspace_id,
        "source_observation_id": None,
    }
    candidate = {"source": "atomic_facts", "record": fact_record, "status": "active"}
    assert assess_provenance_completeness(candidate)["complete"] is True
    assert assess_evidence(candidate)["provenance_complete"] is True

    delete_document(document_id, workspace_id=workspace_id, storage=storage)
    assert not storage.objects
    assert list_active_evidence("atomic_fact", fact_id, workspace_id=workspace_id) == []
    with sqlite3.connect(database) as connection:
        assert (
            connection.execute(
                "SELECT status FROM atomic_facts WHERE id = ?", (fact_id,)
            ).fetchone()[0]
            == "expired"
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
