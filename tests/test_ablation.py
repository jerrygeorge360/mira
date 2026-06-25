"""Verify ISSUE-053 architecture ablation study.

Ownership: MIRA contributors.
Related issue: ISSUE-053.
Architecture area: evaluation.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from core import agent
from core.agent import handle_user_message
from core.db.repositories import configure_database, create_session
from evaluation.ablation import (
    ABLATION_COMPONENTS,
    AblationConfig,
    apply_ablation,
    render_ablation_table,
    run_ablation,
    run_ablation_study,
    standard_ablations,
)


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    """Configure ablation tests to use an isolated database."""
    path = tmp_path / "mira.sqlite3"
    configure_database(path)
    yield path


@pytest.fixture
def fake_qwen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock the Qwen call with a deterministic answer."""

    def _call(messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
        return {"json": {"answer": "Your deadline is Friday.", "used_memory_ids": []}}

    monkeypatch.setattr(agent, "call_qwen_json", _call)


def _write_cases(tmp_path: Path) -> Path:
    cases = {
        "cases": [
            {
                "id": "fact",
                "category": "direct_fact_recall",
                "interactions": [{"message": "What is my deadline?"}],
                "expect": {"retrieval_mode": "quick"},
            },
            {
                "id": "correction",
                "category": "session_correction_handling",
                "interactions": [{"message": "Use 2026, not 2025."}],
                "expect": {"used_session_items_nonempty": True},
            },
        ]
    }
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(cases), encoding="utf-8")
    return path


def test_ablation_flags_and_configs_exist() -> None:
    """The architecture ablation flags and standard configs are defined."""
    assert "session_working_set" in ABLATION_COMPONENTS
    assert "vector_only" in ABLATION_COMPONENTS

    names = {config.name for config in standard_ablations()}
    assert "full_system" in names
    assert "without_session_working_set" in names
    assert "vector_only_baseline" in names


def test_evaluation_can_disable_session_working_set(database_path: Path, fake_qwen: None) -> None:
    """Disabling the Session Working Set genuinely removes it from the turn."""
    session_id = create_session("jerry")
    baseline = handle_user_message(session_id, "Use 2026, not 2025.")
    assert baseline["used_session_items"]  # present in the full system

    ablated_session = create_session("jerry")
    with apply_ablation(AblationConfig("no_sws", frozenset({"session_working_set"}))):
        ablated = handle_user_message(ablated_session, "Use 2026, not 2025.")
    assert ablated["used_session_items"] == []  # genuinely disabled

    # The seam is restored after the context exits.
    restored_session = create_session("jerry")
    restored = handle_user_message(restored_session, "Use 2026, not 2025.")
    assert restored["used_session_items"]


def test_evaluation_can_disable_deep_mode(database_path: Path, fake_qwen: None) -> None:
    """Disabling Deep Mode downgrades a broad query to Quick."""
    session_id = create_session("jerry")
    baseline = handle_user_message(session_id, "What kind of developer am I?")
    assert baseline["retrieval_mode"] == "deep"

    ablated_session = create_session("jerry")
    with apply_ablation(AblationConfig("no_deep", frozenset({"deep_mode"}))):
        ablated = handle_user_message(ablated_session, "What kind of developer am I?")
    assert ablated["retrieval_mode"] == "quick"


def test_output_table_generated_from_cases(
    database_path: Path, tmp_path: Path, fake_qwen: None
) -> None:
    """An ablation study produces a comparison table over the test cases."""
    cases_path = _write_cases(tmp_path)

    study = run_ablation_study(
        str(cases_path),
        configs=[
            AblationConfig("full_system", frozenset()),
            AblationConfig("without_session_working_set", frozenset({"session_working_set"})),
        ],
    )

    assert len(study["rows"]) == 2
    table = str(study["table"])
    assert "Pass rate" in table
    assert "full_system" in table
    assert "without_session_working_set" in table


def test_run_ablation_reports_coverage(
    database_path: Path, tmp_path: Path, fake_qwen: None
) -> None:
    """A slow-path-only ablation is honestly noted, not faked."""
    cases_path = _write_cases(tmp_path)

    result = run_ablation(["contradiction_supersession"], cases_path=str(cases_path))

    assert result["disabled"] == ["contradiction_supersession"]
    assert "slow-path-only" in result["note"]


def test_render_ablation_table_has_header() -> None:
    """The rendered table is Markdown with the expected header."""
    table = render_ablation_table([])
    assert table.splitlines()[0].startswith("| Config | Disabled |")
