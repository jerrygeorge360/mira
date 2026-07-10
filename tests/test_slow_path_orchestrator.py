"""Verify ISSUE-121 automatic slow-path orchestrator chain.

Ownership: MIRA contributors.
Related issue: ISSUE-121.
Architecture area: slow path.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from core.db import chroma
from core.db.repositories import (
    configure_database,
    create_session,
    enqueue_observation,
    repository_connection,
    save_observation,
)
from core.memory import slow_path
from core.memory.graph import canonicalize_entity, find_edges_by_type
from core.memory.slow_path import run_slow_path_batch, run_slow_path_for_observation


@pytest.fixture
def database_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Configure the orchestrator tests to use an isolated database."""
    path = tmp_path / "mira.sqlite3"
    monkeypatch.setenv("CHROMA_DB_PATH", str(tmp_path / "chroma"))
    monkeypatch.setenv("EMBEDDING_MODE", "deterministic")
    configure_database(path)
    for collection in sorted(chroma.SUPPORTED_COLLECTIONS):
        chroma.delete_collection(collection)
    yield path
    for collection in sorted(chroma.SUPPORTED_COLLECTIONS):
        chroma.delete_collection(collection)


def _count(query: str, *params: object) -> int:
    with repository_connection() as connection:
        row = connection.execute(query, params).fetchone()
    return int(row[0])


def _queue_status(observation_id: str) -> str:
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT status FROM slow_path_queue WHERE observation_id = ?",
            (observation_id,),
        ).fetchone()
    return str(row["status"])


def _fact_status(object_value: str) -> str:
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT status FROM atomic_facts WHERE object = ?",
            (object_value,),
        ).fetchone()
    return str(row["status"])


def _processed_at(observation_id: str) -> object:
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT processed_at FROM observations WHERE id = ?",
            (observation_id,),
        ).fetchone()
    return row["processed_at"]


def test_orchestrator_processes_queued_observation(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One orchestrator call turns a queued observation into durable memory."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "Jerry prefers the TypeScript backend.")
    enqueue_observation(observation_id)
    entity_id = canonicalize_entity("TypeScript")

    monkeypatch.setattr(
        slow_path,
        "extract_atomic_facts",
        lambda oid, content: [
            {
                "subject": "Jerry",
                "predicate": "PREFERS",
                "object": "TypeScript",
                "confidence": 0.9,
                "source_observation_id": oid,
            }
        ],
    )
    monkeypatch.setattr(
        slow_path,
        "extract_entities",
        lambda text: [
            {"id": entity_id, "name": "TypeScript", "entity_type": "technology", "aliases": []}
        ],
    )

    results = run_slow_path_batch(10)

    assert len(results) == 1
    assert results[0]["succeeded"] is True
    assert (
        _count("SELECT COUNT(*) FROM atomic_facts WHERE source_observation_id = ?", observation_id)
        == 1
    )
    assert (
        _count(
            "SELECT COUNT(*) FROM graph_nodes WHERE node_type = 'entity' AND source_id = ?",
            entity_id,
        )
        == 1
    )
    assert len(find_edges_by_type("MENTIONS")) == 1
    assert _queue_status(observation_id) == "done"
    vector_results = chroma.query_embeddings(
        "observations",
        slow_path.embed_text("Jerry prefers the TypeScript backend."),
        top_k=1,
    )
    assert vector_results[0]["sqlite_id"] == observation_id


def test_orchestrator_records_supersession(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A corrected value supersedes the old one through the orchestrator."""
    session_id = create_session("jerry")
    old_observation = save_observation(session_id, "user", "The project year is 2025.")
    new_observation = save_observation(
        session_id, "user", "The project year is now 2030, not 2025 anymore."
    )
    enqueue_observation(old_observation)
    enqueue_observation(new_observation)

    def _facts(observation_id: str, content: str) -> list[dict[str, object]]:
        year = "2030" if "2030" in content else "2025"
        return [
            {
                "subject": "project year",
                "predicate": "IS",
                "object": year,
                "confidence": 0.9,
                "source_observation_id": observation_id,
            }
        ]

    monkeypatch.setattr(slow_path, "extract_atomic_facts", _facts)
    monkeypatch.setattr(slow_path, "extract_entities", lambda text: [])

    run_slow_path_for_observation(old_observation)
    run_slow_path_for_observation(new_observation)

    assert _fact_status("2030") == "active"
    assert _fact_status("2025") == "superseded"  # superseded, not deleted
    assert _count("SELECT COUNT(*) FROM atomic_facts WHERE object = '2025'") == 1
    edges = find_edges_by_type("SUPERSEDED_BY")
    assert len(edges) == 1


def test_preference_correction_records_supersession(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A direct preference correction supersedes the prior preference fact."""
    session_id = create_session("jerry")
    old_observation = save_observation(session_id, "user", "I prefer Python.")
    new_observation = save_observation(session_id, "user", "Actually I prefer Rust.")

    def _facts(observation_id: str, content: str) -> list[dict[str, object]]:
        language = "Rust" if "Rust" in content else "Python"
        return [
            {
                "subject": "user",
                "predicate": "prefers",
                "object": language,
                "confidence": 0.9,
                "source_observation_id": observation_id,
            }
        ]

    monkeypatch.setattr(slow_path, "extract_atomic_facts", _facts)
    monkeypatch.setattr(slow_path, "extract_entities", lambda text: [])

    run_slow_path_for_observation(old_observation)
    run_slow_path_for_observation(new_observation)

    assert _fact_status("Rust") == "active"
    assert _fact_status("Python") == "superseded"
    edges = find_edges_by_type("SUPERSEDED_BY")
    assert len(edges) == 1


def test_failed_step_marks_queue_failed_and_retry_is_idempotent(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failing step fails the queue item, stays retryable, and does not duplicate records."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "Jerry prefers Rust now.")
    enqueue_observation(observation_id)

    monkeypatch.setattr(
        slow_path,
        "extract_atomic_facts",
        lambda oid, content: [
            {
                "subject": "Jerry",
                "predicate": "PREFERS",
                "object": "Rust",
                "confidence": 0.9,
                "source_observation_id": oid,
            }
        ],
    )
    monkeypatch.setattr(slow_path, "extract_entities", lambda text: [])

    real_evaluate = slow_path.evaluate_promotion_candidate
    calls = {"n": 0}

    def _flaky(record_type: str, record_id: str) -> dict[str, object]:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("tier boom")
        return real_evaluate(record_type, record_id)

    monkeypatch.setattr(slow_path, "evaluate_promotion_candidate", _flaky)

    # First run: the tier step fails after the fact was created.
    results = run_slow_path_batch(10)
    assert results[0]["succeeded"] is False
    assert "tier boom" in str(results[0]["error_message"])
    assert _queue_status(observation_id) == "failed"
    assert (
        _count("SELECT COUNT(*) FROM atomic_facts WHERE source_observation_id = ?", observation_id)
        == 1
    )
    assert _processed_at(observation_id) is None  # retryable

    # Retry: succeeds without duplicating the already-created fact.
    retry = run_slow_path_for_observation(observation_id)
    assert retry["succeeded"] is True
    assert (
        _count("SELECT COUNT(*) FROM atomic_facts WHERE source_observation_id = ?", observation_id)
        == 1
    )
    assert _processed_at(observation_id) is not None


def test_llm_verify_changes_validates_ids_and_confidence(monkeypatch: pytest.MonkeyPatch) -> None:
    """The LLM verifier keeps only valid, confident verdicts and uses observation evidence."""
    fact = {
        "id": "new",
        "subject": "project deadline",
        "predicate": "is",
        "object": "Monday",
        "source_observation_id": "obs_new",
    }
    candidates = [
        {
            "id": "cand",
            "subject": "project",
            "predicate": "has deadline",
            "object": "Friday",
            "source_observation_id": "obs_cand",
        }
    ]

    def _fake(messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
        assert schema_name == "contradiction_supersession_detection"
        return {
            "json": {
                "relations": [
                    {
                        "relation": "CONTRADICTS",
                        "source_id": "cand",
                        "target_id": "new",
                        "confidence": 0.9,
                        "reason": "conflicting dates",
                    },
                    {
                        "relation": "CONTRADICTS",
                        "source_id": "ghost",
                        "target_id": "new",
                        "confidence": 0.9,
                    },  # unknown id -> filtered
                    {
                        "relation": "CONTRADICTS",
                        "source_id": "cand",
                        "target_id": "new",
                        "confidence": 0.1,
                    },  # below gate -> filtered
                ]
            }
        }

    monkeypatch.setattr(slow_path, "call_qwen_json", _fake)

    changes = slow_path._llm_verify_changes(fact, candidates)

    assert len(changes) == 1
    assert changes[0]["relation"] == "CONTRADICTS"
    assert (changes[0]["source_id"], changes[0]["target_id"]) == ("cand", "new")
    assert changes[0]["evidence"] == ["obs_cand", "obs_new"]


def test_agent_self_facts_keeps_only_assistant_attributed() -> None:
    """A non-user turn contributes only agent self-facts; echoes and world facts are dropped."""
    facts = [
        {"subject": "You", "predicate": "prefers", "object": "Rust"},  # echo of the user
        {"subject": "I", "predicate": "will use", "object": "PostgreSQL"},  # agent commitment
        {"subject": "the assistant", "predicate": "keeps", "object": "answers concise"},
        {"subject": "PostgreSQL", "predicate": "is", "object": "a database"},  # third-party
    ]

    kept = slow_path._agent_self_facts(facts)

    # Self-reference ("I", "the assistant") is re-attributed to the assistant.
    assert [fact["subject"] for fact in kept] == ["assistant", "assistant"]
    assert {str(fact["object"]) for fact in kept} == {"PostgreSQL", "answers concise"}
    # The user echo and the third-party/world assertion are dropped.
    assert all(str(fact["object"]) not in {"Rust", "a database"} for fact in kept)
