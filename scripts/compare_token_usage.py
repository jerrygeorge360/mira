"""Run identical MIRA answer prompts directly and through Paritok."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

from core.context.prompt_builder import build_answer_messages
from core.db.repositories import configure_database, list_llm_usage_events
from core.db.schema import LEGACY_WORKSPACE_ID
from core.llm.profiles import active_profile
from core.llm.qwen import call_llm_json
from core.llm.usage import llm_usage_context, new_usage_run_id

DEFAULT_INPUT = Path("data/token_comparison_cases.json")
DEFAULT_OUTPUT = Path("tmp/token-comparison.json")


def main(argv: list[str] | None = None) -> int:
    """Execute paired calls and write a reproducible JSON report."""
    load_dotenv()
    args = _parser().parse_args(argv)
    input_path = Path(args.input)
    cases = _load_cases(input_path)[: args.limit]
    if not cases:
        raise ValueError("token comparison input must contain at least one case")
    configure_database(os.environ.get("MIRA_DB_PATH", "./mira.db"))
    profile = active_profile()
    if profile is None:
        raise ValueError("configure LLM_PROFILE before running a comparison")
    health = _proxy_json("/health")
    if not health or str(health.get("status")) != "ok":
        raise RuntimeError("Paritok proxy is unavailable; run `make paritok-up` first")
    stats_before = _proxy_json("/stats")

    rows: list[dict[str, object]] = []
    for index, case in enumerate(cases, 1):
        identifier = str(case.get("id") or f"case-{index}")
        messages = _case_messages(case)
        print(f"[{index}/{len(cases)}] {identifier}: direct", flush=True)
        direct = _run_call(messages, "direct", profile.chat_model)
        print(f"[{index}/{len(cases)}] {identifier}: paritok", flush=True)
        compressed = _run_call(messages, "paritok", profile.chat_model)
        direct_input = _required_input_tokens(direct, "direct")
        compressed_input = _required_input_tokens(compressed, "paritok")
        saved = direct_input - compressed_input
        expected_terms = _expected_terms(case)
        direct_quality = _quality_check(str(direct["answer"]), expected_terms)
        paritok_quality = _quality_check(str(compressed["answer"]), expected_terms)
        rows.append(
            {
                "id": identifier,
                "prompt_fingerprint": direct["prompt_fingerprint"],
                "provider": profile.name,
                "model": profile.chat_model,
                "direct": direct,
                "paritok": compressed,
                "input_tokens_saved": saved,
                "input_reduction_percent": round(saved / direct_input * 100, 2)
                if direct_input
                else 0.0,
                "answers_match_exactly": direct["answer"] == compressed["answer"],
                "quality_check": {
                    "required_terms": expected_terms,
                    "direct": direct_quality,
                    "paritok": paritok_quality,
                },
            }
        )

    stats_after = _proxy_json("/stats")
    summary = _summary(rows)
    report = {
        "schema_version": 1,
        "measurement_scope": "answer_generation",
        "measurement_source": "upstream_provider_usage",
        "input": str(input_path),
        "provider": profile.name,
        "model": profile.chat_model,
        "summary": summary,
        "paritok_stats_before": stats_before,
        "paritok_stats_after": stats_after,
        "cases": rows,
    }
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(
        "comparison complete: "
        f"direct={summary['direct_input_tokens']} input tokens, "
        f"paritok={summary['paritok_input_tokens']} input tokens, "
        f"saved={summary['input_tokens_saved']} "
        f"({summary['input_reduction_percent']}%)",
        flush=True,
    )
    print(f"report: {output_path}", flush=True)
    return 0


def _run_call(
    messages: list[dict[str, str]],
    gateway: str,
    model: str,
) -> dict[str, object]:
    run_id = new_usage_run_id(f"comparison-{gateway}")
    with llm_usage_context(
        run_id=run_id,
        workspace_id=LEGACY_WORKSPACE_ID,
        component="token_comparison",
    ):
        response = call_llm_json(
            messages,
            schema_name="answer_generation",
            model=model,
            gateway=gateway,
        )
    records = list_llm_usage_events(run_id=run_id)
    if not records:
        raise RuntimeError(f"no durable usage event was recorded for {gateway}")
    records.reverse()
    payload = response.get("json")
    answer = str(payload.get("answer") or "") if isinstance(payload, dict) else ""
    return {
        "run_id": run_id,
        "answer": answer,
        "provider_calls": len(records),
        "usage_source": (
            "provider"
            if all(record.get("usage_source") == "provider" for record in records)
            else "estimated"
        ),
        "input_tokens": _sum_record_int(records, "input_tokens"),
        "output_tokens": _sum_record_int(records, "output_tokens"),
        "total_tokens": _sum_record_int(records, "total_tokens"),
        "latency_ms": _sum_record_int(records, "latency_ms"),
        "estimated_cost_usd": round(
            sum(_float_or_zero(record.get("estimated_cost_usd")) for record in records),
            8,
        ),
        "prompt_fingerprint": records[0].get("prompt_fingerprint"),
        "attempt_fingerprints": [record.get("prompt_fingerprint") for record in records],
    }


def _case_messages(case: dict[str, object]) -> list[dict[str, str]]:
    raw_context = case.get("context")
    context = (
        [dict(item) for item in raw_context if isinstance(item, dict)]
        if isinstance(raw_context, list)
        else []
    )
    user_message = str(case.get("user_message") or "").strip()
    if not user_message:
        raise ValueError("each token comparison case requires user_message")
    raw_sufficiency = case.get("sufficiency")
    sufficiency = dict(raw_sufficiency) if isinstance(raw_sufficiency, dict) else None
    return build_answer_messages(
        user_message,
        context,
        answer_mode=str(case.get("answer_mode") or "memory_grounded"),
        sufficiency=sufficiency,
    )


def _required_input_tokens(result: dict[str, object], label: str) -> int:
    if result.get("usage_source") != "provider":
        raise RuntimeError(f"{label} response did not provide authoritative token usage")
    value = result.get("input_tokens")
    if not isinstance(value, int):
        raise RuntimeError(f"{label} response omitted provider-reported input token usage")
    return value


def _summary(rows: list[dict[str, object]]) -> dict[str, object]:
    direct = sum(_int_or_zero(_nested(row, "direct", "input_tokens")) for row in rows)
    compressed = sum(_int_or_zero(_nested(row, "paritok", "input_tokens")) for row in rows)
    saved = direct - compressed
    return {
        "cases": len(rows),
        "direct_input_tokens": direct,
        "paritok_input_tokens": compressed,
        "input_tokens_saved": saved,
        "input_reduction_percent": round(saved / direct * 100, 2) if direct else 0.0,
        "exact_answer_matches": sum(bool(row["answers_match_exactly"]) for row in rows),
        "direct_quality_passes": sum(_quality_passed(row, "direct") for row in rows),
        "paritok_quality_passes": sum(_quality_passed(row, "paritok") for row in rows),
    }


def _nested(row: dict[str, object], parent: str, key: str) -> object:
    value = row.get(parent)
    return value.get(key) if isinstance(value, dict) else None


def _int_or_zero(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _sum_record_int(records: list[dict[str, object]], key: str) -> int | None:
    values = [record.get(key) for record in records]
    if any(not isinstance(value, int) or isinstance(value, bool) for value in values):
        return None
    return sum(value for value in values if isinstance(value, int))


def _float_or_zero(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _expected_terms(case: dict[str, object]) -> list[str]:
    value = case.get("expected_terms")
    if not isinstance(value, list):
        return []
    return [str(term).strip() for term in value if str(term).strip()]


def _quality_check(answer: str, expected_terms: list[str]) -> dict[str, object]:
    normalized = answer.casefold()
    missing = [term for term in expected_terms if term.casefold() not in normalized]
    return {"passed": not missing, "missing_terms": missing}


def _quality_passed(row: dict[str, object], gateway: str) -> bool:
    quality = row.get("quality_check")
    gateway_quality = quality.get(gateway) if isinstance(quality, dict) else None
    return bool(gateway_quality.get("passed")) if isinstance(gateway_quality, dict) else False


def _proxy_json(path: str) -> dict[str, object] | None:
    base_url = os.environ.get("PARITOK_BASE_URL", "http://127.0.0.1:8081").rstrip("/")
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]
    try:
        response = httpx.get(f"{base_url}{path}", timeout=5.0)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    return dict(payload) if isinstance(payload, dict) else None


def _load_cases(path: Path) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("token comparison input must be a JSON array")
    return [dict(item) for item in payload if isinstance(item, dict)]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT))
    return parser


if __name__ == "__main__":
    sys.exit(main())
