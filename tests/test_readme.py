"""Verify ISSUE-057 README is professional and matches paper terminology.

Ownership: MIRA contributors.
Related issue: ISSUE-057.
Architecture area: docs.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
README = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")


def test_readme_explains_mira_and_sections_for_new_contributor() -> None:
    """A new contributor can find the description and the key sections."""
    assert "Memory-Integrated Reasoning Architecture" in README
    for section in (
        "## Session memory vs. cross-session memory",
        "## Architecture flow",
        "## Setup",
        "## Demo",
        "## Makefile commands",
        "## Implementation status",
        "## Team ownership",
        "## Architecture decision records",
    ):
        assert section in README, f"missing section: {section}"


def test_readme_setup_instructions_present() -> None:
    """Setup instructions a clean clone can follow are present."""
    for command in ("python3.11 -m venv", "make install", "cp .env.example .env", "make check"):
        assert command in README, f"missing setup command: {command}"


def test_readme_terminology_matches_paper() -> None:
    """README terminology matches the MIRA paper vocabulary."""
    for term in (
        "Session Working Set",
        "session micro-path",
        "cross-session",
        "Quick",
        "Deep",
        "Relational",
        "Auto",
        "SUPERSEDED_BY",
        "CONTRADICTS",
        "foresight",
        "community summaries",
        "reflection",
        "ambient",
        "token budget",
    ):
        assert term in README, f"missing paper term: {term}"


def test_readme_links_to_adrs_and_paper() -> None:
    """README links to the ADRs and the in-repo paper, which exist."""
    assert "docs/mira-paper.md" in README
    assert "docs/adr/0001-session-working-set.md" in README
    assert (PROJECT_ROOT / "docs" / "mira-paper.md").is_file()
    assert (PROJECT_ROOT / "docs" / "adr" / "0001-session-working-set.md").is_file()


def test_readme_does_not_overclaim_scaffold() -> None:
    """Status is honest: stale scaffold framing is gone."""
    assert "## Implementation status" in README
    assert "## Roadmap" in README
    # The stale 'scaffold only / no business logic' claim must be gone.
    assert "no business logic" not in README.lower()
    assert "scaffold only" not in README.lower()
    assert "🟡 Stub" not in README


def test_readme_keeps_docker_instructions() -> None:
    """Docker local-development instructions remain intact."""
    for fragment in (
        "Docker local development",
        "docker compose build",
        "docker compose up app",
        ".docker-data/sqlite/mira.db",
        ".docker-data/chroma",
    ):
        assert fragment in README, f"missing docker fragment: {fragment}"
