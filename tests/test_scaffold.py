"""Verify the final MIRA scaffold contract without exercising runtime behavior.

Ownership: MIRA contributors.
Related issue: ISSUE-900.
Architecture area: evaluation.
"""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_IMPORT_ROOTS = frozenset({"core", "ui", "slack", "evaluation", "scripts"})
EXPECTED_MODULES = (
    "core.agent",
    "core.llm.qwen",
    "core.llm.functions",
    "core.llm.prompts",
    "core.memory.observation",
    "core.memory.atomic_fact",
    "core.memory.slow_path",
    "core.memory.tiers",
    "core.memory.working",
    "core.memory.reflection",
    "core.memory.foresight",
    "core.memory.graph",
    "core.memory.community",
    "core.session.micro_path",
    "core.session.extractor",
    "core.session.validator",
    "core.session.working_set",
    "core.session.confirmation",
    "core.session.hydration",
    "core.retrieval.quick",
    "core.retrieval.deep",
    "core.retrieval.relational",
    "core.retrieval.auto",
    "core.retrieval.vector",
    "core.retrieval.keyword",
    "core.retrieval.sufficiency",
    "core.retrieval.router",
    "core.context.prompt_builder",
    "core.context.budget",
    "core.context.merger",
    "core.context.ambient",
    "core.db.schema",
    "core.db.sqlite",
    "core.db.chroma",
    "core.db.repositories",
    "core.db.queue",
    "ui.app",
    "ui.chat",
    "ui.graph_viz",
    "ui.memory_inspector",
    "ui.retrieval_trace",
    "ui.foresight_view",
    "slack.bot",
    "slack.mcp_server",
    "evaluation.judge",
    "evaluation.longmemeval",
    "evaluation.ablation",
    "evaluation.cases",
    "scripts.test_qwen",
    "scripts.seed_demo",
)


def test_expected_modules_exist() -> None:
    """Ensure each architecture module exists at its expected path."""
    for module_name in EXPECTED_MODULES:
        path = PROJECT_ROOT.joinpath(*module_name.split(".")).with_suffix(".py")
        assert path.is_file()


def test_application_modules_import_without_third_party() -> None:
    """Ensure scaffold modules import without optional third-party packages."""
    for module_name in EXPECTED_MODULES:
        importlib.import_module(module_name)


def test_application_imports_are_standard_library_only() -> None:
    """Ensure application imports remain standard-library or local-only."""
    for module_name in EXPECTED_MODULES:
        path = PROJECT_ROOT.joinpath(*module_name.split(".")).with_suffix(".py")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots = {alias.name.partition(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported_roots = {(node.module or "").partition(".")[0]}
            else:
                continue
            assert imported_roots <= sys.stdlib_module_names | LOCAL_IMPORT_ROOTS
