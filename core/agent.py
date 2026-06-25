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

import logging
import re

from core.context.ambient import build_ambient_context
from core.context.budget import estimate_tokens
from core.context.merger import merge_context_sources
from core.db.repositories import (
    create_prompt_log,
    create_retrieval_log,
    list_observations,
    repository_connection,
)
from core.llm.prompts import render_prompt
from core.llm.qwen import call_qwen_json
from core.memory.observation import persist_turn_fast_path
from core.memory.tiers import list_hot_memory_for_context
from core.memory.trace import TraceBuilder
from core.observability import (
    log_observation_saved,
    log_qwen_error,
    log_retrieval_route,
    log_session_hydration,
)
from core.retrieval.auto import route_retrieval
from core.retrieval.deep import retrieve_deep
from core.retrieval.quick import retrieve_quick
from core.retrieval.relational import relational_retrieve
from core.session.hydration import hydrate_session_from_memory
from core.session.micro_path import run_session_micro_path
from core.session.working_set import (
    expire_session_item,
    export_prompt_ready_session_items,
    list_active_session_items,
)

Response = dict[str, object]

LOGGER = logging.getLogger(__name__)

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

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_'-]+")
STOPWORDS = frozenset({"a", "an", "the", "is", "are", "to", "of", "for", "on", "in", "and", "my"})


def handle_user_message(session_id: str, user_message: str) -> Response:
    """Run one full MIRA turn and return a structured response object."""
    if not session_id:
        raise ValueError("session_id must not be empty")
    if not user_message.strip():
        raise ValueError("user_message must not be empty")

    prior_observations = list_observations(session_id)
    recent_turns = _recent_turn_records(prior_observations)
    recent_turn_texts = [str(turn["content"]) for turn in recent_turns]

    # Fast path: persist and queue the raw user turn (no model calls).
    user_observation_id = persist_turn_fast_path(session_id, "user", user_message)
    log_observation_saved(session_id, user_observation_id, "user")

    # Initialise the trace builder for this turn.
    trace = TraceBuilder(session_id, user_observation_id)

    # Session micro-path: provisional Session Working Set updates for this turn.
    run_session_micro_path(session_id, user_observation_id, user_message, recent_turn_texts)

    # Bring durable memory back into a new or continuing session.
    if _should_hydrate(prior_observations, user_message):
        hydrated_ids = hydrate_session_from_memory(session_id, user_message, HYDRATION_MAX)
        trace.record_hydration(hydrated_ids)
        log_session_hydration(session_id, hydrated_ids)

    # Routed retrieval of cross-session memory.
    decision = route_retrieval(user_message, session_id)
    retrieval_mode = str(decision["mode"])
    log_retrieval_route(session_id, retrieval_mode, str(decision.get("reason", "")))
    retrieved = _dispatch_retrieval(retrieval_mode, user_message, session_id, RETRIEVAL_LIMIT)
    trace.record_retrieval(retrieval_mode, retrieved)

    # Hot memory: pull active working-memory items for prompt context.
    session_items = export_prompt_ready_session_items(session_id, SESSION_ITEMS_MAX)
    trace.record_session_items(session_items)

    hot_memory_items = list_hot_memory_for_context(session_id, user_message, HOT_MEMORY_LIMIT)
    trace.record_hot_memory(hot_memory_items)

    # Context pack + prompt.
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
    prompt = render_prompt(
        "answer_generation",
        {"user_message": user_message, "prompt_context": _render_context(context_pack)},
    )

    # Generation.
    try:
        answer = _generate_answer(prompt)
    except Exception as error:
        log_qwen_error(error, session_id=session_id, observation_id=user_observation_id)
        raise

    # Persist and queue the assistant turn.
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
        used_session_items=used_session_items,
        used_memory_items=used_memory_items,
        recent_turns=recent_turns,
        prompt=prompt,
    )
    trace.link_retrieval_log(retrieval_log_id)
    trace.link_prompt_log(prompt_log_id)

    # Persist the complete answer trace and return its identifier.
    trace_id = trace.build()

    return {
        "answer": answer,
        "session_id": session_id,
        "user_observation_id": user_observation_id,
        "assistant_observation_id": assistant_observation_id,
        "retrieval_mode": retrieval_mode,
        "used_session_items": used_session_items,
        "used_memory_items": used_memory_items,
        "trace_id": trace_id,
    }


class Agent:
    """Convenience wrapper around the per-turn runtime for a single session."""

    def __init__(self, session_id: str) -> None:
        """Create an agent bound to a conversation session."""
        if not session_id:
            raise ValueError("session_id must not be empty")
        self.session_id = session_id

    def handle_turn(self, user_message: str) -> str:
        """Accept one user turn and return the model response text."""
        return str(handle_user_message(self.session_id, user_message)["answer"])

    def respond(self, user_message: str) -> Response:
        """Accept one user turn and return the full structured response."""
        return handle_user_message(self.session_id, user_message)

    def reset_session(self) -> None:
        """Reset temporary session state without deleting durable memory."""
        for item in list_active_session_items(self.session_id):
            item_id = item.get("id")
            if isinstance(item_id, str):
                expire_session_item(self.session_id, item_id, "session reset")


def _dispatch_retrieval(
    mode: str,
    query: str,
    session_id: str | None,
    limit: int,
) -> list[dict[str, object]]:
    if mode == "deep":
        return retrieve_deep(query, session_id, limit)
    if mode == "relational":
        anchors = _matching_graph_node_ids(query, limit)
        if anchors:
            return relational_retrieve(anchors, set(), limit)
        return retrieve_quick(query, session_id, limit)
    return retrieve_quick(query, session_id, limit)


def _generate_answer(prompt: str) -> str:
    response = call_qwen_json(
        [{"role": "user", "content": prompt}],
        schema_name="answer_generation",
    )
    payload = response.get("json", {})
    if isinstance(payload, dict):
        return str(payload.get("answer", "")).strip()
    return ""


def _should_hydrate(prior_observations: list[dict[str, object]], user_message: str) -> bool:
    if not prior_observations:
        return True
    normalized = user_message.casefold()
    return any(marker in normalized for marker in CONTINUE_MARKERS)


def _recent_turn_records(prior_observations: list[dict[str, object]]) -> list[dict[str, object]]:
    recent = prior_observations[-RECENT_TURNS:]
    return [
        {"content": str(row["content"]), "id": str(row["id"]), "role": str(row.get("role", ""))}
        for row in recent
    ]


def _render_context(context_pack: list[dict[str, object]]) -> str:
    lines: list[str] = []
    for section in context_pack:
        name = str(section.get("section", "context"))
        if name == "current_user_message":
            continue
        rendered = _stringify_content(section.get("content"))
        if rendered:
            lines.append(f"[{name}] {rendered}")
    return "\n".join(lines)


def _stringify_content(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        return "; ".join(f"{key}={value}" for key, value in content.items() if value is not None)
    if content is None:
        return ""
    return str(content)


def _memory_ids(retrieved: list[dict[str, object]]) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for item in retrieved:
        identifier = item.get("id") or item.get("source_id")
        if isinstance(identifier, str) and identifier not in seen:
            seen.add(identifier)
            ids.append(identifier)
    return ids


def _matching_graph_node_ids(query: str, limit: int) -> list[str]:
    query_tokens = _tokens(query)
    if not query_tokens:
        return []
    node_ids: list[str] = []
    with repository_connection() as connection:
        rows = connection.execute("SELECT id, label FROM graph_nodes").fetchall()
    for row in rows:
        if query_tokens & _tokens(str(row["label"])):
            node_ids.append(str(row["id"]))
        if len(node_ids) >= limit:
            break
    return node_ids


def _log_traces(
    *,
    session_id: str,
    user_observation_id: str,
    query: str,
    retrieval_mode: str,
    retrieved: list[dict[str, object]],
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


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in TOKEN_PATTERN.findall(value.casefold())
        if len(token) > 1 and token not in STOPWORDS
    }
