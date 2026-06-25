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

Because the asynchronous slow-path *orchestrator* (core/memory/slow_path.py) is still a
stub, the slow-path *steps* are driven here with the real implemented functions
(confirmation, promotion, atomic facts, graph edges) -- exactly what the orchestrator will
chain once built.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from core import agent
from core.agent import handle_user_message
from core.db.repositories import (
    configure_database,
    create_atomic_fact,
    create_session,
    repository_connection,
)
from core.memory.graph import create_graph_edge, create_graph_node, find_edges_by_type
from core.session.confirmation import (
    confirm_session_item,
    promote_session_item_to_durable_candidate,
)
from core.session.working_set import list_active_session_items


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
    pipeline actually injected, not a canned string.
    """

    def _call(messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
        # 2030 is used as the corrected year (not the ambient/current year) so the
        # answer can only be satisfied by the memory pipeline, not the ambient date.
        prompt = messages[0]["content"]
        year = "2030" if "2030" in prompt else "2025" if "2025" in prompt else "unknown"
        return {"json": {"answer": f"The project year is {year}.", "used_memory_ids": []}}

    monkeypatch.setattr(agent, "call_qwen_json", _call)


def _correction_item(session_id: str) -> dict[str, object]:
    items = [item for item in list_active_session_items(session_id) if item["type"] == "correction"]
    assert items, "expected a session correction item"
    return items[0]


def _consolidate_correction_slow_path(
    correction_item_id: str,
    old_observation_id: str,
    new_observation_id: str,
) -> str:
    """Drive the slow-path steps the orchestrator will eventually chain."""
    # 5. confirm the provisional session correction.
    confirm_session_item(correction_item_id, "slow_path")
    # 6. promote it into durable cross-session (hot) memory.
    candidate_id = promote_session_item_to_durable_candidate(correction_item_id)
    # Durable atomic facts: old superseded, new active.
    old_fact = create_atomic_fact(
        {
            "subject": "MIRA project",
            "predicate": "HAS_YEAR",
            "object": "2025",
            "confidence": 0.9,
            "status": "superseded",
            "source_observation_id": old_observation_id,
        }
    )
    new_fact = create_atomic_fact(
        {
            "subject": "MIRA project",
            "predicate": "HAS_YEAR",
            "object": "2030",
            "confidence": 0.95,
            "status": "active",
            "source_observation_id": new_observation_id,
        }
    )
    # 11. graph supersession edge 2025 -> 2030.
    old_node = create_graph_node(
        node_type="atomic_fact",
        label="MIRA project HAS_YEAR 2025",
        source_table="atomic_facts",
        source_id=old_fact,
    )
    new_node = create_graph_node(
        node_type="atomic_fact",
        label="MIRA project HAS_YEAR 2030",
        source_table="atomic_facts",
        source_id=new_fact,
    )
    create_graph_edge(old_node, new_node, "SUPERSEDED_BY", 0.95, [new_observation_id])
    return candidate_id


def _count(query: str, parameter: str) -> int:
    with repository_connection() as connection:
        row = connection.execute(query, (parameter,)).fetchone()
    return int(row[0])


def test_full_loop_session_correction_to_cross_session_recall(
    database_path: Path, year_aware_qwen: None
) -> None:
    """The complete correction-to-recall loop is green end to end."""
    # --- Session 1: original value, then correction -------------------------
    session_one = create_session("jerry")
    original = handle_user_message(session_one, "The project year is 2025.")
    assert "2025" in str(original["answer"])  # original value before correction

    corrected = handle_user_message(session_one, "Correction: the project year is 2030, not 2025.")
    # 3 + 4: Session Working Set updated immediately and the same response uses 2030.
    assert corrected["used_session_items"], "session correction must enter the working set"
    assert "2030" in str(corrected["answer"])

    # The next response in the same session still reflects 2030.
    follow_up = handle_user_message(session_one, "Remind me, what is the project year?")
    assert "2030" in str(follow_up["answer"])

    correction = _correction_item(session_one)
    correction_id = str(correction["id"])
    new_observation_id = str(correction["source_observations"][0])

    # --- Slow path: confirm + store durable cross-session memory -------------
    candidate_id = _consolidate_correction_slow_path(
        correction_id,
        old_observation_id=str(original["user_observation_id"]),
        new_observation_id=new_observation_id,
    )

    # 6: cross-session memory now holds a durable confirmed-correction fact.
    assert (
        _count(
            "SELECT COUNT(*) FROM working_memory WHERE id = ? AND status = 'active'", candidate_id
        )
        == 1
    )
    # 11: the graph records the 2025 -> 2030 supersession.
    supersession_edges = find_edges_by_type("SUPERSEDED_BY")
    assert len(supersession_edges) == 1
    assert supersession_edges[0]["source_observations"] == [new_observation_id]

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
    response = handle_user_message(session_id, "Correction: the project year is 2030, not 2025.")

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
    database_path: Path, year_aware_qwen: None
) -> None:
    """Both the Session Working Set and durable memory take part in the loop."""
    session_one = create_session("jerry")
    original = handle_user_message(session_one, "The project year is 2025.")
    corrected = handle_user_message(session_one, "Correction: the project year is 2030, not 2025.")
    correction = _correction_item(session_one)

    # Session memory participated this turn.
    assert correction["id"] in corrected["used_session_items"]

    candidate_id = _consolidate_correction_slow_path(
        str(correction["id"]),
        old_observation_id=str(original["user_observation_id"]),
        new_observation_id=str(correction["source_observations"][0]),
    )
    # Cross-session memory participated: durable candidate links back to the session item.
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT source_record_type, source_record_id FROM working_memory WHERE id = ?",
            (candidate_id,),
        ).fetchone()
    assert row["source_record_type"] == "session_working_set"
    assert row["source_record_id"] == str(correction["id"])
