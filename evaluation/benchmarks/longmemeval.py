"""LongMemEval / LoCoMo-style adapter skeleton for long-session memory evaluation.

Ownership: MIRA contributors.
Related issue: ISSUE-052.
Architecture area: evaluation.

This is a prototype adapter, not an official benchmark run. It shows MIRA can be
evaluated against long-term multi-session memory tasks by providing thin,
composable skeletons for each stage:

- session loader -- parse the sessions of a benchmark example;
- multi-session importer -- replay those sessions into MIRA memory;
- question runner -- ask the benchmark question through the agent;
- answer capture -- record MIRA's answer;
- scoring hooks -- pluggable scoring (default: lenient containment match).

Results are explicitly labeled prototype/unofficial. Do not report these as
official LongMemEval/LoCoMo scores unless the real datasets are actually run.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from core.agent import handle_user_message
from core.db.repositories import create_session
from core.memory.observation import persist_turn_fast_path

BenchmarkExample = dict[str, object]
ScoreResult = dict[str, object]
Scorer = Callable[[str, str], ScoreResult]

LOGGER = logging.getLogger(__name__)

VALID_ROLES = frozenset({"user", "assistant"})


@dataclass(frozen=True)
class BenchmarkTurn:
    """One turn within a benchmark session."""

    role: str
    content: str


@dataclass(frozen=True)
class BenchmarkSession:
    """One session of a multi-session benchmark example."""

    session_ref: str
    turns: list[BenchmarkTurn]


@dataclass
class ImportResult:
    """Outcome of importing a benchmark example's sessions into MIRA."""

    session_id_map: dict[str, str] = field(default_factory=dict)
    imported_turns: int = 0


# --- Session loader ---------------------------------------------------------


def load_benchmark_dataset(dataset_path: str) -> dict[str, object]:
    """Load a benchmark dataset file (object with ``examples`` or a bare list)."""
    data = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return {"examples": [item for item in data if isinstance(item, dict)]}
    if isinstance(data, dict):
        examples = data.get("examples", [])
        valid = (
            [item for item in examples if isinstance(item, dict)]
            if isinstance(examples, list)
            else []
        )
        return {**data, "examples": valid}
    return {"examples": []}


def iter_examples(dataset: dict[str, object]) -> list[BenchmarkExample]:
    """Return the benchmark examples from a loaded dataset."""
    examples = dataset.get("examples", [])
    if not isinstance(examples, list):
        return []
    return [example for example in examples if isinstance(example, dict)]


def load_sessions(example: BenchmarkExample) -> list[BenchmarkSession]:
    """Parse the sessions (and turns) of one benchmark example."""
    raw_sessions = example.get("sessions", [])
    sessions: list[BenchmarkSession] = []
    if not isinstance(raw_sessions, list):
        return sessions
    for index, raw_session in enumerate(raw_sessions):
        if not isinstance(raw_session, dict):
            continue
        session_ref = str(raw_session.get("session_id", f"session_{index}"))
        sessions.append(BenchmarkSession(session_ref, _parse_turns(raw_session.get("turns"))))
    return sessions


# --- Multi-session conversation importer ------------------------------------


def import_conversations(example: BenchmarkExample) -> ImportResult:
    """Replay a benchmark example's sessions into MIRA as raw observations.

    Each turn is persisted on the fast path (and queued for the slow path), so
    the haystack conversation becomes ingestible memory without regenerating the
    given assistant turns. Returns a mapping from benchmark session refs to the
    created MIRA session ids.
    """
    result = ImportResult()
    for session in load_sessions(example):
        mira_session_id = create_session("benchmark")
        result.session_id_map[session.session_ref] = mira_session_id
        for turn in session.turns:
            if turn.role not in VALID_ROLES or not turn.content.strip():
                continue
            persist_turn_fast_path(mira_session_id, turn.role, turn.content)
            result.imported_turns += 1
    LOGGER.info(
        "Imported %d turns across %d sessions",
        result.imported_turns,
        len(result.session_id_map),
    )
    return result


# --- Question runner + answer capture ---------------------------------------


def run_question(question: str, session_id: str | None = None) -> dict[str, object]:
    """Ask a benchmark question through the agent and capture the answer."""
    if not question.strip():
        raise ValueError("question must not be empty")
    target_session_id = session_id or create_session("benchmark")
    response = handle_user_message(target_session_id, question)
    return {
        "session_id": target_session_id,
        "question": question,
        "answer": str(response.get("answer", "")),
        "retrieval_mode": response.get("retrieval_mode"),
        "used_memory_items": response.get("used_memory_items", []),
    }


# --- Scoring hooks ----------------------------------------------------------


def score_answer(expected: str, actual: str, scorer: Scorer | None = None) -> ScoreResult:
    """Score a captured answer against the gold answer via a pluggable scorer."""
    return (scorer or default_scorer)(expected, actual)


def default_scorer(expected: str, actual: str) -> ScoreResult:
    """Lenient containment scorer: gold answer (or its terms) present in the answer."""
    expected_norm = _normalize(expected)
    actual_norm = _normalize(actual)
    if not expected_norm:
        return {"match": False, "score": 0.0, "reason": "no gold answer"}
    if expected_norm in actual_norm:
        return {"match": True, "score": 1.0, "reason": "exact containment"}
    expected_terms = set(expected_norm.split())
    actual_terms = set(actual_norm.split())
    overlap = len(expected_terms & actual_terms) / len(expected_terms)
    return {"match": overlap >= 0.5, "score": round(overlap, 4), "reason": "term overlap"}


# --- Orchestrator -----------------------------------------------------------


def run_longmemeval(
    dataset_path: str,
    *,
    scorer: Scorer | None = None,
    limit: int | None = None,
) -> dict[str, object]:
    """Run the prototype LongMemEval-style adapter over a dataset.

    Imports each example's sessions, asks its question through the agent in a
    fresh session, scores the answer, and aggregates a clearly-labeled prototype
    summary. This is not an official benchmark score.
    """
    dataset = load_benchmark_dataset(dataset_path)
    examples = iter_examples(dataset)
    if limit is not None:
        examples = examples[:limit]

    results: list[dict[str, object]] = []
    for example in examples:
        import_conversations(example)
        question = str(example.get("question", ""))
        try:
            captured = run_question(question)
            score = score_answer(str(example.get("answer", "")), str(captured["answer"]), scorer)
        except (ValueError, KeyError) as failure:
            captured = {"answer": "", "retrieval_mode": None}
            score = {"match": False, "score": 0.0, "reason": str(failure)}
        results.append(
            {
                "question_id": str(example.get("question_id", "unknown")),
                "question_type": str(example.get("question_type", "unspecified")),
                "matched": bool(score["match"]),
                "score": score["score"],
                "answer": captured["answer"],
            }
        )

    matched = sum(1 for result in results if result["matched"])
    total = len(results)
    return {
        "official": False,
        "status": "prototype",
        "note": "Prototype adapter output; not an official LongMemEval/LoCoMo score.",
        "dataset": str(dataset.get("name", Path(dataset_path).name)),
        "total": total,
        "matched": matched,
        "match_rate": round(matched / total, 4) if total else 0.0,
        "results": results,
    }


def _parse_turns(raw_turns: object) -> list[BenchmarkTurn]:
    turns: list[BenchmarkTurn] = []
    if not isinstance(raw_turns, list):
        return turns
    for raw_turn in raw_turns:
        if not isinstance(raw_turn, dict):
            continue
        role = str(raw_turn.get("role", "")).strip()
        content = str(raw_turn.get("content", "")).strip()
        if role and content:
            turns.append(BenchmarkTurn(role, content))
    return turns


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())
