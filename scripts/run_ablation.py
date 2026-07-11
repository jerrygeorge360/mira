"""One-command runner for MIRA's ablation study.

Ownership: MIRA contributors.
Related issue: ISSUE-122.
Architecture area: evaluation.

Wraps ``evaluation.ablation.run_ablation_study`` with a command-line interface so
the study runs reproducibly without opening Python. It configures an isolated
SQLite database, installs a deterministic offline LLM stub by default (live model
only with ``--live`` and a key), optionally drains the slow-path queue after each
interaction for durable-memory ablations, prints the Markdown comparison table,
and writes the full JSON results plus a Markdown summary. It does not duplicate
the ablation engine -- it only makes it runnable.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from dotenv import load_dotenv

from core.observability import configure_logging

# The ablation defaults to its own lean, per-layer case set (fast). Pass
# --cases evaluation/local/memory_cases.json for the full behavior-coverage set (slower).
DEFAULT_CASES = "evaluation/ablation/ablation_cases.json"
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
        SELECTABLE_ABLATIONS,
        run_ablation_study,
        select_ablations,
        standard_ablations,
    )

    cases_path = Path(args.cases)
    if not cases_path.is_file():
        raise RunnerError(f"cases file not found: {cases_path}")

    # LLM response cache: on by default (huge win for the ablation, where slow-path ingestion
    # prompts repeat across configs). Opt out with --no-cache; respect an externally-set path.
    if args.no_cache:
        os.environ.pop("MIRA_LLM_CACHE", None)
    elif not os.environ.get("MIRA_LLM_CACHE"):
        os.environ["MIRA_LLM_CACHE"] = args.cache_dir

    if args.single:
        configs = [config for config in standard_ablations() if config.name == args.single]
        if not configs:
            raise RunnerError(f"unknown --single config: {args.single}")
    else:
        if args.components:
            unknown = [name for name in args.components if name not in SELECTABLE_ABLATIONS]
            if unknown:
                raise RunnerError(
                    f"unknown component(s): {', '.join(unknown)}; "
                    f"valid: {', '.join(SELECTABLE_ABLATIONS)}"
                )
        configs = select_ablations(args.components)

    # Parallel path: run each config in its own subprocess (own DB + Chroma path), N at a time.
    if args.parallel > 1 and not args.single:
        if args.live:
            _require_live_key()
        summary = _run_parallel(args, configs, str(Path(args.out) / args.json_name))
        summary["llm_mode"] = "live" if args.live else "stub"
        summary["parallel"] = args.parallel
        _write_outputs(summary, args)
        return summary

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
    # Checkpoint to the same JSON output file so a crashed run can be resumed.
    checkpoint_path = str(Path(args.out) / args.json_name)
    try:
        summary = run_ablation_study(
            str(cases_path),
            configs=configs,
            progress=progress,
            limit=args.limit,
            run_slow_path=args.run_slow_path,
            slow_path_batch_size=args.slow_path_batch_size,
            delay_s=args.delay_s,
            isolate_cases=not args.shared_db,
            checkpoint_path=checkpoint_path,
            resume=args.resume,
        )
    finally:
        agent.call_qwen_json = original_qwen  # type: ignore[attr-defined]

    summary["llm_mode"] = "live" if args.live else "stub"
    summary["database_path"] = database_path
    summary["shared_db"] = bool(args.shared_db)
    _write_outputs(summary, args)
    return summary


def _run_parallel(
    args: argparse.Namespace,
    configs: Sequence[object],
    checkpoint_path: str,
) -> dict[str, object]:
    """Run each config in its own subprocess, ``args.parallel`` at a time, and merge rows.

    Each child is a normal ``--single`` invocation with its own temp database and a unique
    CHROMA_DB_PATH, so configs are fully isolated at the OS level. Children inherit the parent
    env (provider keys and MIRA_LLM_CACHE), so they share the on-disk cache. Rows are written
    to the checkpoint file in config order as each child finishes.
    """
    import concurrent.futures
    import json as _json
    import subprocess  # nosec B404 - fixed argv, no shell
    import tempfile

    from evaluation.ablation.studies import render_ablation_table, rows_from_dicts

    order = [config.name for config in configs]  # type: ignore[attr-defined]
    prior = _load_checkpoint_rows(checkpoint_path) if args.resume else []
    results: dict[str, dict[str, object]] = {str(row["name"]): row for row in prior}
    remaining = [config for config in configs if config.name not in results]  # type: ignore[attr-defined]
    base = Path(tempfile.mkdtemp(prefix="mira-ablation-par-"))

    def _child(config_name: str, index: int) -> dict[str, object]:
        out_dir = base / config_name
        env = dict(os.environ)
        env["CHROMA_DB_PATH"] = str(base / f"chroma-{index}")
        cmd = [
            sys.executable, "-m", "scripts.run_ablation",
            "--single", config_name, "--out", str(out_dir), "--json-name", "row.json",
            "--cases", args.cases, "--quiet",
            "--slow-path-batch-size", str(args.slow_path_batch_size),
        ]  # fmt: skip
        cmd.append("--live" if args.live else "--stub")
        if args.limit:
            cmd += ["--limit", str(args.limit)]
        if args.run_slow_path:
            cmd.append("--run-slow-path")
        if args.delay_s:
            cmd += ["--delay-s", str(args.delay_s)]
        if args.shared_db:
            cmd.append("--shared-db")
        cmd += ["--no-cache"] if args.no_cache else ["--cache-dir", args.cache_dir]
        subprocess.run(cmd, env=env, check=True)  # nosec B603 - fixed argv, no shell
        data = _json.loads((out_dir / "row.json").read_text(encoding="utf-8"))
        return dict(data["rows"][0])

    def _write() -> dict[str, object]:
        ordered = [results[name] for name in order if name in results]
        summary: dict[str, object] = {
            "cases_path": args.cases,
            "run_slow_path": args.run_slow_path,
            "rows": ordered,
            "table": render_ablation_table(rows_from_dicts(list(ordered))),
        }
        path = Path(checkpoint_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_json.dumps(summary, indent=2, default=str), encoding="utf-8")
        return summary

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as pool:
        futures = {
            pool.submit(_child, config.name, index): config.name  # type: ignore[attr-defined]
            for index, config in enumerate(remaining)
        }
        for future in concurrent.futures.as_completed(futures):
            row = future.result()
            results[str(row["name"])] = row
            if not args.quiet:
                _print_progress(f"parallel: {row['name']} done ({len(results)}/{len(configs)})")
            _write()
    return _write()


def _load_checkpoint_rows(checkpoint_path: str) -> list[dict[str, object]]:
    path = Path(checkpoint_path)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    rows = data.get("rows") if isinstance(data, dict) else None
    return [row for row in rows if isinstance(row, dict) and row.get("name")] if rows else []


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
            "reflection, community_summaries, contradiction_supersession, vector_only, "
            "flat_memory, full_transcript."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Run only the first N cases per config, for a faster run.",
    )
    parser.add_argument(
        "--run-slow-path",
        action="store_true",
        help=(
            "Drain the slow-path queue after each interaction so durable-memory "
            "components are fairly exercised."
        ),
    )
    parser.add_argument(
        "--slow-path-batch-size",
        default=20,
        type=int,
        help="Maximum queued observations to claim per inline slow-path batch.",
    )
    parser.add_argument(
        "--delay-s",
        default=0.0,
        type=float,
        help="Seconds to sleep between live provider calls/interactions.",
    )
    parser.add_argument(
        "--shared-db",
        action="store_true",
        help=(
            "Run configs/cases against one shared database instead of fresh per-case "
            "databases. Use only for intentional continuity experiments."
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-config progress and structured logs on stderr.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Skip configs already recorded in the output JSON and continue with the rest. "
            "The table is checkpointed after every config, so a crashed run can be resumed."
        ),
    )
    parser.add_argument(
        "--parallel",
        type=int,
        default=1,
        metavar="N",
        help=(
            "Run N configs concurrently, each in its own isolated subprocess (big wall-clock "
            "win for live runs). Default 1 (sequential). Keep N within the provider's "
            "concurrency limit."
        ),
    )
    parser.add_argument(
        "--single",
        default=None,
        metavar="CONFIG",
        help="Run exactly one named config (no full_system baseline). Used by --parallel.",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable the on-disk LLM response cache (on by default for the ablation).",
    )
    parser.add_argument(
        "--cache-dir",
        default=".llm-cache",
        metavar="DIR",
        help="Directory for the LLM response cache when enabled (default: .llm-cache).",
    )
    parser.set_defaults(live=False)
    return parser.parse_args(argv)


def _print_progress(message: str) -> None:
    print(f"[ablation] {message}", file=sys.stderr, flush=True)


if __name__ == "__main__":  # pragma: no cover - module entry point
    sys.exit(main())
