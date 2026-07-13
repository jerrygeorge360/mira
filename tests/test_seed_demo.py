"""Verify ISSUE-049 deterministic demo seeding.

Ownership: MIRA contributors.
Related issue: ISSUE-049.
Architecture area: demo.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from core.db.repositories import repository_connection
from core.db.schema import LEGACY_WORKSPACE_ID
from scripts.seed_demo import seed_demo_data
from ui.foresight_view import load_foresight
from ui.graph_viz import load_graph
from ui.session_view import load_session_items


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    """Provide an isolated database path for the seed."""
    yield tmp_path / "demo.sqlite3"


def _count(table: str) -> int:
    with repository_connection() as connection:
        row = connection.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()  # noqa: S608
    return int(row["n"])


def test_seed_creates_demo_database(database_path: Path) -> None:
    """Running the seed populates every demo-relevant table."""
    summary = seed_demo_data(str(database_path), LEGACY_WORKSPACE_ID)

    assert summary["status"] == "seeded"
    assert database_path.exists()
    assert _count("sessions") == 1
    assert _count("observations") >= 5
    assert _count("session_working_set") == 3
    assert _count("atomic_facts") >= 4
    assert _count("foresight_records") == 1
    assert _count("reflections") == 2
    assert _count("community_summaries") == 1
    assert _count("graph_edges") >= 5
    assert _count("retrieval_logs") == 1
    assert _count("prompt_logs") == 1
    assert _count("answer_traces") == 1


def test_running_twice_does_not_corrupt(database_path: Path) -> None:
    """A second seed is idempotent: it detects existing data and no-ops."""
    first = seed_demo_data(str(database_path), LEGACY_WORKSPACE_ID)
    observations_before = _count("observations")
    edges_before = _count("graph_edges")

    second = seed_demo_data(str(database_path), LEGACY_WORKSPACE_ID)

    assert second["status"] == "already_seeded"
    assert second["session_id"] == first["session_id"]
    assert _count("observations") == observations_before
    assert _count("graph_edges") == edges_before
    assert _count("sessions") == 1


def test_reset_rebuilds_demo(database_path: Path) -> None:
    """The reset flag rebuilds the demo without accumulating duplicates."""
    seed_demo_data(str(database_path), LEGACY_WORKSPACE_ID)
    observations_before = _count("observations")

    summary = seed_demo_data(str(database_path), LEGACY_WORKSPACE_ID, reset=True)

    assert summary["status"] == "seeded"
    assert _count("sessions") == 1
    assert _count("observations") == observations_before
    assert _count("foresight_records") == 1


def test_ui_pages_have_meaningful_data(database_path: Path) -> None:
    """The seeded data is consumable by the UI page loaders."""
    summary = seed_demo_data(str(database_path), LEGACY_WORKSPACE_ID)
    session_id = str(summary["session_id"])

    session_items = load_session_items(session_id)
    assert {str(item["status"]) for item in session_items} >= {"provisional", "rejected"}

    graph = load_graph(LEGACY_WORKSPACE_ID)
    edge_types = {str(edge["type"]) for edge in graph["edges"]}
    assert {"CONTRADICTS", "SUPERSEDED_BY"} <= edge_types

    foresight = load_foresight(LEGACY_WORKSPACE_ID)
    assert any("hackathon" in str(record["content"]).lower() for record in foresight)
