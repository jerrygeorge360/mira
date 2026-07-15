"""Verify ISSUE-030 foresight records and lifecycle.

Ownership: MIRA contributors.
Related issue: ISSUE-030.
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
from core.memory import foresight
from core.memory.foresight import (
    cancel_foresight,
    create_foresight,
    detect_foresight,
    list_relevant_foresight,
    resolve_foresight,
    update_foresight_status,
)


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    """Configure foresight tests to use an isolated database."""
    path = tmp_path / "mira.sqlite3"
    configure_database(path)
    yield path


def _status(record_id: str) -> str:
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT status FROM foresight_records WHERE id = ?",
            (record_id,),
        ).fetchone()
    assert row is not None
    return str(row["status"])


def _record(record_id: str) -> dict[str, object]:
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT * FROM foresight_records WHERE id = ?",
            (record_id,),
        ).fetchone()
    assert row is not None
    return dict(row)


def test_hackathon_deadline_activates(database_path: Path) -> None:
    """A pending deadline whose window has opened becomes active."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "The hackathon ends on 2026-07-01.")
    record_id = create_foresight(
        {
            "content": "Hackathon submission is due 2026-07-01.",
            "reason": "User stated the deadline.",
            "status": "pending",
            "source_observation_id": observation_id,
            "valid_from": "2026-06-24T00:00:00+00:00",
            "valid_until": "2026-07-01T23:59:59+00:00",
        }
    )

    update_foresight_status(record_id, "2026-06-25T09:00:00+00:00")

    assert _status(record_id) == "active"


def test_deadline_expires(database_path: Path) -> None:
    """An active deadline expires once now passes valid_until."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "The hackathon ends on 2026-07-01.")
    record_id = create_foresight(
        {
            "content": "Hackathon submission is due 2026-07-01.",
            "status": "active",
            "source_observation_id": observation_id,
            "valid_from": "2026-06-24T00:00:00+00:00",
            "valid_until": "2026-07-01T23:59:59+00:00",
        }
    )

    update_foresight_status(record_id, "2026-07-02T08:00:00+00:00")

    assert _status(record_id) == "expired"


def test_user_completion_resolves_early(database_path: Path) -> None:
    """Explicit completion resolves an active record before its deadline."""
    session_id = create_session("jerry")
    deadline_observation_id = save_observation(session_id, "user", "Hackathon ends 2026-07-01.")
    record_id = create_foresight(
        {
            "content": "Hackathon submission is due 2026-07-01.",
            "status": "active",
            "source_observation_id": deadline_observation_id,
            "valid_until": "2026-07-01T23:59:59+00:00",
        }
    )
    completion_observation_id = save_observation(session_id, "user", "I submitted the project.")

    resolve_foresight(record_id, completion_observation_id)

    record = _record(record_id)
    assert record["status"] == "resolved"
    assert record["resolved_by"] == completion_observation_id


def test_cancel_active_foresight(database_path: Path) -> None:
    """An active record can be cancelled and refuses double-cancellation."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "Avoid deploys this week.")
    record_id = create_foresight(
        {
            "content": "Hold deploys until the freeze lifts.",
            "status": "active",
            "source_observation_id": observation_id,
        }
    )

    cancel_foresight(record_id)
    assert _status(record_id) == "cancelled"
    with pytest.raises(ValueError, match="terminal status"):
        cancel_foresight(record_id)


def test_prompt_builder_retrieves_active_relevant_foresight(database_path: Path) -> None:
    """Relevant active foresight and always-inject records are returned for a query."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "Hackathon ends 2026-07-01.")
    deadline_id = create_foresight(
        {
            "content": "Hackathon submission is due 2026-07-01.",
            "status": "active",
            "source_observation_id": observation_id,
            "valid_from": "2026-06-24T00:00:00+00:00",
            "valid_until": "2026-07-01T23:59:59+00:00",
        }
    )
    always_id = create_foresight(
        {
            "content": "Always run make check before opening a PR.",
            "status": "active",
            "source_observation_id": observation_id,
            "always_inject": True,
        }
    )
    # An unrelated, non-always-inject record should not surface for this query.
    create_foresight(
        {
            "content": "Renew the domain certificate next quarter.",
            "status": "active",
            "source_observation_id": observation_id,
        }
    )

    results = list_relevant_foresight("How is the hackathon going?", "2026-06-26T10:00:00+00:00")

    result_ids = [record["id"] for record in results]
    assert deadline_id in result_ids
    assert always_id in result_ids
    assert len(result_ids) == 2
    # Always-inject ranks first.
    assert results[0]["id"] == always_id


def test_expired_window_excluded_from_relevant(database_path: Path) -> None:
    """A temporally invalid active record is not returned as relevant."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "Hackathon ended 2026-06-01.")
    create_foresight(
        {
            "content": "Hackathon submission was due 2026-06-01.",
            "status": "active",
            "source_observation_id": observation_id,
            "valid_until": "2026-06-01T23:59:59+00:00",
        }
    )

    assert list_relevant_foresight("hackathon", "2026-06-26T10:00:00+00:00") == []


def test_detect_foresight_grounds_records_in_ambient(
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detection attaches the source observation and ambient valid_from."""
    session_id = create_session("jerry")
    observation_id = save_observation(
        session_id, "user", "Remind me to submit before the deadline."
    )

    def _fake(messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
        assert schema_name == "foresight_detection"
        return {
            "json": {
                "foresight": [
                    {
                        "content": "Submit the project before the deadline.",
                        "reason": "User asked for a reminder.",
                        "status": "active",
                        "always_inject": False,
                    }
                ]
            }
        }

    monkeypatch.setattr(foresight, "call_qwen_json", _fake)

    records = detect_foresight(
        observation_id,
        "Remind me to submit before the deadline.",
        {"current_time": "2026-06-24T09:00:00+00:00"},
    )

    assert len(records) == 1
    assert records[0]["source_observation_id"] == observation_id
    assert records[0]["valid_from"] == "2026-06-24T09:00:00+00:00"
    assert records[0]["status"] == "active"

    record_id = create_foresight(records[0])
    assert _status(record_id) == "active"


def test_detect_foresight_rejects_standing_response_preferences(
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Answer-style preferences belong in working set, not foresight."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "Prefer detailed responses.")

    def _fake(messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
        assert schema_name == "foresight_detection"
        return {
            "json": {
                "foresight": [
                    {
                        "content": "Prefer detailed, thorough responses rather than concise ones.",
                        "reason": "User stated an answer-style preference.",
                        "status": "active",
                        "always_inject": False,
                    }
                ]
            }
        }

    monkeypatch.setattr(foresight, "call_qwen_json", _fake)

    assert (
        detect_foresight(
            observation_id,
            "Prefer detailed responses.",
            {"current_time": "2026-06-24T09:00:00+00:00"},
        )
        == []
    )
