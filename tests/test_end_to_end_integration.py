"""Verify ISSUE-060 full MIRA loop: session correction to cross-session recall.

Ownership: MIRA contributors.
Related issue: ISSUE-060.
Architecture area: integration.

This is the most important correctness test for the architecture. It exercises the
complete loop with a mocked LLM (no live model in CI):

  1. user states the project year is 2025
  2. user corrects it to 2030
  3. the Session Working Set updates immediately (session memory)
  4. the next response uses 2030
  5-6. the slow path confirms the correction and stores durable cross-session memory
  7. a new session starts
  8. hydration retrieves the project year from durable memory
  9-10. the user asks and MIRA answers 2030 (cross-session memory)
  11. the graph records the 2025 -> 2030 supersession

The slow path now runs through the real orchestrator entry point
(``run_slow_path_for_observation``, ISSUE-121) rather than manually wiring the
individual memory steps. Only the LLM-dependent extraction is mocked, per the
no-live-LLM-in-CI rule.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from core import agent
from core.agent import handle_user_message
from core.db.repositories import (
    configure_database,
    create_session,
    repository_connection,
)
from core.memory import slow_path
from core.memory.graph import find_edges_by_type
from core.memory.slow_path import run_slow_path_for_observation
from core.session.working_set import list_active_session_items

CORRECTION_MESSAGE = "Correction: use 2030 instead of 2025 for the project year."


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    """Configure the integration test to use an isolated database."""
    path = tmp_path / "mira.sqlite3"
    configure_database(path)
    yield path


@pytest.fixture
def year_aware_qwen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock Qwen to answer with whichever project year reached the prompt context.

    This makes "uses 2030" a real assertion: the answer reflects what the memory
    pipeline actually injected, not a canned string. 2030 (not the ambient/current
    year) is used so the answer cannot be satisfied by the injected ambient date.
    """

    def _call(messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
        prompt = messages[0]["content"]
        year = "2030" if "2030" in prompt else "2025" if "2025" in prompt else "unknown"
        return {"json": {"answer": f"The project year is {year}.", "used_memory_ids": []}}

    monkeypatch.setattr(agent, "call_qwen_json", _call)


@pytest.fixture
def slow_path_extraction(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock the slow path's LLM-dependent extraction (atomic facts and entities)."""

    def _facts(observation_id: str, content: str) -> list[dict[str, object]]:
        year = "2030" if "2030" in content else "2025"
        return [
            {
                "subject": "project year",
                "predicate": "IS",
                "object": year,
                "confidence": 0.9,
                "source_observation_id": observation_id,
            }
        ]

    monkeypatch.setattr(slow_path, "extract_atomic_facts", _facts)
    monkeypatch.setattr(slow_path, "extract_entities", lambda text: [])


def _correction_item(session_id: str) -> dict[str, object]:
    items = [item for item in list_active_session_items(session_id) if item["type"] == "correction"]
    assert items, "expected a session correction item"
    return items[0]


def _count(query: str, *params: object) -> int:
    with repository_connection() as connection:
        row = connection.execute(query, params).fetchone()
    return int(row[0])


def test_full_loop_session_correction_to_cross_session_recall(
    database_path: Path, year_aware_qwen: None, slow_path_extraction: None
) -> None:
    """The complete correction-to-recall loop is green end to end via the orchestrator."""
    # --- Session 1: original value, then correction -------------------------
    session_one = create_session("jerry")
    original = handle_user_message(session_one, "The project year is 2025.")
    assert "2025" in str(original["answer"])  # original value before correction
    run_slow_path_for_observation(str(original["user_observation_id"]))  # durable 2025 fact

    corrected = handle_user_message(session_one, CORRECTION_MESSAGE)
    # 3 + 4: Session Working Set updated immediately and the same response uses 2030.
    assert corrected["used_session_items"], "session correction must enter the working set"
    assert "2030" in str(corrected["answer"])

    # The next response in the same session still reflects 2030.
    follow_up = handle_user_message(session_one, "Remind me, what is the project year?")
    assert "2030" in str(follow_up["answer"])

    correction = _correction_item(session_one)
    correction_observation_id = str(correction["source_observations"][0])

    # --- Slow path: one orchestrator call confirms + stores durable memory ---
    result = run_slow_path_for_observation(correction_observation_id)
    assert result["succeeded"] is True

    # 6: cross-session memory now holds a durable confirmed-correction item.
    assert (
        _count(
            "SELECT COUNT(*) FROM working_memory WHERE source_record_type = 'session_working_set'"
        )
        >= 1
    )
    # 11: the graph records the 2025 -> 2030 supersession; the old fact is kept.
    assert len(find_edges_by_type("SUPERSEDED_BY")) == 1
    assert _count("SELECT COUNT(*) FROM atomic_facts WHERE object = '2025'") == 1

    # --- Session 2: new session, hydration, recall --------------------------
    session_two = create_session("jerry")
    recall = handle_user_message(session_two, "Continue: what project year are we using?")

    # 8 + 9 + 10: durable memory hydrated into the new session, MIRA answers 2030.
    assert "2030" in str(recall["answer"])
    hydrated = [
        item
        for item in list_active_session_items(session_two)
        if item["origin"] == "cross_session_hydration"
    ]
    assert hydrated, "the new session must hydrate durable cross-session memory"


def test_evidence_trace_exists(database_path: Path, year_aware_qwen: None) -> None:
    """Each turn produces an inspectable evidence trace."""
    session_id = create_session("jerry")
    response = handle_user_message(session_id, CORRECTION_MESSAGE)

    trace_id = str(response["trace_id"])
    assert trace_id
    assert _count("SELECT COUNT(*) FROM answer_traces WHERE id = ?", trace_id) == 1
    assert _count("SELECT COUNT(*) FROM prompt_logs WHERE session_id = ?", session_id) >= 1
    assert _count("SELECT COUNT(*) FROM retrieval_logs WHERE session_id = ?", session_id) >= 1

    # The session correction is grounded in a real source observation (evidence chain).
    correction = _correction_item(session_id)
    assert correction["source_observations"]
    observation_id = str(correction["source_observations"][0])
    assert _count("SELECT COUNT(*) FROM observations WHERE id = ?", observation_id) == 1


def test_session_and_cross_session_memory_both_participate(
    database_path: Path, year_aware_qwen: None, slow_path_extraction: None
) -> None:
    """Both the Session Working Set and durable memory take part in the loop."""
    session_one = create_session("jerry")
    corrected = handle_user_message(session_one, CORRECTION_MESSAGE)
    correction = _correction_item(session_one)

    # Session memory participated this turn.
    assert correction["id"] in corrected["used_session_items"]

    # Cross-session memory participates through the orchestrator (no manual wiring).
    run_slow_path_for_observation(str(correction["source_observations"][0]))
    with repository_connection() as connection:
        row = connection.execute(
            """
            SELECT source_record_type, source_record_id FROM working_memory
            WHERE source_record_id = ?
            """,
            (str(correction["id"]),),
        ).fetchone()
    assert row is not None
    assert row["source_record_type"] == "session_working_set"
    assert row["source_record_id"] == str(correction["id"])
