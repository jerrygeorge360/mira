"""Top-level MIRA agent runtime: user message to answer.

Ownership: Jerry.
Related issue: ISSUE-039.
Architecture area: agent runtime.

This is the first point where MIRA is an agent rather than separate modules. One
turn flows: fast-path persistence -> session micro-path -> optional cross-session
hydration -> routed retrieval -> context merge + prompt -> Qwen -> persist the
assistant turn -> trace logs -> structured response.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from core.context.ambient import build_ambient_context
from core.context.budget import estimate_tokens
from core.context.merger import merge_context_sources
from core.context.prompt_builder import build_prompt_from_context
from core.db.repositories import (
    create_prompt_log,
    create_retrieval_log,
    list_observations,
)
from core.llm.functions import maybe_structured_tool_call, tool_result_context_record
from core.llm.prompts import render_prompt
from core.llm.qwen import LLMClientError, call_qwen_json
from core.memory.change import resolve_retrieved_contradictions
from core.memory.observation import persist_turn_fast_path
from core.memory.tiers import list_hot_memory_for_context
from core.memory.trace import TraceBuilder
from core.observability import (
    log_observation_saved,
    log_qwen_error,
    log_retrieval_route,
    log_session_hydration,
)
from core.retrieval.auto import (
    GENERAL_KNOWLEDGE_INTENT,
    PROCEDURAL_INTENT,
    route_retrieval,
)
from core.retrieval.router import route_retrieval as retrieve_by_mode
from core.retrieval.sufficiency import resolve_with_one_retry
from core.session.hydration import hydrate_session_from_memory
from core.session.micro_path import run_session_micro_path
from core.session.working_set import (
    expire_session_item,
    export_prompt_ready_session_items,
    list_active_session_items,
)

Response = dict[str, object]
RoutingStrategy = str
ProgressEvent = dict[str, object]
ProgressCallback = Callable[[ProgressEvent], None]
CancelCheck = Callable[[], bool]

RECENT_TURNS = 6
RETRIEVAL_LIMIT = 8
SESSION_ITEMS_MAX = 12
HYDRATION_MAX = 8
HOT_MEMORY_LIMIT = 8
PROMPT_TOKEN_BUDGET = 4000

CONTINUE_MARKERS = (
    "continue",
    "where we left off",
    "where we stopped",
    "pick up where",
    "resume",
    "last time",
    "carry on",
)

GENERAL_KNOWLEDGE_MODE = "general_knowledge"
MEMORY_GROUNDED_MODE = "memory_grounded"
GENERAL_RETRIEVAL_MODE = "general"
QUESTION_PREFIXES = (
    "am ",
    "are ",
    "can ",
    "could ",
    "did ",
    "do ",
    "does ",
    "explain",
    "how ",
    "is ",
    "should ",
    "summarize",
    "tell me",
    "what ",
    "when ",
    "where ",
    "which ",
    "who ",
    "why ",
    "will ",
    "would ",
)
REQUEST_MARKERS = (
    "can you",
    "could you",
    "do this",
    "fix ",
    "give me",
    "help ",
    "implement",
    "please",
    "run ",
    "show me",
)
CASUAL_MARKERS = (
    "alright",
    "cool",
    "got it",
    "hello",
    "hi",
    "nice",
    "ok",
    "okay",
    "thanks",
    "thank you",
)
CORRECTION_TURN_MARKERS = (
    "actually",
    "correction:",
    "instead",
    "no longer",
    "switched from",
    "moved from",
    "migrated from",
    "changed from",
)
USE_NOT_CORRECTION_RE = re.compile(
    r"^\s*(use|set|make|call|treat|store|prefer|reply|answer|assume)\b.+\bnot\b.+",
    re.IGNORECASE,
)


class AgentTurnCancelled(RuntimeError):
    """Raised when a streaming client disconnects before a turn is complete."""


def handle_user_message(
    session_id: str,
    user_message: str,
    *,
    routing_strategy: RoutingStrategy = "hybrid",
    progress_callback: ProgressCallback | None = None,
    should_cancel: CancelCheck | None = None,
) -> Response:
    """Run one full MIRA turn and return a structured response object."""
    if not session_id:
        raise ValueError("session_id must not be empty")
    if not user_message.strip():
        raise ValueError("user_message must not be empty")

    _emit_progress(progress_callback, "start", "Starting the memory run.")
    _raise_if_cancelled(should_cancel)

    prior_observations = list_observations(session_id)
    recent_turns = _recent_turn_records(prior_observations)
    recent_turn_texts = [str(turn["content"]) for turn in recent_turns]

    # Fast path: persist and queue the raw user turn (no model calls).
    _emit_progress(progress_callback, "fast_path", "Saving the turn.")
    user_observation_id = persist_turn_fast_path(session_id, "user", user_message)
    log_observation_saved(session_id, user_observation_id, "user")
    _raise_if_cancelled(should_cancel)

    # Initialise the trace builder for this turn.
    trace = TraceBuilder(session_id, user_observation_id)

    # Session micro-path: provisional Session Working Set updates for this turn.
    _emit_progress(progress_callback, "session", "Updating session context.")
    run_session_micro_path(session_id, user_observation_id, user_message, recent_turn_texts)
    _raise_if_cancelled(should_cancel)

    turn_purpose = _classify_turn_purpose(user_message)
    if turn_purpose == "informational_update":
        return _acknowledge_informational_update(
            session_id=session_id,
            user_message=user_message,
            user_observation_id=user_observation_id,
            trace=trace,
            recent_turns=recent_turns,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
        )

    # Bring durable memory back into a new or continuing session.
    if routing_strategy not in {"fast", "hybrid", "accurate"}:
        raise ValueError("routing_strategy must be one of: fast, hybrid, accurate")
    _emit_progress(progress_callback, "routing", "Choosing how to use memory.")
    decision = route_retrieval(user_message, session_id, strategy=routing_strategy)

    answer_mode = _answer_mode_from_decision(user_message, decision)
    if _decision_uses_memory(decision) and _should_hydrate(prior_observations, user_message):
        _emit_progress(progress_callback, "hydration", "Checking related session context.")
        hydrated_ids = hydrate_session_from_memory(session_id, user_message, HYDRATION_MAX)
        trace.record_hydration(hydrated_ids)
        log_session_hydration(session_id, hydrated_ids)
        _raise_if_cancelled(should_cancel)

    # Routed retrieval of cross-session memory.
    if not _decision_uses_memory(decision):
        retrieval_mode = GENERAL_RETRIEVAL_MODE
        log_retrieval_route(session_id, retrieval_mode, str(decision.get("reason", "")))
        retrieved: list[dict[str, object]] = []
    else:
        retrieval_mode = str(decision["mode"])
        log_retrieval_route(session_id, retrieval_mode, str(decision.get("reason", "")))

        def _retrieve(candidate_query: str) -> list[dict[str, object]]:
            _emit_progress(progress_callback, "retrieval", _retrieval_status(retrieval_mode))
            _raise_if_cancelled(should_cancel)
            return retrieve_by_mode(
                candidate_query,
                mode=retrieval_mode,
                limit=RETRIEVAL_LIMIT,
                session_id=session_id,
            )

        if decision.get("needs_sufficiency_check"):
            # Ambiguous query: retrieve, check sufficiency, and rewrite+retry once
            # (Auto rule 4) rather than answering on possibly-thin context.
            _emit_progress(progress_callback, "sufficiency", "Verifying retrieved evidence.")
            resolution = resolve_with_one_retry(user_message, _retrieve)
            resolved_context = resolution.get("context")
            retrieved = resolved_context if isinstance(resolved_context, list) else []
            if resolution.get("retries"):
                _emit_progress(progress_callback, "retry", "Expanded the memory search once.")
        else:
            retrieved = _retrieve(user_message)

    _raise_if_cancelled(should_cancel)
    tool_calls = _structured_tool_calls(session_id, user_message)
    if tool_calls:
        retrieved.extend(tool_result_context_record(tool_call) for tool_call in tool_calls)
    # Surface any unresolved contradiction among the retrieved facts so the answer flags
    # the conflict instead of asserting one contested value as settled.
    _emit_progress(progress_callback, "verification", "Checking corrections and conflicts.")
    retrieved.extend(
        resolve_retrieved_contradictions(_retrieved_fact_ids(retrieved), query=user_message)
    )
    trace.record_retrieval(retrieval_mode, retrieved)
    _raise_if_cancelled(should_cancel)

    # Hot memory: pull active working-memory items for prompt context.
    _emit_progress(progress_callback, "working_set", "Selecting active session memory.")
    session_items = export_prompt_ready_session_items(session_id, SESSION_ITEMS_MAX)
    trace.record_session_items(session_items)

    hot_memory_items = (
        []
        if answer_mode == GENERAL_KNOWLEDGE_MODE
        else list_hot_memory_for_context(session_id, user_message, HOT_MEMORY_LIMIT)
    )
    trace.record_hot_memory(hot_memory_items)
    _raise_if_cancelled(should_cancel)

    # Context pack + prompt.
    _emit_progress(progress_callback, "context", "Preparing answer context.")
    ambient_context = build_ambient_context(session_id)
    context_pack = merge_context_sources(
        current_message=user_message,
        recent_turns=recent_turns,
        session_items=session_items,
        durable_memory_items=hot_memory_items,
        ambient_context=ambient_context,
        retrieved_items=retrieved,
    )
    trace.record_prompt_sections(context_pack)
    prompt = build_prompt_from_context(user_message, context_pack, answer_mode=answer_mode)

    # Generation.
    try:
        _raise_if_cancelled(should_cancel)
        _emit_progress(progress_callback, "generation", "Preparing the answer.")
        answer = _generate_answer(prompt)
        _raise_if_cancelled(should_cancel)
    except AgentTurnCancelled:
        raise
    except Exception as error:
        log_qwen_error(error, session_id=session_id, observation_id=user_observation_id)
        raise

    # Persist and queue the assistant turn.
    _emit_progress(progress_callback, "persistence", "Saving the completed answer.")
    assistant_observation_id = persist_turn_fast_path(session_id, "assistant", answer)
    trace.assistant_observation_id = assistant_observation_id

    used_session_items = [str(item["id"]) for item in session_items if item.get("id")]
    used_memory_items = _memory_ids(retrieved)
    retrieval_log_id, prompt_log_id = _log_traces(
        session_id=session_id,
        user_observation_id=user_observation_id,
        query=user_message,
        retrieval_mode=retrieval_mode,
        retrieved=retrieved,
        routing_decision=decision,
        used_session_items=used_session_items,
        used_memory_items=used_memory_items,
        recent_turns=recent_turns,
        prompt=prompt,
    )
    trace.link_retrieval_log(retrieval_log_id)
    trace.link_prompt_log(prompt_log_id)

    # Persist the complete answer trace and return its identifier.
    _emit_progress(progress_callback, "trace", "Writing the answer trace.")
    trace_id = trace.build()

    return {
        "answer": answer,
        "session_id": session_id,
        "user_observation_id": user_observation_id,
        "assistant_observation_id": assistant_observation_id,
        "retrieval_mode": retrieval_mode,
        "used_session_items": used_session_items,
        "used_memory_items": used_memory_items,
        "routing_decision": dict(decision),
        "retrieval_trace": _retrieval_trace(decision, retrieval_mode, retrieved),
        "tool_calls": tool_calls,
        "trace_id": trace_id,
    }


def _acknowledge_informational_update(
    *,
    session_id: str,
    user_message: str,
    user_observation_id: str,
    trace: TraceBuilder,
    recent_turns: list[dict[str, object]],
    progress_callback: ProgressCallback | None,
    should_cancel: CancelCheck | None,
) -> Response:
    """Persist a brief acknowledgement for declarative updates without retrieval."""
    _emit_progress(progress_callback, "acknowledgement", "Saving the update.")
    _raise_if_cancelled(should_cancel)
    retrieval_mode = GENERAL_RETRIEVAL_MODE
    decision = {
        "mode": retrieval_mode,
        "route": "acknowledge_and_store",
        "intent": "informational_update",
        "reason": "declarative update; saved for slow-path processing without retrieval",
        "confidence": 0.9,
        "used_memory": False,
    }
    retrieved: list[dict[str, object]] = []
    session_items = export_prompt_ready_session_items(session_id, SESSION_ITEMS_MAX)
    trace.record_session_items(session_items)
    trace.record_retrieval(retrieval_mode, retrieved)
    trace.record_prompt_sections([])
    answer = "Noted."
    assistant_observation_id = persist_turn_fast_path(session_id, "assistant", answer)
    trace.assistant_observation_id = assistant_observation_id
    used_session_items = [str(item["id"]) for item in session_items if item.get("id")]
    retrieval_log_id, prompt_log_id = _log_traces(
        session_id=session_id,
        user_observation_id=user_observation_id,
        query=user_message,
        retrieval_mode=retrieval_mode,
        retrieved=retrieved,
        routing_decision=decision,
        used_session_items=used_session_items,
        used_memory_items=[],
        recent_turns=recent_turns,
        prompt="",
    )
    trace.link_retrieval_log(retrieval_log_id)
    trace.link_prompt_log(prompt_log_id)
    _emit_progress(progress_callback, "trace", "Writing the answer trace.")
    trace_id = trace.build()
    return {
        "answer": answer,
        "session_id": session_id,
        "user_observation_id": user_observation_id,
        "assistant_observation_id": assistant_observation_id,
        "retrieval_mode": retrieval_mode,
        "used_session_items": used_session_items,
        "used_memory_items": [],
        "routing_decision": decision,
        "retrieval_trace": _retrieval_trace(decision, retrieval_mode, retrieved),
        "tool_calls": [],
        "trace_id": trace_id,
    }


class Agent:
    """Convenience wrapper around the per-turn runtime for a single session."""

    def __init__(self, session_id: str) -> None:
        """Create an agent bound to a conversation session."""
        if not session_id:
            raise ValueError("session_id must not be empty")
        self.session_id = session_id

    def handle_turn(
        self, user_message: str, *, routing_strategy: RoutingStrategy = "hybrid"
    ) -> str:
        """Accept one user turn and return the model response text."""
        return str(
            handle_user_message(self.session_id, user_message, routing_strategy=routing_strategy)[
                "answer"
            ]
        )

    def respond(
        self,
        user_message: str,
        *,
        routing_strategy: RoutingStrategy = "hybrid",
        progress_callback: ProgressCallback | None = None,
        should_cancel: CancelCheck | None = None,
    ) -> Response:
        """Accept one user turn and return the full structured response."""
        return handle_user_message(
            self.session_id,
            user_message,
            routing_strategy=routing_strategy,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
        )

    def reset_session(self) -> None:
        """Reset temporary session state without deleting durable memory."""
        for item in list_active_session_items(self.session_id):
            item_id = item.get("id")
            if isinstance(item_id, str):
                expire_session_item(self.session_id, item_id, "session reset")


def _generate_answer(prompt: str) -> str:
    response = call_qwen_json(
        [{"role": "user", "content": prompt}],
        schema_name="answer_generation",
    )
    payload = response.get("json", {})
    if isinstance(payload, dict):
        return str(payload.get("answer", "")).strip()
    return ""


def _emit_progress(
    callback: ProgressCallback | None,
    stage: str,
    message: str,
    **fields: object,
) -> None:
    if callback is None:
        return
    callback({"type": "stage", "stage": stage, "message": message, **fields})


def _raise_if_cancelled(should_cancel: CancelCheck | None) -> None:
    if should_cancel is not None and should_cancel():
        raise AgentTurnCancelled("chat stream was cancelled")


def _retrieval_status(retrieval_mode: str) -> str:
    if retrieval_mode == "relational":
        return "Checking related memories in the graph."
    if retrieval_mode == "deep":
        return "Searching broader memory context."
    if retrieval_mode == "quick":
        return "Searching relevant memory."
    return "Checking available context."


def _should_hydrate(prior_observations: list[dict[str, object]], user_message: str) -> bool:
    if not prior_observations:
        return True
    normalized = user_message.casefold()
    return any(marker in normalized for marker in CONTINUE_MARKERS)


def _answer_mode_from_decision(
    user_message: str,
    decision: dict[str, object],
) -> str:
    del user_message
    if (
        decision.get("intent") == GENERAL_KNOWLEDGE_INTENT
        or decision.get("mode") == GENERAL_RETRIEVAL_MODE
    ):
        return GENERAL_KNOWLEDGE_MODE
    if decision.get("intent") == PROCEDURAL_INTENT:
        return MEMORY_GROUNDED_MODE
    return MEMORY_GROUNDED_MODE


def _decision_uses_memory(decision: dict[str, object]) -> bool:
    return bool(decision.get("used_memory", decision.get("mode") != GENERAL_RETRIEVAL_MODE))


def _classify_turn_purpose(user_message: str) -> str:
    normalized = _normalize_turn(user_message)
    if not normalized:
        return "casual_message"
    if normalized.strip(".!, ") in CASUAL_MARKERS:
        return "casual_message"
    if normalized.startswith(("hello ", "hi ")):
        return "casual_message"
    if _looks_like_question_or_request(normalized, user_message):
        return "question"
    if USE_NOT_CORRECTION_RE.search(normalized):
        return "correction"
    if any(marker in normalized for marker in CORRECTION_TURN_MARKERS):
        return "correction"
    if _looks_like_declarative_update(normalized):
        return "informational_update"
    if _should_ask_llm_turn_classifier(normalized):
        return _llm_classify_turn_purpose(user_message) or "casual_message"
    return "casual_message"


def _llm_classify_turn_purpose(user_message: str) -> str | None:
    prompt = render_prompt(
        "turn_purpose_classification",
        {"recent_turns": [], "user_message": user_message},
    )
    try:
        response = call_qwen_json(
            [{"role": "user", "content": prompt}],
            schema_name="turn_purpose_classification",
        )
    except LLMClientError:
        return None
    payload = response.get("json", {})
    if not isinstance(payload, dict):
        return None
    purpose = str(payload.get("purpose", "")).casefold()
    if purpose in {
        "question",
        "informational_update",
        "instruction",
        "correction",
        "decision",
        "resolution",
        "casual_message",
    }:
        return purpose
    return None


def _looks_like_question_or_request(normalized: str, original: str) -> bool:
    return (
        "?" in original
        or normalized.startswith(QUESTION_PREFIXES)
        or any(marker in normalized for marker in REQUEST_MARKERS)
    )


def _looks_like_declarative_update(normalized: str) -> bool:
    if not _looks_like_architecture_note(normalized):
        return False
    declarative_markers = (
        " is ",
        " are ",
        " uses ",
        " use ",
        " keeps ",
        " tracks ",
        " stores ",
        " supports ",
        " exposes ",
        " prioritizes ",
        " represents ",
        " distinguishes ",
        " means ",
        " should ",
        " must ",
        " prefers ",
        " prefer ",
    )
    if normalized.startswith(("i ", "my ", "our ", "the ", "mira ", "sqlite ", "chromadb ")):
        return any(marker in f" {normalized} " for marker in declarative_markers)
    return (
        any(marker in f" {normalized} " for marker in declarative_markers)
        and len(normalized.split()) >= 4
    )


def _looks_like_architecture_note(normalized: str) -> bool:
    architecture_markers = (
        "chromadb",
        "contradicts",
        "durable memory",
        "memory store",
        "mira",
        "prompt",
        "quick retrieval",
        "raw observations",
        "session working set",
        "sqlite",
        "superseded_by",
    )
    return any(marker in normalized for marker in architecture_markers)


def _should_ask_llm_turn_classifier(normalized: str) -> bool:
    llm_assist_markers = (
        "architecture",
        "context",
        "memoryagent",
        "mira",
        "note",
        "project note",
        "submission",
    )
    return any(marker in normalized for marker in llm_assist_markers)


def _normalize_turn(value: str) -> str:
    return " ".join(value.casefold().split())


def _retrieved_fact_ids(retrieved: list[dict[str, object]]) -> list[str]:
    return [
        str(item.get("source_id") or item.get("id"))
        for item in retrieved
        if item.get("source") == "atomic_facts" and (item.get("source_id") or item.get("id"))
    ]


def _structured_tool_calls(session_id: str, user_message: str) -> list[dict[str, object]]:
    result = maybe_structured_tool_call(session_id, user_message)
    return [] if result is None else [result]


def _retrieval_trace(
    decision: dict[str, object],
    retrieval_mode: str,
    retrieved: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "intent": decision.get("intent"),
        "used_memory": _decision_uses_memory(decision),
        "route": decision.get("route", retrieval_mode),
        "retrieval_mode": retrieval_mode,
        "reason": decision.get("reason", ""),
        "confidence": decision.get("confidence"),
        "needs_sufficiency_check": decision.get("needs_sufficiency_check", False),
        "retrieved": [
            {
                "source": item.get("source"),
                "id": item.get("id") or item.get("source_id"),
                "score": item.get("score"),
            }
            for item in retrieved
        ],
    }


def _recent_turn_records(prior_observations: list[dict[str, object]]) -> list[dict[str, object]]:
    recent = prior_observations[-RECENT_TURNS:]
    return [
        {"content": str(row["content"]), "id": str(row["id"]), "role": str(row.get("role", ""))}
        for row in recent
    ]


def _memory_ids(retrieved: list[dict[str, object]]) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for item in retrieved:
        identifier = item.get("id") or item.get("source_id")
        if isinstance(identifier, str) and identifier not in seen:
            seen.add(identifier)
            ids.append(identifier)
    return ids


def _log_traces(
    *,
    session_id: str,
    user_observation_id: str,
    query: str,
    retrieval_mode: str,
    retrieved: list[dict[str, object]],
    routing_decision: dict[str, object],
    used_session_items: list[str],
    used_memory_items: list[str],
    recent_turns: list[dict[str, object]],
    prompt: str,
) -> tuple[str, str]:
    retrieval_log_id = create_retrieval_log(
        {
            "session_id": session_id,
            "query": query,
            "retrieval_mode": retrieval_mode,
            "retrieved_records_json": [
                {"source": item.get("source"), "id": item.get("id") or item.get("source_id")}
                for item in retrieved
            ],
            "sufficiency_json": {
                "routing_decision": routing_decision,
                "retrieved_count": len(retrieved),
            },
        }
    )
    prompt_log_id = create_prompt_log(
        {
            "session_id": session_id,
            "user_observation_id": user_observation_id,
            "included_session_items_json": used_session_items,
            "included_memory_items_json": used_memory_items,
            "included_recent_turns_json": [str(turn["id"]) for turn in recent_turns],
            "token_budget_json": {
                "prompt_tokens": estimate_tokens(prompt),
                "budget": PROMPT_TOKEN_BUDGET,
            },
        }
    )
    return retrieval_log_id, prompt_log_id
