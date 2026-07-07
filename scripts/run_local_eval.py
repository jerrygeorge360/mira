"""Run MIRA's small local memory regression suite."""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, cast

from dotenv import load_dotenv

from core.db.repositories import configure_database
from core.observability import configure_logging
from evaluation.cases import run_evaluation_cases


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = _parse_args(argv)
    if not args.quiet:
        # Emit structured mira INFO events (slow-path steps, change detection) to stderr
        # so diagnostics like candidate counts are actually observable during eval runs.
        configure_logging(logging.INFO)
    database_path = _configure_database(args.db)
    _progress(args, f"using db={database_path}")
    isolation = "shared" if args.shared_db else "per-case"
    _progress(args, f"mode={'live' if args.live else 'stub'} cases={args.cases} db={isolation}")
    summary = _run_cases(args)
    print(json.dumps(_summary_for_terminal(summary), indent=2, sort_keys=True, default=str))
    return 0 if int(str(summary.get("failed", 0))) == 0 else 1


def _configure_database(database_path: str | None) -> str:
    path = database_path or str(Path(tempfile.mkdtemp(prefix="mira-local-eval-")) / "eval.sqlite3")
    configure_database(path)
    return path


def _run_cases(args: argparse.Namespace) -> dict[str, object]:
    progress = None if args.quiet else _print_progress
    if args.live:
        summary = run_evaluation_cases(
            args.cases,
            progress=progress,
            delay_s=args.delay_s,
            run_slow_path=args.run_slow_path,
            slow_path_batch_size=args.slow_path_batch_size,
            debug_trace=args.debug_trace,
            case_ids=args.case_id,
            isolate_cases=not args.shared_db,
        )
        summary["llm_mode"] = "live"
        return summary

    from core import agent
    from core.memory import atomic_fact, community, foresight, graph, reflection

    patchable_agent = cast(Any, agent)
    patchable_modules = [
        patchable_agent,
        cast(Any, atomic_fact),
        cast(Any, graph),
        cast(Any, foresight),
        cast(Any, reflection),
        cast(Any, community),
    ]
    originals = [module.call_qwen_json for module in patchable_modules]
    patchable_agent.call_qwen_json = _stub_llm
    for module in patchable_modules[1:]:
        module.call_qwen_json = _stub_llm
    try:
        summary = run_evaluation_cases(
            args.cases,
            progress=progress,
            run_slow_path=args.run_slow_path,
            slow_path_batch_size=args.slow_path_batch_size,
            debug_trace=args.debug_trace,
            case_ids=args.case_id,
            isolate_cases=not args.shared_db,
        )
    finally:
        for module, original in zip(patchable_modules, originals, strict=True):
            module.call_qwen_json = original
    summary["llm_mode"] = "stub"
    return summary


def _summary_for_terminal(summary: dict[str, object]) -> dict[str, object]:
    return {
        "total": summary.get("total"),
        "passed": summary.get("passed"),
        "failed": summary.get("failed"),
        "pass_rate": summary.get("pass_rate"),
        "results_path": summary.get("results_path"),
        "debug_trace_path": summary.get("debug_trace_path"),
        "by_category": summary.get("by_category", {}),
    }


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", default="evaluation/memory_cases.json")
    parser.add_argument(
        "--case-id",
        action="append",
        default=None,
        help="Run only a named case. Can be passed more than once.",
    )
    parser.add_argument("--db", default=None, help="SQLite path. Defaults to an isolated temp DB.")
    parser.add_argument(
        "--shared-db",
        action="store_true",
        help=(
            "Run every case against one shared database instead of isolating each case. "
            "Use only for intentional multi-case continuity scenarios."
        ),
    )
    parser.add_argument("--live", action="store_true", help="Use the configured live LLM provider.")
    parser.add_argument(
        "--delay-s",
        default=0.0,
        type=float,
        help="Seconds to sleep between interactions, useful for live provider rate limits.",
    )
    parser.add_argument(
        "--run-slow-path",
        action="store_true",
        help="Drain the slow-path worker queue after each interaction.",
    )
    parser.add_argument(
        "--slow-path-batch-size",
        default=20,
        type=int,
        help="Maximum queued observations to claim per inline slow-path batch.",
    )
    parser.add_argument(
        "--debug-trace",
        action="store_true",
        help="Write a Markdown debug trace with routing, prompt sections, and slow-path details.",
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress progress logs on stderr.")
    return parser.parse_args(argv)


def _progress(args: argparse.Namespace, message: str) -> None:
    if not args.quiet:
        _print_progress(message)


def _print_progress(message: str) -> None:
    print(f"[local-eval] {message}", file=sys.stderr, flush=True)


def _stub_llm(
    messages: list[dict[str, str]],
    schema_name: str,
    timeout_s: int = 60,
) -> dict[str, object]:
    del timeout_s
    prompt = messages[0]["content"] if messages else ""
    if schema_name != "answer_generation":
        return {"json": _stub_schema_payload(schema_name, prompt)}
    context = prompt.split("Prompt context:", 1)[1] if "Prompt context:" in prompt else prompt
    return {"json": {"answer": f"Based on the available memory: {' '.join(context.split())}"}}


def _stub_schema_payload(schema_name: str, prompt: str) -> dict[str, object]:
    evidence = _prompt_tail(prompt, "Evidence:")
    if schema_name == "atomic_fact_extraction":
        return {"facts": [_stub_fact(evidence)] if evidence else []}
    if schema_name == "entity_extraction":
        return {"entities": _stub_entities(evidence)}
    if schema_name == "foresight_detection":
        return {"foresight": _stub_foresight(evidence)}
    if schema_name == "reflection_synthesis":
        return {"reflections": []}
    if schema_name == "community_summary_generation":
        return {
            "title": "Local Evaluation Community",
            "summary": "Deterministic local-eval summary for graph community diagnostics.",
            "member_node_ids": [],
        }
    return {}


def _stub_fact(evidence: str) -> dict[str, object]:
    return {
        "subject": "user",
        "predicate": "said",
        "object": evidence,
        "confidence": 0.8,
        "evidence_span": evidence,
    }


def _stub_entities(evidence: str) -> list[dict[str, object]]:
    names = []
    for token in re.findall(r"\b[A-Z][A-Za-z0-9_+-]*\b", evidence):
        if token not in names and token not in {"I", "The", "What", "Your", "Based"}:
            names.append(token)
    return [{"name": name, "entity_type": "concept", "aliases": []} for name in names[:5]]


def _stub_foresight(evidence: str) -> list[dict[str, object]]:
    normalized = evidence.casefold()
    if not any(marker in normalized for marker in ("deadline", "due", "remember", "remind")):
        return []
    return [
        {
            "content": evidence,
            "reason": "Deterministic local-eval future-relevant marker.",
            "status": "active",
            "always_inject": False,
        }
    ]


def _prompt_tail(prompt: str, marker: str) -> str:
    if marker not in prompt:
        return ""
    return prompt.rsplit(marker, 1)[1].strip()


if __name__ == "__main__":
    raise SystemExit(main())
