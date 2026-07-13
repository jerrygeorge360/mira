"""Hydrate a new Session Working Set from durable cross-session memory.

Ownership: Jerry.
Related issue: ISSUE-015.
Architecture area: session micro-path.

Session memory and durable memory flow both ways: the slow path sends confirmed
session decisions into durable memory, and hydration brings durable memory back
into a new session at session start or when the user asks to continue prior work.
Hydrated items are written into the Session Working Set with ``status=hydrated``
and ``origin=cross_session_hydration`` so they are clearly provisional, durable-
sourced context -- never new durable memory, and never overriding a correction
the user has already made in the current session.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from core.db.repositories import repository_connection, workspace_id_for_session
from core.memory.foresight import list_relevant_foresight
from core.memory.tiers import list_hot_memory_for_context
from core.retrieval.auto import route_retrieval
from core.retrieval.relational import relational_retrieve
from core.session.working_set import list_active_session_items, upsert_session_item

HydrationCandidate = dict[str, object]

LOGGER = logging.getLogger(__name__)

HYDRATED_STATUS = "hydrated"
HYDRATION_ORIGIN = "cross_session_hydration"

CONFLICT_OVERLAP = 0.5
DUPLICATE_OVERLAP = 0.7

MEMORY_TYPE_TO_SESSION = {
    "confirmed_correction": ("correction", "direct_correction"),
    "project_constraint": ("active_constraint", "direct_instruction"),
    "behavioral_instruction": ("decision", "direct_decision"),
    "active_goal": ("current_goal", "direct_instruction"),
    "user_preference": ("active_constraint", "explicit_preference"),
    "active_foresight": ("active_constraint", "direct_instruction"),
}

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_'-]+")
STOPWORDS = frozenset(
    {"a", "an", "the", "is", "are", "to", "of", "for", "on", "in", "and", "my", "i", "we"}
)


def hydrate_session_from_memory(
    session_id: str,
    user_message: str,
    max_items: int,
) -> list[str]:
    """Seed a new Session Working Set from relevant durable cross-session memory."""
    if max_items < 1:
        raise ValueError("max_items must be a positive integer")
    workspace_id = workspace_id_for_session(session_id)

    candidates = [
        *_hot_memory_candidates(session_id, user_message, max_items),
        *_foresight_candidates(user_message, max_items, workspace_id),
        *_reflection_candidates(user_message, max_items, workspace_id),
        *_community_candidates(user_message, max_items, workspace_id),
        *_project_fact_candidates(user_message, max_items, workspace_id),
        *_unresolved_prior_session_candidates(session_id, user_message, max_items, workspace_id),
        *_graph_candidates(session_id, user_message, max_items, workspace_id),
    ]
    if not candidates:
        return []

    current_tokens = _current_session_token_sets(session_id)
    selected = _select_candidates(candidates, current_tokens, max_items)
    hydrated_ids = [
        upsert_session_item(session_id, _to_session_item(candidate)) for candidate in selected
    ]
    if hydrated_ids:
        LOGGER.info("Hydrated %d item(s) into session %s", len(hydrated_ids), session_id)
    return hydrated_ids


def _select_candidates(
    candidates: list[HydrationCandidate],
    current_tokens: list[set[str]],
    max_items: int,
) -> list[HydrationCandidate]:
    ordered = sorted(
        candidates,
        key=lambda candidate: (-_float(candidate.get("priority")), str(candidate.get("content"))),
    )
    selected: list[HydrationCandidate] = []
    selected_tokens: list[set[str]] = []
    for candidate in ordered:
        candidate_tokens = _tokens(str(candidate["content"]))
        if not candidate_tokens:
            continue
        # Current-session items (especially corrections) win: never hydrate over them.
        if any(_overlap(candidate_tokens, tokens) >= CONFLICT_OVERLAP for tokens in current_tokens):
            continue
        if any(
            _overlap(candidate_tokens, tokens) >= DUPLICATE_OVERLAP for tokens in selected_tokens
        ):
            continue
        selected.append(candidate)
        selected_tokens.append(candidate_tokens)
        if len(selected) >= max_items:
            break
    return selected


def _hot_memory_candidates(session_id: str, query: str, limit: int) -> list[HydrationCandidate]:
    query_tokens = _tokens(query)
    candidates: list[HydrationCandidate] = []
    for item in list_hot_memory_for_context(session_id, query, limit):
        if _overlap(query_tokens, _tokens(str(item["content"]))) <= 0.0:
            continue
        session_type, explicitness = MEMORY_TYPE_TO_SESSION.get(
            str(item.get("memory_type")), ("decision", "agent_inference")
        )
        source_item = _source_session_item(item)
        if source_item is not None:
            session_type = str(source_item["type"])
            explicitness = str(source_item["explicitness_label"])
        candidates.append(
            _candidate(
                content=str(item["content"]),
                session_type=session_type,
                scope=str(item.get("scope") or "project"),
                priority=_float(item.get("priority"), 0.7),
                explicitness=explicitness,
                source_observations=_source_observations_from_item(source_item),
            )
        )
    return candidates


def _foresight_candidates(query: str, limit: int, workspace_id: str) -> list[HydrationCandidate]:
    candidates: list[HydrationCandidate] = []
    for record in list_relevant_foresight(query, _now(), workspace_id=workspace_id)[:limit]:
        candidates.append(
            _candidate(
                content=str(record["content"]),
                session_type="active_constraint",
                scope="project",
                priority=0.85,
                explicitness="direct_instruction",
                source_observations=_string_list([record.get("source_observation_id")]),
            )
        )
    return candidates


def _reflection_candidates(query: str, limit: int, workspace_id: str) -> list[HydrationCandidate]:
    query_tokens = _tokens(query)
    candidates: list[HydrationCandidate] = []
    for row in _fetch_rows(
        "SELECT * FROM reflections WHERE workspace_id = ? AND status = ? ORDER BY created_at ASC",
        (workspace_id, "active"),
    ):
        if _overlap(query_tokens, _tokens(str(row["content"]))) <= 0.0:
            continue
        candidates.append(
            _candidate(
                content=str(row["content"]),
                session_type="decision",
                scope="cross_session",
                priority=_float(row.get("confidence"), 0.6),
                explicitness="inferred_preference",
            )
        )
    return candidates[:limit]


def _community_candidates(query: str, limit: int, workspace_id: str) -> list[HydrationCandidate]:
    query_tokens = _tokens(query)
    candidates: list[HydrationCandidate] = []
    for row in _fetch_rows(
        "SELECT * FROM community_summaries WHERE workspace_id = ? ORDER BY created_at ASC",
        (workspace_id,),
    ):
        text = f"{row['title']} {row['summary']}"
        if _overlap(query_tokens, _tokens(text)) <= 0.0:
            continue
        candidates.append(
            _candidate(
                content=f"{row['title']}: {row['summary']}",
                session_type="decision",
                scope="cross_session",
                priority=0.55,
                explicitness="agent_inference",
            )
        )
    return candidates[:limit]


def _project_fact_candidates(query: str, limit: int, workspace_id: str) -> list[HydrationCandidate]:
    query_tokens = _tokens(query)
    candidates: list[HydrationCandidate] = []
    for row in _fetch_rows(
        "SELECT * FROM atomic_facts WHERE workspace_id = ? AND status = ? "
        "ORDER BY created_at DESC LIMIT ?",
        (workspace_id, "active", limit * 5),
    ):
        content = f"{row['subject']} {row['predicate']} {row['object']}"
        if _overlap(query_tokens, _tokens(content)) <= 0.0:
            continue
        candidates.append(
            _candidate(
                content=content,
                session_type="decision",
                scope="project",
                priority=_float(row.get("confidence"), 0.5) * 0.8,
                explicitness="agent_inference",
                source_observations=_string_list([row.get("source_observation_id")]),
            )
        )
    return candidates[:limit]


def _unresolved_prior_session_candidates(
    session_id: str,
    query: str,
    limit: int,
    workspace_id: str,
) -> list[HydrationCandidate]:
    query_tokens = _tokens(query)
    candidates: list[HydrationCandidate] = []
    rows = _fetch_rows(
        """
        SELECT session_working_set.* FROM session_working_set
        JOIN sessions ON sessions.id = session_working_set.session_id
        WHERE sessions.workspace_id = ? AND session_working_set.session_id != ?
          AND session_working_set.type IN ('decision', 'open_question')
          AND session_working_set.scope IN ('project', 'cross_session')
          AND session_working_set.status IN ('provisional', 'hydrated', 'confirmed')
        ORDER BY session_working_set.updated_at DESC
        """,
        (workspace_id, session_id),
    )
    for row in rows:
        if _overlap(query_tokens, _tokens(str(row["content"]))) <= 0.0:
            continue
        candidates.append(
            _candidate(
                content=str(row["content"]),
                session_type=str(row["type"]),
                scope=str(row["scope"]),
                priority=_float(row.get("priority"), 0.55),
                explicitness="direct_decision" if str(row["type"]) == "decision" else "ambiguous",
            )
        )
    return candidates[:limit]


def _graph_candidates(
    session_id: str, query: str, limit: int, workspace_id: str
) -> list[HydrationCandidate]:
    if route_retrieval(query, session_id)["mode"] != "relational":
        return []
    node_ids = _matching_graph_node_ids(query, limit, workspace_id)
    if not node_ids:
        return []
    candidates: list[HydrationCandidate] = []
    for relation in relational_retrieve(node_ids, set(), limit, workspace_id=workspace_id):
        candidates.append(
            _candidate(
                content=str(relation["content"]),
                session_type="decision",
                scope="project",
                priority=0.7,
                explicitness="agent_inference",
                source_observations=_string_list(relation.get("source_observations")),
            )
        )
    return candidates


def _matching_graph_node_ids(query: str, limit: int, workspace_id: str) -> list[str]:
    query_tokens = _tokens(query)
    if not query_tokens:
        return []
    node_ids: list[str] = []
    for row in _fetch_rows(
        "SELECT id, label FROM graph_nodes WHERE workspace_id = ?", (workspace_id,)
    ):
        if _overlap(query_tokens, _tokens(str(row["label"]))) > 0.0:
            node_ids.append(str(row["id"]))
        if len(node_ids) >= limit:
            break
    return node_ids


def _to_session_item(candidate: HydrationCandidate) -> dict[str, object]:
    content = str(candidate["content"])
    return {
        "type": candidate["session_type"],
        "content": content,
        "scope": candidate["scope"],
        "status": HYDRATED_STATUS,
        "priority": _float(candidate.get("priority")),
        "explicitness_label": candidate["explicitness"],
        "evidence_span": content,
        "source_observations": _string_list(candidate.get("source_observations")),
        "supersedes": [],
        "origin": HYDRATION_ORIGIN,
    }


def _candidate(
    *,
    content: str,
    session_type: str,
    scope: str,
    priority: float,
    explicitness: str,
    source_observations: list[str] | None = None,
) -> HydrationCandidate:
    return {
        "content": content,
        "session_type": session_type,
        "scope": scope,
        "priority": priority,
        "explicitness": explicitness,
        "source_observations": source_observations or [],
    }


def _current_session_token_sets(session_id: str) -> list[set[str]]:
    return [_tokens(str(item.get("content", ""))) for item in list_active_session_items(session_id)]


def _fetch_rows(statement: str, parameters: tuple[object, ...]) -> list[dict[str, object]]:
    with repository_connection() as connection:
        rows = connection.execute(statement, parameters).fetchall()
    return [dict(row) for row in rows]


def _source_session_item(item: dict[str, object]) -> dict[str, object] | None:
    if item.get("source_record_type") != "session_working_set":
        return None
    source_id = item.get("source_record_id")
    if not isinstance(source_id, str) or not source_id:
        return None
    rows = _fetch_rows("SELECT * FROM session_working_set WHERE id = ?", (source_id,))
    return rows[0] if rows else None


def _source_observations_from_item(item: dict[str, object] | None) -> list[str]:
    if item is None:
        return []
    return _json_string_list(item.get("source_observations_json"))


def _overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left)


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in TOKEN_PATTERN.findall(value.casefold())
        if len(token) > 1 and token not in STOPWORDS
    }


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item]
    return []


def _json_string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return []
        return _string_list(decoded)
    return _string_list(value)


def _float(value: object, default: float = 0.0) -> float:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()  # noqa: UP017
