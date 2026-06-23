"""Verify the ISSUE-014 session-item confirmation lifecycle.

Ownership: MIRA contributors.
Related issue: ISSUE-014.
Architecture area: session micro-path.
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
from core.session.confirmation import (
    confirm_session_item,
    downgrade_session_item_scope,
    mark_session_item_forward_only,
    promote_session_item_to_durable_candidate,
    reject_session_item_after_review,
)
from core.session.working_set import export_prompt_ready_session_items, upsert_session_item


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    """Configure the confirmation lifecycle to use an isolated database."""
    path = tmp_path / "mira.sqlite3"
    configure_database(path)
    yield path


def _seed_item(
    session_id: str,
    content: str,
    *,
    item_type: str = "correction",
    scope: str = "current_session",
    explicitness_label: str = "direct_correction",
    priority: float = 0.9,
) -> str:
    observation_id = save_observation(session_id, "user", content)
    return upsert_session_item(
        session_id,
        {
            "type": item_type,
            "content": content,
            "scope": scope,
            "status": "provisional",
            "priority": priority,
            "explicitness_label": explicitness_label,
            "evidence_span": content,
            "source_observations": [observation_id],
            "supersedes": [],
        },
    )


def _item_status(item_id: str) -> str | None:
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT status FROM session_working_set WHERE id = ?",
            (item_id,),
        ).fetchone()
    return None if row is None else str(row["status"])


def _item_scope_and_reason(item_id: str) -> tuple[str, str | None]:
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT scope, resolution_reason FROM session_working_set WHERE id = ?",
            (item_id,),
        ).fetchone()
    if row is None:
        raise AssertionError(f"missing session item {item_id}")
    reason = row["resolution_reason"]
    return str(row["scope"]), None if reason is None else str(reason)


def _working_memory_item(candidate_id: str) -> dict[str, object] | None:
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT * FROM working_memory WHERE id = ?",
            (candidate_id,),
        ).fetchone()
    return None if row is None else dict(row)


def test_provisional_correction_confirmed(database_path: Path) -> None:
    """A grounded, explicit provisional correction clears the gate and is confirmed."""
    session_id = create_session("jerry")
    item_id = _seed_item(session_id, "Use 2026, not 2025.")

    confirm_session_item(item_id, "kelechi")

    assert _item_status(item_id) == "confirmed"


def test_ambiguous_item_rejected(database_path: Path) -> None:
    """An ambiguous item fails explicitness re-verification and is rejected."""
    session_id = create_session("jerry")
    item_id = _seed_item(
        session_id,
        "Should we maybe add recursive summaries?",
        item_type="open_question",
        explicitness_label="ambiguous",
    )

    confirm_session_item(item_id, "kelechi")

    assert _item_status(item_id) == "rejected"
    assert export_prompt_ready_session_items(session_id, 10) == []


def test_project_item_promoted_to_durable_candidate(database_path: Path) -> None:
    """A project-scoped item is promoted into a durable working-memory candidate."""
    session_id = create_session("jerry")
    item_id = _seed_item(
        session_id,
        "Community summaries must stay distinct from recursive summaries.",
        item_type="active_constraint",
        scope="project",
        explicitness_label="direct_instruction",
    )

    candidate_id = promote_session_item_to_durable_candidate(item_id)

    candidate = _working_memory_item(candidate_id)
    assert candidate is not None
    assert candidate["memory_type"] == "project_constraint"
    assert candidate["scope"] == "project"
    assert candidate["source_record_id"] == item_id
    assert _item_status(item_id) == "confirmed"


def test_scope_downgrade_is_forward_only(database_path: Path) -> None:
    """A broad item can be narrowed without changing its prior influence."""
    session_id = create_session("jerry")
    item_id = _seed_item(
        session_id,
        "For this project, prefer plain sqlite3 repositories.",
        item_type="active_constraint",
        scope="project",
        explicitness_label="direct_instruction",
    )

    downgrade_session_item_scope(item_id, "current_session", "Only relevant to current work.")

    scope, reason = _item_scope_and_reason(item_id)
    assert scope == "current_session"
    assert reason == "scope_downgraded:Only relevant to current work."


def test_scope_downgrade_rejects_widening(database_path: Path) -> None:
    """Downgrade cannot accidentally widen session-only evidence to durable scope."""
    session_id = create_session("jerry")
    item_id = _seed_item(session_id, "Use repository helpers for this session.")

    with pytest.raises(ValueError, match="new_scope must narrow"):
        downgrade_session_item_scope(item_id, "project", "Make durable.")


def test_local_current_response_item_expires(database_path: Path) -> None:
    """A current-response item retired forward-only expires from future prompts."""
    session_id = create_session("jerry")
    item_id = _seed_item(
        session_id,
        "Only for this reply: answer in one sentence.",
        item_type="active_constraint",
        scope="current_response",
        explicitness_label="direct_instruction",
    )

    mark_session_item_forward_only(item_id, "Response completed.")

    assert _item_status(item_id) == "expired"
    assert export_prompt_ready_session_items(session_id, 10) == []


def test_later_resolution_blocks_confirmation(database_path: Path) -> None:
    """A newer explicit resolution prevents an older provisional item from confirming."""
    session_id = create_session("jerry")
    original_id = _seed_item(session_id, "Use recursive summaries for communities.")
    observation_id = save_observation(session_id, "user", "Ignore that recursive summary idea.")
    upsert_session_item(
        session_id,
        {
            "type": "resolution",
            "content": "Ignore the recursive summary idea.",
            "scope": "current_session",
            "status": "provisional",
            "priority": 0.95,
            "explicitness_label": "direct_instruction",
            "evidence_span": "Ignore that recursive summary idea.",
            "source_observations": [observation_id],
            "supersedes": [original_id],
        },
    )

    confirm_session_item(original_id, "kelechi")

    assert _item_status(original_id) == "rejected"


def test_missing_source_grounding_blocks_promotion(database_path: Path) -> None:
    """Durable promotion requires source observations that exist in cold storage."""
    session_id = create_session("jerry")
    item_id = upsert_session_item(
        session_id,
        {
            "type": "active_constraint",
            "content": "Use project scope only when the user is explicit.",
            "scope": "project",
            "status": "provisional",
            "priority": 0.9,
            "explicitness_label": "direct_instruction",
            "evidence_span": "Use project scope only when the user is explicit.",
            "source_observations": ["obs_missing"],
            "supersedes": [],
        },
    )

    with pytest.raises(ValueError, match="ungrounded_source_observations"):
        promote_session_item_to_durable_candidate(item_id)


def test_rejected_item_not_in_prompt_export(database_path: Path) -> None:
    """A rejected item no longer appears in prompt export."""
    session_id = create_session("jerry")
    item_id = _seed_item(session_id, "Use repository helpers, not raw SQL.")

    reject_session_item_after_review(item_id, "Contradicted by a later turn.")

    assert _item_status(item_id) == "rejected"
    assert export_prompt_ready_session_items(session_id, 10) == []
