"""Verify bounded discourse-reference resolution for memory-changing turns."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from core.db.repositories import configure_database, create_session, save_observation
from core.llm.qwen import LLMClientError
from core.session import reference


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    path = tmp_path / "mira.sqlite3"
    configure_database(path)
    yield path


def test_explicit_immediate_reference_uses_previous_user_turn(
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "AWS hosts the application.")

    def fail_retrieval(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        raise AssertionError("an explicit immediate reference must not run durable retrieval")

    monkeypatch.setattr(reference, "retrieve_quick", fail_retrieval)
    result = reference.resolve_discourse_reference(
        session_id,
        "Disregard what I just said.",
        [{"id": observation_id, "role": "user", "content": "AWS hosts the application."}],
    )

    assert result["status"] == "resolved"
    assert result["target_observation_id"] == observation_id
    assert result["source"] == "recent_conversation"


def test_model_can_select_only_a_supplied_candidate(
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = create_session("jerry")
    aws_id = save_observation(session_id, "user", "AWS hosts the application.")
    autoscaling_id = save_observation(
        session_id,
        "user",
        "Autoscaling starts at 80 percent CPU.",
    )
    recent_turns = [
        {"id": aws_id, "role": "user", "content": "AWS hosts the application."},
        {
            "id": autoscaling_id,
            "role": "user",
            "content": "Autoscaling starts at 80 percent CPU.",
        },
    ]
    monkeypatch.setattr(reference, "retrieve_quick", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        reference,
        "call_qwen_json",
        lambda *_args, **_kwargs: {
            "json": {
                "status": "resolved",
                "target_id": "observation:invented",
                "confidence": 0.99,
                "reason": "Invented target.",
            }
        },
    )

    result = reference.resolve_discourse_reference(
        session_id,
        "Ignore the hosting detail.",
        recent_turns,
    )

    assert result["status"] == "ambiguous"
    assert result["target_observation_id"] is None
    assert result["clarification"]


def test_provider_failure_leaves_reference_unresolved(
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = create_session("jerry")
    first_id = save_observation(session_id, "user", "AWS hosts the application.")
    second_id = save_observation(session_id, "user", "The API runs in Docker.")
    monkeypatch.setattr(reference, "retrieve_quick", lambda *_args, **_kwargs: [])

    def fail_provider(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise LLMClientError("provider unavailable")

    monkeypatch.setattr(reference, "call_qwen_json", fail_provider)
    result = reference.resolve_discourse_reference(
        session_id,
        "Ignore that.",
        [
            {"id": first_id, "role": "user", "content": "AWS hosts the application."},
            {"id": second_id, "role": "user", "content": "The API runs in Docker."},
        ],
    )

    assert result["status"] == "unresolved"
    assert result["target_observation_id"] is None
    assert result["clarification"] == "Which earlier statement should I disregard?"
