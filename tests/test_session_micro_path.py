"""Verify the ISSUE-201 session micro-path orchestration.

Ownership: MIRA contributors.
Related issue: ISSUE-201.
Architecture area: session micro-path.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from core.db.repositories import configure_database, create_session, save_observation
from core.session import micro_path
from core.session.micro_path import run_session_micro_path
from core.session.working_set import list_active_session_items, upsert_session_item


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    """Configure the micro-path to use an isolated database."""
    path = tmp_path / "mira.sqlite3"
    configure_database(path)
    yield path


def _existing_item(observation_id: str, *, content: str) -> dict[str, object]:
    return {
        "type": "correction",
        "content": content,
        "scope": "current_session",
        "status": "provisional",
        "priority": 0.6,
        "explicitness_label": "direct_correction",
        "evidence_span": content,
        "source_observations": [observation_id],
        "supersedes": [],
    }


def test_correction_creates_new_session_item(database_path: Path) -> None:
    """A direct correction turn creates a new Session Working Set item."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "Use 2026, not 2025.")

    changed_ids = run_session_micro_path(session_id, observation_id, "Use 2026, not 2025.", [])

    active_items = list_active_session_items(session_id)
    assert len(changed_ids) == 1
    assert [item["id"] for item in active_items] == changed_ids
    assert active_items[0]["type"] == "correction"
    assert active_items[0]["content"] == "Use 2026, not 2025."
    assert active_items[0]["source_observations"] == [observation_id]


def test_supersede_operation_updates_old_item(database_path: Path) -> None:
    """A correction matching an existing item supersedes that item."""
    session_id = create_session("jerry")
    seed_observation = save_observation(session_id, "user", "Use 2025.")
    old_id = upsert_session_item(session_id, _existing_item(seed_observation, content="use 2025"))
    observation_id = save_observation(session_id, "user", "Do not use 2025, use 2026 instead.")

    changed_ids = run_session_micro_path(
        session_id, observation_id, "Do not use 2025, use 2026 instead.", []
    )

    active_items = list_active_session_items(session_id)
    active_ids = [item["id"] for item in active_items]
    assert old_id in changed_ids
    assert old_id not in active_ids
    new_id = next(item_id for item_id in changed_ids if item_id != old_id)
    assert active_ids == [new_id]
    assert active_items[0]["supersedes"] == [old_id]


def test_invalid_operation_is_logged_and_ignored(
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Operations that fail validation are logged and never applied."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "Use 2026, not 2025.")

    def _fake_extract(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        return [{"op": "teleport", "type": "correction"}]

    monkeypatch.setattr(micro_path, "extract_session_operations", _fake_extract)

    with caplog.at_level(logging.WARNING, logger="core.session.micro_path"):
        changed_ids = run_session_micro_path(session_id, observation_id, "Use 2026, not 2025.", [])

    assert changed_ids == []
    assert list_active_session_items(session_id) == []
    assert "Rejected micro-path operation" in caplog.text


def test_no_op_does_not_change_state(database_path: Path) -> None:
    """Ambiguous low-confidence turns leave the working set untouched."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "Maybe I might use Python later.")

    changed_ids = run_session_micro_path(
        session_id, observation_id, "Maybe I might use Python later.", []
    )

    assert changed_ids == []
    assert list_active_session_items(session_id) == []
