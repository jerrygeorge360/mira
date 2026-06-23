"""Verify the ISSUE-018 ambient context provider.

Ownership: MIRA contributors.
Related issue: ISSUE-018.
Architecture area: context.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.context.ambient import build_ambient_context, calculate_session_gap
from core.context.merger import merge_context_sources
from core.db.repositories import (
    configure_database,
    create_session,
    repository_connection,
    save_observation,
)


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    """Configure ambient context tests to use an isolated database."""
    path = tmp_path / "mira.sqlite3"
    configure_database(path)
    yield path


def test_current_date_time_and_timezone_are_produced(database_path: Path) -> None:
    """Ambient context includes stable current temporal fields."""
    session_id = create_session("jerry")

    context = build_ambient_context(session_id, user_timezone="Africa/Lagos")

    assert context["kind"] == "ambient_context"
    assert context["ambient_context_role"] == "prompt_signal"
    assert context["memory_tier"] is None
    assert context["retrieval_mode"] is None
    assert context["timezone"] == "Africa/Lagos"
    assert isinstance(context["current_date"], str)
    assert isinstance(context["current_time"], str)
    assert datetime.fromisoformat(str(context["current_time"]))
    assert context["weather_context"] is None


def test_session_gap_uses_latest_observation(database_path: Path) -> None:
    """Session gap is based on the newest observation when observations exist."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "Continue MIRA.")
    started_at = datetime.now(timezone.utc) - timedelta(hours=2)  # noqa: UP017
    observed_at = datetime.now(timezone.utc) - timedelta(minutes=30)  # noqa: UP017
    _set_session_times(session_id, started_at)
    _set_observation_time(observation_id, observed_at)

    gap = calculate_session_gap(session_id)

    assert gap["basis"] == "latest_observation"
    assert gap["latest_activity_at"] == observed_at.isoformat()
    assert 1_700 <= int(gap["seconds_since_latest_activity"]) <= 1_900
    assert int(gap["seconds_since_session_start"]) >= 7_100


def test_session_gap_falls_back_to_session_record(database_path: Path) -> None:
    """Session gap can be calculated even before the first observation."""
    session_id = create_session("jerry")
    started_at = datetime.now(timezone.utc) - timedelta(minutes=12)  # noqa: UP017
    _set_session_times(session_id, started_at)

    gap = calculate_session_gap(session_id)

    assert gap["basis"] == "session_record"
    assert gap["latest_activity_at"] == started_at.isoformat()
    assert 700 <= int(gap["seconds_since_latest_activity"]) <= 800


def test_prompt_context_can_consume_ambient_output(database_path: Path) -> None:
    """Prompt-ready context packing can include ambient context unchanged."""
    session_id = create_session("jerry")
    ambient_context = build_ambient_context(session_id, user_timezone="UTC")

    context_pack = merge_context_sources(
        current_message="What is active now?",
        recent_turns=[],
        session_items=[],
        durable_memory_items=[],
        ambient_context=ambient_context,
        retrieved_items=[],
    )

    ambient_sections = [
        section for section in context_pack if section["section"] == "ambient_context"
    ]
    assert len(ambient_sections) == 1
    assert ambient_sections[0]["content"] == ambient_context


def _set_session_times(session_id: str, timestamp: datetime) -> None:
    with repository_connection() as connection:
        connection.execute(
            """
            UPDATE sessions
            SET created_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (timestamp.isoformat(), timestamp.isoformat(), session_id),
        )


def _set_observation_time(observation_id: str, timestamp: datetime) -> None:
    with repository_connection() as connection:
        connection.execute(
            "UPDATE observations SET created_at = ? WHERE id = ?",
            (timestamp.isoformat(), observation_id),
        )
