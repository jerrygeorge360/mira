"""Verify the ISSUE-024 atomic fact extraction path.

Ownership: MIRA contributors.
Related issue: ISSUE-024.
Architecture area: slow path.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from core.db.repositories import (
    configure_database,
    create_session,
    repository_connection,
    save_observation,
)
from core.memory import atomic_fact
from core.memory.atomic_fact import extract_atomic_facts, store_atomic_facts


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    """Configure atomic fact tests to use an isolated database."""
    path = tmp_path / "mira.sqlite3"
    configure_database(path)
    yield path


def test_direct_statement_extracts_and_stores_fact(
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Direct evidence becomes a source-backed atomic fact."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "Jerry prefers TypeScript backend.")

    monkeypatch.setattr(
        atomic_fact,
        "call_qwen_json",
        lambda messages, schema_name: {
            "json": {
                "facts": [
                    {
                        "subject": "Jerry",
                        "predicate": "PREFERS",
                        "object": "TypeScript backend",
                        "confidence": 0.82,
                        "evidence_span": "Jerry prefers TypeScript backend.",
                    }
                ]
            }
        },
    )

    facts = extract_atomic_facts(observation_id, "Jerry prefers TypeScript backend.")
    fact_ids = store_atomic_facts(facts)

    assert facts == [
        {
            "subject": "Jerry",
            "predicate": "PREFERS",
            "object": "TypeScript backend",
            "confidence": 0.82,
            "source_observation_id": observation_id,
            "evidence_span": "Jerry prefers TypeScript backend.",
        }
    ]
    stored_fact = _stored_atomic_fact(fact_ids[0])
    assert stored_fact["subject"] == "Jerry"
    assert stored_fact["predicate"] == "PREFERS"
    assert stored_fact["object"] == "TypeScript backend"
    assert stored_fact["source_observation_id"] == observation_id


def test_ambiguous_statement_is_conservative(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ambiguous claims with no extracted direct fact produce no facts."""
    monkeypatch.setattr(
        atomic_fact,
        "call_qwen_json",
        lambda messages, schema_name: {"json": {"facts": []}},
    )

    facts = extract_atomic_facts("obs_1", "Maybe Jerry might use Rust later.")

    assert facts == []


def test_unsupported_inference_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unsupported personality inference is filtered out before storage."""
    monkeypatch.setattr(
        atomic_fact,
        "call_qwen_json",
        lambda messages, schema_name: {
            "json": {
                "facts": [
                    {
                        "subject": "Jerry",
                        "predicate": "IS",
                        "object": "careless",
                        "confidence": 0.91,
                        "evidence_span": "Jerry forgot the semicolon.",
                    }
                ]
            }
        },
    )

    facts = extract_atomic_facts("obs_2", "Jerry forgot the semicolon.")

    assert facts == []


def test_ungrounded_evidence_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Facts must preserve source grounding through an evidence span."""
    monkeypatch.setattr(
        atomic_fact,
        "call_qwen_json",
        lambda messages, schema_name: {
            "json": {
                "facts": [
                    {
                        "subject": "MIRA",
                        "predicate": "USES",
                        "object": "MongoDB",
                        "confidence": 0.9,
                        "evidence_span": "MIRA uses MongoDB.",
                    }
                ]
            }
        },
    )

    facts = extract_atomic_facts("obs_3", "MIRA uses SQLite.")

    assert facts == []


def _stored_atomic_fact(fact_id: str) -> dict[str, object]:
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT * FROM atomic_facts WHERE id = ?",
            (fact_id,),
        ).fetchone()
    assert row is not None
    return dict(row)
