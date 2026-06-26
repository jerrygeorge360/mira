"""Verify ISSUE-123 LLM-as-Judge and deterministic scoring.

Ownership: MIRA contributors.
Related issue: ISSUE-123.
Architecture area: evaluation.
"""

from __future__ import annotations

from evaluation.judge import (
    JudgeInput,
    deterministic_judge,
    hybrid_judge,
    llm_judge,
    rubric_dimensions,
    score_with_judge,
)


def _judge_input(expected: str, actual: str, category: str = "knowledge_update") -> JudgeInput:
    return JudgeInput(
        question_id="q1",
        question="What changed?",
        expected_answer=expected,
        actual_answer=actual,
        category=category,
    )


def test_deterministic_judge_works_offline() -> None:
    """The deterministic judge scores by containment/overlap without any API."""
    passed = deterministic_judge(_judge_input("PostgreSQL", "We moved to PostgreSQL now."))
    assert passed["passed"] is True
    assert passed["method"] == "deterministic"

    failed = deterministic_judge(_judge_input("Kubernetes", "We use Postgres."))
    assert failed["passed"] is False
    assert failed["error_type"] == "missing_memory"


def test_llm_judge_parses_valid_json() -> None:
    """A valid judge JSON response parses into a structured verdict."""

    def fake_call(messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
        return {
            "json": {
                "passed": True,
                "score": 0.9,
                "reason": "correctly identifies 2030 and explains supersession",
                "error_type": None,
                "dimensions": {"correctness": 1.0, "evidence_support": 0.8},
            }
        }

    verdict = llm_judge(_judge_input("2030", "active year is 2030"), call=fake_call)
    assert verdict["passed"] is True
    assert verdict["score"] == 0.9
    assert verdict["method"] == "llm"
    assert verdict["dimensions"]["correctness"] == 1.0
    assert "prompt_hash" in verdict


def test_llm_judge_handles_invalid_json_safely() -> None:
    """Unparseable judge output degrades to a judge_parse_error, not a crash."""

    def fake_call(messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
        return {"json": "not a judge object"}

    verdict = llm_judge(_judge_input("2030", "irrelevant"), call=fake_call)
    assert verdict["passed"] is False
    assert verdict["score"] == 0.0
    assert verdict["error_type"] == "judge_parse_error"


def test_llm_judge_handles_call_failure() -> None:
    """A judge call exception becomes a judge_call_failed verdict."""

    def fake_call(messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
        raise RuntimeError("judge upstream down")

    verdict = llm_judge(_judge_input("2030", "x"), call=fake_call)
    assert verdict["passed"] is False
    assert verdict["error_type"] == "judge_call_failed"


def test_hybrid_judge_preserves_both_scores() -> None:
    """Hybrid mode keeps both the deterministic and LLM judge results."""

    def fake_call(messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
        return {"json": {"passed": True, "score": 0.8, "reason": "ok"}}

    verdict = hybrid_judge(_judge_input("2030", "the year is 2030"), call=fake_call)
    assert verdict["method"] == "hybrid"
    assert "deterministic" in verdict
    assert "llm_judge" in verdict
    assert verdict["passed"] is True


def test_score_with_judge_dispatches_modes() -> None:
    """score_with_judge routes to deterministic, llm, and hybrid."""

    def fake_call(messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
        return {"json": {"passed": True, "score": 1.0}}

    ji = _judge_input("2030", "2030")
    assert score_with_judge(ji, "deterministic")["method"] == "deterministic"
    assert score_with_judge(ji, "llm", call=fake_call)["method"] == "llm"
    assert score_with_judge(ji, "hybrid", call=fake_call)["method"] == "hybrid"


def test_rubric_dimensions_are_category_specific() -> None:
    """Rubric dimensions vary by benchmark category."""
    assert "temporal_validity" in rubric_dimensions("temporal_reasoning")
    assert "contradiction_supersession_handling" in rubric_dimensions("knowledge_update")
    assert "broad_synthesis_quality" in rubric_dimensions("broad_pattern_synthesis")
    assert rubric_dimensions("unknown_category") == ("correctness", "evidence_support")
