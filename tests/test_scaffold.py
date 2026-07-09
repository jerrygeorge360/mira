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
    "core.llm.profiles",
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
    "evaluation.benchmarks.judge",
    "evaluation.benchmarks.longmemeval",
    "evaluation.ablation.studies",
    "evaluation.local.cases",
    "scripts.inspect_graph",
    "scripts.run_local_eval",
    "scripts.search_memory",
    "scripts.slow_path_status",
    "scripts.seed_demo",
)


def test_expected_modules_exist() -> None:
    """Ensure each architecture module exists at its expected path."""
    for module_name in EXPECTED_MODULES:
        path = PROJECT_ROOT.joinpath(*module_name.split(".")).with_suffix(".py")
        assert path.is_file()


def test_application_modules_import_without_third_party() -> None:
    """Ensure scaffold modules import without optional third-party packages."""
    third_party_allowlist: dict[str, frozenset[str]] = {
        "core.llm.qwen": frozenset({"openai"}),
        "core.memory.graph": frozenset({"networkx"}),
        "scripts.inspect_graph": frozenset({"dotenv"}),
        "scripts.run_local_eval": frozenset({"dotenv"}),
        "scripts.search_memory": frozenset({"dotenv"}),
        "scripts.slow_path_status": frozenset({"dotenv"}),
        "slack.bot": frozenset({"slack_bolt", "dotenv"}),
    }
    for module_name in EXPECTED_MODULES:
        try:
            importlib.import_module(module_name)
        except ModuleNotFoundError:
            if module_name in third_party_allowlist:
                continue
            raise


def test_application_imports_are_standard_library_only() -> None:
    """Ensure application imports remain standard-library or local-only."""
    third_party_allowlist: dict[str, frozenset[str]] = {
        "core.llm.qwen": frozenset({"openai"}),
        "core.memory.graph": frozenset({"networkx"}),
        "scripts.inspect_graph": frozenset({"dotenv"}),
        "scripts.run_local_eval": frozenset({"dotenv"}),
        "scripts.search_memory": frozenset({"dotenv"}),
        "scripts.slow_path_status": frozenset({"dotenv"}),
        "slack.bot": frozenset({"slack_bolt", "dotenv"}),
    }
    allowed_modules = sys.stdlib_module_names | LOCAL_IMPORT_ROOTS
    for module_name in EXPECTED_MODULES:
        extra = third_party_allowlist.get(module_name, frozenset())
        path = PROJECT_ROOT.joinpath(*module_name.split(".")).with_suffix(".py")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots = {alias.name.partition(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported_roots = {(node.module or "").partition(".")[0]}
            else:
                continue
            assert imported_roots <= allowed_modules | extra
