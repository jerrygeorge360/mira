"""Verify ISSUE-029 reflection staleness through evidence invalidation.

Ownership: MIRA contributors.
Related issue: ISSUE-029.
Architecture area: slow path.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from core.db.repositories import (
    configure_database,
    create_atomic_fact,
    create_session,
    repository_connection,
    save_observation,
)
from core.memory.reflection import (
    find_reflections_derived_from,
    invalidate_reflection_if_unsupported,
    mark_reflection_stale,
    recompute_reflection_confidence,
    store_reflection_with_evidence,
)
from core.memory.tiers import evaluate_promotion_candidate


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    """Configure reflection-staleness tests to use an isolated database."""
    path = tmp_path / "mira.sqlite3"
    configure_database(path)
    yield path


def _fact(observation_id: str, object_value: str) -> str:
    return create_atomic_fact(
        {
            "subject": "Jerry",
            "predicate": "PREFERS",
            "object": object_value,
            "confidence": 0.9,
            "status": "active",
            "source_observation_id": observation_id,
        }
    )


def _supersede_fact(fact_id: str) -> None:
    with repository_connection() as connection:
        connection.execute(
            "UPDATE atomic_facts SET status = ? WHERE id = ?",
            ("superseded", fact_id),
        )


def _reflection_row(reflection_id: str) -> dict[str, object]:
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT * FROM reflections WHERE id = ?",
            (reflection_id,),
        ).fetchone()
    assert row is not None
    return dict(row)


def _two_evidence_reflection(session_id: str) -> tuple[str, str, str]:
    obs_one = save_observation(session_id, "user", "I prefer Python.")
    obs_two = save_observation(session_id, "user", "I use Python for data work.")
    fact_one = _fact(obs_one, "Python")
    _fact(obs_two, "Python")
    reflection_id = store_reflection_with_evidence(
        {
            "reflection_type": "user_knowledge",
            "content": "Jerry leans on Python across projects.",
            "confidence": 0.86,
        },
        [obs_one, obs_two],
    )
    return reflection_id, obs_one, fact_one


def test_find_reflections_derived_from_observation(database_path: Path) -> None:
    """Reflections are discoverable from any observation in their evidence."""
    session_id = create_session("jerry")
    reflection_id, obs_one, _ = _two_evidence_reflection(session_id)

    assert find_reflections_derived_from(obs_one) == [reflection_id]


def test_superseded_evidence_makes_reflection_stale(database_path: Path) -> None:
    """Superseding part of the evidence marks the dependent reflection stale."""
    session_id = create_session("jerry")
    reflection_id, obs_one, fact_one = _two_evidence_reflection(session_id)
    _supersede_fact(fact_one)

    for dependent_id in find_reflections_derived_from(obs_one):
        invalidate_reflection_if_unsupported(dependent_id)

    row = _reflection_row(reflection_id)
    assert row["status"] == "stale"
    assert row["stale_reason"]


def test_reflection_with_remaining_evidence_keeps_reduced_confidence(database_path: Path) -> None:
    """Partial evidence loss reduces confidence rather than removing the reflection."""
    session_id = create_session("jerry")
    reflection_id, _, fact_one = _two_evidence_reflection(session_id)
    _supersede_fact(fact_one)

    new_confidence = recompute_reflection_confidence(reflection_id)

    assert new_confidence == pytest.approx(0.43)  # 0.86 * (1 valid / 2 total)
    assert _reflection_row(reflection_id)["confidence"] == pytest.approx(0.43)


def test_unsupported_reflection_is_invalidated(database_path: Path) -> None:
    """A reflection whose only evidence collapses is invalidated for future use."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "I prefer Python.")
    fact_id = _fact(observation_id, "Python")
    reflection_id = store_reflection_with_evidence(
        {
            "reflection_type": "user_knowledge",
            "content": "Jerry prefers Python.",
            "confidence": 0.9,
        },
        [observation_id],
    )
    _supersede_fact(fact_id)

    invalidate_reflection_if_unsupported(reflection_id)

    assert _reflection_row(reflection_id)["status"] == "invalidated"
    # Removed from hot-tier eligibility.
    assert evaluate_promotion_candidate("reflections", reflection_id)["eligible"] is False


def test_fully_supported_reflection_is_unchanged(database_path: Path) -> None:
    """A reflection with all evidence intact stays active at full confidence."""
    session_id = create_session("jerry")
    reflection_id, _, _ = _two_evidence_reflection(session_id)

    invalidate_reflection_if_unsupported(reflection_id)

    row = _reflection_row(reflection_id)
    assert row["status"] == "active"
    assert row["confidence"] == pytest.approx(0.86)


def test_mark_stale_does_not_override_invalidated(database_path: Path) -> None:
    """A more severe invalidated status is preserved against a later stale call."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "I prefer Python.")
    fact_id = _fact(observation_id, "Python")
    reflection_id = store_reflection_with_evidence(
        {
            "reflection_type": "user_knowledge",
            "content": "Jerry prefers Python.",
            "confidence": 0.9,
        },
        [observation_id],
    )
    _supersede_fact(fact_id)
    invalidate_reflection_if_unsupported(reflection_id)

    mark_reflection_stale(reflection_id, "later partial signal")

    assert _reflection_row(reflection_id)["status"] == "invalidated"
