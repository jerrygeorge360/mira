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
from core.retrieval.sufficiency import check_grounded_sufficiency, check_retrieval_sufficiency

Decision = dict[str, object]
RoutingStrategy = str
ROUTING_STRATEGIES = frozenset({"fast", "hybrid", "accurate"})

# Under the "hybrid" strategy, a deterministic route below this confidence (or one
# flagged ambiguous) defers to the LLM classifier. Kept below the deterministic router's
# base memory-cue confidence (0.7) so a correct-but-borderline personal-memory route is not
# handed to the less reliable, non-deterministic LLM classifier (which was observed to flip
# such a route to general_knowledge and abstain -- see the downgrade guard in route_retrieval).
ROUTER_ESCALATION_CONFIDENCE = 0.65
MIN_LLM_ROUTE_CONFIDENCE = 0.65
ROUTER_MODES = frozenset({"quick", "deep", "relational"})
MODE_SUFFICIENCY_CONFIDENCE = 0.75

GENERAL_KNOWLEDGE_INTENT = "general_knowledge"
PERSONAL_MEMORY_INTENT = "personal_memory"
MIXED_INTENT = "mixed"
PROCEDURAL_INTENT = "procedural"

NO_RETRIEVAL_CONTEXT = "no_retrieval"
GENERAL_CONTEXT = "general_knowledge"
RECENT_CONTEXT = "recent_conversation"
SESSION_CONTEXT = "session_memory"
DURABLE_CONTEXT = "durable_memory"
MIXED_CONTEXT = "mixed"
CONTEXT_SCOPES = frozenset(
    {
        NO_RETRIEVAL_CONTEXT,
        GENERAL_CONTEXT,
        RECENT_CONTEXT,
        SESSION_CONTEXT,
        DURABLE_CONTEXT,
        MIXED_CONTEXT,
    }
)
NO_DURABLE_RETRIEVAL_SCOPES = frozenset(
    {NO_RETRIEVAL_CONTEXT, GENERAL_CONTEXT, RECENT_CONTEXT, SESSION_CONTEXT}
)
DURABLE_RETRIEVAL_SCOPES = frozenset({DURABLE_CONTEXT, MIXED_CONTEXT})

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
    "agenda today",
    "on the agenda",
    "on my agenda",
    "my schedule",
    "my plans",
    "schedule today",
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
    "what was ",
    "what were ",
    "what did ",
    "what does ",
    "what made ",
    "what can ",
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
    "why did ",
    "why is ",
    "why was ",
    "why were ",
    "explain ",
    "define ",
    "what kind of ",
    "what sort of ",
    "what type of ",
)
DISCOURSE_PREFIX_RE = re.compile(
    r"^(?:alright|also|and|but|okay|ok|quick question|so|well|yeah|yh|yes)[,\s]+",
    re.IGNORECASE,
)
CASUAL_REACTION_MARKERS = frozenset(
    {
        "alright",
        "cool",
        "got it",
        "nice",
        "okay",
        "ok",
        "thanks",
        "thank you",
        "that is sad",
        "that is unfortunate",
        "that's sad",
        "that's unfortunate",
    }
)
PROCEDURAL_MARKERS = (
    "summarize this",
    "summarise this",
    "this conversation",
    "current conversation",
    "this session",
    "what did i just",
    "what did we just",
    "what i just said",
    "what i just told",
    "remind me what i just",
    "what are we doing",
)
GENERAL_ADVICE_MARKERS = (
    "should i ",
    "should we ",
    "would it make sense ",
    "is it worth ",
    "do you recommend ",
)
STANDALONE_GREETING_RE = re.compile(
    r"^(?:hello|hey|hi|good morning|good afternoon|good evening)(?:\s+there)?[!.]?$"
)
STANDALONE_CLOSING_RE = re.compile(r"^(?:appreciate it|thanks|thank you|got it|okay|ok)[!.]?$")

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
CONVERSATION_PARTICIPANT_RE = re.compile(
    r"\b(?:i|me|my|mine|we|us|our|ours|you|your|yours)\b",
    re.IGNORECASE,
)

TRANSITION_PATTERN = re.compile(r"\bfrom\s+\w[\w.+-]*\s+to\s+\w[\w.+-]*")


def route_retrieval(
    query: str,
    session_id: str | None,
    *,
    strategy: RoutingStrategy = "fast",
    context: list[dict[str, object]] | None = None,
    turn_purpose: str | None = None,
) -> Decision:
    """Select context scope first, then a durable retrieval mode when required."""
    del session_id
    if strategy not in ROUTING_STRATEGIES:
        raise ValueError("strategy must be one of: fast, hybrid, accurate")

    purpose = turn_purpose or _infer_turn_purpose(query)
    deterministic_scope = _deterministic_context_scope(query, context, purpose)
    semantic_recent_scope = _semantic_recent_scope_decision(
        query,
        context,
        purpose,
        strategy,
        deterministic_scope,
    )
    if semantic_recent_scope is not None:
        deterministic_scope = semantic_recent_scope
    scope_decision = _select_context_scope(
        query,
        context,
        purpose,
        strategy,
        deterministic_scope,
    )
    scope = str(scope_decision["context_scope"])
    if scope not in DURABLE_RETRIEVAL_SCOPES:
        return _compose_decision(
            query,
            purpose,
            scope_decision,
            mode_decision=None,
        )

    deterministic_mode = _deterministic_retrieval_mode(query)
    mode_decision = _select_retrieval_mode(
        query,
        context,
        scope,
        strategy,
        deterministic_mode,
    )
    return _compose_decision(query, purpose, scope_decision, mode_decision)


def _semantic_recent_scope_decision(
    query: str,
    context: list[dict[str, object]] | None,
    turn_purpose: str,
    strategy: RoutingStrategy,
    deterministic: Decision,
) -> Decision | None:
    if (
        strategy == "fast"
        or turn_purpose != "question"
        or not context
        or not _llm_routing_available()
        or deterministic.get("context_scope") not in DURABLE_RETRIEVAL_SCOPES
    ):
        return None
    evidence = _recent_user_evidence(context)
    if not evidence:
        return None
    verdict = check_grounded_sufficiency(query, evidence)
    if not verdict.get("is_sufficient"):
        return None
    return _scope_decision(
        RECENT_CONTEXT,
        "structured evidence verification found the bounded recent conversation sufficient",
        0.9,
        source="semantic_grounding",
        explicit_memory=bool(deterministic.get("explicit_memory_cue")),
    )


def _select_context_scope(
    query: str,
    context: list[dict[str, object]] | None,
    turn_purpose: str,
    strategy: RoutingStrategy,
    deterministic: Decision,
) -> Decision:
    deterministic_scope = str(deterministic["context_scope"])
    conversation_addressed_general = bool(
        context
        and deterministic_scope == GENERAL_CONTEXT
        and CONVERSATION_PARTICIPANT_RE.search(query)
    )
    if deterministic_scope == NO_RETRIEVAL_CONTEXT or (
        deterministic_scope in {GENERAL_CONTEXT, RECENT_CONTEXT}
        and _decision_confidence(deterministic) >= 0.9
        and not conversation_addressed_general
        and strategy != "accurate"
    ):
        return deterministic
    should_use_llm = strategy == "accurate" or (
        strategy == "hybrid"
        and (
            _decision_confidence(deterministic) < ROUTER_ESCALATION_CONFIDENCE
            or conversation_addressed_general
        )
        and _llm_routing_available()
    )
    if not should_use_llm:
        return deterministic
    llm_decision = _llm_context_scope(query, context, turn_purpose)
    return _validated_scope_decision(deterministic, llm_decision)


def _select_retrieval_mode(
    query: str,
    context: list[dict[str, object]] | None,
    context_scope: str,
    strategy: RoutingStrategy,
    deterministic: Decision,
) -> Decision:
    should_use_llm = strategy == "accurate" or (
        strategy == "hybrid"
        and _decision_confidence(deterministic) < ROUTER_ESCALATION_CONFIDENCE
        and _llm_routing_available()
    )
    if not should_use_llm:
        return deterministic
    llm_decision = _llm_retrieval_mode(query, context, context_scope)
    if llm_decision is None or _decision_confidence(llm_decision) < MIN_LLM_ROUTE_CONFIDENCE:
        return deterministic
    return llm_decision


def _validated_scope_decision(
    deterministic: Decision,
    llm_decision: Decision | None,
) -> Decision:
    if llm_decision is None or _decision_confidence(llm_decision) < MIN_LLM_ROUTE_CONFIDENCE:
        return deterministic
    deterministic_scope = str(deterministic["context_scope"])
    llm_scope = str(llm_decision["context_scope"])
    if deterministic_scope == GENERAL_CONTEXT and llm_scope not in {
        GENERAL_CONTEXT,
        RECENT_CONTEXT,
    }:
        return deterministic
    if bool(deterministic.get("explicit_memory_cue")) and llm_scope in {
        NO_RETRIEVAL_CONTEXT,
        GENERAL_CONTEXT,
        RECENT_CONTEXT,
    }:
        return deterministic
    return llm_decision


def _compose_decision(
    query: str,
    turn_purpose: str,
    scope_decision: Decision,
    mode_decision: Decision | None,
) -> Decision:
    scope = str(scope_decision["context_scope"])
    retrieval_required = scope in DURABLE_RETRIEVAL_SCOPES
    retrieval_mode = str(mode_decision["mode"]) if mode_decision is not None else None
    scope_confidence = _decision_confidence(scope_decision)
    mode_confidence = _decision_confidence(mode_decision or {})
    confidence = mode_confidence if retrieval_required else scope_confidence
    needs_sufficiency = bool(
        retrieval_required
        and (
            scope_confidence < MODE_SUFFICIENCY_CONFIDENCE
            or mode_confidence < MODE_SUFFICIENCY_CONFIDENCE
            or bool((mode_decision or {}).get("needs_sufficiency_check"))
        )
    )
    intent = _intent_for_scope(scope)
    route = _route_for_scope(scope, retrieval_mode)
    return {
        # ``mode=general`` remains a compatibility projection for current API clients.
        "mode": retrieval_mode or "general",
        "retrieval_mode": retrieval_mode,
        "route": route,
        "intent": intent,
        "turn_purpose": turn_purpose,
        "context_scope": scope,
        "scope_source": scope_decision.get("source", "deterministic"),
        "scope_confidence": scope_confidence,
        "mode_source": (mode_decision or {}).get("source"),
        "mode_confidence": mode_confidence if retrieval_required else None,
        "retrieval_required": retrieval_required,
        "used_memory": scope in {SESSION_CONTEXT, DURABLE_CONTEXT, MIXED_CONTEXT},
        "reason": str((mode_decision or scope_decision).get("reason", "")),
        "confidence": confidence,
        "needs_sufficiency_check": needs_sufficiency,
        "explicit_memory_cue": _looks_explicitly_memory_grounded(_normalize(query)),
    }


def _looks_like_anaphoric_followup(normalized: str) -> bool:
    stripped = normalized.strip()
    if not FOLLOWUP_REFERENCE_RE.search(stripped):
        return False
    return bool(
        "?" in stripped
        or FOLLOWUP_QUESTION_RE.search(stripped)
        or stripped.startswith(("tell me more", "explain that", "explain this", "go on"))
    )


def _llm_routing_available() -> bool:
    """True when an LLM provider key is configured, so hybrid escalation can call it."""
    if os.environ.get("LLM_API_KEY") or os.environ.get("DASHSCOPE_API_KEY"):
        return True
    profile = active_profile()
    return bool(profile and os.environ.get(profile.api_key_env))


def _deterministic_context_scope(
    query: str,
    context: list[dict[str, object]] | None,
    turn_purpose: str,
) -> Decision:
    normalized = _normalize(query)
    explicit_memory = _looks_explicitly_memory_grounded(normalized)
    if not normalized.strip():
        return _scope_decision(
            MIXED_CONTEXT,
            "empty query has no reliable context scope",
            0.3,
            explicit_memory=explicit_memory,
        )
    if turn_purpose == "casual_message":
        return _scope_decision(
            NO_RETRIEVAL_CONTEXT,
            "casual turn can be answered without replaying prior factual context",
            0.96,
            explicit_memory=explicit_memory,
        )
    if turn_purpose in {"informational_update", "correction", "decision", "resolution"}:
        return _scope_decision(
            NO_RETRIEVAL_CONTEXT,
            f"{turn_purpose} terminates before memory retrieval",
            0.96,
            explicit_memory=explicit_memory,
        )
    if (
        context
        and turn_purpose == "question"
        and _recent_user_context_is_sufficient(query, context)
    ):
        return _scope_decision(
            RECENT_CONTEXT,
            "recent user statements directly satisfy the question",
            0.94,
            explicit_memory=explicit_memory,
        )
    contextual_memory = _looks_contextually_memory_grounded(normalized)
    if _looks_procedural(normalized):
        return _scope_decision(
            RECENT_CONTEXT,
            "the current conversational task is sufficient",
            0.82,
            explicit_memory=False,
        )
    if explicit_memory and _looks_like_mixed_personal_advice_query(normalized):
        return _scope_decision(
            MIXED_CONTEXT,
            "the query combines a personal-memory lookup with general advice",
            0.82,
            explicit_memory=True,
        )
    if explicit_memory:
        return _scope_decision(
            DURABLE_CONTEXT,
            "the response explicitly depends on user or project memory",
            0.84,
            explicit_memory=True,
        )
    if contextual_memory:
        return _scope_decision(
            MIXED_CONTEXT,
            "the query references context that may span recent and durable memory",
            0.58,
            explicit_memory=False,
        )
    if context and _looks_like_recent_followup(normalized):
        return _scope_decision(
            RECENT_CONTEXT,
            "the turn is an elliptical follow-up to the current conversation",
            0.9,
            explicit_memory=False,
        )
    if not context and _looks_like_anaphoric_followup(normalized):
        return _scope_decision(
            MIXED_CONTEXT,
            "the referenced context is unavailable; use quick retrieval with sufficiency",
            0.4,
            explicit_memory=False,
        )
    if _looks_general_question(normalized):
        return _scope_decision(
            GENERAL_CONTEXT,
            "general knowledge question; no user memory required",
            0.9,
            explicit_memory=False,
        )
    if turn_purpose == "instruction":
        return _scope_decision(
            GENERAL_CONTEXT,
            "standalone instruction does not require stored user memory",
            0.76,
            explicit_memory=False,
        )
    return _scope_decision(
        MIXED_CONTEXT,
        "the required context scope is ambiguous",
        0.45,
        explicit_memory=False,
    )


def _deterministic_retrieval_mode(query: str) -> Decision:
    normalized = _normalize(query)
    relational_reason = _relational_reason(normalized)
    if relational_reason is not None:
        return _mode_decision("relational", relational_reason, 0.86)
    deep_reason = _deep_reason(normalized)
    if deep_reason is not None:
        return _mode_decision("deep", deep_reason, 0.8)
    quick_reason = _quick_reason(normalized)
    if quick_reason is not None:
        return _mode_decision("quick", quick_reason, 0.84)
    if _looks_explicitly_memory_grounded(normalized):
        return _mode_decision("quick", "direct personal-memory lookup", 0.8)
    return _mode_decision(
        "quick",
        "uncertain durable mode defaults to quick with a sufficiency check",
        0.55,
        needs_sufficiency=True,
    )


def _deterministic_route_retrieval(query: str) -> Decision:
    """Compatibility helper returning the composed deterministic decision."""
    purpose = _infer_turn_purpose(query)
    scope = _deterministic_context_scope(query, None, purpose)
    mode = (
        _deterministic_retrieval_mode(query)
        if str(scope["context_scope"]) in DURABLE_RETRIEVAL_SCOPES
        else None
    )
    return _compose_decision(query, purpose, scope, mode)


def classify_retrieval_mode(query: str) -> str:
    """Classify a query into Quick, Deep, or Relational retrieval (mode only)."""
    return str(route_retrieval(query, None)["mode"])


def _llm_context_scope(
    query: str,
    context: list[dict[str, object]] | None,
    turn_purpose: str,
) -> Decision | None:
    prompt = render_prompt(
        "context_scope_classification",
        {
            "query": query,
            "context": context or [],
            "turn_purpose": turn_purpose,
        },
    )
    try:
        response = call_qwen_json(
            [{"role": "user", "content": prompt}],
            schema_name="context_scope_classification",
        )
    except LLMClientError:
        return None
    payload = response.get("json", {})
    if not isinstance(payload, dict):
        return None
    context_scope = str(payload.get("context_scope", "")).casefold()
    if context_scope not in CONTEXT_SCOPES:
        return None
    return _scope_decision(
        context_scope,
        _reason(payload, "LLM-assisted context-scope decision"),
        _payload_confidence(payload),
        source="llm",
    )


def _llm_retrieval_mode(
    query: str,
    context: list[dict[str, object]] | None,
    context_scope: str,
) -> Decision | None:
    prompt = render_prompt(
        "retrieval_mode_classification",
        {
            "query": query,
            "context": context or [],
            "context_scope": context_scope,
        },
    )
    try:
        response = call_qwen_json(
            [{"role": "user", "content": prompt}],
            schema_name="retrieval_mode_classification",
        )
    except LLMClientError:
        return None
    payload = response.get("json", {})
    if not isinstance(payload, dict):
        return None
    mode = str(payload.get("mode", "")).casefold()
    if mode not in ROUTER_MODES:
        return None
    confidence = _payload_confidence(payload)
    return _mode_decision(
        mode,
        _reason(payload, "LLM-assisted retrieval-mode decision"),
        confidence,
        source="llm",
        needs_sufficiency=confidence < MODE_SUFFICIENCY_CONFIDENCE,
    )


def _scope_decision(
    context_scope: str,
    reason: str,
    confidence: float,
    *,
    source: str = "deterministic",
    explicit_memory: bool = False,
) -> Decision:
    return {
        "context_scope": context_scope,
        "reason": reason,
        "confidence": confidence,
        "source": source,
        "explicit_memory_cue": explicit_memory,
    }


def _mode_decision(
    mode: str,
    reason: str,
    confidence: float,
    *,
    source: str = "deterministic",
    needs_sufficiency: bool = False,
) -> Decision:
    return {
        "mode": mode,
        "reason": reason,
        "confidence": confidence,
        "source": source,
        "needs_sufficiency_check": needs_sufficiency,
    }


def _infer_turn_purpose(query: str) -> str:
    stripped = _strip_discourse_prefix(query.casefold().strip(" .,!"))
    if not stripped or stripped in CASUAL_REACTION_MARKERS:
        return "casual_message"
    if "?" in query or _looks_general_question(_normalize(query)):
        return "question"
    if stripped.startswith(
        ("explain ", "give me ", "help ", "show me ", "tell me ", "write ", "summarize ")
    ):
        return "instruction"
    return "casual_message"


def _looks_like_recent_followup(normalized: str) -> bool:
    stripped = normalized.strip()
    if _looks_like_anaphoric_followup(normalized):
        return True
    without_discourse = _strip_discourse_prefix(stripped)
    if _looks_general_question(_normalize(without_discourse)):
        return False
    words = re.findall(r"[\w'-]+", without_discourse)
    return "?" in stripped and 0 < len(words) <= 7


def _recent_user_context_is_sufficient(
    query: str,
    context: list[dict[str, object]],
) -> bool:
    return bool(check_retrieval_sufficiency(query, _recent_user_evidence(context))["is_sufficient"])


def _recent_user_evidence(
    context: list[dict[str, object]],
) -> list[dict[str, object]]:
    return [
        {
            "id": turn.get("id"),
            "source": "recent_turn",
            "content": str(turn.get("content", "")),
            "record": {"content": str(turn.get("content", ""))},
        }
        for turn in context[-6:]
        if turn.get("role") == "user" and str(turn.get("content", "")).strip()
    ]


def _intent_for_scope(context_scope: str) -> str:
    if context_scope in {NO_RETRIEVAL_CONTEXT, GENERAL_CONTEXT, RECENT_CONTEXT}:
        return GENERAL_KNOWLEDGE_INTENT
    if context_scope == SESSION_CONTEXT:
        return PROCEDURAL_INTENT
    if context_scope == MIXED_CONTEXT:
        return MIXED_INTENT
    return PERSONAL_MEMORY_INTENT


def _route_for_scope(context_scope: str, retrieval_mode: str | None) -> str:
    if context_scope == NO_RETRIEVAL_CONTEXT:
        return "direct_conversation"
    if context_scope == SESSION_CONTEXT:
        return "session_context"
    if context_scope in {GENERAL_CONTEXT, RECENT_CONTEXT}:
        return "direct_llm"
    return retrieval_mode or "quick"


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
    first_person_assertion = re.search(
        r"\b(?:i|we)\s+(?:changed|decided|migrated|moved|prefer|switched|use|used|work)\b",
        normalized,
    )
    first_person_lookup = re.search(
        r"\b(?:what|which)\b.+\b(?:am i using|are we using|do i use|do we use)\b",
        normalized,
    )
    return bool(
        re.search(r"\b(?:my|our)\b", normalized)
        or identity_question
        or first_person_assertion
        or first_person_lookup
    ) or any(_contains_phrase(normalized, marker) for marker in EXPLICIT_MEMORY_QUERY_MARKERS)


def _looks_contextually_memory_grounded(normalized: str) -> bool:
    return any(marker in normalized for marker in CONTEXTUAL_MEMORY_QUERY_MARKERS)


def _looks_general_question(normalized: str) -> bool:
    stripped = _strip_discourse_prefix(normalized.strip())
    return any(stripped.startswith(prefix) for prefix in GENERAL_QUESTION_PREFIXES)


def _looks_procedural(normalized: str) -> bool:
    return any(marker in normalized for marker in PROCEDURAL_MARKERS)


def _looks_like_mixed_personal_advice_query(normalized: str) -> bool:
    """Recognize a personal lookup followed by a separate advice request."""
    return bool(
        re.search(r"[,;]|\band\b", normalized)
        and any(marker in normalized for marker in GENERAL_ADVICE_MARKERS)
    )


def _contains_phrase(normalized: str, phrase: str) -> bool:
    pattern = rf"(?<!\w){re.escape(phrase.strip())}(?!\w)"
    return bool(re.search(pattern, normalized))


def _strip_discourse_prefix(value: str) -> str:
    stripped = value.strip()
    while True:
        updated = DISCOURSE_PREFIX_RE.sub("", stripped, count=1)
        if updated == stripped:
            return stripped
        stripped = updated


def _payload_confidence(payload: dict[object, object]) -> float:
    value = payload.get("confidence")
    if isinstance(value, int | float):
        return min(1.0, max(0.0, float(value)))
    return 0.7


def _decision_confidence(decision: Decision) -> float:
    value = decision.get("confidence")
    return float(value) if isinstance(value, int | float) else 0.0


def _reason(payload: dict[object, object], fallback: str) -> str:
    reason = payload.get("reason")
    if isinstance(reason, str) and reason.strip():
        return reason.strip()
    return fallback


def _normalize(value: str) -> str:
    collapsed = re.sub(r"\s+", " ", value.casefold()).strip()
    return f" {collapsed} "
