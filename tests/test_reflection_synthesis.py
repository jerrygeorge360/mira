"""Verify reflection synthesis rejects fact restatements.

Ownership: MIRA contributors.
Architecture area: slow path.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from core.db.repositories import configure_database, create_session, save_observation
from core.memory import reflection


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    """Configure reflection tests to use an isolated database."""
    path = tmp_path / "mira.sqlite3"
    configure_database(path)
    yield path


def test_reflection_rejects_single_fact_restatement(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Atomic architecture facts should stay facts, not become reflections."""
    del database_path
    session_id = create_session("jerry")
    one = save_observation(session_id, "user", "MIRA uses a hybrid retrieval router.")
    two = save_observation(session_id, "user", "Quick retrieval prioritizes structured facts.")
    monkeypatch.setattr(
        reflection,
        "call_qwen_json",
        lambda *_args, **_kwargs: {
            "json": {
                "reflections": [
                    {
                        "reflection_type": "self_knowledge",
                        "content": "MIRA uses a hybrid retrieval router.",
                        "confidence": 0.9,
                        "evidence_ids": [one, two],
                    }
                ]
            }
        },
    )

    assert reflection.synthesize_reflections([one, two]) == []


def test_reflection_requires_multiple_evidence_records(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A single source-backed model output is still too thin for reflection."""
    del database_path
    session_id = create_session("jerry")
    observation_id = save_observation(
        session_id,
        "user",
        "MIRA favors traceable memory over raw prompt stuffing.",
    )
    monkeypatch.setattr(
        reflection,
        "call_qwen_json",
        lambda *_args, **_kwargs: {
            "json": {
                "reflections": [
                    {
                        "reflection_type": "self_knowledge",
                        "content": (
                            "MIRA consistently favors traceable memory over raw prompt stuffing."
                        ),
                        "confidence": 0.9,
                        "evidence_ids": [observation_id],
                    }
                ]
            }
        },
    )

    assert reflection.synthesize_reflections([observation_id]) == []


def test_reflection_rejects_near_duplicate_evidence(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repeated paraphrases should not count as a real pattern."""
    del database_path
    session_id = create_session("jerry")
    one = save_observation(session_id, "user", "MIRA uses SQLite as source of truth.")
    two = save_observation(session_id, "user", "MIRA uses SQLite as the source of truth.")
    monkeypatch.setattr(
        reflection,
        "call_qwen_json",
        lambda *_args, **_kwargs: {
            "json": {
                "reflections": [
                    {
                        "reflection_type": "self_knowledge",
                        "content": "MIRA consistently uses SQLite as source of truth.",
                        "confidence": 0.9,
                        "evidence_ids": [one, two],
                    }
                ]
            }
        },
    )

    assert reflection.synthesize_reflections([one, two]) == []


def test_reflection_accepts_diverse_pattern_evidence(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Diverse evidence can still produce a higher-order reflection."""
    del database_path
    session_id = create_session("jerry")
    one = save_observation(session_id, "user", "MIRA keeps SQLite as durable storage.")
    two = save_observation(session_id, "user", "MIRA returns answer traces for inspection.")
    monkeypatch.setattr(
        reflection,
        "call_qwen_json",
        lambda *_args, **_kwargs: {
            "json": {
                "reflections": [
                    {
                        "reflection_type": "self_knowledge",
                        "content": (
                            "MIRA consistently favors inspectable memory infrastructure "
                            "over flat transcript recall."
                        ),
                        "confidence": 0.9,
                        "evidence_ids": [one, two],
                    }
                ]
            }
        },
    )

    reflections = reflection.synthesize_reflections([one, two])

    assert len(reflections) == 1
    assert reflections[0]["reflection_type"] == "self_knowledge"
