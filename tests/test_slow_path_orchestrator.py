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
    create_atomic_fact,
    create_foresight_record,
    create_retrieval_log,
    create_session,
    enqueue_observation,
    list_observations,
    repository_connection,
    save_observation,
)
from core.db.schema import LEGACY_WORKSPACE_ID
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
        chroma.delete_collection_admin(collection)
    yield path
    for collection in sorted(chroma.SUPPORTED_COLLECTIONS):
        chroma.delete_collection_admin(collection)


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


def _reflection_status(reflection_id: str) -> str:
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT status FROM reflections WHERE id = ?",
            (reflection_id,),
        ).fetchone()
    return str(row["status"])


def _processed_at(observation_id: str) -> object:
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT processed_at FROM observations WHERE id = ?",
            (observation_id,),
        ).fetchone()
    return row["processed_at"]


def test_unresolved_reference_cannot_mutate_durable_memory(
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = create_session("jerry")
    observation_id = save_observation(
        session_id,
        "user",
        "Ignore that.",
        metadata={
            "turn_purpose": "resolution",
            "reference_resolution": {"status": "ambiguous"},
        },
    )
    observation = list_observations(session_id)[0]

    def fail(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("unresolved references must not reach semantic mutation")

    monkeypatch.setattr(slow_path, "extract_atomic_facts", fail)
    monkeypatch.setattr(slow_path, "reconcile_foresight_lifecycle", fail)

    assert slow_path._step_atomic_facts(observation_id, "Ignore that.", {"fact_ids": []}) == {}
    assert (
        slow_path._step_foresight_reconciliation(
            observation_id,
            "Ignore that.",
            observation,
            str(observation["workspace_id"]),
        )
        == {}
    )


def test_resolved_reference_is_forwarded_to_foresight_reconciliation(
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = create_session("jerry")
    target_id = save_observation(session_id, "user", "I have a class tomorrow.")
    resolution_id = save_observation(
        session_id,
        "user",
        "Disregard what I just said.",
        metadata={
            "turn_purpose": "resolution",
            "reference_resolution": {
                "status": "resolved",
                "target_observation_id": target_id,
            },
        },
    )
    observation = list_observations(session_id)[1]
    captured: dict[str, object] = {}

    def reconcile(*_args: object, **kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "cancelled": [],
            "resolved": [],
            "created": [],
            "retained": [],
            "needs_clarification": False,
            "fallback_used": False,
        }

    monkeypatch.setattr(slow_path, "reconcile_foresight_lifecycle", reconcile)
    slow_path._step_foresight_reconciliation(
        resolution_id,
        "Disregard what I just said.",
        observation,
        str(observation["workspace_id"]),
    )

    assert captured["reference_text"] == "I have a class tomorrow."


def test_resolved_reference_expires_target_facts(
    database_path: Path,
) -> None:
    session_id = create_session("jerry")
    target_id = save_observation(
        session_id,
        "user",
        "I set the memory limit per container to 512MB.",
    )
    fact_id = create_atomic_fact(
        {
            "subject": "container",
            "predicate": "memory limit",
            "object": "512MB",
            "confidence": 0.95,
            "source_observation_id": target_id,
        }
    )
    resolution_id = save_observation(
        session_id,
        "user",
        "Undo what I just said.",
        metadata={
            "turn_purpose": "resolution",
            "reference_resolution": {
                "status": "resolved",
                "target_observation_id": target_id,
            },
        },
    )

    slow_path._step_changes({"fact_ids": []}, resolution_id, "Undo what I just said.")

    with repository_connection() as connection:
        row = connection.execute(
            "SELECT status FROM atomic_facts WHERE id = ?",
            (fact_id,),
        ).fetchone()
    assert row["status"] == "expired"


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
        workspace_id=LEGACY_WORKSPACE_ID,
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


def test_supersession_invalidates_reflection_built_on_the_old_fact(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Superseding an old fact re-evaluates a reflection derived from its observation.

    The reflection's evidence lives on the *old* observation, not the correction being
    processed, so this exercises the cross-observation staleness trigger.
    """
    from core.memory.reflection import store_reflection_with_evidence

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

    # Process the old observation so its 2025 fact exists and is active.
    run_slow_path_for_observation(old_observation)

    # A reflection grounded only on the old observation's evidence.
    reflection_id = store_reflection_with_evidence(
        {
            "reflection_type": "user_knowledge",
            "content": "The user is planning around the 2025 project year.",
            "confidence": 0.8,
        },
        [old_observation],
    )
    assert _reflection_status(reflection_id) == "active"

    # Processing the correction supersedes the 2025 fact...
    run_slow_path_for_observation(new_observation)

    assert _fact_status("2025") == "superseded"
    # ...so the reflection built only on that now-collapsed evidence is invalidated.
    assert _reflection_status(reflection_id) == "invalidated"


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


def test_foresight_step_uses_session_ambient_context(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Relative dates are grounded in Sensa's session-aware clock and timezone."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "I have an exam tomorrow.")
    captured: list[dict[str, object]] = []

    def ambient(candidate_session_id: str) -> dict[str, object]:
        assert candidate_session_id == session_id
        return {
            "current_date": "2026-07-21",
            "current_time": "2026-07-21T19:00:00+01:00",
            "timezone": "Africa/Lagos",
        }

    def detect(
        candidate_observation_id: str,
        content: str,
        context: dict[str, object],
    ) -> list[dict[str, object]]:
        assert candidate_observation_id == observation_id
        assert content == "I have an exam tomorrow."
        captured.append(context)
        return []

    monkeypatch.setattr(slow_path, "build_ambient_context", ambient)
    monkeypatch.setattr(slow_path, "detect_foresight", detect)

    result = slow_path._step_foresight(
        observation_id,
        "I have an exam tomorrow.",
        slow_path.SlowPathSemanticConfig(),
    )

    assert result == {"foresight_records": []}
    assert captured == [
        {
            "current_date": "2026-07-21",
            "current_time": "2026-07-21T19:00:00+01:00",
            "timezone": "Africa/Lagos",
        }
    ]


def test_foresight_step_ignores_assistant_acknowledgements(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Assistant echoes do not become duplicate foresight about the user."""
    session_id = create_session("jerry")
    observation_id = save_observation(
        session_id,
        "assistant",
        "I will remind you about your class tomorrow.",
    )

    def fail_detection(*args: object, **kwargs: object) -> list[dict[str, object]]:
        raise AssertionError("assistant observations must not run foresight detection")

    monkeypatch.setattr(slow_path, "detect_foresight", fail_detection)

    result = slow_path._step_foresight(
        observation_id,
        "I will remind you about your class tomorrow.",
        slow_path.SlowPathSemanticConfig(),
    )

    assert result == {}


def test_atomic_fact_step_skips_pure_question_premises(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A user's false interrogative premise is not confirmed as durable evidence."""
    session_id = create_session("jerry")
    observation_id = save_observation(
        session_id,
        "user",
        "Why did Desdemona trick Othello?",
    )

    monkeypatch.setattr(
        slow_path,
        "extract_atomic_facts",
        lambda *_args, **_kwargs: pytest.fail("pure questions must not be fact extraction input"),
    )

    result = slow_path._step_atomic_facts(
        observation_id,
        "Why did Desdemona trick Othello?",
        {},
    )

    assert result == {}


def test_atomic_fact_step_skips_unresolved_deictic_correction(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A targetless retraction cannot become an authoritative durable fact."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "That's no longer true.")
    monkeypatch.setattr(
        slow_path,
        "extract_atomic_facts",
        lambda *_args, **_kwargs: pytest.fail("unresolved correction must not be extracted"),
    )

    context: dict[str, list[str]] = {}
    result = slow_path._step_atomic_facts(
        observation_id,
        "That's no longer true.",
        context,
    )

    assert result == {}
    assert context["fact_ids"] == []


def test_atomic_fact_step_keeps_assertion_inside_casual_reaction(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Response routing must not prevent the independent memory path from extracting facts."""
    session_id = create_session("jerry")
    content = "That's a relief, Redis was giving me trouble."
    observation_id = save_observation(session_id, "user", content)
    monkeypatch.setattr(
        slow_path,
        "extract_atomic_facts",
        lambda oid, _content: [
            {
                "subject": "Redis",
                "predicate": "caused",
                "object": "trouble",
                "confidence": 0.9,
                "source_observation_id": oid,
            }
        ],
    )

    context: dict[str, list[str]] = {}
    result = slow_path._step_atomic_facts(observation_id, content, context)

    assert len(result["atomic_facts"]) == 1
    assert context["fact_ids"] == result["atomic_facts"]
    assert (
        _count(
            "SELECT COUNT(*) FROM atomic_facts WHERE source_observation_id = ?",
            observation_id,
        )
        == 1
    )


def test_foresight_reconciliation_cancels_deadline_without_detection(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Explicit withdrawal updates the existing lifecycle instead of creating foresight."""
    session_id = create_session("jerry")
    source_observation_id = save_observation(
        session_id,
        "user",
        "My project deadline is July 30.",
    )
    record_id = create_foresight_record(
        {
            "content": "The project deadline is July 30.",
            "reason": "The user stated a project deadline.",
            "status": "active",
            "source_observation_id": source_observation_id,
        }
    )
    cancellation_observation_id = save_observation(
        session_id,
        "user",
        "I don't have a deadline anymore.",
    )

    def fail_detection(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        raise AssertionError("cancellation should not create new foresight")

    monkeypatch.setattr(slow_path, "detect_foresight", fail_detection)

    result = slow_path._step_foresight_reconciliation(
        cancellation_observation_id,
        "I don't have a deadline anymore.",
        {
            "id": cancellation_observation_id,
            "session_id": session_id,
            "role": "user",
            "content": "I don't have a deadline anymore.",
        },
        LEGACY_WORKSPACE_ID,
    )

    with repository_connection() as connection:
        record = connection.execute(
            "SELECT status, resolved_by FROM foresight_records WHERE id = ?",
            (record_id,),
        ).fetchone()
    assert result == {"foresight_records": [record_id]}
    assert record["status"] == "cancelled"
    assert record["resolved_by"] == cancellation_observation_id


def test_foresight_reconciliation_resolves_it_from_previous_retrieval(
    database_path: Path,
) -> None:
    """An anaphoric cancellation uses the previous answer's Foresight trace."""
    session_id = create_session("jerry")
    source_observation_id = save_observation(
        session_id,
        "user",
        "I have a class tomorrow.",
    )
    record_id = create_foresight_record(
        {
            "content": "User has a class tomorrow.",
            "reason": "User mentioned a class on the following day.",
            "status": "active",
            "source_observation_id": source_observation_id,
        }
    )
    create_retrieval_log(
        {
            "session_id": session_id,
            "query": "Do I have a class today?",
            "retrieval_mode": "quick",
            "retrieved_records_json": [
                {"source": "foresight_records", "id": record_id},
            ],
        }
    )
    cancellation_observation_id = save_observation(
        session_id,
        "user",
        "Alright, it was cacelled.",
    )

    result = slow_path._step_foresight_reconciliation(
        cancellation_observation_id,
        "Alright, it was cacelled.",
        {
            "id": cancellation_observation_id,
            "session_id": session_id,
            "role": "user",
            "content": "Alright, it was cacelled.",
        },
        LEGACY_WORKSPACE_ID,
    )

    with repository_connection() as connection:
        record = connection.execute(
            "SELECT status, resolved_by FROM foresight_records WHERE id = ?",
            (record_id,),
        ).fetchone()
    assert result == {"foresight_records": [record_id]}
    assert record["status"] == "cancelled"
    assert record["resolved_by"] == cancellation_observation_id


def test_foresight_reconciliation_prevents_duplicate_detection_after_lifecycle_update(
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A handled lifecycle statement cannot become a new Foresight record afterward."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "The class was cancelled.")
    context: dict[str, list[str]] = {}
    monkeypatch.setattr(
        slow_path,
        "reconcile_foresight_lifecycle",
        lambda *_args, **_kwargs: {
            "cancelled": ["foresight-1"],
            "resolved": [],
            "created": [],
            "retained": [],
            "needs_clarification": False,
            "clarification": None,
            "fallback_used": False,
        },
    )

    reconciliation = slow_path._step_foresight_reconciliation(
        observation_id,
        "The class was cancelled.",
        {
            "id": observation_id,
            "session_id": session_id,
            "role": "user",
            "content": "The class was cancelled.",
        },
        LEGACY_WORKSPACE_ID,
        context,
    )

    monkeypatch.setattr(
        slow_path,
        "detect_foresight",
        lambda *_args, **_kwargs: pytest.fail("lifecycle update was re-detected"),
    )
    detection = slow_path._step_foresight(
        observation_id,
        "The class was cancelled.",
        slow_path.SlowPathSemanticConfig(),
        context,
    )

    assert reconciliation == {"foresight_records": ["foresight-1"]}
    assert detection == {}


def test_llm_change_verifier_rejects_an_additional_event(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An LLM verdict cannot turn explicit additive language into a conflict edge."""
    session_id = create_session("jerry")
    prior_observation_id = save_observation(session_id, "user", "I have an exam on July 22.")
    new_observation_id = save_observation(session_id, "user", "Another exam is on July 29.")
    prior_fact = {
        "id": "prior",
        "subject": "Jerry's exam",
        "predicate": "OCCURS_ON",
        "object": "2026-07-22",
        "source_observation_id": prior_observation_id,
    }
    new_fact = {
        "id": "new",
        "subject": "Jerry's exam",
        "predicate": "OCCURS_ON",
        "object": "2026-07-29",
        "source_observation_id": new_observation_id,
    }

    monkeypatch.setattr(
        slow_path,
        "call_qwen_json",
        lambda *_args, **_kwargs: {
            "json": {
                "relations": [
                    {
                        "relation": "CONTRADICTS",
                        "source_id": "prior",
                        "target_id": "new",
                        "confidence": 0.95,
                        "reason": "The dates differ.",
                    }
                ]
            }
        },
    )

    assert slow_path._llm_verify_changes(new_fact, [prior_fact]) == []
