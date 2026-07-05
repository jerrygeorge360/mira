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

GENERAL_KNOWLEDGE_INTENT = "general_knowledge"
PERSONAL_MEMORY_INTENT = "personal_memory"
MIXED_INTENT = "mixed"
PROCEDURAL_INTENT = "procedural"

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
    "do i use now",
    "am i using now",
    "use now",
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
MEMORY_QUERY_MARKERS = (
    "my ",
    "our ",
    "about me",
    "for me",
    "who am i",
    "what kind of",
    "am i",
    "you remember",
    "remember",
    "remind me",
    "did i",
    "did we",
    "what did i",
    "what did we",
    "what have i",
    "what have we",
    "what do i",
    "what do we",
    "what was my",
    "what is my",
    "what's my",
    "where did i",
    "where is my",
    "when did i",
    "when is my",
    "last time",
    "previously",
    "before",
    "deadline",
    "preference",
    "prefer",
    "project",
    "task",
)
GENERAL_QUESTION_PREFIXES = (
    "what is ",
    "what's ",
    "what are ",
    "who is ",
    "who are ",
    "where is ",
    "where are ",
    "when is ",
    "how does ",
    "how do ",
    "how can ",
    "why does ",
    "why is ",
    "explain ",
    "define ",
)
PROCEDURAL_MARKERS = (
    "summarize this",
    "summarise this",
    "this conversation",
    "current conversation",
    "this session",
    "what did we just",
    "what are we doing",
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
        return _decision(
            "quick",
            "empty query defaults to quick facts",
            0.3,
            ambiguous=True,
            intent=PERSONAL_MEMORY_INTENT,
        )

    if _looks_procedural(normalized):
        return _decision(
            "quick",
            "current-session procedural question; use recent/session context first",
            0.74,
            intent=PROCEDURAL_INTENT,
        )

    if _looks_general_question(normalized) and not _looks_memory_grounded(normalized):
        return _decision(
            "general",
            "general knowledge question; no user memory required",
            0.82,
            intent=GENERAL_KNOWLEDGE_INTENT,
        )

    relational_reason = _relational_reason(normalized)
    if relational_reason is not None:
        return _decision("relational", relational_reason, 0.86, intent=PERSONAL_MEMORY_INTENT)

    deep_reason = _deep_reason(normalized)
    if deep_reason is not None:
        return _decision("deep", deep_reason, 0.8, intent=PERSONAL_MEMORY_INTENT)

    quick_reason = _quick_reason(normalized)
    if quick_reason is not None:
        return _decision("quick", quick_reason, 0.8, intent=PERSONAL_MEMORY_INTENT)

    if _looks_memory_grounded(normalized):
        return _decision(
            "quick",
            "personal or session-specific memory cue",
            0.7,
            intent=PERSONAL_MEMORY_INTENT,
        )

    return _decision(
        "quick",
        "ambiguous query; running quick first and deferring to the sufficiency check",
        0.4,
        ambiguous=True,
        intent=MIXED_INTENT,
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
            intent=_intent(payload, MIXED_INTENT),
        )
    if mode not in ROUTER_MODES:
        return None
    return _decision(mode, _reason(payload, "LLM router decision"), 0.9, intent=_intent(payload))


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


def _looks_memory_grounded(normalized: str) -> bool:
    return any(marker in normalized for marker in MEMORY_QUERY_MARKERS)


def _looks_general_question(normalized: str) -> bool:
    stripped = normalized.strip()
    return any(stripped.startswith(prefix) for prefix in GENERAL_QUESTION_PREFIXES)


def _looks_procedural(normalized: str) -> bool:
    return any(marker in normalized for marker in PROCEDURAL_MARKERS)


def _decision(
    mode: str,
    reason: str,
    confidence: float,
    *,
    ambiguous: bool = False,
    intent: str | None = None,
) -> Decision:
    selected_intent = intent or (
        GENERAL_KNOWLEDGE_INTENT if mode == "general" else PERSONAL_MEMORY_INTENT
    )
    used_memory = mode != "general"
    return {
        "mode": mode,
        "route": "direct_llm" if mode == "general" else mode,
        "intent": selected_intent,
        "used_memory": used_memory,
        "reason": reason,
        "confidence": confidence,
        "needs_sufficiency_check": ambiguous,
    }


def _reason(payload: dict[object, object], fallback: str) -> str:
    reason = payload.get("reason")
    if isinstance(reason, str) and reason.strip():
        return reason.strip()
    return fallback


def _intent(payload: dict[object, object], fallback: str | None = None) -> str:
    intent = payload.get("intent")
    if isinstance(intent, str) and intent:
        normalized = intent.casefold()
        if normalized in {
            GENERAL_KNOWLEDGE_INTENT,
            PERSONAL_MEMORY_INTENT,
            MIXED_INTENT,
            PROCEDURAL_INTENT,
        }:
            return normalized
    mode = str(payload.get("mode", "")).casefold()
    if mode == "general":
        return GENERAL_KNOWLEDGE_INTENT
    return fallback or PERSONAL_MEMORY_INTENT


def _normalize(value: str) -> str:
    collapsed = re.sub(r"\s+", " ", value.casefold()).strip()
    return f" {collapsed} "
