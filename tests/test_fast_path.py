"""Verify the strict fast path for raw observation persistence and queueing.

Ownership: MIRA contributors.
Related issue: ISSUE-101.
Architecture area: fast path.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from core.db.repositories import configure_database
from core.db.schema import LEGACY_WORKSPACE_ID
from core.db.sqlite import connect_sqlite
from core.memory import observation


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    """Configure the fast path to use an isolated SQLite database."""
    path = tmp_path / "mira.sqlite3"
    configure_database(path)
    yield path


def _create_session(database_path: Path) -> str:
    with connect_sqlite(database_path) as connection:
        connection.execute(
            """
            INSERT INTO sessions (
                id, workspace_id, user_id, title, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "session-1",
                LEGACY_WORKSPACE_ID,
                "user-1",
                "Fast Path Session",
                "active",
                "2026-06-23T00:00:00+00:00",
                "2026-06-23T00:00:00+00:00",
            ),
        )
    return "session-1"


def _queue_count(database_path: Path, observation_id: str) -> int:
    with connect_sqlite(database_path) as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM slow_path_queue WHERE observation_id = ?",
            (observation_id,),
        ).fetchone()
    assert row is not None
    return int(row["count"])


def test_fast_path_saves_user_turn_and_returns_observation_id(database_path: Path) -> None:
    """Saving a user turn creates an observation row and returns its identifier."""
    session_id = _create_session(database_path)

    observation_id = observation.persist_turn_fast_path(
        session_id,
        "user",
        "Remember the fast path contract.",
        metadata={"slice": "fast-path"},
    )

    with connect_sqlite(database_path) as connection:
        row = connection.execute(
            "SELECT * FROM observations WHERE id = ?",
            (observation_id,),
        ).fetchone()

    assert row is not None
    assert row["session_id"] == session_id
    assert row["role"] == "user"
    assert row["content"] == "Remember the fast path contract."
    assert row["metadata_json"] == '{"slice": "fast-path"}'


def test_fast_path_saves_assistant_turn(database_path: Path) -> None:
    """Saving an assistant turn creates an observation row."""
    session_id = _create_session(database_path)

    observation_id = observation.persist_turn_fast_path(
        session_id,
        "assistant",
        "I saved your turn without enrichment.",
    )

    with connect_sqlite(database_path) as connection:
        row = connection.execute(
            "SELECT role, content FROM observations WHERE id = ?",
            (observation_id,),
        ).fetchone()

    assert row is not None
    assert row["role"] == "assistant"
    assert row["content"] == "I saved your turn without enrichment."


def test_fast_path_creates_queue_entry(database_path: Path) -> None:
    """Each fast-path observation is queued for later slow-path processing."""
    session_id = _create_session(database_path)

    observation_id = observation.persist_turn_fast_path(session_id, "user", "Queue this turn.")

    assert _queue_count(database_path, observation_id) == 1

    with connect_sqlite(database_path) as connection:
        row = connection.execute(
            """
            SELECT status
            FROM slow_path_queue
            WHERE observation_id = ?
            """,
            (observation_id,),
        ).fetchone()

    assert row is not None
    assert row["status"] == "pending"


def test_fast_path_does_not_invoke_llm_or_embedding_calls(
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fast path persists and queues only, without LLM or embedding work."""
    session_id = _create_session(database_path)

    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("fast path must not invoke non-persistence side effects")

    monkeypatch.setattr("core.llm.qwen.call_qwen_chat", fail)
    monkeypatch.setattr("core.llm.qwen.call_qwen_json", fail)
    monkeypatch.setattr("core.db.chroma.index_memory", fail)
    monkeypatch.setattr("core.db.chroma.remove_from_index", fail)

    observation_id = observation.persist_turn_fast_path(session_id, "user", "Persist only.")

    assert observation_id
    assert _queue_count(database_path, observation_id) == 1


def test_fast_path_is_safe_under_repeated_calls(database_path: Path) -> None:
    """Repeated calls create distinct observations and queue records."""
    session_id = _create_session(database_path)

    first_id = observation.persist_turn_fast_path(session_id, "user", "First turn.")
    second_id = observation.persist_turn_fast_path(session_id, "user", "Second turn.")

    assert first_id != second_id

    with connect_sqlite(database_path) as connection:
        observation_count = connection.execute(
            "SELECT COUNT(*) AS count FROM observations WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        queue_count = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM slow_path_queue
            WHERE observation_id IN (?, ?)
            """,
            (first_id, second_id),
        ).fetchone()

    assert observation_count is not None
    assert queue_count is not None
    assert int(observation_count["count"]) == 2
    assert int(queue_count["count"]) == 2
