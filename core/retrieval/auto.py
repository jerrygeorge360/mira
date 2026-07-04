"""Automatic retrieval-mode classifier (router decision, not dispatch).

Ownership: Jerry.
Related issue: ISSUE-037.
Architecture area: retrieval.

Routing keeps every query from paying graph or deep-synthesis cost. The decision
is deterministic and cheap (no model call just to route) and follows a fixed
order so specific graph questions are not swallowed by broad Deep Mode:

1. Relational first  -- entity-centered change / conflict / causal / comparison.
2. Deep second       -- broad pattern / synthesis / evolution / identity.
3. Quick default     -- specific facts.
4. Ambiguous         -- run Quick first and flag for the sufficiency check.

This module only decides the mode; it never retrieves records.
"""

from __future__ import annotations

import re

from core.llm.prompts import render_prompt
from core.llm.qwen import LLMClientError, call_qwen_json

Decision = dict[str, object]
RoutingStrategy = str
ROUTING_STRATEGIES = frozenset({"fast", "accurate"})
ROUTER_MODES = frozenset({"general", "quick", "deep", "relational", "auto"})

RELATIONAL_MARKERS = (
    "switch",
    "switched",
    "migrate",
    "migrated",
    "moved from",
    "changed from",
    "change from",
    "used to",
    "no longer",
    "instead of",
    "contradict",
    "conflict",
    "inconsistent",
    "versus",
    " vs ",
    "compare",
    "compared to",
    "difference between",
    "different from",
    "why did",
    "why is",
    "why does",
    "what caused",
    "cause of",
    "led to",
    "leads to",
    "result of",
    "because of",
    "→",
    "->",
)
DEEP_MARKERS = (
    "what kind of",
    "what sort of",
    "what type of",
    "who am i",
    "am i",
    "describe me",
    "my style",
    "personality",
    "overall",
    "in general",
    "generally",
    "pattern",
    "patterns",
    "themes",
    "summarize",
    "summary",
    "big picture",
    "high level",
    "over time",
    "evolution",
    "evolved",
    "how have i",
    "trend",
)
QUICK_FACT_MARKERS = (
    "what is my",
    "what's my",
    "when is",
    "when's",
    "what time",
    "deadline",
    "due date",
    "due",
    "what did i say",
    "remind me",
    "do i have",
    "where is",
    "how many",
)

TRANSITION_PATTERN = re.compile(r"\bfrom\s+\w[\w.+-]*\s+to\s+\w[\w.+-]*")


def route_retrieval(
    query: str,
    session_id: str | None,
    *,
    strategy: RoutingStrategy = "fast",
) -> Decision:
    """Classify a query into Quick, Deep, or Relational retrieval.

    Returns the chosen ``mode`` with a human-readable ``reason`` and a
    ``confidence``. Ambiguous queries route to Quick with
    ``needs_sufficiency_check`` set so the caller can retry after a sufficiency
    check. ``session_id`` is accepted for interface parity and future
    session-aware routing; the decision is query-driven.
    """
    del session_id  # Reserved for future session-aware routing.
    if strategy not in ROUTING_STRATEGIES:
        raise ValueError("strategy must be one of: fast, accurate")
    if strategy == "accurate":
        decision = _llm_route_retrieval(query)
        if decision is not None:
            return decision
    return _deterministic_route_retrieval(query)


def _deterministic_route_retrieval(query: str) -> Decision:
    normalized = _normalize(query)
    if not normalized.strip():
        return _decision("quick", "empty query defaults to quick facts", 0.3, ambiguous=True)

    relational_reason = _relational_reason(normalized)
    if relational_reason is not None:
        return _decision("relational", relational_reason, 0.86)

    deep_reason = _deep_reason(normalized)
    if deep_reason is not None:
        return _decision("deep", deep_reason, 0.8)

    quick_reason = _quick_reason(normalized)
    if quick_reason is not None:
        return _decision("quick", quick_reason, 0.8)

    return _decision(
        "quick",
        "ambiguous query; running quick first and deferring to the sufficiency check",
        0.4,
        ambiguous=True,
    )


def classify_retrieval_mode(query: str) -> str:
    """Classify a query into Quick, Deep, or Relational retrieval (mode only)."""
    return str(route_retrieval(query, None)["mode"])


def _llm_route_retrieval(query: str) -> Decision | None:
    prompt = render_prompt("retrieval_router_classification", {"query": query, "context": []})
    try:
        response = call_qwen_json(
            [{"role": "user", "content": prompt}],
            schema_name="retrieval_router_classification",
        )
    except LLMClientError:
        return None

    payload = response.get("json", {})
    if not isinstance(payload, dict):
        return None
    mode = str(payload.get("mode", "")).casefold()
    if mode == "auto":
        return _decision(
            "quick",
            _reason(payload, "LLM router returned auto; running quick first"),
            0.45,
            ambiguous=True,
        )
    if mode not in ROUTER_MODES:
        return None
    return _decision(mode, _reason(payload, "LLM router decision"), 0.9)


def _relational_reason(normalized: str) -> str | None:
    if TRANSITION_PATTERN.search(normalized):
        return "entity-centered change question (transition between two values)"
    marker = _first_marker(normalized, RELATIONAL_MARKERS)
    if marker is not None:
        return f"entity-centered relational cue ({marker.strip()!r})"
    return None


def _deep_reason(normalized: str) -> str | None:
    marker = _first_marker(normalized, DEEP_MARKERS)
    if marker is not None:
        return f"broad synthesis or identity cue ({marker.strip()!r})"
    return None


def _quick_reason(normalized: str) -> str | None:
    marker = _first_marker(normalized, QUICK_FACT_MARKERS)
    if marker is not None:
        return f"specific factual lookup ({marker.strip()!r})"
    return None


def _first_marker(normalized: str, markers: tuple[str, ...]) -> str | None:
    for marker in markers:
        if marker in normalized:
            return marker
    return None


def _decision(mode: str, reason: str, confidence: float, *, ambiguous: bool = False) -> Decision:
    return {
        "mode": mode,
        "reason": reason,
        "confidence": confidence,
        "needs_sufficiency_check": ambiguous,
    }


def _reason(payload: dict[object, object], fallback: str) -> str:
    reason = payload.get("reason")
    if isinstance(reason, str) and reason.strip():
        return reason.strip()
    return fallback


def _normalize(value: str) -> str:
    collapsed = re.sub(r"\s+", " ", value.casefold()).strip()
    return f" {collapsed} "
