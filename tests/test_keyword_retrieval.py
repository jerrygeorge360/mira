"""Verify the ISSUE-033 keyword retrieval prototype.

Ownership: MIRA contributors.
Related issue: ISSUE-033.
Architecture area: retrieval.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from core.db.repositories import (
    configure_database,
    create_atomic_fact,
    create_session,
    save_observation,
)
from core.retrieval.keyword import (
    keyword_search_atomic_facts,
    keyword_search_observations,
)


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    """Configure keyword retrieval to use an isolated SQLite database."""
    path = tmp_path / "mira.sqlite3"
    configure_database(path)
    yield path


def test_exact_phrase_retrieves_matching_observation(database_path: Path) -> None:
    """Exact phrases recover the observation row and include its SQLite ID."""
    session_id = create_session("jerry")
    matching_id = save_observation(
        session_id,
        "user",
        "The launch deadline is 2026-07-15 for Project MIRA.",
    )
    save_observation(session_id, "assistant", "The roadmap mentions a different date.")

    results = keyword_search_observations("launch deadline is 2026-07-15", limit=5)

    assert results[0]["id"] == matching_id
    assert results[0]["record_type"] == "observation"
    assert results[0]["score"] > 0


def test_entity_name_retrieves_related_atomic_facts(database_path: Path) -> None:
    """Entity names match fact subjects and objects."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "Kelechi reviews persistence work.")
    fact_id = create_atomic_fact(
        {
            "subject": "Kelechi",
            "predicate": "reviews",
            "object": "MIRA persistence layer",
            "confidence": 0.91,
            "source_observation_id": observation_id,
        }
    )

    results = keyword_search_atomic_facts("Kelechi", limit=5)

    assert results[0]["id"] == fact_id
    assert results[0]["subject"] == "Kelechi"
    assert results[0]["source_observation_id"] == observation_id
    assert results[0]["record_type"] == "atomic_fact"


def test_limit_is_respected_for_observation_results(database_path: Path) -> None:
    """Keyword retrieval returns no more than the requested result count."""
    session_id = create_session("jerry")
    first_id = save_observation(session_id, "user", "MIRA issue ID ABC-123 appears here.")
    second_id = save_observation(session_id, "assistant", "MIRA issue ID ABC-123 appears again.")

    results = keyword_search_observations("ABC-123", limit=1)

    assert len(results) == 1
    assert isinstance(results[0]["id"], str)
    assert results[0]["id"] in {first_id, second_id}


def test_invalid_limit_is_rejected(database_path: Path) -> None:
    """Callers must request a positive result limit."""
    with pytest.raises(ValueError, match="limit"):
        keyword_search_observations("MIRA", limit=0)
