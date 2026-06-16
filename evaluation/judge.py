"""LLM-as-judge evaluation for MIRA.

Scores agent responses against expected behaviour using an LLM judge, producing
per-criterion scores and rationale for the evaluation reports.

ISSUE-021: LLM judge.
"""

from __future__ import annotations

from typing import Any


def judge_response(question: str, response: str, reference: str) -> dict[str, Any]:
    """Score a single agent response against a reference answer.

    Args:
        question: The question or prompt that was posed to the agent.
        response: The agent's response under evaluation.
        reference: The expected or gold-standard answer.

    Returns:
        A mapping of criterion to score, plus the judge's rationale.
    """
    raise NotImplementedError
