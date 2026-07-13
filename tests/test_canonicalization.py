"""Verify canonical subject/predicate registry and change-detection pairing.

Ownership: MIRA contributors.
Related issue: ISSUE-027.
Architecture area: slow path.

Regression coverage for the contradiction/supersession pairing bug: inconsistent
extraction wording (``I`` vs ``Speaker``, ``prefer`` vs ``prefers_language``) used to
produce zero pairing candidates because the query matched on raw subject/predicate
strings. Facts are now paired on canonical registry ids resolved at write time.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.db.repositories import (
    canonical_form_for_id,
    configure_database,
    create_atomic_fact,
    create_session,
    repository_connection,
    resolve_canonical_form,
    save_observation,
)
from core.db.schema import initialize_database
from core.memory.change import detect_memory_change
from core.memory.slow_path import _active_prior_fact_ids


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    """Configure canonicalization tests to use an isolated database."""
    path = tmp_path / "mira.sqlite3"
    configure_database(path)
    yield path


def _fetch_fact(fact_id: str) -> dict[str, object]:
    with repository_connection() as connection:
        row = connection.execute("SELECT * FROM atomic_facts WHERE id = ?", (fact_id,)).fetchone()
    assert row is not None
    return dict(row)


def test_seeded_aliases_resolve_case_insensitively(database_path: Path) -> None:
    """Seeded aliases collapse pronoun/speaker surface forms to one canonical bucket."""
    first = resolve_canonical_form("canonical_subjects", "I")
    second = resolve_canonical_form("canonical_subjects", "Speaker")
    third = resolve_canonical_form("canonical_subjects", "user")

    assert first == second == third
    assert canonical_form_for_id("canonical_subjects", first) == "user"


def test_leading_determiner_collapses_onto_seeded_alias(database_path: Path) -> None:
    """ "the speaker" strips its determiner and collapses onto the seeded user bucket.

    Without this, a determiner forks the subject into its own canonical bucket and
    contradiction/supersession pairing (which requires a shared canonical subject)
    silently finds no candidates.
    """
    user = resolve_canonical_form("canonical_subjects", "user")
    the_speaker = resolve_canonical_form("canonical_subjects", "the speaker")

    assert the_speaker == user
    assert canonical_form_for_id("canonical_subjects", the_speaker) == "user"


def test_unmapped_form_creates_visible_low_confidence_bucket(database_path: Path) -> None:
    """Unknown wording gets its own reviewable bucket rather than failing silently."""
    prefers = resolve_canonical_form("canonical_predicates", "prefer")
    junk = resolve_canonical_form("canonical_predicates", "prefers_language")

    assert junk != prefers
    # snake_case normalizes to spaces so "prefers_language" and "prefers language"
    # share one reviewable bucket instead of forking on punctuation alone.
    assert canonical_form_for_id("canonical_predicates", junk) == "prefers language"
    with repository_connection() as connection:
        confidence = connection.execute(
            "SELECT confidence FROM canonical_predicates WHERE id = ?", (junk,)
        ).fetchone()[0]
    assert confidence == 0.3


def test_create_atomic_fact_preserves_raw_and_sets_canonical(database_path: Path) -> None:
    """Raw extracted wording is kept for provenance; canonical ids are populated."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "I prefer Python.")

    fact_id = create_atomic_fact(
        {
            "subject": "I",
            "predicate": "prefer",
            "object": "Python",
            "confidence": 0.9,
            "source_observation_id": observation_id,
        }
    )

    fact = _fetch_fact(fact_id)
    assert fact["subject"] == "I"
    assert fact["predicate"] == "prefer"
    assert canonical_form_for_id("canonical_subjects", str(fact["canonical_subject_id"])) == "user"
    assert (
        canonical_form_for_id("canonical_predicates", str(fact["canonical_predicate_id"]))
        == "prefers"
    )


def test_canonical_pairing_detects_supersession_across_messy_extraction(
    database_path: Path,
) -> None:
    """The exact noisy extraction that broke pairing now yields SUPERSEDED_BY end to end."""
    session_id = create_session("jerry")
    python_observation = save_observation(session_id, "user", "I prefer Python.")
    rust_observation = save_observation(session_id, "user", "Actually I prefer Rust.")

    create_atomic_fact(_fact("I", "prefer", "Python", python_observation))
    create_atomic_fact(_fact("User", "prefers", "Python", python_observation))
    create_atomic_fact(_fact("Speaker", "prefers_language", "Rust", rust_observation))
    rust_clean_id = create_atomic_fact(_fact("you", "prefers", "Rust", rust_observation))

    priors = _active_prior_fact_ids(_fetch_fact(rust_clean_id))
    changes = detect_memory_change(rust_clean_id, priors)

    assert priors, "canonical pairing should find the prior Python facts"
    assert any(change["relation"] == "SUPERSEDED_BY" for change in changes)


def test_migration_adds_canonical_columns_to_legacy_atomic_facts(tmp_path: Path) -> None:
    """A pre-canonical atomic_facts table is migrated in place without a backfill."""
    path = tmp_path / "legacy.sqlite3"
    now = datetime.now(timezone.utc).isoformat()  # noqa: UP017
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE atomic_facts (id TEXT PRIMARY KEY, subject TEXT, predicate TEXT, "
        "object TEXT, confidence REAL, status TEXT, source_observation_id TEXT, "
        "created_at TEXT, valid_from TEXT, valid_until TEXT)"
    )
    connection.execute(
        "INSERT INTO atomic_facts VALUES ('f1','I','prefer','Python',0.9,'active','o',?,NULL,NULL)",
        (now,),
    )
    connection.commit()
    connection.close()

    initialize_database(path)

    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    columns = {row[1] for row in connection.execute("PRAGMA table_info(atomic_facts)")}
    legacy = connection.execute(
        "SELECT canonical_subject_id FROM atomic_facts WHERE id = 'f1'"
    ).fetchone()
    seeded = connection.execute("SELECT COUNT(*) FROM canonical_subjects").fetchone()[0]
    connection.close()

    assert {"canonical_subject_id", "canonical_predicate_id"} <= columns
    assert legacy["canonical_subject_id"] is None
    assert seeded == len({"user", "assistant"})


def _fact(
    subject: str, predicate: str, object_value: str, observation_id: str
) -> dict[str, object]:
    return {
        "subject": subject,
        "predicate": predicate,
        "object": object_value,
        "confidence": 0.9,
        "source_observation_id": observation_id,
    }
