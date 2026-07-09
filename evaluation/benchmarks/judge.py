"""LLM-as-Judge and deterministic scoring for MIRA benchmark evaluation.

Ownership: MIRA contributors.
Related issue: ISSUE-123.
Architecture area: evaluation.

Scores a MIRA answer against a gold answer for LongMemEval / LoCoMo-style tasks.
Three modes: a cheap offline ``deterministic`` judge, an ``llm`` judge that scores
semantic correctness on category-specific rubric dimensions, and a ``hybrid`` judge
that runs both and preserves each result. Judge output is structured and
JSON-serializable; invalid judge output degrades to a ``judge_parse_error`` result
rather than crashing. Gold answers are only ever shown to the judge.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field

JudgeResult = dict[str, object]
JudgeCall = Callable[[list[dict[str, str]], str], dict[str, object]]

JUDGE_PROMPT_VERSION = "v1"
DEFAULT_JUDGE_MODEL = "qwen-plus"

ERROR_TYPES = frozenset(
    {
        "missing_memory",
        "stale_memory",
        "contradiction_unresolved",
        "wrong_temporal_order",
        "unsupported_claim",
        "failed_abstention",
        "over_abstention",
        "wrong_preference",
        "weak_synthesis",
        "irrelevant_answer",
        "judge_parse_error",
        "judge_call_failed",
        "budget_exceeded",
    }
)

DEFAULT_DIMENSIONS = ("correctness", "evidence_support")
CATEGORY_DIMENSIONS: dict[str, tuple[str, ...]] = {
    "temporal_reasoning": ("correctness", "temporal_validity", "evidence_support"),
    "knowledge_update": (
        "correctness",
        "knowledge_update_handling",
        "contradiction_supersession_handling",
        "temporal_validity",
        "evidence_support",
    ),
    "contradiction": (
        "correctness",
        "knowledge_update_handling",
        "contradiction_supersession_handling",
        "temporal_validity",
        "evidence_support",
    ),
    "supersession": (
        "correctness",
        "knowledge_update_handling",
        "contradiction_supersession_handling",
        "temporal_validity",
        "evidence_support",
    ),
    "multi_session_preference_evolution": (
        "correctness",
        "preference_evolution_handling",
        "temporal_validity",
        "evidence_support",
    ),
    "session_correction": (
        "correctness",
        "session_correction_handling",
        "temporal_validity",
        "evidence_support",
    ),
    "self_knowledge": (
        "correctness",
        "self_knowledge_quality",
        "assistant_behavior_quality",
        "evidence_support",
    ),
    "assistant_behavior": (
        "correctness",
        "self_knowledge_quality",
        "assistant_behavior_quality",
        "evidence_support",
    ),
    "broad_pattern_synthesis": (
        "correctness",
        "broad_synthesis_quality",
        "community_summary_use",
        "evidence_support",
        "abstention_quality",
    ),
    "community_summary_reasoning": (
        "correctness",
        "broad_synthesis_quality",
        "community_summary_use",
        "evidence_support",
    ),
    "abstention": ("correctness", "abstention_quality", "evidence_support"),
}

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_'+#-]+")
_STOPWORDS = frozenset({"a", "an", "the", "is", "are", "to", "of", "for", "on", "in", "and"})
_PASS_THRESHOLD = 0.5


@dataclass(frozen=True)
class JudgeInput:
    """Everything the judge needs to score one answer."""

    question_id: str
    question: str
    expected_answer: str
    actual_answer: str
    category: str
    retrieved_evidence: list[dict[str, object]] = field(default_factory=list)
    metadata: dict[str, object] | None = None


def rubric_dimensions(category: str) -> tuple[str, ...]:
    """Return the rubric dimensions relevant to a benchmark category."""
    return CATEGORY_DIMENSIONS.get(category, DEFAULT_DIMENSIONS)


def deterministic_judge(judge_input: JudgeInput) -> JudgeResult:
    """Cheap, offline scoring by containment and term overlap."""
    expected = _normalize(judge_input.expected_answer)
    actual = _normalize(judge_input.actual_answer)
    if not expected:
        return _result(False, 0.0, "no gold answer", "irrelevant_answer", method="deterministic")
    if expected in actual:
        return _result(True, 1.0, "exact containment", None, method="deterministic")
    overlap = _term_overlap(expected, actual)
    passed = overlap >= _PASS_THRESHOLD
    error_type = None if passed else "missing_memory"
    return _result(passed, round(overlap, 4), "term overlap", error_type, method="deterministic")


def build_judge_prompt(judge_input: JudgeInput) -> str:
    """Build the LLM judge prompt (gold answer shown to the judge only)."""
    dimensions = rubric_dimensions(judge_input.category)
    evidence = json.dumps(judge_input.retrieved_evidence, default=str, sort_keys=True)[:2000]
    return (
        "You are a strict evaluation judge for an AI memory system. Score the AI answer "
        "against the gold answer for semantic correctness, not string overlap.\n\n"
        f"Question id: {judge_input.question_id}\n"
        f"Category: {judge_input.category}\n"
        f"Question: {judge_input.question}\n"
        f"Gold answer: {judge_input.expected_answer}\n"
        f"AI answer: {judge_input.actual_answer}\n"
        f"Retrieved memory evidence: {evidence}\n\n"
        f"Score these dimensions in [0,1]: {', '.join(dimensions)}.\n"
        f"If the answer is wrong, choose an error_type from: {', '.join(sorted(ERROR_TYPES))}.\n"
        "Return strict JSON with keys: passed (bool), score (0..1), reason (string), "
        "error_type (string or null), dimensions (object of dimension->0..1).\n"
    )


def llm_judge(
    judge_input: JudgeInput,
    *,
    model: str = DEFAULT_JUDGE_MODEL,
    temperature: float = 0.0,
    call: JudgeCall | None = None,
) -> JudgeResult:
    """Score one answer with an LLM judge, parsing structured JSON safely."""
    del temperature  # the call adapter owns sampling params; recorded by the caller
    prompt = build_judge_prompt(judge_input)
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    invoke = call if call is not None else _default_call
    try:
        response = invoke([{"role": "user", "content": prompt}], "benchmark_judge")
    except Exception as error:  # noqa: BLE001 - judge call failures must not crash the runner
        return _result(
            False,
            0.0,
            f"judge call failed: {error}",
            "judge_call_failed",
            method="llm",
            model=model,
            prompt_hash=prompt_hash,
        )
    parsed = _parse_judge_payload(response.get("json"), rubric_dimensions(judge_input.category))
    if parsed is None:
        return _result(
            False,
            0.0,
            "judge returned unparseable output",
            "judge_parse_error",
            method="llm",
            model=model,
            prompt_hash=prompt_hash,
        )
    parsed["method"] = "llm"
    parsed["model"] = model
    parsed["prompt_hash"] = prompt_hash
    return parsed


def hybrid_judge(
    judge_input: JudgeInput,
    *,
    model: str = DEFAULT_JUDGE_MODEL,
    temperature: float = 0.0,
    call: JudgeCall | None = None,
) -> JudgeResult:
    """Run both judges and preserve both results; the LLM judge decides pass/fail."""
    deterministic = deterministic_judge(judge_input)
    llm = llm_judge(judge_input, model=model, temperature=temperature, call=call)
    return {
        "method": "hybrid",
        "passed": bool(llm["passed"]),
        "score": llm["score"],
        "deterministic": deterministic,
        "llm_judge": llm,
    }


def score_with_judge(
    judge_input: JudgeInput,
    mode: str,
    *,
    model: str = DEFAULT_JUDGE_MODEL,
    temperature: float = 0.0,
    call: JudgeCall | None = None,
) -> JudgeResult:
    """Dispatch to the deterministic, llm, or hybrid judge."""
    if mode == "deterministic":
        return deterministic_judge(judge_input)
    if mode == "llm":
        return llm_judge(judge_input, model=model, temperature=temperature, call=call)
    if mode == "hybrid":
        return hybrid_judge(judge_input, model=model, temperature=temperature, call=call)
    raise ValueError(f"unknown judge mode: {mode!r}")


def judge_response(
    response: str,
    expected: str,
    context: list[dict[str, object]],
) -> dict[str, object]:
    """Backward-compatible deterministic scoring entry point."""
    return deterministic_judge(
        JudgeInput(
            question_id="",
            question="",
            expected_answer=expected,
            actual_answer=response,
            category="",
            retrieved_evidence=context,
        )
    )


def _parse_judge_payload(payload: object, dimensions: tuple[str, ...]) -> JudgeResult | None:
    if not isinstance(payload, dict):
        return None
    if "score" not in payload and "passed" not in payload:
        return None
    score = _clamp(payload.get("score"))
    passed = bool(payload.get("passed", score >= _PASS_THRESHOLD))
    error_type = payload.get("error_type")
    if error_type is not None and (
        not isinstance(error_type, str) or error_type not in ERROR_TYPES
    ):
        error_type = None
    raw_dimensions = payload.get("dimensions")
    scored_dimensions = {}
    if isinstance(raw_dimensions, dict):
        scored_dimensions = {
            dimension: _clamp(raw_dimensions.get(dimension))
            for dimension in dimensions
            if dimension in raw_dimensions
        }
    return {
        "passed": passed,
        "score": score,
        "reason": str(payload.get("reason", "")),
        "error_type": error_type,
        "dimensions": scored_dimensions,
    }


def _default_call(messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
    from core.llm.qwen import call_qwen_json

    return call_qwen_json(messages, schema_name=schema_name)


def _result(
    passed: bool,
    score: float,
    reason: str,
    error_type: str | None,
    *,
    method: str,
    model: str | None = None,
    prompt_hash: str | None = None,
) -> JudgeResult:
    result: JudgeResult = {
        "passed": passed,
        "score": score,
        "reason": reason,
        "error_type": error_type,
        "dimensions": {},
        "method": method,
    }
    if model is not None:
        result["model"] = model
    if prompt_hash is not None:
        result["prompt_hash"] = prompt_hash
    return result


def _term_overlap(expected: str, actual: str) -> float:
    expected_terms = _tokens(expected)
    actual_terms = _tokens(actual)
    if not expected_terms:
        return 0.0
    return len(expected_terms & actual_terms) / len(expected_terms)


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in _TOKEN_PATTERN.findall(value.casefold())
        if len(token) > 1 and token not in _STOPWORDS
    }


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def _clamp(value: object) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, int | float):
        return min(1.0, max(0.0, float(value)))
    return 0.0
