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
from core.context.prompt_builder import build_answer_messages
from core.db.repositories import (
    attach_llm_usage_run_observation,
    create_prompt_log,
    create_retrieval_log,
    list_observations,
    workspace_id_for_session,
)
from core.llm.functions import maybe_structured_tool_call, tool_result_context_record
from core.llm.prompts import render_prompt
from core.llm.qwen import LLMClientError, call_qwen_json
from core.llm.usage import llm_usage_context, new_usage_run_id, usage_summary
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
    DURABLE_CONTEXT,
    GENERAL_CONTEXT,
    GENERAL_KNOWLEDGE_INTENT,
    MIXED_CONTEXT,
    NO_RETRIEVAL_CONTEXT,
    PROCEDURAL_INTENT,
    RECENT_CONTEXT,
    SESSION_CONTEXT,
    route_retrieval,
)
from core.retrieval.router import route_retrieval as retrieve_by_mode
from core.retrieval.sufficiency import check_grounded_sufficiency, resolve_with_one_retry
from core.session.hydration import hydrate_session_from_memory
from core.session.micro_path import run_session_micro_path
from core.session.reference import (
    ReferenceResolution,
    resolve_discourse_reference,
)
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
CONVERSATIONAL_MODE = "conversational"
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
    "remind me",
    "run ",
    "show me",
)
CASUAL_MARKERS = (
    "appreciate it",
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
AMBIGUOUS_DEICTIC_CORRECTIONS = frozenset(
    {
        "actually that is wrong",
        "actually that's wrong",
        "it is no longer true",
        "it's no longer true",
        "that is wrong",
        "that's wrong",
        "that is no longer true",
        "that's no longer true",
        "that isn't true anymore",
        "that is not true anymore",
        "that's not true anymore",
        "not true anymore",
    }
)
CONVERSATIONAL_PREAMBLE_RE = re.compile(
    r"^\s*(?:(?:alright|cool|fair enough|nice|okay|ok|oh|so|well)[,.!]?\s+)?"
    r"(?:(?:also|anyway|by the way|side note)[,.\s]+)*",
    re.IGNORECASE,
)
NOT_ANYMORE_CORRECTION_RE = re.compile(r"\bnot\b.+\banymore\b", re.IGNORECASE)
CONTEXTUAL_TEMPORAL_AMENDMENT_RE = re.compile(
    r"^(?:it|that|the\s+(?:class|deadline|exam|interview|meeting))\s+"
    r"(?:has\s+been\s+|was\s+)?(?:moved|postponed|rescheduled|shifted)\b",
    re.IGNORECASE,
)
PERSONAL_INCIDENT_RE = re.compile(
    r"\b(?:failed|kept|started)\b.+\b(?:for|on)\s+me\b",
    re.IGNORECASE,
)
EXPLICIT_TRANSITION_RE = re.compile(
    r"\b(?:switched|moved|migrated|changed)"
    r"(?:\s+(?:my|our|the)\s+[\w -]{1,60})?\s+from\b",
    re.IGNORECASE,
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
    """Run one MIRA turn and include measured usage for every model call it made."""
    if not session_id:
        raise ValueError("session_id must not be empty")
    workspace_id = workspace_id_for_session(session_id)
    run_id = new_usage_run_id("agent")
    with llm_usage_context(
        run_id=run_id,
        workspace_id=workspace_id,
        component="agent",
        session_id=session_id,
    ):
        result = _handle_user_message(
            session_id,
            user_message,
            routing_strategy=routing_strategy,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
        )
    observation_id = result.get("user_observation_id")
    if isinstance(observation_id, str) and observation_id:
        attach_llm_usage_run_observation(run_id, observation_id)
    result["llm_usage"] = usage_summary(run_id)
    return result


def _handle_user_message(
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
    turn_purpose = _classify_turn_purpose(user_message, recent_turns=recent_turns)
    reference_resolution = (
        resolve_discourse_reference(session_id, user_message, recent_turns)
        if turn_purpose == "resolution"
        else None
    )
    resolution_target_id = (
        reference_resolution["target_observation_id"] if reference_resolution else None
    )
    direct_contextual_answer = None
    if reference_resolution is not None and reference_resolution["status"] != "resolved":
        direct_contextual_answer = reference_resolution["clarification"]

    # Fast path: persist and queue the raw user turn (no model calls).
    _emit_progress(progress_callback, "fast_path", "Saving the turn.")
    user_observation_id = persist_turn_fast_path(
        session_id,
        "user",
        user_message,
        metadata=_turn_metadata(turn_purpose, reference_resolution),
    )
    log_observation_saved(session_id, user_observation_id, "user")
    _raise_if_cancelled(should_cancel)

    # Initialise the trace builder for this turn.
    trace = TraceBuilder(session_id, user_observation_id)

    # Session micro-path: provisional Session Working Set updates for this turn.
    _emit_progress(progress_callback, "session", "Updating session context.")
    run_session_micro_path(
        session_id,
        user_observation_id,
        user_message,
        recent_turn_texts,
        turn_purpose=turn_purpose,
        resolution_target_observation_id=resolution_target_id,
    )
    _raise_if_cancelled(should_cancel)

    casual_answer = (
        _low_information_casual_response(user_message) if turn_purpose == "casual_message" else None
    )
    if (
        turn_purpose in {"informational_update", "correction", "decision", "resolution"}
        or casual_answer is not None
        or direct_contextual_answer is not None
    ):
        return _respond_without_retrieval(
            session_id=session_id,
            user_message=user_message,
            user_observation_id=user_observation_id,
            trace=trace,
            recent_turns=recent_turns,
            turn_purpose=turn_purpose,
            reference_resolution=reference_resolution,
            direct_answer=direct_contextual_answer or casual_answer,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
        )

    # Bring durable memory back into a new or continuing session.
    if routing_strategy not in {"fast", "hybrid", "accurate"}:
        raise ValueError("routing_strategy must be one of: fast, hybrid, accurate")
    _emit_progress(progress_callback, "routing", "Choosing how to use memory.")
    decision = route_retrieval(
        user_message,
        session_id,
        strategy=routing_strategy,
        context=recent_turns,
        turn_purpose=turn_purpose,
    )

    answer_mode = _answer_mode_from_decision(user_message, decision)
    sufficiency_outcome: dict[str, object] | None = None
    if _decision_uses_memory(decision) and _should_hydrate(prior_observations, user_message):
        _emit_progress(progress_callback, "hydration", "Checking related session context.")
        hydrated_ids = hydrate_session_from_memory(session_id, user_message, HYDRATION_MAX)
        trace.record_hydration(hydrated_ids)
        log_session_hydration(session_id, hydrated_ids)
        _raise_if_cancelled(should_cancel)

    # Routed retrieval of cross-session memory.
    if not _decision_requires_durable_retrieval(decision):
        retrieval_mode = GENERAL_RETRIEVAL_MODE
        log_retrieval_route(session_id, retrieval_mode, str(decision.get("reason", "")))
        retrieved: list[dict[str, object]] = []
    else:
        retrieval_mode = str(decision["mode"])
        log_retrieval_route(session_id, retrieval_mode, str(decision.get("reason", "")))

        def _retrieve(candidate_query: str) -> list[dict[str, object]]:
            _emit_progress(progress_callback, "retrieval", _retrieval_status(retrieval_mode))
            _raise_if_cancelled(should_cancel)
            return _without_current_observation(
                retrieve_by_mode(
                    candidate_query,
                    mode=retrieval_mode,
                    limit=RETRIEVAL_LIMIT,
                    session_id=session_id,
                ),
                user_observation_id,
            )

        _emit_progress(progress_callback, "sufficiency", "Verifying retrieved evidence.")
        resolution = resolve_with_one_retry(user_message, _retrieve, semantic=True)
        resolved_context = resolution.get("context")
        retrieved = resolved_context if isinstance(resolved_context, list) else []
        sufficiency_outcome = {key: value for key, value in resolution.items() if key != "context"}
        if resolution.get("retries"):
            _emit_progress(progress_callback, "retry", "Expanded the memory search once.")

    if (
        sufficiency_outcome is None
        and decision.get("context_scope") == RECENT_CONTEXT
        and turn_purpose == "question"
    ):
        sufficiency_outcome = _recent_context_sufficiency(user_message, recent_turns)

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
    trace.record_sufficiency(sufficiency_outcome)
    _raise_if_cancelled(should_cancel)

    # Hot memory: pull active working-memory items for prompt context.
    _emit_progress(progress_callback, "working_set", "Selecting active session memory.")
    session_items = (
        export_prompt_ready_session_items(session_id, SESSION_ITEMS_MAX)
        if _decision_uses_session_context(decision)
        else []
    )
    trace.record_session_items(session_items)

    hot_memory_items = (
        list_hot_memory_for_context(session_id, user_message, HOT_MEMORY_LIMIT)
        if _decision_uses_durable_context(decision)
        else []
    )
    trace.record_hot_memory(hot_memory_items)
    _raise_if_cancelled(should_cancel)

    # Context pack + prompt.
    _emit_progress(progress_callback, "context", "Preparing answer context.")
    selected_recent_turns = _recent_turns_for_decision(decision, recent_turns)
    ambient_context = (
        build_ambient_context(session_id) if _decision_uses_durable_context(decision) else {}
    )
    context_pack = merge_context_sources(
        current_message=user_message,
        recent_turns=selected_recent_turns,
        session_items=session_items,
        durable_memory_items=hot_memory_items,
        ambient_context=ambient_context,
        retrieved_items=retrieved,
    )
    trace.record_prompt_sections(context_pack)
    answer_messages = build_answer_messages(
        user_message,
        context_pack,
        answer_mode=answer_mode,
        sufficiency=sufficiency_outcome,
    )
    prompt = "\n\n".join(message["content"] for message in answer_messages)

    # Generation.
    try:
        _raise_if_cancelled(should_cancel)
        _emit_progress(progress_callback, "generation", "Preparing the answer.")
        answer = _generate_answer(answer_messages)
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
        recent_turns=selected_recent_turns,
        prompt=prompt,
        sufficiency=sufficiency_outcome,
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
        "retrieval_trace": _retrieval_trace(
            decision,
            retrieval_mode,
            retrieved,
            sufficiency=sufficiency_outcome,
        ),
        "sufficiency": sufficiency_outcome,
        "tool_calls": tool_calls,
        "trace_id": trace_id,
    }


def _respond_without_retrieval(
    *,
    session_id: str,
    user_message: str,
    user_observation_id: str,
    trace: TraceBuilder,
    recent_turns: list[dict[str, object]],
    turn_purpose: str,
    reference_resolution: ReferenceResolution | None,
    direct_answer: str | None,
    progress_callback: ProgressCallback | None,
    should_cancel: CancelCheck | None,
) -> Response:
    """Persist a brief update or social response without retrieval or generation."""
    is_casual = turn_purpose == "casual_message"
    is_update = turn_purpose in {"informational_update", "correction", "decision", "resolution"}
    is_contextual_answer = turn_purpose == "question" and direct_answer is not None
    _emit_progress(
        progress_callback,
        "acknowledgement",
        "Preparing a brief reply." if is_casual else "Saving the update.",
    )
    _raise_if_cancelled(should_cancel)
    retrieval_mode = GENERAL_RETRIEVAL_MODE
    decision: dict[str, object] = {
        "mode": retrieval_mode,
        "route": "acknowledge_and_store" if is_update else "direct_conversation",
        "retrieval_mode": None,
        "intent": turn_purpose,
        "turn_purpose": turn_purpose,
        "context_scope": RECENT_CONTEXT if is_contextual_answer else NO_RETRIEVAL_CONTEXT,
        "scope_source": "deterministic",
        "scope_confidence": 0.96,
        "mode_source": None,
        "mode_confidence": None,
        "retrieval_required": False,
        "reason": (
            "recent conversational reference resolved from role-labelled turns"
            if is_contextual_answer
            else (
                "low-information social turn; answered without retrieval"
                if is_casual
                else f"{turn_purpose}; saved for slow-path processing without answer retrieval"
            )
        ),
        "confidence": 0.9,
        "used_memory": False,
        "needs_sufficiency_check": False,
    }
    if _is_ambiguous_deictic_correction(user_message):
        decision.update(
            {
                "route": "clarify_update",
                "context_scope": RECENT_CONTEXT,
                "reason": (
                    "the correction refers to prior text without identifying the changed fact"
                ),
                "confidence": 0.98,
            }
        )
    if reference_resolution is not None:
        decision["reference_resolution"] = {
            "status": reference_resolution["status"],
            "source": reference_resolution["source"],
            "confidence": reference_resolution["confidence"],
            "reason": reference_resolution["reason"],
        }
        if reference_resolution["status"] != "resolved":
            decision.update(
                {
                    "route": "clarify_update",
                    "context_scope": RECENT_CONTEXT,
                    "reason": reference_resolution["reason"],
                    "confidence": 1.0,
                }
            )
    retrieved: list[dict[str, object]] = []
    session_items = (
        export_prompt_ready_session_items(session_id, SESSION_ITEMS_MAX) if is_update else []
    )
    trace.record_session_items(session_items)
    trace.record_retrieval(retrieval_mode, retrieved)
    trace.record_prompt_sections([])
    answer = direct_answer or _informational_update_acknowledgement(
        user_message,
        recent_turns,
        turn_purpose=turn_purpose,
        reference_resolution=reference_resolution,
    )
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
        sufficiency=None,
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
        "retrieval_trace": _retrieval_trace(decision, retrieval_mode, retrieved, sufficiency=None),
        "sufficiency": None,
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


def _generate_answer(messages: list[dict[str, str]]) -> str:
    response = call_qwen_json(
        messages,
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
    context_scope = str(decision.get("context_scope", ""))
    if context_scope == NO_RETRIEVAL_CONTEXT:
        return CONVERSATIONAL_MODE
    if context_scope in {GENERAL_CONTEXT, RECENT_CONTEXT}:
        return GENERAL_KNOWLEDGE_MODE
    if context_scope in {SESSION_CONTEXT, DURABLE_CONTEXT, MIXED_CONTEXT}:
        return MEMORY_GROUNDED_MODE
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


def _decision_requires_durable_retrieval(decision: dict[str, object]) -> bool:
    scope = str(decision.get("context_scope", ""))
    if scope:
        return scope in {DURABLE_CONTEXT, MIXED_CONTEXT}
    return _decision_uses_memory(decision)


def _decision_uses_durable_context(decision: dict[str, object]) -> bool:
    scope = str(decision.get("context_scope", ""))
    if scope:
        return scope in {DURABLE_CONTEXT, MIXED_CONTEXT}
    return _decision_uses_memory(decision)


def _decision_uses_session_context(decision: dict[str, object]) -> bool:
    scope = str(decision.get("context_scope", ""))
    if scope:
        return scope in {SESSION_CONTEXT, DURABLE_CONTEXT, MIXED_CONTEXT}
    return _decision_uses_memory(decision)


def _recent_turns_for_decision(
    decision: dict[str, object],
    recent_turns: list[dict[str, object]],
) -> list[dict[str, object]]:
    scope = str(decision.get("context_scope", ""))
    if scope in {GENERAL_CONTEXT, NO_RETRIEVAL_CONTEXT}:
        return []
    return recent_turns[-RECENT_TURNS:]


def _classify_turn_purpose(
    user_message: str,
    *,
    recent_turns: list[dict[str, object]] | None = None,
) -> str:
    normalized = _normalize_turn(user_message)
    semantic = _strip_conversational_preamble(normalized)
    if not normalized:
        return "casual_message"
    if (
        semantic.strip(".!, ") in CASUAL_MARKERS
        or semantic.startswith(("thanks", "thank you"))
        or semantic.startswith("cheers")
        or "that's all for now" in semantic
        or "that is all for now" in semantic
        or "that's everything for now" in semantic
        or "that is everything for now" in semantic
        or _looks_like_casual_reaction(semantic)
    ):
        return "casual_message"
    if semantic.startswith(("hello ", "hi ")):
        return "casual_message"
    if _looks_like_question_or_request(semantic, user_message):
        return "question"
    if (
        USE_NOT_CORRECTION_RE.search(semantic)
        or NOT_ANYMORE_CORRECTION_RE.search(semantic)
        or EXPLICIT_TRANSITION_RE.search(semantic)
    ):
        return "correction"
    if any(marker in semantic for marker in CORRECTION_TURN_MARKERS):
        return "correction"
    if _looks_like_contextual_temporal_amendment(semantic, recent_turns):
        return "correction"
    if _looks_like_declarative_update(semantic) or _looks_like_personal_update(semantic):
        return "informational_update"
    if _should_ask_llm_turn_classifier(semantic, recent_turns):
        classified = _llm_classify_turn_purpose(user_message, recent_turns or [])
        if classified is not None and not (
            _looks_like_additional_event_update(semantic, recent_turns)
            and classified != "informational_update"
        ):
            return classified
        if _looks_like_contextual_update_fragment(semantic, recent_turns):
            return "informational_update"
    return "casual_message"


def _turn_metadata(
    turn_purpose: str,
    reference_resolution: ReferenceResolution | None,
) -> dict[str, object]:
    metadata: dict[str, object] = {"turn_purpose": turn_purpose}
    if reference_resolution is not None:
        metadata["reference_resolution"] = {
            "status": reference_resolution["status"],
            "target_observation_id": reference_resolution["target_observation_id"],
            "target_content": reference_resolution["target_content"],
            "source": reference_resolution["source"],
            "confidence": reference_resolution["confidence"],
            "reason": reference_resolution["reason"],
        }
    return metadata


def _llm_classify_turn_purpose(
    user_message: str,
    recent_turns: list[dict[str, object]],
) -> str | None:
    prompt = render_prompt(
        "turn_purpose_classification",
        {"recent_turns": recent_turns, "user_message": user_message},
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
    conversational = re.sub(
        r"^(?:alright|also|and|but|okay|ok|so|well|yeah|yh|yes)[,\s]+",
        "",
        normalized,
        count=1,
    )
    clauses = [clause.strip() for clause in re.split(r"[,;]", conversational)]
    return (
        "?" in original
        or conversational.startswith(QUESTION_PREFIXES)
        or any(clause.startswith(QUESTION_PREFIXES) for clause in clauses)
        or any(marker in conversational for marker in REQUEST_MARKERS)
    )


def _looks_like_declarative_update(normalized: str) -> bool:
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
    is_architecture_note = _looks_like_architecture_note(normalized)
    is_clear_fact_statement = normalized.startswith("the ") and len(normalized.split()) >= 4
    if not is_architecture_note and not is_clear_fact_statement:
        return False
    if normalized.startswith(("i ", "my ", "our ", "the ", "mira ", "sqlite ", "chromadb ")):
        return any(marker in f" {normalized} " for marker in declarative_markers)
    return (
        any(marker in f" {normalized} " for marker in declarative_markers)
        and len(normalized.split()) >= 4
    )


def _looks_like_personal_update(normalized: str) -> bool:
    """Recognize clear user-state assertions without treating requests as updates."""
    if normalized.startswith(("i am wondering", "i'm wondering", "i have a question")):
        return False
    if normalized.startswith(
        (
            "i configured ",
            "i changed ",
            "i created ",
            "i deployed ",
            "i deploy ",
            "i have ",
            "i moved ",
            "i migrated ",
            "i prefer ",
            "i scheduled ",
            "i set up ",
            "i started ",
            "i switched ",
            "i use ",
            "i'm currently ",
            "i've got ",
            "we configured ",
            "we changed ",
            "we created ",
            "we deployed ",
            "we have ",
            "we moved ",
            "we migrated ",
            "we scheduled ",
            "we set up ",
            "we started ",
            "we switched ",
            "we use ",
        )
    ):
        return True
    if normalized.startswith(("i am ", "i'm ")):
        return len(normalized.split()) >= 3
    if normalized.startswith(("i also ", "we also ")):
        return any(
            marker in normalized
            for marker in (
                " back up ",
                " configured ",
                " created ",
                " run ",
                " scheduled ",
                " set up ",
                " started ",
                " use ",
                " using ",
            )
        )
    if normalized.startswith(("my ", "our ")):
        return any(
            marker in f" {normalized} "
            for marker in (" is ", " are ", " starts ", " begins ", " ends ", " will be ")
        )
    return bool(PERSONAL_INCIDENT_RE.search(normalized))


def _looks_like_casual_reaction(normalized: str) -> bool:
    return any(
        marker in normalized
        for marker in (
            "glad to hear",
            "off my plate",
            "one less thing",
            "that is helpful",
            "that is unfortunate",
            "that's helpful",
            "that's unfortunate",
            "that's a relief",
        )
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


def _should_ask_llm_turn_classifier(
    normalized: str,
    _recent_turns: list[dict[str, object]] | None,
) -> bool:
    return bool(normalized)


def _looks_like_contextual_update_fragment(
    normalized: str,
    recent_turns: list[dict[str, object]] | None,
) -> bool:
    if not recent_turns:
        return False
    return normalized.startswith(("another ", "an additional ", "one more "))


def _looks_like_additional_event_update(
    normalized: str,
    recent_turns: list[dict[str, object]] | None,
) -> bool:
    if not _looks_like_contextual_update_fragment(normalized, recent_turns):
        return False
    event_terms = ("exam", "appointment", "deadline", "flight", "interview", "meeting")
    matching_terms = {term for term in event_terms if term in normalized}
    if not matching_terms:
        return False
    prior_user_text = " ".join(
        _normalize_turn(str(turn.get("content", "")))
        for turn in (recent_turns or [])
        if turn.get("role") == "user"
    )
    return any(term in prior_user_text for term in matching_terms)


def _informational_update_acknowledgement(
    user_message: str,
    recent_turns: list[dict[str, object]],
    *,
    turn_purpose: str,
    reference_resolution: ReferenceResolution | None = None,
) -> str:
    semantic_message = _strip_conversational_preamble(user_message).strip()
    normalized = _normalize_turn(semantic_message).strip(".! ")
    if turn_purpose == "resolution":
        if (
            reference_resolution is not None
            and reference_resolution["status"] == "resolved"
            and reference_resolution["target_content"]
        ):
            target = str(reference_resolution["target_content"]).strip()
            return f'Okay. I will treat this statement as withdrawn: "{target}"'
        if "keep going" in normalized or "continue" in normalized:
            return "Okay, let's keep going."
        return "Okay. We can leave that there."
    if turn_purpose == "correction" and _is_ambiguous_deictic_correction(user_message):
        return "What specifically in the previous answer is no longer true?"
    if turn_purpose == "correction":
        correction = re.sub(
            r"^(?:correction|update)\s*:\s*",
            "",
            semantic_message.rstrip(".!?"),
            count=1,
            flags=re.IGNORECASE,
        )
        return f"Noted. I'll apply this correction: {correction}."
    if _looks_like_contextual_update_fragment(normalized, recent_turns):
        if "exam" in normalized:
            return "Got it. I'll treat that as a separate exam. When is it?"
        return "Got it. I'll treat that as an additional item. What details should I attach to it?"
    if not _looks_like_personal_update(normalized):
        return "Noted."
    statement = re.sub(
        r"^(?:that is|that's)\s+a relief[,;]?\s*",
        "",
        semantic_message.rstrip(".!?"),
        count=1,
        flags=re.IGNORECASE,
    )
    replacements = (
        (r"^I also\b", "you also"),
        (r"^We also\b", "you also"),
        (r"^I have\b", "you have"),
        (r"^I've got\b", "you have"),
        (r"^I am\b", "you are"),
        (r"^I'm\b", "you're"),
        (r"^I prefer\b", "you prefer"),
        (r"^We have\b", "you have"),
        (r"^My\b", "your"),
        (r"^Our\b", "your"),
        (r"^I\b", "you"),
        (r"^We\b", "you"),
    )
    for pattern, replacement in replacements:
        updated = re.sub(pattern, replacement, statement, count=1, flags=re.IGNORECASE)
        if updated != statement:
            statement = updated
            break
    statement = re.sub(r"\bmy\b", "your", statement, flags=re.IGNORECASE)
    statement = re.sub(r"\bour\b", "your", statement, flags=re.IGNORECASE)
    return f"Got it. I'll remember that {statement}."


def _low_information_casual_response(user_message: str) -> str | None:
    normalized = _normalize_turn(user_message).strip(" .!?")
    if re.fullmatch(r"(?:good morning|good afternoon|good evening)", normalized):
        greeting = normalized.capitalize()
        return f"{greeting}! What can I help you with?"
    if re.fullmatch(r"(?:hello|hey|hi)(?: there)?", normalized):
        return "Hey! What can I help you with?"
    if (
        normalized.startswith(("thanks", "thank you", "appreciate it", "cheers"))
        or "that's all for now" in normalized
        or "that is all for now" in normalized
        or "that's everything for now" in normalized
        or "that is everything for now" in normalized
    ):
        return "You're welcome."
    if (
        "one less thing to worry about" in normalized
        or "off my plate" in normalized
        or "that's a relief" in normalized
    ):
        return "Glad that's sorted."
    if normalized in {"alright", "cool", "got it", "nice", "okay", "ok"}:
        return "Sounds good."
    return None


def _normalize_turn(value: str) -> str:
    return " ".join(value.casefold().split())


def _strip_conversational_preamble(value: str) -> str:
    return CONVERSATIONAL_PREAMBLE_RE.sub("", value, count=1).strip()


def _looks_like_contextual_temporal_amendment(
    normalized: str,
    recent_turns: list[dict[str, object]] | None,
) -> bool:
    if not recent_turns or not CONTEXTUAL_TEMPORAL_AMENDMENT_RE.search(normalized):
        return False
    recent_text = " ".join(str(turn.get("content", "")).casefold() for turn in recent_turns[-4:])
    return any(
        marker in recent_text for marker in ("class", "deadline", "exam", "interview", "meeting")
    )


def _is_ambiguous_deictic_correction(value: str) -> bool:
    normalized = _strip_conversational_preamble(_normalize_turn(value)).strip(" .!?")
    return normalized in AMBIGUOUS_DEICTIC_CORRECTIONS


def _without_current_observation(
    retrieved: list[dict[str, object]],
    observation_id: str,
) -> list[dict[str, object]]:
    filtered: list[dict[str, object]] = []
    for item in retrieved:
        record = item.get("record")
        record_id = record.get("id") if isinstance(record, dict) else None
        if observation_id in {item.get("id"), item.get("source_id"), record_id}:
            continue
        filtered.append(item)
    return filtered


def _recent_context_sufficiency(
    query: str,
    recent_turns: list[dict[str, object]],
) -> dict[str, object]:
    evidence: list[dict[str, object]] = []
    for turn in recent_turns:
        content = str(turn.get("content", ""))
        if turn.get("role") != "user":
            continue
        identifier = str(turn.get("id", ""))
        evidence.append(
            {
                "id": identifier,
                "source": "recent_turn",
                "source_id": identifier,
                "content": content,
                "record": {"content": content},
            }
        )
    verdict = check_grounded_sufficiency(query, evidence)
    return {
        "sufficiency": verdict,
        "retries": 0,
        "answered_with_uncertainty": not bool(verdict.get("is_sufficient")),
    }


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
    *,
    sufficiency: dict[str, object] | None,
) -> dict[str, object]:
    return {
        "intent": decision.get("intent"),
        "turn_purpose": decision.get("turn_purpose"),
        "context_scope": decision.get("context_scope"),
        "scope_source": decision.get("scope_source"),
        "scope_confidence": decision.get("scope_confidence"),
        "retrieval_required": decision.get("retrieval_required"),
        "mode_source": decision.get("mode_source"),
        "mode_confidence": decision.get("mode_confidence"),
        "used_memory": _decision_uses_memory(decision),
        "route": decision.get("route", retrieval_mode),
        "retrieval_mode": retrieval_mode,
        "reason": decision.get("reason", ""),
        "confidence": decision.get("confidence"),
        "needs_sufficiency_check": decision.get("needs_sufficiency_check", False),
        "sufficiency": sufficiency,
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
    content_by_id = {
        str(row["id"]): str(row["content"])
        for row in prior_observations
        if row.get("id") and row.get("content")
    }
    recent = prior_observations[-RECENT_TURNS:]
    records: list[dict[str, object]] = []
    for row in recent:
        content = str(row["content"])
        metadata = row.get("metadata_json")
        resolution = metadata.get("reference_resolution") if isinstance(metadata, dict) else None
        if isinstance(resolution, dict) and resolution.get("status") == "resolved":
            target_id = resolution.get("target_observation_id")
            target_content = resolution.get("target_content")
            if not isinstance(target_content, str) and isinstance(target_id, str):
                target_content = content_by_id.get(target_id)
            if isinstance(target_content, str) and target_content.strip():
                content = f"{content}\n[Resolved memory operation target: {target_content.strip()}]"
        records.append(
            {
                "content": content,
                "id": str(row["id"]),
                "role": str(row.get("role", "")),
            }
        )
    return records


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
    sufficiency: dict[str, object] | None,
) -> tuple[str, str]:
    sufficiency_log = dict(sufficiency or {})
    sufficiency_log["routing_decision"] = routing_decision
    sufficiency_log["retrieved_count"] = len(retrieved)
    retrieval_log_id = create_retrieval_log(
        {
            "session_id": session_id,
            "query": query,
            "retrieval_mode": retrieval_mode,
            "retrieved_records_json": [
                {"source": item.get("source"), "id": item.get("id") or item.get("source_id")}
                for item in retrieved
            ],
            "sufficiency_json": sufficiency_log,
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
