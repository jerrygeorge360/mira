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
    WorkspaceContext,
    bind_workspace,
    configure_database,
    create_session,
    create_working_memory_item,
    create_workspace,
    repository_connection,
    save_observation,
)
from core.llm.qwen import LLMRequestError
from core.memory import foresight
from core.memory.foresight import (
    cancel_foresight,
    cancel_matching_foresight,
    create_foresight,
    detect_foresight,
    list_relevant_foresight,
    reconcile_foresight_lifecycle,
    refresh_foresight_lifecycle,
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


def test_explicit_deadline_removal_cancels_matching_foresight(database_path: Path) -> None:
    """A new user observation can withdraw a previously active deadline."""
    session_id = create_session("jerry")
    deadline_observation_id = save_observation(
        session_id,
        "user",
        "My project deadline is July 30.",
    )
    deadline_id = create_foresight(
        {
            "content": "The project deadline is July 30.",
            "reason": "The user stated a project deadline.",
            "status": "active",
            "source_observation_id": deadline_observation_id,
        }
    )
    cancellation_observation_id = save_observation(
        session_id,
        "user",
        "I don't have a deadline anymore.",
    )

    cancelled = cancel_matching_foresight(
        cancellation_observation_id,
        "I don't have a deadline anymore.",
    )

    assert cancelled == [deadline_id]
    record = _record(deadline_id)
    assert record["status"] == "cancelled"
    assert record["resolved_by"] == cancellation_observation_id


def test_explicit_event_removal_matches_the_event_noun(database_path: Path) -> None:
    """Cancellation is not limited to hard-coded event categories such as deadlines."""
    session_id = create_session("jerry")
    match_observation_id = save_observation(session_id, "user", "I have a match today.")
    match_id = create_foresight(
        {
            "content": "The user has a match today.",
            "reason": "A match today is a time-sensitive event.",
            "status": "active",
            "source_observation_id": match_observation_id,
        }
    )
    cancellation_observation_id = save_observation(
        session_id,
        "user",
        "I don't have the match anymore.",
    )

    cancelled = cancel_matching_foresight(
        cancellation_observation_id,
        "I don't have the match anymore.",
    )

    assert cancelled == [match_id]
    assert _record(match_id)["status"] == "cancelled"


@pytest.mark.parametrize(
    "cancellation_text",
    ["I am not jogging anymore.", "I cancelled the jogging."],
)
def test_event_removal_matches_gerund_to_event_noun(
    database_path: Path,
    cancellation_text: str,
) -> None:
    """A natural verb form can withdraw a Foresight record using its event noun."""
    session_id = create_session("jerry")
    jog_observation_id = save_observation(session_id, "user", "I have a jog today.")
    jog_id = create_foresight(
        {
            "content": "User has a jog scheduled today.",
            "reason": "The user mentioned having a jog today.",
            "status": "active",
            "source_observation_id": jog_observation_id,
        }
    )
    cancellation_observation_id = save_observation(
        session_id,
        "user",
        cancellation_text,
    )

    cancelled = cancel_matching_foresight(
        cancellation_observation_id,
        cancellation_text,
    )

    assert cancelled == [jog_id]
    assert _record(jog_id)["status"] == "cancelled"


def test_anaphoric_cancellation_uses_referenced_foresight(database_path: Path) -> None:
    """A cancellation can resolve "it" from the preceding retrieval evidence."""
    session_id = create_session("jerry")
    class_observation_id = save_observation(session_id, "user", "I have a class tomorrow.")
    class_id = create_foresight(
        {
            "content": "User has a class tomorrow.",
            "reason": "User mentioned a class on the following day.",
            "status": "active",
            "source_observation_id": class_observation_id,
        }
    )
    cancellation_observation_id = save_observation(
        session_id,
        "user",
        "Alright, it was cacelled.",
    )

    cancelled = cancel_matching_foresight(
        cancellation_observation_id,
        "Alright, it was cacelled.",
        reference_text="User has a class tomorrow.",
    )

    assert cancelled == [class_id]
    assert _record(class_id)["status"] == "cancelled"


def test_semantic_reconciliation_cancels_a_cross_session_synonym(
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A later session can cancel lesson Foresight by referring to it as a class."""
    source_session_id = create_session("jerry")
    source_observation_id = save_observation(
        source_session_id,
        "user",
        "I have a lesson today.",
    )
    record_id = create_foresight(
        {
            "content": "User has a lesson today.",
            "reason": "The user stated a scheduled lesson.",
            "status": "active",
            "source_observation_id": source_observation_id,
        }
    )
    update_session_id = create_session("jerry")
    update_observation_id = save_observation(
        update_session_id,
        "user",
        "The class has been cancelled.",
    )
    monkeypatch.setattr(foresight, "embed_text", lambda _text: [1.0, 0.0])

    def classify(messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
        assert schema_name == "foresight_reconciliation"
        assert record_id in messages[0]["content"]
        assert "I have a lesson today." in messages[0]["content"]
        return {
            "json": {
                "decisions": [
                    {
                        "target_id": record_id,
                        "action": "cancel",
                        "confidence": 0.97,
                        "reason": "Class and lesson refer to the same event.",
                        "replacement_content": None,
                        "replacement_valid_until": None,
                    }
                ],
                "needs_clarification": False,
                "clarification": None,
            }
        }

    monkeypatch.setattr(foresight, "call_qwen_json", classify)

    result = reconcile_foresight_lifecycle(
        update_observation_id,
        "The class has been cancelled.",
        session_id=update_session_id,
    )

    assert result["cancelled"] == [record_id]
    record = _record(record_id)
    assert record["status"] == "cancelled"
    assert record["resolved_by"] == update_observation_id


def test_semantic_reconciliation_never_exposes_another_workspace(
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cross-session resolution remains strictly bounded to one workspace."""
    workspace_a = create_workspace("A", "foresight-a", "development")
    workspace_b = create_workspace("B", "foresight-b", "development")
    repo_a = bind_workspace(WorkspaceContext(workspace_a))
    repo_b = bind_workspace(WorkspaceContext(workspace_b))
    session_a = repo_a.create_session("user-a")
    session_b = repo_b.create_session("user-b")
    observation_a = repo_a.save_observation(session_a, "user", "I have a class today.")
    observation_b = repo_b.save_observation(session_b, "user", "I have a class today.")
    record_a = create_foresight(
        {
            "content": "User A has a class today.",
            "status": "active",
            "source_observation_id": observation_a,
        }
    )
    record_b = create_foresight(
        {
            "content": "User B has a class today.",
            "status": "active",
            "source_observation_id": observation_b,
        }
    )
    update_observation_id = repo_b.save_observation(
        session_b,
        "user",
        "The lesson was cancelled.",
    )
    monkeypatch.setattr(foresight, "embed_text", lambda _text: [1.0])

    def classify(messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
        assert schema_name == "foresight_reconciliation"
        assert record_a not in messages[0]["content"]
        assert record_b in messages[0]["content"]
        return {
            "json": {
                "decisions": [
                    {
                        "target_id": record_b,
                        "action": "cancel",
                        "confidence": 0.97,
                        "reason": "Lesson and class identify the same event.",
                        "replacement_content": None,
                        "replacement_valid_until": None,
                    }
                ],
                "needs_clarification": False,
                "clarification": None,
            }
        }

    monkeypatch.setattr(foresight, "call_qwen_json", classify)

    result = reconcile_foresight_lifecycle(
        update_observation_id,
        "The lesson was cancelled.",
        workspace_id=workspace_b,
        session_id=session_b,
    )

    assert result["cancelled"] == [record_b]
    assert _record(record_a)["status"] == "active"
    assert _record(record_b)["status"] == "cancelled"


def test_semantic_reconciliation_resolves_a_completed_action(
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Completion evidence resolves rather than cancels an active obligation."""
    source_session_id = create_session("jerry")
    source_observation_id = save_observation(
        source_session_id,
        "user",
        "Submit the report tomorrow.",
    )
    record_id = create_foresight(
        {
            "content": "User needs to submit the report tomorrow.",
            "status": "active",
            "source_observation_id": source_observation_id,
        }
    )
    update_session_id = create_session("jerry")
    update_observation_id = save_observation(
        update_session_id,
        "user",
        "I sent in the report.",
    )
    monkeypatch.setattr(foresight, "embed_text", lambda _text: [1.0])
    monkeypatch.setattr(
        foresight,
        "call_qwen_json",
        lambda *_args, **_kwargs: {
            "json": {
                "decisions": [
                    {
                        "target_id": record_id,
                        "action": "resolve",
                        "confidence": 0.94,
                        "reason": "Sent in and submit describe completion of the report.",
                        "replacement_content": None,
                        "replacement_valid_until": None,
                    }
                ],
                "needs_clarification": False,
                "clarification": None,
            }
        },
    )

    result = reconcile_foresight_lifecycle(
        update_observation_id,
        "I sent in the report.",
        session_id=update_session_id,
    )

    assert result["resolved"] == [record_id]
    assert _record(record_id)["status"] == "resolved"
    assert _record(record_id)["resolved_by"] == update_observation_id


def test_semantic_reconciliation_replaces_a_modified_event(
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rescheduling retires the prior event and creates one traced replacement."""
    source_session_id = create_session("jerry")
    source_observation_id = save_observation(
        source_session_id,
        "user",
        "I have a lesson tomorrow.",
    )
    record_id = create_foresight(
        {
            "content": "User has a lesson tomorrow.",
            "status": "active",
            "source_observation_id": source_observation_id,
        }
    )
    update_session_id = create_session("jerry")
    update_observation_id = save_observation(
        update_session_id,
        "user",
        "The class was moved to Friday.",
    )
    monkeypatch.setattr(foresight, "embed_text", lambda _text: [1.0])
    monkeypatch.setattr(
        foresight,
        "call_qwen_json",
        lambda *_args, **_kwargs: {
            "json": {
                "decisions": [
                    {
                        "target_id": record_id,
                        "action": "modify",
                        "confidence": 0.96,
                        "reason": "Class and lesson identify the same rescheduled event.",
                        "replacement_content": "User has a class on Friday.",
                        "replacement_valid_until": "2026-07-24T23:59:59+01:00",
                    }
                ],
                "needs_clarification": False,
                "clarification": None,
            }
        },
    )

    result = reconcile_foresight_lifecycle(
        update_observation_id,
        "The class was moved to Friday.",
        session_id=update_session_id,
    )

    assert result["cancelled"] == [record_id]
    assert len(result["created"]) == 1
    assert _record(record_id)["status"] == "cancelled"
    replacement = _record(result["created"][0])
    assert replacement["content"] == "User has a class on Friday."
    assert replacement["source_observation_id"] == update_observation_id
    assert replacement["status"] == "active"


def test_semantic_reconciliation_leaves_an_unrelated_event_active(
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancelling a match cannot cancel a semantically nearby lesson record."""
    session_id = create_session("jerry")
    lesson_observation_id = save_observation(session_id, "user", "I have a lesson today.")
    lesson_id = create_foresight(
        {
            "content": "User has a lesson today.",
            "status": "active",
            "source_observation_id": lesson_observation_id,
        }
    )
    cancellation_observation_id = save_observation(
        session_id,
        "user",
        "The match has been cancelled.",
    )
    monkeypatch.setattr(foresight, "embed_text", lambda _text: [1.0])
    monkeypatch.setattr(
        foresight,
        "call_qwen_json",
        lambda *_args, **_kwargs: {
            "json": {
                "decisions": [
                    {
                        "target_id": lesson_id,
                        "action": "unrelated",
                        "confidence": 0.99,
                        "reason": "A lesson and a match are distinct events.",
                        "replacement_content": None,
                        "replacement_valid_until": None,
                    }
                ],
                "needs_clarification": False,
                "clarification": None,
            }
        },
    )

    result = reconcile_foresight_lifecycle(
        cancellation_observation_id,
        "The match has been cancelled.",
        session_id=session_id,
    )

    assert result["cancelled"] == []
    assert _record(lesson_id)["status"] == "active"


def test_semantic_reconciliation_rejects_unknown_and_low_confidence_targets(
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider output cannot mutate an unsupplied or uncertain Foresight record."""
    session_id = create_session("jerry")
    source_observation_id = save_observation(session_id, "user", "I have a lesson today.")
    record_id = create_foresight(
        {
            "content": "User has a lesson today.",
            "status": "active",
            "source_observation_id": source_observation_id,
        }
    )
    update_observation_id = save_observation(session_id, "user", "Maybe it changed.")
    monkeypatch.setattr(foresight, "embed_text", lambda _text: [1.0])
    monkeypatch.setattr(
        foresight,
        "call_qwen_json",
        lambda *_args, **_kwargs: {
            "json": {
                "decisions": [
                    {
                        "target_id": "invented",
                        "action": "cancel",
                        "confidence": 1.0,
                        "reason": "Invalid target.",
                        "replacement_content": None,
                        "replacement_valid_until": None,
                    },
                    {
                        "target_id": record_id,
                        "action": "cancel",
                        "confidence": 0.5,
                        "reason": "Too uncertain.",
                        "replacement_content": None,
                        "replacement_valid_until": None,
                    },
                ],
                "needs_clarification": True,
                "clarification": "Which lesson changed?",
            }
        },
    )

    result = reconcile_foresight_lifecycle(
        update_observation_id,
        "Maybe it changed.",
        session_id=session_id,
    )

    assert result["needs_clarification"] is True
    assert result["cancelled"] == []
    assert _record(record_id)["status"] == "active"


def test_semantic_reconciliation_fails_closed_when_clarification_is_required(
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A contradictory high-confidence decision cannot bypass an ambiguity signal."""
    session_id = create_session("jerry")
    source_observation_id = save_observation(session_id, "user", "I have a class today.")
    record_id = create_foresight(
        {
            "content": "User has a class today.",
            "status": "active",
            "source_observation_id": source_observation_id,
        }
    )
    update_observation_id = save_observation(session_id, "user", "That was cancelled.")
    monkeypatch.setattr(foresight, "embed_text", lambda _text: [1.0])
    monkeypatch.setattr(
        foresight,
        "call_qwen_json",
        lambda *_args, **_kwargs: {
            "json": {
                "decisions": [
                    {
                        "target_id": record_id,
                        "action": "cancel",
                        "confidence": 0.99,
                        "reason": "Possible target, but the reference is ambiguous.",
                        "replacement_content": None,
                        "replacement_valid_until": None,
                    }
                ],
                "needs_clarification": True,
                "clarification": "Which event was cancelled?",
            }
        },
    )

    result = reconcile_foresight_lifecycle(
        update_observation_id,
        "That was cancelled.",
        session_id=session_id,
    )

    assert result["needs_clarification"] is True
    assert result["cancelled"] == []
    assert _record(record_id)["status"] == "active"


def test_semantic_reconciliation_uses_conservative_fallback_on_provider_failure(
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A visible provider failure retains the narrow explicit cancellation fallback."""
    session_id = create_session("jerry")
    source_observation_id = save_observation(session_id, "user", "I have a match today.")
    record_id = create_foresight(
        {
            "content": "User has a match today.",
            "status": "active",
            "source_observation_id": source_observation_id,
        }
    )
    cancellation_observation_id = save_observation(
        session_id,
        "user",
        "The match was cancelled.",
    )
    monkeypatch.setattr(foresight, "embed_text", lambda _text: [1.0])

    def fail_provider(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise LLMRequestError("provider unavailable")

    monkeypatch.setattr(foresight, "call_qwen_json", fail_provider)

    result = reconcile_foresight_lifecycle(
        cancellation_observation_id,
        "The match was cancelled.",
        session_id=session_id,
    )

    assert result["fallback_used"] is True
    assert result["cancelled"] == [record_id]
    assert _record(record_id)["status"] == "cancelled"


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
    record_id = create_foresight(
        {
            "content": "Hackathon submission was due 2026-06-01.",
            "status": "active",
            "source_observation_id": observation_id,
            "valid_until": "2026-06-01T23:59:59+00:00",
        }
    )

    assert list_relevant_foresight("hackathon", "2026-06-26T10:00:00+00:00") == []
    assert _status(record_id) == "expired"


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
                        "valid_until": "2026-07-01",
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
    assert records[0]["valid_until"] == "2026-07-01T23:59:59+00:00"
    assert records[0]["status"] == "active"

    record_id = create_foresight(records[0])
    assert _status(record_id) == "active"


def test_detect_foresight_accepts_a_same_day_upcoming_event(
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A remaining event window today is valid Foresight, not historical memory."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "I have a jog today.")

    monkeypatch.setattr(
        foresight,
        "call_qwen_json",
        lambda messages, schema_name: {
            "json": {
                "foresight": [
                    {
                        "content": "User has a jog today.",
                        "reason": "User stated a time-bounded activity today.",
                        "status": "active",
                        "always_inject": False,
                        "valid_until": "2026-07-22T23:59:59+01:00",
                    }
                ]
            }
        },
    )

    records = detect_foresight(
        observation_id,
        "I have a jog today.",
        {"current_time": "2026-07-22T07:00:00+01:00"},
    )

    assert len(records) == 1
    assert records[0]["content"] == "User has a jog today."
    assert records[0]["valid_until"] == "2026-07-22T23:59:59+01:00"


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
                        "valid_until": None,
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


def test_lifecycle_refresh_expires_record_and_promoted_hot_copy(database_path: Path) -> None:
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "The deadline was yesterday.")
    record_id = create_foresight(
        {
            "content": "The project deadline is 2026-07-01.",
            "status": "active",
            "source_observation_id": observation_id,
            "valid_until": "2026-07-01T23:59:59+00:00",
        }
    )
    hot_id = create_working_memory_item(
        {
            "content": "The project deadline is 2026-07-01.",
            "memory_type": "active_foresight",
            "scope": "cross_session",
            "priority": 0.9,
            "status": "active",
            "source_record_type": "foresight_records",
            "source_record_id": record_id,
        }
    )

    summary = refresh_foresight_lifecycle("2026-07-02T08:00:00+00:00")

    assert summary["expired"] == 1
    assert _status(record_id) == "expired"
    with repository_connection() as connection:
        hot_status = connection.execute(
            "SELECT status FROM working_memory WHERE id = ?", (hot_id,)
        ).fetchone()["status"]
    assert hot_status == "expired"
