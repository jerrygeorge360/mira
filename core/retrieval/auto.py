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

import os
import re

from core.llm.profiles import active_profile
from core.llm.prompts import render_prompt
from core.llm.qwen import LLMClientError, call_qwen_json

Decision = dict[str, object]
RoutingStrategy = str
ROUTING_STRATEGIES = frozenset({"fast", "hybrid", "accurate"})

# Under the "hybrid" strategy, a deterministic route below this confidence (or one
# flagged ambiguous) defers to the LLM classifier. Kept below the deterministic router's
# base memory-cue confidence (0.7) so a correct-but-borderline personal-memory route is not
# handed to the less reliable, non-deterministic LLM classifier (which was observed to flip
# such a route to general_knowledge and abstain -- see the downgrade guard in route_retrieval).
ROUTER_ESCALATION_CONFIDENCE = 0.65
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
EXPLICIT_MEMORY_QUERY_MARKERS = (
    "about me",
    "for me",
    "who am i",
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
)
CONTEXTUAL_MEMORY_QUERY_MARKERS = (
    "the deadline",
    "this deadline",
    "that deadline",
    "the project",
    "this project",
    "that project",
    "the task",
    "this task",
    "that task",
    "the preference",
    "this preference",
    "that preference",
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
    "what kind of ",
    "what sort of ",
    "what type of ",
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

FOLLOWUP_REFERENCE_RE = re.compile(r"\b(?:that|this|it|those|these|they|them)\b")
FOLLOWUP_QUESTION_RE = re.compile(
    r"\b(?:what|why|how|who|where|when|is|are|was|were|do|does|did|can|could|would|should)\b"
)
CONVERSATION_MEMORY_MARKERS = (
    "you said",
    "you told",
    "did you",
    "i said",
    "i told",
    "we said",
    "we decided",
)

TRANSITION_PATTERN = re.compile(r"\bfrom\s+\w[\w.+-]*\s+to\s+\w[\w.+-]*")


def route_retrieval(
    query: str,
    session_id: str | None,
    *,
    strategy: RoutingStrategy = "fast",
    context: list[dict[str, object]] | None = None,
) -> Decision:
    """Classify a query into Quick, Deep, or Relational retrieval.

    Returns the chosen ``mode`` with a human-readable ``reason`` and a
    ``confidence``. Ambiguous queries route to Quick with
    ``needs_sufficiency_check`` set so the caller can retry after a sufficiency
    check. Recent ``context`` is supplied only to the LLM-assisted router for
    ambiguous follow-ups; confident general questions remain query-driven.
    """
    del session_id
    if strategy not in ROUTING_STRATEGIES:
        raise ValueError("strategy must be one of: fast, hybrid, accurate")

    inherited_general = _general_followup_decision(query, context)
    if inherited_general is not None:
        return inherited_general

    if strategy == "accurate":
        decision = _llm_route_retrieval(query, context)
        if decision is not None:
            return decision
        return _deterministic_route_retrieval(query)

    deterministic = _deterministic_route_retrieval(query)
    # Hybrid keeps the cheap deterministic route unless it is uncertain, then defers to
    # the LLM classifier -- but only when a provider key is configured, so unit tests
    # and offline runs stay deterministic and never attempt a network call.
    if strategy == "hybrid" and _should_escalate_to_llm(deterministic) and _llm_routing_available():
        llm_decision = _llm_route_retrieval(query, context)
        if llm_decision is not None and not _is_personal_to_general_downgrade(
            deterministic, llm_decision
        ):
            return llm_decision
    return deterministic


def _general_followup_decision(
    query: str,
    context: list[dict[str, object]] | None,
) -> Decision | None:
    """Keep an anaphoric follow-up on the preceding general-knowledge topic.

    Words such as ``that`` refer to the immediate conversation as often as they
    refer to durable memory. When the preceding user turn was clearly general
    knowledge, preserve that route instead of letting an LLM router reinterpret
    the pronoun as a request for personal graph traversal.
    """
    if not context:
        return None
    normalized = _normalize(query)
    if not _looks_like_anaphoric_followup(normalized):
        return None
    if _looks_explicitly_memory_grounded(normalized) or _looks_contextually_memory_grounded(
        normalized
    ):
        return None
    if any(marker in normalized for marker in CONVERSATION_MEMORY_MARKERS):
        return None

    prior_user_message = _latest_user_message(context)
    if prior_user_message is None:
        return None
    prior_decision = _deterministic_route_retrieval(prior_user_message)
    if prior_decision.get("intent") != GENERAL_KNOWLEDGE_INTENT:
        return None
    return _decision(
        "general",
        "follow-up to the current general-knowledge topic; durable memory is not required",
        0.88,
        intent=GENERAL_KNOWLEDGE_INTENT,
    )


def _looks_like_anaphoric_followup(normalized: str) -> bool:
    stripped = normalized.strip()
    if not FOLLOWUP_REFERENCE_RE.search(stripped):
        return False
    return bool(
        "?" in stripped
        or FOLLOWUP_QUESTION_RE.search(stripped)
        or stripped.startswith(("tell me more", "explain that", "explain this", "go on"))
    )


def _latest_user_message(context: list[dict[str, object]]) -> str | None:
    for turn in reversed(context):
        if str(turn.get("role", "")).casefold() != "user":
            continue
        content = turn.get("content")
        if isinstance(content, str) and content.strip():
            return content
    return None


def _is_personal_to_general_downgrade(deterministic: Decision, llm_decision: Decision) -> bool:
    """True when the LLM would turn a personal-memory route into general knowledge.

    A first-person memory question ("what did I ...") must still hit memory, so the
    deterministic personal-memory intent is kept rather than abstaining as general knowledge.
    """
    return (
        bool(deterministic.get("explicit_memory_cue"))
        and deterministic.get("intent") == PERSONAL_MEMORY_INTENT
        and llm_decision.get("intent") == GENERAL_KNOWLEDGE_INTENT
    )


def _should_escalate_to_llm(decision: Decision) -> bool:
    """A low-confidence or ambiguous deterministic route defers to the LLM classifier."""
    raw_confidence = decision.get("confidence", 1.0)
    confidence = float(raw_confidence) if isinstance(raw_confidence, (int, float)) else 0.0
    return confidence < ROUTER_ESCALATION_CONFIDENCE or bool(
        decision.get("needs_sufficiency_check")
    )


def _llm_routing_available() -> bool:
    """True when an LLM provider key is configured, so hybrid escalation can call it."""
    if os.environ.get("LLM_API_KEY") or os.environ.get("DASHSCOPE_API_KEY"):
        return True
    profile = active_profile()
    return bool(profile and os.environ.get(profile.api_key_env))


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

    explicit_memory = _looks_explicitly_memory_grounded(normalized)
    contextual_memory = _looks_contextually_memory_grounded(normalized)

    if _looks_general_question(normalized) and not explicit_memory and not contextual_memory:
        return _decision(
            "general",
            "general knowledge question; no user memory required",
            0.82,
            intent=GENERAL_KNOWLEDGE_INTENT,
        )

    relational_reason = _relational_reason(normalized)
    if relational_reason is not None:
        return _decision(
            "relational",
            relational_reason,
            0.86,
            intent=PERSONAL_MEMORY_INTENT,
            explicit_memory=explicit_memory,
        )

    deep_reason = _deep_reason(normalized)
    if deep_reason is not None:
        return _decision(
            "deep",
            deep_reason,
            0.8,
            intent=PERSONAL_MEMORY_INTENT,
            explicit_memory=explicit_memory,
        )

    if contextual_memory and not explicit_memory:
        return _decision(
            "quick",
            "context-dependent memory reference; verify against recent conversation",
            0.55,
            ambiguous=True,
            intent=MIXED_INTENT,
        )

    quick_reason = _quick_reason(normalized)
    if quick_reason is not None:
        return _decision(
            "quick",
            quick_reason,
            0.8,
            intent=PERSONAL_MEMORY_INTENT,
            explicit_memory=explicit_memory,
        )

    if explicit_memory:
        return _decision(
            "quick",
            "personal or session-specific memory cue",
            0.7,
            intent=PERSONAL_MEMORY_INTENT,
            explicit_memory=True,
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


def _llm_route_retrieval(
    query: str, context: list[dict[str, object]] | None = None
) -> Decision | None:
    prompt = render_prompt(
        "retrieval_router_classification",
        {"query": query, "context": context or []},
    )
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


def _looks_explicitly_memory_grounded(normalized: str) -> bool:
    identity_question = re.search(
        r"\b(?:what kind|what sort|what type) of .+\b(?:am i|are we)\b",
        normalized,
    )
    return bool(re.search(r"\b(?:my|our)\b", normalized) or identity_question) or any(
        marker in normalized for marker in EXPLICIT_MEMORY_QUERY_MARKERS
    )


def _looks_contextually_memory_grounded(normalized: str) -> bool:
    return any(marker in normalized for marker in CONTEXTUAL_MEMORY_QUERY_MARKERS)


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
    explicit_memory: bool = False,
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
        "explicit_memory_cue": explicit_memory,
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
