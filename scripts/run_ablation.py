"""One-command runner for MIRA's ablation study.

Ownership: MIRA contributors.
Related issue: ISSUE-122.
Architecture area: evaluation.

Wraps ``evaluation.ablation.run_ablation_study`` with a command-line interface so
the study runs reproducibly without opening Python. It configures an isolated
SQLite database, installs a deterministic offline LLM stub by default (live model
only with ``--live`` and a key), runs the study, prints the Markdown comparison
table, and writes the full JSON results plus a Markdown summary. It does not
duplicate the ablation engine -- it only makes it runnable.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

from core.observability import configure_logging

DEFAULT_CASES = "evaluation/local/memory_cases.json"
DEFAULT_OUT = "evaluation/results"
DEFAULT_JSON_NAME = "ablation_results.json"
DEFAULT_MD_NAME = "ablation_summary.md"

LLM_API_KEY_ENV = "LLM_API_KEY"
DASHSCOPE_API_KEY_ENV = "DASHSCOPE_API_KEY"


class RunnerError(Exception):
    """A setup failure that should exit with a clear message, not a traceback."""


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, run the ablation study, and print the table."""
    load_dotenv()
    args = _parse_args(argv)
    if not args.quiet:
        # Show per-config/per-case progress plus mira INFO events so a long live run
        # reports what it is doing instead of appearing to hang before the final table.
        configure_logging(logging.INFO)
    try:
        summary = run(args)
    except RunnerError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(str(summary.get("table", "")))
    return 0


def run(args: argparse.Namespace) -> dict[str, object]:
    """Configure the environment, run the study, and write the result files."""
    from core import agent
    from core.db.repositories import configure_database
    from evaluation.ablation.studies import (
        ABLATION_COMPONENTS,
        run_ablation_study,
        select_ablations,
    )

    cases_path = Path(args.cases)
    if not cases_path.is_file():
        raise RunnerError(f"cases file not found: {cases_path}")

    if args.components:
        unknown = [name for name in args.components if name not in ABLATION_COMPONENTS]
        if unknown:
            raise RunnerError(
                f"unknown component(s): {', '.join(unknown)}; "
                f"valid: {', '.join(ABLATION_COMPONENTS)}"
            )
    configs = select_ablations(args.components)

    # Isolated database so the study never touches a developer's local DB.
    database_path = args.db or str(
        Path(tempfile.mkdtemp(prefix="mira-ablation-")) / "ablation.sqlite3"
    )
    configure_database(database_path)

    original_qwen = agent.call_qwen_json  # type: ignore[attr-defined]
    if args.live:
        _require_live_key()
    else:
        agent.call_qwen_json = _stub_llm  # type: ignore[attr-defined]
    progress = None if args.quiet else _print_progress
    try:
        summary = run_ablation_study(
            str(cases_path), configs=configs, progress=progress, limit=args.limit
        )
    finally:
        agent.call_qwen_json = original_qwen  # type: ignore[attr-defined]

    summary["llm_mode"] = "live" if args.live else "stub"
    summary["database_path"] = database_path
    _write_outputs(summary, args)
    return summary


def _write_outputs(summary: dict[str, object], args: argparse.Namespace) -> None:
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / args.json_name).write_text(
        json.dumps(summary, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )
    (out_dir / args.md_name).write_text(
        f"# MIRA Ablation Study\n\n{summary.get('table', '')}\n", encoding="utf-8"
    )


def _require_live_key() -> None:
    from core.llm.profiles import active_profile

    profile = active_profile()
    profile_key_set = bool(profile and os.environ.get(profile.api_key_env))
    if (
        not os.environ.get(LLM_API_KEY_ENV)
        and not os.environ.get(DASHSCOPE_API_KEY_ENV)
        and not profile_key_set
    ):
        raise RunnerError(
            f"--live requires a provider key: {LLM_API_KEY_ENV}, {DASHSCOPE_API_KEY_ENV}, "
            "or the key for the active LLM_PROFILE (e.g. DEEPSEEK_API_KEY). "
            "run without --live for deterministic offline mode"
        )


def _stub_llm(
    messages: list[dict[str, str]],
    schema_name: str,
    timeout_s: int = 60,
) -> dict[str, object]:
    """Deterministic offline LLM stub driven by the prompt context.

    The answer reflects the context the memory pipeline actually injected, so an
    ablation that removes that context changes the answer -- it never returns a
    canned correct string. Non-answer schemas return an empty payload.
    """
    del timeout_s
    if schema_name != "answer_generation":
        return {"json": {}}
    prompt = messages[0]["content"] if messages else ""
    return {"json": {"answer": _answer_from_context(prompt), "used_memory_ids": []}}


def _answer_from_context(prompt: str) -> str:
    marker = "Prompt context:"
    context = prompt.split(marker, 1)[1] if marker in prompt else prompt
    collapsed = " ".join(context.split())[:600].strip()
    if not collapsed:
        return "I don't have enough context to answer confidently."
    return f"Based on the available memory: {collapsed}"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run_ablation",
        description="Run MIRA's ablation study and write JSON/Markdown results.",
    )
    parser.add_argument("--cases", default=DEFAULT_CASES, help="Path to the evaluation cases JSON.")
    parser.add_argument("--out", default=DEFAULT_OUT, help="Directory for the result files.")
    parser.add_argument("--db", default=None, help="SQLite path (default: isolated temp DB).")
    parser.add_argument("--json-name", default=DEFAULT_JSON_NAME, help="JSON results filename.")
    parser.add_argument("--md-name", default=DEFAULT_MD_NAME, help="Markdown summary filename.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--stub",
        dest="live",
        action="store_false",
        help="Deterministic offline LLM stub (default).",
    )
    mode.add_argument(
        "--live",
        dest="live",
        action="store_true",
        help=f"Use the configured LLM provider (requires {LLM_API_KEY_ENV}).",
    )
    parser.add_argument(
        "--components",
        nargs="+",
        metavar="COMPONENT",
        help=(
            "Run only the full_system baseline plus these ablations, for a faster run. "
            "Choices: session_working_set, relational_mode, deep_mode, foresight, "
            "reflection, contradiction_supersession, vector_only."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Run only the first N cases per config, for a faster run.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-config progress and structured logs on stderr.",
    )
    parser.set_defaults(live=False)
    return parser.parse_args(argv)


def _print_progress(message: str) -> None:
    print(f"[ablation] {message}", file=sys.stderr, flush=True)


if __name__ == "__main__":  # pragma: no cover - module entry point
    sys.exit(main())
