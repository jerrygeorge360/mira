"""Manual, official-capable LongMemEval / LoCoMo-style benchmark runner.

Ownership: MIRA contributors.
Related issue: ISSUE-123.
Architecture area: evaluation.

Runs only when manually triggered (``make benchmark`` / ``python -m
scripts.run_benchmark``), never during normal MIRA usage. For each benchmark
example it imports the conversation into MIRA, runs the slow path so durable
memory forms, asks the question through the agent (gold answer never shown to
MIRA), then scores with a deterministic and/or LLM-as-Judge scorer. It enforces a
hard budget cap with cost estimation, caches answers and judge verdicts, supports
resume, and writes reproducible JSON/Markdown/cost-ledger outputs with honest
prototype / official / official-subset labeling.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import multiprocessing
import os
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

Restore = Callable[[], None]
JudgeCallAdapter = Callable[[list[dict[str, str]], str], dict[str, object]]
Ledger = dict[str, Any]
CostEstimate = dict[str, Any]

LLM_API_KEY_ENV = "LLM_API_KEY"
LLM_MODEL_ENV = "LLM_MODEL"
DASHSCOPE_API_KEY_ENV = "DASHSCOPE_API_KEY"
DEFAULT_DATASET = "data/benchmarks/longmemeval.json"
DEFAULT_OUT = "evaluation/results/benchmarks"
DEFAULT_BUDGET_USD = 15.0
DEFAULT_MODEL = "qwen-plus"
DEFAULT_MAX_INPUT_TOKENS = 8000
DEFAULT_MAX_OUTPUT_TOKENS = 512
SUITES = ("longmemeval", "locomo_style")
JUDGE_MODES = ("deterministic", "llm", "hybrid")

# Estimated USD per 1K tokens (input, output). Clearly an estimate, not billing.
# DeepSeek standard-hours list price (deepseek-chat): $0.27/1M in (cache miss), $1.10/1M out
# -- verify at platform.deepseek.com/pricing; DeepSeek also runs a ~50% off-peak discount
# and much cheaper cache-hit input, so real spend tends to come in under this estimate.
PRICING: dict[str, tuple[float, float]] = {
    "qwen-plus": (0.0004, 0.0012),
    "qwen-flash": (0.0001, 0.0003),
    "qwen-max": (0.0024, 0.0096),
    "deepseek-chat": (0.00027, 0.0011),
    "deepseek-reasoner": (0.00055, 0.00219),
}
DEFAULT_PRICE = (0.0004, 0.0012)


class RunnerError(Exception):
    """A setup/budget failure that should exit with a clear message."""


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    args = _parse_args(argv)
    try:
        summary = run(args)
    except RunnerError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if summary.get("refused"):
        print(str(summary["refusal_message"]), file=sys.stderr)
        return 3
    print(str(summary.get("table", "")))
    return 0


def run(args: argparse.Namespace) -> dict[str, object]:
    """Configure the environment, run the benchmark, and write outputs."""
    from core.db.repositories import configure_database
    from evaluation.benchmarks.longmemeval import iter_examples, load_benchmark_dataset

    dataset_path = Path(args.dataset)
    if not dataset_path.is_file():
        raise RunnerError(f"dataset not found: {dataset_path} (pass --dataset)")

    status, official = _resolve_status(args)
    dataset = load_benchmark_dataset(str(dataset_path))
    examples = iter_examples(dataset)
    if args.limit is not None:
        examples = examples[: args.limit]
    _progress(
        args,
        f"loaded suite={args.suite} dataset={dataset_path} examples={len(examples)}",
    )

    estimate = _estimate_cost(examples, args)
    if args.dry_run_cost:
        return _cost_only_summary(args, dataset_path, status, official, examples, estimate)
    if estimate["estimated_cost_usd"] > args.budget_usd:
        return _budget_refusal(args, estimate)

    database_path = args.db or str(
        Path(tempfile.mkdtemp(prefix="mira-benchmark-")) / "benchmark.sqlite3"
    )
    configure_database(database_path)
    _progress(args, f"using db={database_path}")

    restore = _install_llm_mode(args)
    try:
        results, ledger = _run_examples(examples, args, estimate)
    finally:
        restore()

    summary = _summarize(args, dataset_path, status, official, results, ledger)
    _write_outputs(summary, args)
    _progress(args, f"wrote results to {args.out}")
    return summary


# --- benchmark execution ----------------------------------------------------


def _run_examples(
    examples: list[dict[str, object]],
    args: argparse.Namespace,
    estimate: CostEstimate,
) -> tuple[list[dict[str, object]], Ledger]:
    completed = _resume_completed(args) if args.resume else set()
    ledger = _new_ledger(args, estimate)
    total_examples = len(examples)
    _progress(
        args,
        "starting benchmark "
        f"mode={'live' if args.live else 'stub'} judge={args.judge} parallel={args.parallel} "
        f"budget=${args.budget_usd:.2f} estimate=${float(estimate['estimated_cost_usd']):.4f}",
    )

    # Each example is isolated in its own database + vector store, so one example's memory
    # never leaks into another's retrieval (they are independent conversations) and examples
    # can run concurrently. iso_base holds the per-example stores.
    iso_base = Path(tempfile.mkdtemp(prefix="mira-benchmark-ex-"))
    todo: list[tuple[int, dict[str, object]]] = []
    for index, example in enumerate(examples, start=1):
        question_id = str(example.get("question_id", "unknown"))
        if question_id in completed:
            ledger["examples_skipped"] = int(ledger["examples_skipped"]) + 1
            _progress(args, f"example {index}/{total_examples} {question_id}: skipped resume")
            continue
        todo.append((index, example))

    if args.parallel > 1:
        return _run_examples_parallel(todo, args, ledger, iso_base, total_examples)
    return _run_examples_sequential(todo, args, ledger, iso_base, total_examples)


def _run_examples_sequential(
    todo: list[tuple[int, dict[str, object]]],
    args: argparse.Namespace,
    ledger: Ledger,
    iso_base: Path,
    total_examples: int,
) -> tuple[list[dict[str, object]], Ledger]:
    results: list[dict[str, object]] = []
    for index, example in todo:
        question_id = str(example.get("question_id", "unknown"))
        if float(ledger["estimated_cost_usd"]) >= args.budget_usd:
            ledger["stopped_for_budget"] = True
            ledger["examples_skipped"] = int(ledger["examples_skipped"]) + 1
            _progress(args, f"example {index}/{total_examples} {question_id}: skipped budget")
            continue
        outcome = _process_example((example, args, str(iso_base), index))
        _merge_ledger_delta(ledger, cast("dict[str, Any]", outcome["ledger_delta"]))
        results.append(cast("dict[str, object]", outcome["result"]))
        ledger["examples_completed"] = int(ledger["examples_completed"]) + 1
        _progress(
            args,
            f"example {index}/{total_examples} {question_id}: done "
            f"cost=${float(ledger['actual_cost_usd']):.4f}",
        )
    return results, ledger


def _run_examples_parallel(
    todo: list[tuple[int, dict[str, object]]],
    args: argparse.Namespace,
    ledger: Ledger,
    iso_base: Path,
    total_examples: int,
) -> tuple[list[dict[str, object]], Ledger]:
    """Run examples N at a time in isolated subprocesses; merge ledgers as each finishes.

    Wave-based so the running estimate can gate the budget between waves (bounded overshoot).
    Results are checkpointed after every wave so ``--resume`` can pick up after a crash.
    """
    results: list[dict[str, object]] = []
    # fork so workers inherit the installed LLM mode (env or stub patches) and the loaded
    # embedding model without re-initializing per worker.
    context = multiprocessing.get_context("fork")
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=args.parallel, mp_context=context
    ) as pool:
        for start in range(0, len(todo), args.parallel):
            if float(ledger["estimated_cost_usd"]) >= args.budget_usd:
                ledger["stopped_for_budget"] = True
                ledger["examples_skipped"] = int(ledger["examples_skipped"]) + (len(todo) - start)
                break
            wave = todo[start : start + args.parallel]
            futures = {
                pool.submit(_process_example, (example, args, str(iso_base), index)): (
                    index,
                    example,
                )
                for index, example in wave
            }
            for future in concurrent.futures.as_completed(futures):
                index, example = futures[future]
                outcome = future.result()
                _merge_ledger_delta(ledger, cast("dict[str, Any]", outcome["ledger_delta"]))
                results.append(cast("dict[str, object]", outcome["result"]))
                ledger["examples_completed"] = int(ledger["examples_completed"]) + 1
                question_id = str(example.get("question_id", "unknown"))
                _progress(
                    args,
                    f"example {index}/{total_examples} {question_id}: done "
                    f"cost=${float(ledger['actual_cost_usd']):.4f}",
                )
            _checkpoint_results(results, args)
    return results, ledger


def _process_example(
    payload: tuple[dict[str, object], argparse.Namespace, str, int],
) -> dict[str, object]:
    """Run one example end-to-end in an isolated database + vector store.

    Import the conversation, drain the slow path, answer the question (no gold answer passed
    in -- anti-leakage), and judge it. Charges a local ledger and returns it as a delta so
    the parent can merge costs from many workers.
    """
    from evaluation.benchmarks.longmemeval import import_conversations

    example, args, iso_base, index = payload
    _isolate_example(Path(iso_base), index)
    cache = _Cache(Path(args.out) / "cache", enabled=bool(args.cache or args.resume))
    local = _new_ledger(args, {"estimated_cost_usd": 0.0, "by_stage": {}})

    import_conversations(example)
    _run_slow_path(local, args)
    question = str(example.get("question", ""))
    captured = _answer_with_cache(cache, example, question, local, args)
    verdict = _judge_with_cache(cache, example, captured, local, args)
    result = _example_result(example, captured, verdict, args)
    return {
        "result": result,
        "ledger_delta": {
            "calls": local["calls"],
            "estimated_cost_usd": local["estimated_cost_usd"],
            "actual_cost_usd": local["actual_cost_usd"],
        },
    }


def _isolate_example(iso_base: Path, index: int) -> None:
    from core.db.chroma import reset_vector_store
    from core.db.repositories import configure_database

    os.environ["CHROMA_DB_PATH"] = str(iso_base / f"chroma-{index}")
    reset_vector_store()
    database_path = iso_base / f"db-{index}" / "benchmark.sqlite3"
    database_path.parent.mkdir(parents=True, exist_ok=True)
    configure_database(str(database_path))
    reset_vector_store()


def _merge_ledger_delta(ledger: Ledger, delta: dict[str, Any]) -> None:
    for stage, call in delta["calls"].items():
        master = ledger["calls"][stage]
        master["count"] += int(call["count"])
        master["input_tokens"] += int(call["input_tokens"])
        master["output_tokens"] += int(call["output_tokens"])
        master["estimated_cost_usd"] = round(
            float(master["estimated_cost_usd"]) + float(call["estimated_cost_usd"]), 6
        )
    ledger["estimated_cost_usd"] = round(
        float(ledger["estimated_cost_usd"]) + float(delta["estimated_cost_usd"]), 6
    )
    ledger["actual_cost_usd"] = round(
        float(ledger["actual_cost_usd"]) + float(delta["actual_cost_usd"]), 6
    )


def _checkpoint_results(results: list[dict[str, object]], args: argparse.Namespace) -> None:
    """Persist results-so-far so a crashed parallel run can resume by question_id."""
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "benchmark_results.json").write_text(
        json.dumps({"results": results}, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )


def _answer_with_cache(
    cache: _Cache,
    example: dict[str, object],
    question: str,
    ledger: Ledger,
    args: argparse.Namespace,
) -> dict[str, object]:
    from evaluation.benchmarks.longmemeval import run_question

    key = _hash(args.model, args.suite, str(example.get("question_id")), question)
    cached = cache.get("answer", key)
    if cached is not None:
        return cached
    captured = run_question(question)
    _charge(ledger, "agent_answer", question, str(captured.get("answer", "")), args)
    cache.put("answer", key, captured)
    return captured


def _judge_with_cache(
    cache: _Cache,
    example: dict[str, object],
    captured: dict[str, object],
    ledger: Ledger,
    args: argparse.Namespace,
) -> dict[str, object]:
    from evaluation.benchmarks.judge import JUDGE_PROMPT_VERSION, JudgeInput, score_with_judge

    category = _category(example)
    judge_input = JudgeInput(
        question_id=str(example.get("question_id", "")),
        question=str(example.get("question", "")),
        expected_answer=str(example.get("answer", "")),
        actual_answer=str(captured.get("answer", "")),
        category=category,
        retrieved_evidence=_evidence(captured),
        metadata={"question_type": example.get("question_type")},
    )
    key = _hash(
        args.judge,
        args.judge_model,
        JUDGE_PROMPT_VERSION,
        str(args.judge_temperature),
        judge_input.question_id,
        _digest(judge_input.expected_answer),
        _digest(judge_input.actual_answer),
        _digest(json.dumps(judge_input.retrieved_evidence, default=str, sort_keys=True)),
        category,
    )
    cached = cache.get("judge", key)
    if cached is not None:
        return cached

    verdict = score_with_judge(
        judge_input,
        args.judge,
        model=args.judge_model,
        temperature=args.judge_temperature,
        call=_judge_call(args),
    )
    if args.judge in ("llm", "hybrid"):
        _charge(ledger, "judge", _judge_prompt_size(judge_input), "", args)
    if args.save_judge_prompts:
        _save_judge_artifacts(args, judge_input, verdict)
    cache.put("judge", key, verdict)
    return verdict


def _run_slow_path(ledger: Ledger, args: argparse.Namespace) -> None:
    from core.db.repositories import claim_pending_batch, mark_done, mark_failed
    from core.memory.slow_path import run_slow_path_for_observation

    queue_records = claim_pending_batch(10_000)
    total = len(queue_records)
    if total == 0:
        _progress(args, "slow path: no pending observations")
        return
    started = time.monotonic()
    _progress(args, f"slow path: claimed {total} observations")
    for index, record in enumerate(queue_records, start=1):
        observation_id = str(record["observation_id"])
        queue_id = str(record["id"])
        _progress(args, f"slow path {index}/{total}: observation={observation_id} start")
        result = run_slow_path_for_observation(observation_id)
        if result["succeeded"]:
            mark_done(queue_id)
            status = "done"
        else:
            error = str(result.get("error_message") or "slow-path step failed")
            mark_failed(queue_id, error)
            status = f"failed: {error}"
        _charge(ledger, "slow_path", "", "", args, tokens=(800, 120))
        elapsed = time.monotonic() - started
        _progress(
            args,
            f"slow path {index}/{total}: observation={observation_id} {status} "
            f"elapsed={elapsed:.1f}s cost=${float(ledger['actual_cost_usd']):.4f}",
        )


# --- status, cost, ledger ---------------------------------------------------


def _resolve_status(args: argparse.Namespace) -> tuple[str, bool]:
    if args.prototype or not args.official:
        return "prototype", False
    if args.limit is not None:
        return "official_protocol_subset", True
    return "official_protocol", True


def _estimate_cost(examples: list[dict[str, object]], args: argparse.Namespace) -> CostEstimate:
    in_price, out_price = PRICING.get(args.model, DEFAULT_PRICE)
    judge_in_price, judge_out_price = PRICING.get(args.judge_model, DEFAULT_PRICE)
    agent_cost = 0.0
    slow_cost = 0.0
    judge_cost = 0.0
    for example in examples:
        input_tokens = min(_example_input_tokens(example), args.max_input_tokens)
        agent_cost += _price(input_tokens, args.max_output_tokens, in_price, out_price)
        slow_cost += _price(
            800 * _turn_count(example), 120 * _turn_count(example), in_price, out_price
        )
        if args.judge in ("llm", "hybrid"):
            judge_cost += _price(input_tokens + 200, 256, judge_in_price, judge_out_price)
    total = round(agent_cost + slow_cost + judge_cost, 4)
    return {
        "estimated_cost_usd": total,
        "by_stage": {
            "agent_answer": round(agent_cost, 4),
            "slow_path": round(slow_cost, 4),
            "judge": round(judge_cost, 4),
        },
    }


def _new_ledger(args: argparse.Namespace, estimate: CostEstimate) -> Ledger:
    return {
        "budget_usd": args.budget_usd,
        "estimated_cost_usd": 0.0,
        "actual_cost_usd": 0.0,
        "llm_mode": "live" if args.live else "stub",
        "examples_completed": 0,
        "examples_skipped": 0,
        "stopped_for_budget": False,
        "pre_run_estimate_usd": estimate["estimated_cost_usd"],
        "calls": {
            stage: {"count": 0, "input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0}
            for stage in ("agent_answer", "slow_path", "judge")
        },
    }


def _charge(
    ledger: Ledger,
    stage: str,
    input_text: str,
    output_text: str,
    args: argparse.Namespace,
    *,
    tokens: tuple[int, int] | None = None,
) -> None:
    in_tokens, out_tokens = tokens or (_tokens(input_text), _tokens(output_text))
    model = args.judge_model if stage == "judge" else args.model
    in_price, out_price = PRICING.get(model, DEFAULT_PRICE)
    cost = _price(in_tokens, out_tokens, in_price, out_price)
    call = ledger["calls"][stage]
    call["count"] += 1
    call["input_tokens"] += in_tokens
    call["output_tokens"] += out_tokens
    call["estimated_cost_usd"] = round(float(call["estimated_cost_usd"]) + cost, 6)
    ledger["estimated_cost_usd"] = round(float(ledger["estimated_cost_usd"]) + cost, 6)
    if args.live:
        ledger["actual_cost_usd"] = round(float(ledger["actual_cost_usd"]) + cost, 6)


def _budget_refusal(args: argparse.Namespace, estimate: CostEstimate) -> dict[str, object]:
    cost = estimate["estimated_cost_usd"]
    message = (
        f"Estimated cost: ${cost:.2f}\n"
        f"Budget: ${args.budget_usd:.2f}\n\n"
        "Refusing to start: estimated cost exceeds budget.\n\n"
        "Options:\n"
        f"1. Run subset: make benchmark-subset LIMIT=100 BUDGET_USD={int(args.budget_usd)}\n"
        f"2. Use cheaper model: make benchmark MODEL=qwen-flash BUDGET_USD={int(args.budget_usd)}\n"
        f"3. Increase budget: make benchmark BUDGET_USD={int(cost) + 1}\n"
    )
    return {"refused": True, "refusal_message": message, "estimate": estimate}


def _cost_only_summary(
    args: argparse.Namespace,
    dataset_path: Path,
    status: str,
    official: bool,
    examples: list[dict[str, object]],
    estimate: CostEstimate,
) -> dict[str, object]:
    table = (
        "# MIRA Benchmark Cost Estimate\n\n"
        f"- Suite: {args.suite}\n"
        f"- Examples: {len(examples)}\n"
        f"- Estimated cost: ${float(estimate['estimated_cost_usd']):.2f}\n"
        f"- Budget: ${args.budget_usd:.2f}\n"
        f"- By stage: {estimate['by_stage']}\n"
    )
    return {
        "suite": args.suite,
        "official": official,
        "status": status,
        "dataset": dataset_path.name,
        "dry_run_cost": True,
        "total": len(examples),
        "estimated_cost_usd": estimate["estimated_cost_usd"],
        "budget_usd": args.budget_usd,
        "table": table,
    }


# --- summary + outputs ------------------------------------------------------


def _summarize(
    args: argparse.Namespace,
    dataset_path: Path,
    status: str,
    official: bool,
    results: list[dict[str, object]],
    ledger: Ledger,
) -> dict[str, object]:
    total = len(results)
    deterministic_matches = sum(1 for r in results if _deterministic_matched(r))
    llm_passes = sum(1 for r in results if _llm_passed(r))
    judge_scores: list[float] = [score for r in results if (score := _judge_score(r)) is not None]
    summary: dict[str, object] = {
        "suite": args.suite,
        "official": official,
        "status": status,
        "dataset": dataset_path.name,
        "llm_mode": "live" if args.live else "stub",
        "judge_mode": args.judge,
        "total": total,
        "deterministic_match_rate": round(deterministic_matches / total, 4) if total else 0.0,
        "llm_judge_pass_rate": round(llm_passes / total, 4) if total else 0.0,
        "average_judge_score": round(sum(judge_scores) / len(judge_scores), 4)
        if judge_scores
        else 0.0,
        "budget_usd": args.budget_usd,
        "estimated_cost_usd": ledger["estimated_cost_usd"],
        "actual_cost_usd": ledger["actual_cost_usd"],
        "category_breakdown": _category_breakdown(results),
        "results": results,
        "cost_ledger": ledger,
    }
    if args.limit is not None:
        summary["limit"] = args.limit
    summary["table"] = _render_markdown(summary)
    return summary


def _render_markdown(summary: dict[str, object]) -> str:
    status_label = {
        "prototype": "Prototype (unofficial)",
        "official_protocol": "Official protocol",
        "official_protocol_subset": "Official-protocol subset",
    }.get(str(summary["status"]), str(summary["status"]))
    lines = [
        "# MIRA Benchmark Summary",
        "",
        f"Status: {status_label}",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Suite | {summary['suite']} |",
        f"| Dataset | {summary['dataset']} |",
        f"| LLM mode | {summary['llm_mode']} |",
        f"| Judge mode | {summary['judge_mode']} |",
        f"| Total examples | {summary['total']} |",
        f"| Deterministic match rate | {summary['deterministic_match_rate']} |",
        f"| LLM judge pass rate | {summary['llm_judge_pass_rate']} |",
        f"| Average judge score | {summary['average_judge_score']} |",
        f"| Budget | ${_num(summary['budget_usd']):.2f} |",
        f"| Estimated cost | ${_num(summary['estimated_cost_usd']):.2f} |",
        f"| Actual cost | ${_num(summary['actual_cost_usd']):.2f} |",
        "",
        "## Category Breakdown",
        "",
        "| Category | Examples | LLM pass rate | Avg score |",
        "| --- | --- | --- | --- |",
    ]
    breakdown = summary["category_breakdown"]
    breakdown = breakdown if isinstance(breakdown, dict) else {}
    for category in sorted(breakdown):
        row = breakdown[category]
        lines.append(
            f"| {category} | {row['examples']} | {row['llm_pass_rate']} | {row['avg_score']} |"
        )
    return "\n".join(lines)


def _write_outputs(summary: dict[str, object], args: argparse.Namespace) -> None:
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "benchmark_results.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )
    (out_dir / "benchmark_summary.md").write_text(f"{summary['table']}\n", encoding="utf-8")
    (out_dir / "benchmark_cost_ledger.json").write_text(
        json.dumps(summary["cost_ledger"], indent=2, sort_keys=True, default=str), encoding="utf-8"
    )


def _progress(args: argparse.Namespace, message: str) -> None:
    if getattr(args, "quiet", False):
        return
    print(f"[benchmark] {message}", file=sys.stderr, flush=True)


def _save_judge_artifacts(
    args: argparse.Namespace, judge_input: Any, verdict: dict[str, object]
) -> None:
    from evaluation.benchmarks.judge import build_judge_prompt

    prompts_dir = Path(args.out) / "judge_prompts"
    outputs_dir = Path(args.out) / "judge_raw_outputs"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    outputs_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / f"{judge_input.question_id}.txt").write_text(
        build_judge_prompt(judge_input), encoding="utf-8"
    )
    (outputs_dir / f"{judge_input.question_id}.json").write_text(
        json.dumps(verdict, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )


# --- LLM mode (stub / live) -------------------------------------------------


def _install_llm_mode(args: argparse.Namespace) -> Restore:
    if args.live:
        _require_live_key()
        return _install_live_model(args.model)

    from core import agent
    from core.memory import slow_path

    swaps: tuple[tuple[object, str, object], ...] = (
        (agent, "call_qwen_json", _stub_answer_llm),
        (slow_path, "extract_atomic_facts", lambda oid, content: []),
        (slow_path, "extract_entities", lambda text: []),
    )
    originals = [(module, name, _get_attr(module, name)) for module, name, _ in swaps]
    for module, name, stub in swaps:
        _set_attr(module, name, stub)

    def restore() -> None:
        for module, name, original in originals:
            _set_attr(module, name, original)

    return restore


def _install_live_model(model: str) -> Restore:
    original_model = os.environ.get(LLM_MODEL_ENV)
    os.environ[LLM_MODEL_ENV] = model

    def restore() -> None:
        if original_model is None:
            os.environ.pop(LLM_MODEL_ENV, None)
            return
        os.environ[LLM_MODEL_ENV] = original_model

    return restore


def _get_attr(module: object, name: str) -> object:
    return getattr(module, name)


def _set_attr(module: object, name: str, value: object) -> None:
    setattr(module, name, value)


def _require_live_key() -> None:
    if not os.environ.get(LLM_API_KEY_ENV) and not os.environ.get(DASHSCOPE_API_KEY_ENV):
        raise RunnerError(
            f"--live requires {LLM_API_KEY_ENV} or {DASHSCOPE_API_KEY_ENV}; "
            "run with --stub for offline mode"
        )


def _stub_answer_llm(
    messages: list[dict[str, str]], schema_name: str, timeout_s: int = 60
) -> dict[str, object]:
    del timeout_s
    if schema_name != "answer_generation":
        return {"json": {}}
    prompt = messages[0]["content"] if messages else ""
    context = prompt.split("Prompt context:", 1)[1] if "Prompt context:" in prompt else prompt
    answer = " ".join(context.split())[:600].strip() or "I don't have enough context to answer."
    return {"json": {"answer": f"Based on memory: {answer}", "used_memory_ids": []}}


def _judge_call(args: argparse.Namespace) -> JudgeCallAdapter:
    if args.live:
        return _live_judge_call(args.judge_model)
    return _stub_judge_call


def _live_judge_call(judge_model: str) -> JudgeCallAdapter:
    def call(messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
        from core.llm.json_helpers import coerce_or_reject_json
        from core.llm.qwen import call_qwen_chat

        response = call_qwen_chat(messages, model=judge_model)
        return {"json": coerce_or_reject_json(str(response["content"]))}

    return call


def _stub_judge_call(messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
    """Deterministic offline judge: scores gold-vs-answer term overlap from the prompt."""
    prompt = messages[0]["content"] if messages else ""
    gold = _extract_line(prompt, "Gold answer:")
    answer = _extract_line(prompt, "AI answer:")
    overlap = _overlap(gold, answer)
    passed = overlap >= 0.5
    return {
        "json": {
            "passed": passed,
            "score": round(overlap, 4),
            "reason": "offline stub judge (term overlap)",
            "error_type": None if passed else "missing_memory",
            "dimensions": {"correctness": round(overlap, 4)},
        }
    }


# --- small helpers ----------------------------------------------------------


class _Cache:
    """File-backed answer/judge cache keyed by content hash."""

    def __init__(self, root: Path, *, enabled: bool) -> None:
        self.root = root
        self.enabled = enabled

    def get(self, kind: str, key: str) -> dict[str, object] | None:
        if not self.enabled:
            return None
        path = self.root / kind / f"{key}.json"
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None

    def put(self, kind: str, key: str, value: dict[str, object]) -> None:
        if not self.enabled:
            return
        directory = self.root / kind
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{key}.json").write_text(
            json.dumps(value, default=str, sort_keys=True), encoding="utf-8"
        )


def _resume_completed(args: argparse.Namespace) -> set[str]:
    path = Path(args.out) / "benchmark_results.json"
    if not path.is_file():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    results = data.get("results", []) if isinstance(data, dict) else []
    return {str(r.get("question_id")) for r in results if isinstance(r, dict)}


def _example_result(
    example: dict[str, object],
    captured: dict[str, object],
    verdict: dict[str, object],
    args: argparse.Namespace,
) -> dict[str, object]:
    from evaluation.benchmarks.judge import JudgeInput, deterministic_judge

    deterministic = (
        verdict.get("deterministic")
        if args.judge == "hybrid"
        else (
            verdict
            if args.judge == "deterministic"
            else deterministic_judge(
                JudgeInput(
                    question_id=str(example.get("question_id", "")),
                    question=str(example.get("question", "")),
                    expected_answer=str(example.get("answer", "")),
                    actual_answer=str(captured.get("answer", "")),
                    category=_category(example),
                )
            )
        )
    )
    llm = (
        verdict
        if args.judge == "llm"
        else verdict.get("llm_judge")
        if args.judge == "hybrid"
        else None
    )
    return {
        "question_id": str(example.get("question_id", "")),
        "question_type": str(example.get("question_type", "")),
        "category": _category(example),
        "question": str(example.get("question", "")),
        "expected": str(example.get("answer", "")),
        "answer": str(captured.get("answer", "")),
        "retrieval_mode": captured.get("retrieval_mode"),
        "used_memory_items": captured.get("used_memory_items", []),
        "deterministic_score": deterministic,
        "llm_judge": llm,
    }


def _category(example: dict[str, object]) -> str:
    return str(example.get("category") or example.get("question_type") or "uncategorized")


def _evidence(captured: dict[str, object]) -> list[dict[str, object]]:
    used = captured.get("used_memory_items", [])
    return [{"id": item} for item in used] if isinstance(used, list) else []


def _category_breakdown(results: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    buckets: dict[str, dict[str, float]] = {}
    for result in results:
        category = str(result.get("category", "uncategorized"))
        bucket = buckets.setdefault(category, {"examples": 0, "passes": 0, "score_sum": 0.0})
        bucket["examples"] += 1
        if _llm_passed(result):
            bucket["passes"] += 1
        score = _judge_score(result)
        if score is not None:
            bucket["score_sum"] += score
    breakdown: dict[str, dict[str, object]] = {}
    for category, bucket in buckets.items():
        examples = int(bucket["examples"])
        breakdown[category] = {
            "examples": examples,
            "llm_pass_rate": round(bucket["passes"] / examples, 4) if examples else 0.0,
            "avg_score": round(bucket["score_sum"] / examples, 4) if examples else 0.0,
        }
    return breakdown


def _deterministic_matched(result: dict[str, object]) -> bool:
    score = result.get("deterministic_score")
    return isinstance(score, dict) and bool(score.get("passed"))


def _llm_passed(result: dict[str, object]) -> bool:
    llm = result.get("llm_judge")
    if isinstance(llm, dict):
        return bool(llm.get("passed"))
    return _deterministic_matched(result)


def _judge_score(result: dict[str, object]) -> float | None:
    llm = result.get("llm_judge")
    if isinstance(llm, dict) and isinstance(llm.get("score"), int | float):
        return float(llm["score"])
    score = result.get("deterministic_score")
    if isinstance(score, dict) and isinstance(score.get("score"), int | float):
        return float(score["score"])
    return None


def _judge_prompt_size(judge_input: Any) -> str:
    return f"{judge_input.question} {judge_input.expected_answer} {judge_input.actual_answer}"


def _example_input_tokens(example: dict[str, object]) -> int:
    text = json.dumps(example.get("sessions", []), default=str) + str(example.get("question", ""))
    return _tokens(text)


def _turn_count(example: dict[str, object]) -> int:
    sessions = example.get("sessions", [])
    if not isinstance(sessions, list):
        return 1
    return max(1, sum(len(s.get("turns", [])) for s in sessions if isinstance(s, dict)))


def _price(input_tokens: int, output_tokens: int, in_price: float, out_price: float) -> float:
    return (input_tokens / 1000.0) * in_price + (output_tokens / 1000.0) * out_price


def _num(value: object) -> float:
    return float(value) if isinstance(value, int | float) else 0.0


def _tokens(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


def _overlap(gold: str, answer: str) -> float:
    gold_terms = set(gold.casefold().split())
    answer_terms = set(answer.casefold().split())
    if not gold_terms:
        return 0.0
    return len(gold_terms & answer_terms) / len(gold_terms)


def _extract_line(prompt: str, label: str) -> str:
    for line in prompt.splitlines():
        if line.startswith(label):
            return line[len(label) :].strip()
    return ""


def _hash(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run_benchmark",
        description="Run a LongMemEval / LoCoMo-style benchmark for MIRA.",
    )
    parser.add_argument("--suite", default="longmemeval", choices=SUITES)
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--db", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--judge", default="deterministic", choices=JUDGE_MODES)
    parser.add_argument("--judge-model", default=DEFAULT_MODEL)
    parser.add_argument("--judge-temperature", type=float, default=0.0)
    parser.add_argument("--budget-usd", type=float, default=DEFAULT_BUDGET_USD)
    parser.add_argument("--judge-budget-usd", type=float, default=None)
    parser.add_argument("--dry-run-cost", action="store_true")
    parser.add_argument("--max-input-tokens", type=int, default=DEFAULT_MAX_INPUT_TOKENS)
    parser.add_argument("--max-output-tokens", type=int, default=DEFAULT_MAX_OUTPUT_TOKENS)
    parser.add_argument("--cache", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--parallel",
        type=int,
        default=1,
        metavar="N",
        help=(
            "Run N examples concurrently, each in its own isolated database (big wall-clock "
            "win for the live run). Default 1. Keep N within the provider's concurrency limit."
        ),
    )
    parser.add_argument("--save-judge-prompts", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    official = parser.add_mutually_exclusive_group()
    official.add_argument("--official", dest="official", action="store_true")
    official.add_argument("--prototype", dest="prototype", action="store_true")
    live = parser.add_mutually_exclusive_group()
    live.add_argument("--live", dest="live", action="store_true")
    live.add_argument("--stub", dest="live", action="store_false")
    parser.set_defaults(official=False, prototype=False, live=False)
    return parser.parse_args(argv)


if __name__ == "__main__":  # pragma: no cover - module entry point
    sys.exit(main())
