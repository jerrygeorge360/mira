"""Verify the ISSUE-010 Session Working Set runtime store.

Ownership: MIRA contributors.
Related issue: ISSUE-010.
Architecture area: session micro-path.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.db.repositories import configure_database, create_session, save_observation
from core.db.sqlite import connect_sqlite
from core.session.working_set import (
    expire_session_item,
    export_prompt_ready_session_items,
    list_active_session_items,
    reject_session_item,
    resolve_session_item,
    supersede_session_item,
    upsert_session_item,
)


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    """Configure the Session Working Set to use an isolated database."""
    path = tmp_path / "mira.sqlite3"
    configure_database(path)
    yield path


def _item(
    observation_id: str,
    *,
    item_type: str = "active_constraint",
    content: str = "Use repository functions.",
    scope: str = "current_task",
    status: str = "provisional",
    priority: float = 0.5,
) -> dict[str, object]:
    return {
        "type": item_type,
        "content": content,
        "scope": scope,
        "status": status,
        "priority": priority,
        "explicitness_label": "direct_instruction",
        "evidence_span": "Use repository functions.",
        "source_observations": [observation_id],
        "supersedes": [],
    }


def _working_memory_count(database_path: Path) -> int:
    with connect_sqlite(database_path) as connection:
        row = connection.execute("SELECT COUNT(*) AS count FROM working_memory").fetchone()
    assert row is not None
    return int(row["count"])


def test_upsert_active_constraint(database_path: Path) -> None:
    """A current-session active constraint can be inserted and updated."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "Use repository functions.")
    item_id = upsert_session_item(session_id, _item(observation_id))

    updated_id = upsert_session_item(
        session_id,
        {
            **_item(observation_id, content="Use typed repository functions.", priority=0.9),
            "id": item_id,
        },
    )
    active_items = list_active_session_items(session_id)

    assert updated_id == item_id
    assert active_items[0]["content"] == "Use typed repository functions."
    assert active_items[0]["source_observations"] == [observation_id]
    assert _working_memory_count(database_path) == 0


def test_supersede_old_correction(database_path: Path) -> None:
    """A newer correction can supersede an older correction."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "Use SQLite.")
    old_id = upsert_session_item(
        session_id,
        _item(
            observation_id,
            item_type="correction",
            content="Use raw SQL everywhere.",
            priority=0.6,
        ),
    )
    new_id = upsert_session_item(
        session_id,
        _item(
            observation_id,
            item_type="correction",
            content="Use repository helpers, not raw SQL.",
            priority=0.8,
        ),
    )

    supersede_session_item(session_id, old_id, new_id)
    active_items = list_active_session_items(session_id)

    assert [item["id"] for item in active_items] == [new_id]
    assert active_items[0]["supersedes"] == [old_id]


def test_resolve_open_question(database_path: Path) -> None:
    """Resolved open questions are retained historically but not active."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "Should this be durable?")
    item_id = upsert_session_item(
        session_id,
        _item(
            observation_id,
            item_type="open_question",
            content="Should this be durable?",
        ),
    )

    resolve_session_item(session_id, item_id, "Answered during the current task.")

    assert list_active_session_items(session_id) == []


def test_expire_temporary_current_response_item(database_path: Path) -> None:
    """Expired current-response items are not exported."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "Only for the next reply.")
    item_id = upsert_session_item(
        session_id,
        _item(
            observation_id,
            content="Only for the next reply.",
            scope="current_response",
            priority=1.0,
        ),
    )

    expire_session_item(session_id, item_id, "Response completed.")

    assert export_prompt_ready_session_items(session_id, 10) == []


def test_reject_requires_reason(database_path: Path) -> None:
    """Rejected session items require an explicit reason."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "Maybe false.")
    item_id = upsert_session_item(session_id, _item(observation_id))

    with pytest.raises(ValueError, match="reason must not be empty"):
        reject_session_item(session_id, item_id, "")

    reject_session_item(session_id, item_id, "Contradicted by the user.")
    assert list_active_session_items(session_id) == []


def test_export_prompt_ready_items_in_priority_order(database_path: Path) -> None:
    """Prompt export prioritizes relevant statuses, priority, type, freshness, and scope."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "Sort session items.")
    upsert_session_item(
        session_id,
        _item(
            observation_id,
            item_type="decision",
            content="Older decision.",
            status="provisional",
            priority=0.8,
        ),
    )
    correction_id = upsert_session_item(
        session_id,
        _item(
            observation_id,
            item_type="correction",
            content="Newer correction.",
            status="provisional",
            priority=0.8,
        ),
    )
    active_id = upsert_session_item(
        session_id,
        _item(
            observation_id,
            item_type="current_goal",
            content="Confirmed goal.",
            status="confirmed",
            priority=0.1,
        ),
    )
    expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)  # noqa: UP017
    upsert_session_item(
        session_id,
        {
            **_item(observation_id, content="Already expired.", priority=1.0),
            "expires_at": expires_at.isoformat(),
        },
    )

    exported = export_prompt_ready_session_items(session_id, 2)

    assert [item["id"] for item in exported] == [active_id, correction_id]
    prompt_statuses = {"active", "confirmed", "hydrated", "provisional"}
    assert all(item["status"] in prompt_statuses for item in exported)
