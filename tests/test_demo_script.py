"""Verify ISSUE-050 end-to-end demo script.

Ownership: MIRA contributors.
Related issue: ISSUE-050.
Architecture area: demo.
"""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEMO_DOC = PROJECT_ROOT / "docs" / "demo-script.md"

REQUIRED_BEATS = (
    "User correction updates Session Working Set immediately",
    "next response respects 2026 before slow-path confirmation",
    "slow path confirmation or rejection",
    "Relational Mode",
    "SUPERSEDED_BY",
    "CONTRADICTS",
    "Deep Mode",
    "community summaries",
    "Foresight activates from the hackathon deadline",
    "Retrieval Trace explains the answer",
)

REQUIRED_SCREENS = (
    "Chat",
    "Session Working Set",
    "Memory Inspector",
    "Graph Viewer",
    "Retrieval Trace",
    "Foresight Timeline",
    "Evaluation Dashboard",
)


def test_demo_doc_exists() -> None:
    """The demo runbook exists in docs."""
    assert DEMO_DOC.is_file()


def test_demo_completes_under_five_minutes() -> None:
    """The scripted target runtime is under five minutes."""
    text = _demo_text()
    match = re.search(r"Target runtime:\s+\*\*(\d+) minutes (\d+) seconds\*\*", text)

    assert match is not None
    minutes = int(match.group(1))
    seconds = int(match.group(2))
    assert (minutes * 60) + seconds <= 300


def test_each_feature_has_expected_demo_beat() -> None:
    """Every required architecture feature appears in the demo narrative."""
    text = _demo_text()

    for beat in REQUIRED_BEATS:
        assert beat in text


def test_each_feature_has_expected_ui_screen() -> None:
    """The runbook names every expected UI screen."""
    text = _demo_text()

    for screen in REQUIRED_SCREENS:
        assert screen in text


def test_readme_links_demo_doc() -> None:
    """The README points teammates to the demo script."""
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

    assert "docs/demo-script.md" in readme


def _demo_text() -> str:
    return DEMO_DOC.read_text(encoding="utf-8")
