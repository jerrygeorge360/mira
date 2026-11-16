"""Evidence migration, scope, idempotence, and durable job recovery."""

from __future__ import annotations

import json
import sqlite3

import pytest

from core.db.evidence import (
    cancel_document_jobs,
    claim_document_jobs,
    complete_document_job,
    create_conversation_fact,
    create_document_fact,
    enqueue_document_job,
    fail_document_job,
    link_evidence,
    list_active_evidence,
    reconcile_ready_document_jobs,
    register_source,
    retract_document_sources,
)
from core.db.repositories import (
    configure_database,
    create_atomic_fact,
    list_session_knowledge_base_ids,
    replace_session_knowledge_base_ids,
)
from core.db.schema import (
    INVALIDATED_RELATION_REPAIR_MIGRATION_ID,
    RELATION_ROLLBACK_MIGRATION_ID,
    initialize_database,
)
from core.evidence.source import resolve_source


@pytest.fixture
def database(tmp_path, monkeypatch):
    path = tmp_path / "evidence.sqlite"
    monkeypatch.setenv("MIRA_DB_PATH", str(path))
    configure_database(path)
    now = "2026-01-01T00:00:00+00:00"
    with sqlite3.connect(path) as db:
        for workspace in ("one", "two"):
            db.execute(
                "INSERT INTO workspaces (id, name, slug, workspace_type, created_at, updated_at) "
                "VALUES (?, ?, ?, 'development', ?, ?)",
                (workspace, workspace, workspace, now, now),
            )
            db.execute(
                "INSERT INTO sessions (id, workspace_id, user_id, status, created_at, updated_at) "
                "VALUES (?, ?, 'user', 'active', ?, ?)",
                (f"session-{workspace}", workspace, now, now),
            )
            db.execute(
                "INSERT INTO observations "
                "(id, workspace_id, session_id, role, content, created_at) "
                "VALUES (?, ?, ?, 'user', 'hello', ?)",
                (f"observation-{workspace}", workspace, f"session-{workspace}", now),
            )
            db.execute(
                "INSERT INTO knowledge_bases "
                "(id, workspace_id, name, status, created_at, updated_at) "
                "VALUES (?, ?, 'KB', 'active', ?, ?)",
                (f"kb-{workspace}", workspace, now, now),
            )
            db.execute(
                "INSERT INTO documents "
                "(id, workspace_id, knowledge_base_id, filename, mime_type, size_bytes, "
                "s3_bucket, s3_key, checksum_sha256, status, created_at, updated_at) "
                "VALUES (?, ?, ?, 'a.txt', 'text/plain', 4, 'bucket', 'key', "
                "'digest', 'ready', ?, ?)",
                (f"document-{workspace}", workspace, f"kb-{workspace}", now, now),
            )
            db.execute(
                "INSERT INTO document_chunks "
                "(id, workspace_id, knowledge_base_id, document_id, "
                "chunk_index, content, created_at) "
                "VALUES (?, ?, ?, ?, 0, 'text', ?)",
                (f"chunk-{workspace}", workspace, f"kb-{workspace}", f"document-{workspace}", now),
            )
    return path


def test_document_fact_retry_isolation_and_retraction(database):
    source = register_source("document_chunk", "chunk-one", workspace_id="one")
    assert register_source("document_chunk", "chunk-one", workspace_id="one") == source
    assert resolve_source(source, workspace_id="one")["content"] == "text"
    with pytest.raises(ValueError):
        resolve_source(source, workspace_id="two")
    with pytest.raises(ValueError):
        register_source("document_chunk", "chunk-one", workspace_id="two")
    fact = create_document_fact("one", source, "User", "likes", "Tea", 0.9)
    assert create_document_fact("one", source, "user", "likes", "tea", 0.9) == fact
    assert len(list_active_evidence("atomic_fact", fact, workspace_id="one")) == 1
    with pytest.raises(ValueError):
        link_evidence(source, "atomic_fact", fact, workspace_id="two")
    assert retract_document_sources("document-one", workspace_id="one")["atomic_facts"] == 1
    assert list_active_evidence("atomic_fact", fact, workspace_id="one") == []
    with sqlite3.connect(database) as db:
        row = db.execute(
            "SELECT source_observation_id FROM atomic_facts WHERE id = ?", (fact,)
        ).fetchone()
        assert row[0] is None
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_conversation_facts_get_normalized_multi_source_support(database):
    first = create_conversation_fact("observation-one", "MIRA", "uses", "SQLite", 0.9)
    with sqlite3.connect(database) as db:
        db.execute(
            "INSERT INTO observations "
            "(id, workspace_id, session_id, role, content, created_at) "
            "VALUES ('observation-one-restate', 'one', 'session-one', 'user', "
            "'MIRA uses SQLite', '2026-01-02T00:00:00+00:00')"
        )

    second = create_conversation_fact("observation-one-restate", "MIRA", "uses", "sqlite", 0.8)

    assert first == second
    evidence = list_active_evidence("atomic_fact", first, workspace_id="one")
    assert {item["source"]["source_id"] for item in evidence} == {
        "observation-one",
        "observation-one-restate",
    }
    assert all(item["source"]["source_type"] == "conversation_observation" for item in evidence)


def test_conversation_source_authority_uses_observation_role(database):
    with sqlite3.connect(database) as db:
        db.execute(
            "INSERT INTO observations "
            "(id, workspace_id, session_id, role, content, created_at) "
            "VALUES ('assistant-fact', 'one', 'session-one', 'assistant', 'assistant content', "
            "'2026-01-02T00:00:00+00:00')"
        )
        db.execute(
            "INSERT INTO observations "
            "(id, workspace_id, session_id, role, content, created_at) "
            "VALUES ('assistant-register', 'one', 'session-one', 'assistant', 'more content', "
            "'2026-01-03T00:00:00+00:00')"
        )

    create_conversation_fact("observation-one", "MIRA", "likes", "tea", 0.9)
    create_conversation_fact("assistant-fact", "MIRA", "uses", "SQLite", 0.8)
    register_source("conversation_observation", "assistant-register", workspace_id="one")

    with sqlite3.connect(database) as db:
        authority_by_observation = dict(
            db.execute(
                "SELECT source.source_id, source.authority FROM evidence_sources AS source "
                "WHERE source.source_type = 'conversation_observation'"
            ).fetchall()
        )
    assert authority_by_observation["observation-one"] == 0.95
    assert authority_by_observation["assistant-fact"] == 0.55
    assert authority_by_observation["assistant-register"] == 0.55


def test_legacy_relation_edges_receive_rollback_metadata(database):
    old_fact = create_atomic_fact(
        {
            "workspace_id": "one",
            "source_observation_id": "observation-one",
            "subject": "MIRA",
            "predicate": "uses",
            "object": "MongoDB",
            "confidence": 0.9,
            "status": "superseded",
        }
    )
    new_fact = create_atomic_fact(
        {
            "workspace_id": "one",
            "source_observation_id": "observation-one",
            "subject": "MIRA",
            "predicate": "uses",
            "object": "PostgreSQL",
            "confidence": 0.9,
        }
    )
    orphaned_prior_fact = create_atomic_fact(
        {
            "workspace_id": "one",
            "source_observation_id": "observation-one",
            "subject": "MIRA",
            "predicate": "uses",
            "object": "Redis",
            "confidence": 0.9,
            "status": "superseded",
        }
    )
    orphaned_current_fact = create_atomic_fact(
        {
            "workspace_id": "one",
            "source_observation_id": "observation-one",
            "subject": "MIRA",
            "predicate": "uses",
            "object": "Valkey",
            "confidence": 0.9,
        }
    )
    now = "2026-01-04T00:00:00+00:00"
    with sqlite3.connect(database) as db:
        for node_id, fact_id, label in (
            ("legacy-old-node", old_fact, "MIRA uses MongoDB"),
            ("legacy-new-node", new_fact, "MIRA uses PostgreSQL"),
            ("legacy-orphaned-old-node", orphaned_prior_fact, "MIRA uses Redis"),
            ("legacy-orphaned-new-node", orphaned_current_fact, "MIRA uses Valkey"),
        ):
            db.execute(
                "INSERT INTO graph_nodes "
                "(id, workspace_id, node_type, source_table, source_id, label, created_at) "
                "VALUES (?, 'one', 'fact', 'atomic_facts', ?, ?, ?)",
                (node_id, fact_id, label, now),
            )
        db.execute("UPDATE atomic_facts SET confidence = 0.63 WHERE id = ?", (old_fact,))
        db.execute("UPDATE atomic_facts SET confidence = 0.42 WHERE id = ?", (new_fact,))
        for edge_id, source_node_id, target_node_id, edge_type, invalidated_at in (
            ("legacy-supersession", "legacy-old-node", "legacy-new-node", "SUPERSEDED_BY", None),
            (
                "legacy-contradiction",
                "legacy-old-node",
                "legacy-new-node",
                "CONTRADICTS",
                now,
            ),
            (
                "legacy-invalidated-supersession",
                "legacy-orphaned-old-node",
                "legacy-orphaned-new-node",
                "SUPERSEDED_BY",
                now,
            ),
        ):
            db.execute(
                "INSERT INTO graph_edges "
                "(id, workspace_id, source_node_id, target_node_id, edge_type, confidence, "
                "source_observations_json, metadata_json, created_at, invalidated_at) "
                "VALUES (?, 'one', ?, ?, ?, 0.9, '[]', '{}', ?, ?)",
                (edge_id, source_node_id, target_node_id, edge_type, now, invalidated_at),
            )
        db.execute("DELETE FROM schema_migrations WHERE id = ?", (RELATION_ROLLBACK_MIGRATION_ID,))
        db.execute(
            "DELETE FROM schema_migrations WHERE id = ?",
            (INVALIDATED_RELATION_REPAIR_MIGRATION_ID,),
        )

    initialize_database(database)

    with sqlite3.connect(database) as db:
        metadata = {
            str(edge_id): json.loads(str(raw_metadata))
            for edge_id, raw_metadata in db.execute(
                "SELECT id, metadata_json FROM graph_edges WHERE id IN "
                "('legacy-supersession', 'legacy-contradiction', "
                "'legacy-invalidated-supersession')"
            ).fetchall()
        }
        fact_states = dict(
            db.execute(
                "SELECT id, status FROM atomic_facts WHERE id IN (?, ?, ?, ?)",
                (old_fact, new_fact, orphaned_prior_fact, orphaned_current_fact),
            ).fetchall()
        )
        confidence = dict(
            db.execute(
                "SELECT id, confidence FROM atomic_facts WHERE id IN (?, ?)",
                (old_fact, new_fact),
            ).fetchall()
        )
        migration_recorded = db.execute(
            "SELECT 1 FROM schema_migrations WHERE id = ?", (RELATION_ROLLBACK_MIGRATION_ID,)
        ).fetchone()
    assert metadata["legacy-supersession"]["supersession_rollback"] == {
        "fact_id": old_fact,
        "status": "active",
        "valid_until": None,
    }
    assert metadata["legacy-contradiction"]["contradiction_rollback"] == {
        "fact_ids": [old_fact, new_fact],
        "confidence_factor": 0.7,
    }
    assert metadata["legacy-invalidated-supersession"]["supersession_rollback"] == {
        "fact_id": orphaned_prior_fact,
        "status": "active",
        "valid_until": None,
    }
    assert fact_states[old_fact] == "superseded"
    assert fact_states[orphaned_prior_fact] == "active"
    assert confidence[old_fact] == pytest.approx(0.9)
    assert confidence[new_fact] == pytest.approx(0.6)
    assert migration_recorded is not None


def test_invalidated_relation_repair_runs_after_existing_rollback_migration(database):
    old_fact = create_atomic_fact(
        {
            "workspace_id": "one",
            "source_observation_id": "observation-one",
            "subject": "MIRA",
            "predicate": "uses",
            "object": "Cassandra",
            "confidence": 0.9,
            "status": "superseded",
        }
    )
    new_fact = create_atomic_fact(
        {
            "workspace_id": "one",
            "source_observation_id": "observation-one",
            "subject": "MIRA",
            "predicate": "uses",
            "object": "CockroachDB",
            "confidence": 0.9,
        }
    )
    now = "2026-01-05T00:00:00+00:00"
    with sqlite3.connect(database) as db:
        for node_id, fact_id in (("upgrade-old-node", old_fact), ("upgrade-new-node", new_fact)):
            db.execute(
                "INSERT INTO graph_nodes "
                "(id, workspace_id, node_type, source_table, source_id, label, created_at) "
                "VALUES (?, 'one', 'fact', 'atomic_facts', ?, 'claim', ?)",
                (node_id, fact_id, now),
            )
        db.execute(
            "INSERT INTO graph_edges "
            "(id, workspace_id, source_node_id, target_node_id, edge_type, confidence, "
            "source_observations_json, metadata_json, created_at, invalidated_at) "
            "VALUES ('upgrade-invalidated-relation', 'one', 'upgrade-old-node', "
            "'upgrade-new-node', 'SUPERSEDED_BY', 0.9, '[]', '{}', ?, ?)",
            (now, now),
        )
        db.execute("UPDATE atomic_facts SET confidence = 0.9 WHERE id = ?", (old_fact,))
        db.execute("UPDATE atomic_facts SET confidence = 0.8 WHERE id = ?", (new_fact,))
        db.execute(
            "INSERT INTO graph_edges "
            "(id, workspace_id, source_node_id, target_node_id, edge_type, confidence, "
            "source_observations_json, metadata_json, created_at, invalidated_at) "
            "VALUES ('upgrade-restored-contradiction', 'one', 'upgrade-old-node', "
            "'upgrade-new-node', 'CONTRADICTS', 0.9, '[]', ?, ?, ?)",
            (
                json.dumps(
                    {
                        "contradiction_rollback": {
                            "fact_ids": [old_fact, new_fact],
                            "confidence_factor": 0.7,
                        }
                    }
                ),
                now,
                now,
            ),
        )
        db.execute(
            "INSERT OR IGNORE INTO schema_migrations (id, applied_at) VALUES (?, ?)",
            (RELATION_ROLLBACK_MIGRATION_ID, now),
        )
        db.execute(
            "DELETE FROM schema_migrations WHERE id = ?",
            (INVALIDATED_RELATION_REPAIR_MIGRATION_ID,),
        )

    initialize_database(database)

    with sqlite3.connect(database) as db:
        fact_status = db.execute(
            "SELECT status FROM atomic_facts WHERE id = ?", (old_fact,)
        ).fetchone()[0]
        confidence = dict(
            db.execute(
                "SELECT id, confidence FROM atomic_facts WHERE id IN (?, ?)",
                (old_fact, new_fact),
            ).fetchall()
        )
        metadata = json.loads(
            db.execute(
                "SELECT metadata_json FROM graph_edges WHERE id = 'upgrade-invalidated-relation'"
            ).fetchone()[0]
        )
    assert fact_status == "active"
    assert confidence[old_fact] == pytest.approx(0.9)
    assert confidence[new_fact] == pytest.approx(0.8)
    assert metadata["supersession_rollback"]["fact_id"] == old_fact


def test_shared_support_survives_one_document_retraction(database):
    with sqlite3.connect(database) as db:
        now = "2026-01-01T00:00:00+00:00"
        db.execute(
            "INSERT INTO document_chunks "
            "(id, workspace_id, knowledge_base_id, document_id, "
            "chunk_index, content, created_at) "
            "VALUES ('chunk-one-b', 'one', 'kb-one', 'document-one', 1, 'text 2', ?)",
            (now,),
        )
    first = register_source("document_chunk", "chunk-one", workspace_id="one")
    second = register_source("document_chunk", "chunk-one-b", workspace_id="one")
    fact = create_document_fact("one", first, "user", "likes", "tea", 0.8)
    assert create_document_fact("one", second, "user", "likes", "tea", 0.8) == fact
    assert len(list_active_evidence("atomic_fact", fact, workspace_id="one")) == 2


def test_document_reinforces_conversation_fact_without_fake_observation(database):
    observation_source = register_source(
        "conversation_observation", "observation-one", workspace_id="one"
    )
    fact = create_atomic_fact(
        {
            "workspace_id": "one",
            "source_observation_id": "observation-one",
            "subject": "user",
            "predicate": "likes",
            "object": "tea",
            "confidence": 0.8,
        }
    )
    link_evidence(observation_source, "atomic_fact", fact, workspace_id="one")
    replace_session_knowledge_base_ids("session-one", ["kb-one"], workspace_id="one")
    document_source = register_source("document_chunk", "chunk-one", workspace_id="one")

    assert create_document_fact("one", document_source, "user", "likes", "tea", 0.9) == fact
    evidence = list_active_evidence("atomic_fact", fact, workspace_id="one")
    assert {item["source"]["source_type"] for item in evidence} == {
        "conversation_observation",
        "document_chunk",
    }
    assert retract_document_sources("document-one", workspace_id="one")["atomic_facts"] == 0
    with sqlite3.connect(database) as db:
        row = db.execute(
            "SELECT source_observation_id, status FROM atomic_facts WHERE id = ?", (fact,)
        ).fetchone()
    assert row == ("observation-one", "active")
    assert len(list_active_evidence("atomic_fact", fact, workspace_id="one")) == 1


def test_document_does_not_merge_into_conversation_memory_without_attachment(database):
    observation_source = register_source(
        "conversation_observation", "observation-one", workspace_id="one"
    )
    fact = create_atomic_fact(
        {
            "workspace_id": "one",
            "source_observation_id": "observation-one",
            "subject": "user",
            "predicate": "likes",
            "object": "tea",
            "confidence": 0.8,
        }
    )
    link_evidence(observation_source, "atomic_fact", fact, workspace_id="one")
    document_source = register_source("document_chunk", "chunk-one", workspace_id="one")

    separate_fact = create_document_fact("one", document_source, "user", "likes", "tea", 0.9)

    assert separate_fact != fact
    assert [
        item["source"]["source_type"]
        for item in list_active_evidence("atomic_fact", fact, workspace_id="one")
    ] == ["conversation_observation"]


def test_session_kb_attachment_repository_is_workspace_scoped(database):
    assert replace_session_knowledge_base_ids("session-one", ["kb-one"], workspace_id="one") == [
        "kb-one"
    ]
    assert list_session_knowledge_base_ids("session-one", workspace_id="one") == ["kb-one"]
    with pytest.raises(ValueError, match="not found"):
        replace_session_knowledge_base_ids("session-one", ["kb-two"], workspace_id="one")


def test_job_claims_retries_and_reconciliation(database):
    job = enqueue_document_job("document-one", workspace_id="one")
    assert enqueue_document_job("document-one", workspace_id="one") == job
    assert reconcile_ready_document_jobs(eligible_workspace_ids=["one"]) == 0
    assert reconcile_ready_document_jobs(eligible_workspace_ids=["two"]) == 1
    claims = claim_document_jobs(2, worker_id="worker")
    assert {item["id"] for item in claims} == {job, claims[1]["id"]}
    assert all(item["attempts"] == 1 for item in claims)
    with pytest.raises(ValueError):
        complete_document_job(job, workspace_id="two")
    fail_document_job(job, workspace_id="one", error_message="transient")
    with sqlite3.connect(database) as db:
        db.execute(
            "UPDATE document_enrichment_jobs SET available_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00+00:00", job),
        )
    retry = claim_document_jobs(1, worker_id="worker-2")[0]
    assert retry["id"] == job and retry["attempts"] == 2
    with sqlite3.connect(database) as db:
        db.execute(
            "UPDATE document_enrichment_jobs SET lease_until = ? WHERE id = ?",
            ("2000-01-01T00:00:00+00:00", job),
        )
    stale = claim_document_jobs(1, worker_id="worker-3")[0]
    assert stale["id"] == job and stale["attempts"] == 3
    complete_document_job(job, workspace_id="one")
    assert cancel_document_jobs("document-two", workspace_id="two") == 1


def test_legacy_nullable_upgrade_preserves_rows_and_backfills(database):
    with sqlite3.connect(database) as db:
        db.execute("PRAGMA foreign_keys = OFF")
        # Simulate a pre-migration database: the old tables predate evidence
        # ownership triggers, which otherwise block this fixture's rebuild.
        for (trigger,) in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'"
        ).fetchall():
            db.execute(f'DROP TRIGGER "{trigger}"')
        db.execute("DELETE FROM schema_migrations WHERE id = '0007_unified_evidence'")
        db.execute(
            "INSERT INTO atomic_facts "
            "(id, workspace_id, subject, predicate, object, confidence, "
            "source_observation_id, created_at) "
            "VALUES ('old-fact', 'one', 'user', 'likes', 'tea', .8, "
            "'observation-one', '2026-01-01')"
        )
        db.execute(
            "INSERT INTO foresight_records "
            "(id, workspace_id, content, status, source_observation_id, "
            "created_at, updated_at) "
            "VALUES ('old-foresight', 'one', 'plan', 'active', "
            "'observation-one', '2026-01-01', '2026-01-01')"
        )
        for table in ("atomic_facts", "foresight_records"):
            ddl = db.execute("SELECT sql FROM sqlite_master WHERE name = ?", (table,)).fetchone()[0]
            ddl = ddl.replace(f"CREATE TABLE {table}", f"CREATE TABLE {table}_old")
            ddl = ddl.replace("source_observation_id TEXT,", "source_observation_id TEXT NOT NULL,")
            db.execute(ddl)
            columns = [row[1] for row in db.execute(f"PRAGMA table_info({table})")]
            names = ", ".join(f'"{name}"' for name in columns)
            db.execute(f"INSERT INTO {table}_old ({names}) SELECT {names} FROM {table}")
            db.execute(f"DROP TABLE {table}")
            db.execute(f"ALTER TABLE {table}_old RENAME TO {table}")
    initialize_database(database)
    initialize_database(database)
    with sqlite3.connect(database) as db:
        assert (
            db.execute("SELECT COUNT(*) FROM atomic_facts WHERE id = 'old-fact'").fetchone()[0] == 1
        )
        assert (
            db.execute(
                "SELECT COUNT(*) FROM evidence_links WHERE target_id = 'old-fact'"
            ).fetchone()[0]
            == 1
        )
        assert (
            db.execute(
                "SELECT COUNT(*) FROM evidence_links WHERE target_id = 'old-foresight'"
            ).fetchone()[0]
            == 1
        )
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
