"""Provider-agnostic LLM usage accounting without retaining prompt content."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from core.context.budget import estimate_tokens
from core.db.repositories import create_llm_usage_event, summarize_llm_usage_run
from core.db.schema import LEGACY_WORKSPACE_ID

LLM_INPUT_COST_ENV = "MIRA_LLM_INPUT_COST_PER_MILLION_USD"
LLM_OUTPUT_COST_ENV = "MIRA_LLM_OUTPUT_COST_PER_MILLION_USD"


@dataclass(frozen=True)
class LLMUsageContext:
    """Ownership and grouping metadata for a logical MIRA runtime operation."""

    run_id: str
    workspace_id: str
    component: str
    session_id: str | None = None
    observation_id: str | None = None


_USAGE_CONTEXT: ContextVar[LLMUsageContext | None] = ContextVar(
    "mira_llm_usage_context",
    default=None,
)


def new_usage_run_id(component: str) -> str:
    """Create an opaque run identifier suitable for grouping provider calls."""
    normalized = component.strip().replace(" ", "-") or "llm"
    return f"{normalized}-{uuid.uuid4().hex}"


@contextmanager
def llm_usage_context(
    *,
    run_id: str,
    workspace_id: str,
    component: str,
    session_id: str | None = None,
    observation_id: str | None = None,
) -> Iterator[LLMUsageContext]:
    """Bind subsequent calls to one workspace-scoped logical run."""
    context = LLMUsageContext(
        run_id=run_id,
        workspace_id=workspace_id or LEGACY_WORKSPACE_ID,
        component=component,
        session_id=session_id,
        observation_id=observation_id,
    )
    token = _USAGE_CONTEXT.set(context)
    try:
        yield context
    finally:
        _USAGE_CONTEXT.reset(token)


def current_usage_context() -> LLMUsageContext | None:
    """Return the active usage context, if this call belongs to a tracked run."""
    return _USAGE_CONTEXT.get()


def record_llm_usage(
    *,
    messages: list[dict[str, str]],
    provider: str,
    model: str,
    gateway: str,
    operation: str,
    status: str,
    latency_ms: int,
    usage: object = None,
    gateway_usage: object = None,
    response_content: str | None = None,
    provider_request_id: str | None = None,
) -> str | None:
    """Persist one logical provider request when a runtime context is active."""
    context = current_usage_context()
    if context is None:
        return None

    normalized_usage = _usage_mapping(usage)
    normalized_gateway_usage = _usage_mapping(gateway_usage)
    input_tokens = _first_int(normalized_usage, "prompt_tokens", "input_tokens")
    output_tokens = _first_int(normalized_usage, "completion_tokens", "output_tokens")
    total_tokens = _first_int(normalized_usage, "total_tokens")
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    cached_input_tokens = _nested_int(
        normalized_usage,
        ("prompt_tokens_details", "cached_tokens"),
        ("input_tokens_details", "cached_tokens"),
    )
    reasoning_output_tokens = _nested_int(
        normalized_usage,
        ("completion_tokens_details", "reasoning_tokens"),
        ("output_tokens_details", "reasoning_tokens"),
    )
    estimated_input_tokens = estimate_message_tokens(messages)
    estimated_output_tokens = (
        estimate_tokens(response_content) if isinstance(response_content, str) else None
    )
    usage_source = (
        "provider" if input_tokens is not None or output_tokens is not None else "estimated"
    )
    cost = _estimated_cost(input_tokens, output_tokens)
    gateway_input_tokens_original = _first_int(normalized_gateway_usage, "input_tokens_original")
    gateway_input_tokens_compressed = _first_int(
        normalized_gateway_usage, "input_tokens_compressed"
    )
    gateway_tokens_saved = _first_int(normalized_gateway_usage, "tokens_saved")
    return create_llm_usage_event(
        {
            "workspace_id": context.workspace_id,
            "run_id": context.run_id,
            "session_id": context.session_id,
            "observation_id": context.observation_id,
            "component": context.component,
            "operation": operation or "chat_completion",
            "provider": provider,
            "model": model,
            "gateway": gateway,
            "status": status,
            "usage_source": usage_source,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "cached_input_tokens": cached_input_tokens,
            "reasoning_output_tokens": reasoning_output_tokens,
            "estimated_input_tokens": estimated_input_tokens,
            "estimated_output_tokens": estimated_output_tokens,
            "gateway_input_tokens_original": gateway_input_tokens_original,
            "gateway_input_tokens_compressed": gateway_input_tokens_compressed,
            "gateway_tokens_saved": gateway_tokens_saved,
            "latency_ms": max(latency_ms, 0),
            "estimated_cost_usd": cost,
            "provider_request_id": provider_request_id,
            "prompt_fingerprint": prompt_fingerprint(messages),
            "usage_json": normalized_usage,
        }
    )


def estimate_message_tokens(messages: list[dict[str, str]]) -> int:
    """Estimate the uncompressed request size when a provider omits usage."""
    return sum(estimate_tokens(message.get("content", "")) + 4 for message in messages) + 2


def prompt_fingerprint(messages: list[dict[str, str]]) -> str:
    """Hash an exact prompt for comparison without retaining its content."""
    payload = json.dumps(messages, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def usage_summary(run_id: str) -> dict[str, object]:
    """Return the durable summary for one logical run."""
    return summarize_llm_usage_run(run_id)


def _usage_mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _first_int(mapping: dict[str, object], *keys: str) -> int | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _nested_int(
    mapping: dict[str, object],
    *paths: tuple[str, str],
) -> int | None:
    for parent_key, child_key in paths:
        parent = mapping.get(parent_key)
        if not isinstance(parent, dict):
            continue
        value = parent.get(child_key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _estimated_cost(input_tokens: int | None, output_tokens: int | None) -> float | None:
    input_rate = _optional_float(LLM_INPUT_COST_ENV)
    output_rate = _optional_float(LLM_OUTPUT_COST_ENV)
    if input_rate is None or output_rate is None or input_tokens is None or output_tokens is None:
        return None
    return round(
        (input_tokens / 1_000_000) * input_rate + (output_tokens / 1_000_000) * output_rate,
        8,
    )


def _optional_float(env_name: str) -> float | None:
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value >= 0 else None
