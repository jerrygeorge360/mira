"""Verify the ISSUE-034 Quick Mode direct retrieval path.

Ownership: MIRA contributors.
Related issue: ISSUE-034.
Architecture area: retrieval.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from core.db.repositories import (
    configure_database,
    create_atomic_fact,
    create_foresight_record,
    create_session,
    save_observation,
)
from core.retrieval.quick import (
    _rank_candidates,
    _semantic_record_is_active,
    retrieve_quick,
)


@pytest.fixture
def database_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Configure Quick Mode tests to use an isolated SQLite database."""
    path = tmp_path / "mira.sqlite3"
    monkeypatch.setenv("CHROMA_DB_PATH", str(tmp_path / "chroma"))
    monkeypatch.setenv("EMBEDDING_MODE", "deterministic")
    configure_database(path)
    yield path


def test_chromadb_question_retrieves_relevant_observation_and_fact(database_path: Path) -> None:
    """Specific prior-statement questions retrieve source-backed observations and facts."""
    session_id = create_session("jerry")
    observation_id = save_observation(
        session_id,
        "user",
        "I said ChromaDB is only a vector index, not the source of truth.",
    )
    fact_id = create_atomic_fact(
        {
            "subject": "ChromaDB",
            "predicate": "IS",
            "object": "vector index only",
            "confidence": 0.92,
            "source_observation_id": observation_id,
        }
    )

    results = retrieve_quick("What did I say about ChromaDB?", session_id, limit=5)

    source_ids = {str(result["source_id"]) for result in results}
    assert observation_id in source_ids
    assert fact_id in source_ids
    assert all("content" in result for result in results)


def test_retracted_observation_is_not_returned_as_current_evidence(database_path: Path) -> None:
    session_id = create_session("jerry")
    target_id = save_observation(
        session_id,
        "user",
        "I set the memory limit per container to 512MB.",
    )
    save_observation(
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

    results = retrieve_quick("What is my container memory limit?", session_id, limit=5)

    assert target_id not in {str(result["source_id"]) for result in results}


def test_deadline_question_retrieves_foresight_and_fact(database_path: Path) -> None:
    """Deadline questions retrieve active foresight and atomic fact evidence."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "My deadline is Friday.")
    fact_id = create_atomic_fact(
        {
            "subject": "deadline",
            "predicate": "IS",
            "object": "Friday",
            "confidence": 0.88,
            "source_observation_id": observation_id,
        }
    )
    foresight_id = create_foresight_record(
        {
            "content": "Deadline is Friday.",
            "reason": "User stated the deadline directly.",
            "status": "active",
            "source_observation_id": observation_id,
        }
    )

    results = retrieve_quick("When is my deadline?", session_id, limit=5)

    source_ids = {str(result["source_id"]) for result in results}
    assert fact_id in source_ids
    assert foresight_id in source_ids


def test_time_sensitive_question_retrieves_foresight_without_keyword_overlap(
    database_path: Path,
) -> None:
    """Time-sensitive queries retrieve active foresight even when wording differs."""
    session_id = create_session("jerry")
    observation_id = save_observation(
        session_id,
        "user",
        "The hackathon submission closes on Friday.",
    )
    foresight_id = create_foresight_record(
        {
            "content": "Hackathon submission closes on Friday.",
            "reason": "User stated an upcoming submission cutoff.",
            "status": "active",
            "source_observation_id": observation_id,
        }
    )

    results = retrieve_quick("Anything time-sensitive I should remember?", session_id, limit=5)

    matching = [result for result in results if result["source_id"] == foresight_id]
    assert matching
    assert matching[0]["source"] == "foresight_records"


def test_foresight_is_retrieved_across_sessions_in_same_workspace(database_path: Path) -> None:
    """Foresight is durable workspace memory, not local to its source session."""
    source_session_id = create_session("jerry")
    query_session_id = create_session("jerry")
    observation_id = save_observation(
        source_session_id,
        "user",
        "I have a class tomorrow.",
    )
    foresight_id = create_foresight_record(
        {
            "content": "User has a class tomorrow.",
            "reason": "User mentioned a class on the following day.",
            "status": "active",
            "source_observation_id": observation_id,
        }
    )

    results = retrieve_quick("Do I have a class?", query_session_id, limit=5)

    assert foresight_id in {str(result["source_id"]) for result in results}


def test_assistant_foresight_is_not_used_as_user_memory(database_path: Path) -> None:
    """An assistant acknowledgement is not independent evidence about the user."""
    source_session_id = create_session("jerry")
    query_session_id = create_session("jerry")
    observation_id = save_observation(
        source_session_id,
        "assistant",
        "I will remind you about your class tomorrow.",
    )
    foresight_id = create_foresight_record(
        {
            "content": "Remind the user about their class tomorrow.",
            "reason": "Assistant acknowledged the user's class.",
            "status": "active",
            "source_observation_id": observation_id,
        }
    )

    results = retrieve_quick("Do I have a class?", query_session_id, limit=5)

    assert foresight_id not in {str(result["source_id"]) for result in results}


def test_quick_retrieval_drops_current_question_and_unrelated_keyword_noise(
    database_path: Path,
) -> None:
    """Auxiliary words do not admit unrelated facts or the query observation itself."""
    session_id = create_session("jerry")
    question_id = save_observation(session_id, "user", "Do I have a class?")
    unrelated_observation_id = save_observation(
        session_id,
        "user",
        "The Holocaust was a genocide.",
    )
    unrelated_fact_id = create_atomic_fact(
        {
            "subject": "the Holocaust",
            "predicate": "is",
            "object": "a genocide",
            "confidence": 0.95,
            "source_observation_id": unrelated_observation_id,
        }
    )

    results = retrieve_quick("Do I have a class?", session_id, limit=8)
    source_ids = {str(result["source_id"]) for result in results}

    assert question_id not in source_ids
    assert unrelated_fact_id not in source_ids


def test_quick_retrieval_uses_assistant_history_only_when_explicitly_requested(
    database_path: Path,
) -> None:
    """Previous model output is not evidence about the user unless directly requested."""
    session_id = create_session("jerry")
    assistant_id = save_observation(
        session_id,
        "assistant",
        "I previously said your class starts at nine.",
    )

    user_memory_results = retrieve_quick("Do I have a class?", session_id, limit=8)
    assistant_history_results = retrieve_quick(
        "What did you say about my class?",
        session_id,
        limit=8,
    )

    assert assistant_id not in {str(result["source_id"]) for result in user_memory_results}
    assert assistant_id in {str(result["source_id"]) for result in assistant_history_results}


def test_duplicates_are_merged_by_source_id(database_path: Path) -> None:
    """The same observation from keyword and recent sources is returned once."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "ChromaDB stores vector pointers.")

    results = retrieve_quick("ChromaDB vector pointers", session_id, limit=5)
    matching_results = [result for result in results if result["source_id"] == observation_id]

    assert len(matching_results) == 1
    assert set(matching_results[0]["sources"]) == {"observations", "recent_observations"}
    assert matching_results[0]["score"] > 0


def test_invalid_limit_is_rejected() -> None:
    """Quick retrieval requires a positive result limit."""
    with pytest.raises(ValueError, match="limit"):
        retrieve_quick("anything", session_id=None, limit=0)


def test_structured_first_ranks_fact_above_observation() -> None:
    """With comparable relevance, a validated fact outranks a raw observation (fallback)."""
    candidates = [
        {
            "source": "observations",
            "source_id": "obs1",
            "content": "I prefer Python",
            "semantic_score": 0.7,
            "keyword_score": 0.0,
            "recency_score": 0.5,
            "confidence": 1.0,
            "status": "active",
        },
        {
            "source": "atomic_facts",
            "source_id": "fact1",
            "content": "user prefers Rust",
            "semantic_score": 0.0,
            "keyword_score": 0.7,
            "recency_score": 0.5,
            "confidence": 0.9,
            "status": "active",
        },
    ]

    ranked = _rank_candidates([dict(candidate) for candidate in candidates])

    # Both are top of their own retriever (equal RRF), so the source weight decides:
    # the atomic fact wins; the raw observation is retained as fallback, ranked below.
    assert ranked[0]["source"] == "atomic_facts"
    assert ranked[1]["source"] == "observations"


def test_semantic_retrieval_drops_non_active_reflections() -> None:
    """Stale/invalidated reflections are excluded; observations remain (immutable evidence)."""
    assert _semantic_record_is_active("reflections", {"status": "active"}) is True
    assert _semantic_record_is_active("reflections", {"status": "stale"}) is False
    assert _semantic_record_is_active("reflections", {"status": "invalidated"}) is False
    assert _semantic_record_is_active("reflections", {"status": "superseded"}) is False
    # Observations carry no lifecycle status and stay retrievable as evidence.
    assert _semantic_record_is_active("observations", {"status": "anything"}) is True
    assert _semantic_record_is_active("observations", {}) is True
