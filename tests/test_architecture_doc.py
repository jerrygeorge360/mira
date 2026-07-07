"""Verify ISSUE-058 implementation architecture document.

Ownership: MIRA contributors.
Related issue: ISSUE-058.
Architecture area: docs.
"""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = PROJECT_ROOT / "docs" / "architecture.md"
DOC = DOC_PATH.read_text(encoding="utf-8")

REQUIRED_SECTIONS = (
    "## Fast path",
    "## Session micro-path",
    "## Session Working Set",
    "## Cross-session slow path",
    "## Prompt builder",
    "## Retrieval modes",
    "## Graph model",
    "## Memory tiers",
    "## Foresight",
    "## Reflection",
    "## Community summaries",
    "## Sensa-style ambient context",
    "## Provisional vs confirmed memory",
    "## Store responsibilities (SQLite / Chroma / NetworkX)",
)


def test_all_required_sections_present() -> None:
    """Every contracted architecture section exists."""
    for section in REQUIRED_SECTIONS:
        assert section in DOC, f"missing section: {section}"


def test_doc_matches_real_code_modules() -> None:
    """Every core/ module path referenced in the doc exists on disk."""
    referenced = set(re.findall(r"core/[\w./]+\.py", DOC))
    assert len(referenced) >= 15, "architecture doc should reference the implementing modules"
    for module_path in referenced:
        assert (PROJECT_ROOT / module_path).is_file(), (
            f"doc references missing module: {module_path}"
        )


def test_key_subsystem_modules_are_named() -> None:
    """The doc names the actual implementing module for key subsystems."""
    for module_path in (
        "core/memory/observation.py",
        "core/session/micro_path.py",
        "core/session/working_set.py",
        "core/memory/slow_path.py",
        "core/retrieval/auto.py",
        "core/context/merger.py",
        "core/memory/graph.py",
        "core/memory/change.py",
        "core/memory/tiers.py",
        "core/memory/foresight.py",
        "core/memory/reflection.py",
        "core/memory/community.py",
        "core/context/ambient.py",
    ):
        assert module_path in DOC, f"doc should name {module_path}"


def test_ascii_diagram_included() -> None:
    """At least one fenced ASCII flow diagram is present."""
    fenced_blocks = re.findall(r"```text\n(.*?)```", DOC, flags=re.DOTALL)
    assert any("->" in block or "└" in block for block in fenced_blocks), "no ASCII diagram found"


def test_no_outdated_memory_pressure_framing() -> None:
    """The doc uses the execution-buffer framing, not context-overflow-as-memory."""
    assert "execution buffer" in DOC
    assert "primary memory event" in DOC  # overflow framed as *not* the primary event
    assert "scaffold only" not in DOC.lower()


def test_no_stale_stub_framing() -> None:
    """The architecture doc describes active facades instead of stale placeholders."""
    assert "**stub**" not in DOC
    assert "NotImplementedError" not in DOC
    assert "slow_path.py" in DOC
