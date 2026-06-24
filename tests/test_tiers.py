"""Verify ISSUE-031 cold/warm/hot memory tier policy.

Ownership: MIRA contributors.
Related issue: ISSUE-031.
Architecture area: slow path.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from core.db.repositories import (
    configure_database,
    create_reflection,
    create_session,
    repository_connection,
    save_observation,
)
from core.memory import tiers
from core.memory.foresight import create_foresight
from core.memory.tiers import (
    demote_hot_memory_item,
    evaluate_promotion_candidate,
    list_hot_memory_for_context,
    promote_to_hot_memory,
)
from core.session.working_set import upsert_session_item


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    """Configure tier-policy tests to use an isolated database."""
    path = tmp_path / "mira.sqlite3"
    configure_database(path)
    yield path


def _project_correction(session_id: str, content: str = "Use ISO dates everywhere.") -> str:
    observation_id = save_observation(session_id, "user", content)
    return upsert_session_item(
        session_id,
        {
            "type": "correction",
            "content": content,
            "scope": "project",
            "status": "confirmed",
            "priority": 0.9,
            "explicitness_label": "direct_correction",
            "evidence_span": content,
            "source_observations": [observation_id],
            "supersedes": [],
        },
    )


def _hot_status(item_id: str) -> str:
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT status FROM working_memory WHERE id = ?",
            (item_id,),
        ).fetchone()
    assert row is not None
    return str(row["status"])


def _active_hot_count() -> int:
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM working_memory WHERE status = ?",
            ("active",),
        ).fetchone()
    assert row is not None
    return int(row["count"])


def test_direct_project_correction_becomes_hot_memory(database_path: Path) -> None:
    """A confirmed project correction is eligible and promotes into hot memory."""
    session_id = create_session("jerry")
    item_id = _project_correction(session_id)

    candidate = evaluate_promotion_candidate("session_working_set", item_id)
    assert candidate["eligible"] is True
    assert candidate["memory_type"] == "confirmed_correction"

    hot_id = promote_to_hot_memory(candidate)

    listed = list_hot_memory_for_context(session_id, "Which date format do we use?", limit=10)
    assert [item["id"] for item in listed] == [hot_id]
    assert listed[0]["content"] == "Use ISO dates everywhere."


def test_expired_foresight_demotes(database_path: Path) -> None:
    """A promoted foresight item demotes once expired and leaves the hot pool."""
    session_id = create_session("jerry")
    observation_id = save_observation(session_id, "user", "Submit the grant before Friday.")
    foresight_id = create_foresight(
        {
            "content": "Grant submission is due Friday.",
            "status": "active",
            "source_observation_id": observation_id,
            "always_inject": True,
        }
    )
    candidate = evaluate_promotion_candidate("foresight_records", foresight_id)
    hot_id = promote_to_hot_memory(candidate)
    assert _hot_status(hot_id) == "active"

    demote_hot_memory_item(hot_id, "expired")

    assert _hot_status(hot_id) == "expired"
    assert list_hot_memory_for_context(session_id, "grant submission", limit=10) == []


def test_stale_reflection_removed_from_hot_eligibility(database_path: Path) -> None:
    """A stale reflection is not eligible for promotion, and a hot item live-filters out."""
    session_id = create_session("jerry")
    save_observation(session_id, "user", "The project prefers repository APIs.")
    active_reflection_id = create_reflection(
        {
            "reflection_type": "self_knowledge",
            "content": "The project prefers repository APIs over ad-hoc SQL.",
            "confidence": 0.86,
            "status": "active",
        }
    )
    hot_id = promote_to_hot_memory(
        evaluate_promotion_candidate("reflections", active_reflection_id)
    )
    assert list_hot_memory_for_context(session_id, "repository APIs", limit=10)[0]["id"] == hot_id

    stale_reflection_id = create_reflection(
        {
            "reflection_type": "self_knowledge",
            "content": "Outdated stale belief about the project.",
            "confidence": 0.9,
            "status": "stale",
        }
    )
    candidate = evaluate_promotion_candidate("reflections", stale_reflection_id)
    assert candidate["eligible"] is False

    # A reflection that goes stale after promotion is live-filtered from context.
    with repository_connection() as connection:
        connection.execute(
            "UPDATE reflections SET status = ? WHERE id = ?",
            ("stale", active_reflection_id),
        )
    assert list_hot_memory_for_context(session_id, "repository APIs", limit=10) == []


def test_hot_tier_respects_max_size(
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Promotions beyond the cap demote the lowest-priority item to stay bounded."""
    monkeypatch.setattr(tiers, "HOT_TIER_MAX", 2)
    session_id = create_session("jerry")

    ids = []
    for index, priority in enumerate((0.55, 0.7, 0.95)):
        observation_id = save_observation(session_id, "user", f"correction number {index}")
        item_id = upsert_session_item(
            session_id,
            {
                "type": "correction",
                "content": f"Correction number {index}.",
                "scope": "project",
                "status": "confirmed",
                "priority": priority,
                "explicitness_label": "direct_correction",
                "evidence_span": f"correction number {index}",
                "source_observations": [observation_id],
                "supersedes": [],
            },
        )
        candidate = evaluate_promotion_candidate("session_working_set", item_id)
        ids.append(promote_to_hot_memory(candidate))

    assert _active_hot_count() == 2
    # The first (lowest-priority) promotion was demoted for capacity.
    assert _hot_status(ids[0]) == "demoted"
    assert _hot_status(ids[2]) == "active"


def test_unsupported_record_type_is_rejected(database_path: Path) -> None:
    """Unknown record types are rejected rather than silently scored."""
    with pytest.raises(ValueError, match="unsupported record_type"):
        evaluate_promotion_candidate("mystery_table", "some-id")


def test_ineligible_candidate_cannot_be_promoted(database_path: Path) -> None:
    """Promotion refuses a candidate the policy marked ineligible."""
    candidate = {
        "record_type": "reflections",
        "record_id": "missing",
        "eligible": False,
        "reason": "source record not found",
    }
    with pytest.raises(ValueError, match="not eligible"):
        promote_to_hot_memory(candidate)
