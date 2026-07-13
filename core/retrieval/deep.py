"""Deep Mode retrieval over cached community summaries and reflections.

Ownership: Jerry.
Related issue: ISSUE-036.
Architecture area: retrieval.

Deep Mode answers broad synthesis questions from graph-derived warm memory --
cached community summaries plus relevant reflections, with optional supporting
observations -- rather than stuffing raw transcripts. It never runs community
detection live: summaries are produced in the background (ISSUE-032). For
synthesis it surfaces both the most similar communities and, where more exist,
a contrasting dissimilar one. When no communities have been built yet, it falls
back to Quick Mode and records why.
"""

from __future__ import annotations

import json
import logging
import re

from core.db.repositories import repository_connection, workspace_id_for_session
from core.db.schema import LEGACY_WORKSPACE_ID
from core.retrieval.quick import retrieve_quick
from core.retrieval.vector import vector_search

Evidence = dict[str, object]

LOGGER = logging.getLogger(__name__)

DISSIMILAR_COMMUNITIES = 1
SUPPORTING_OBSERVATIONS = 2

SOURCE_RANK = {"community_summary": 0, "reflection": 1, "observation": 2}
SOURCE_WEIGHT = {"community_summary": 1.0, "reflection": 0.7, "observation": 0.4}

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_'-]+")
STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "is",
        "are",
        "do",
        "does",
        "did",
        "how",
        "what",
        "when",
        "i",
        "my",
        "me",
        "to",
        "of",
        "for",
        "on",
        "and",
        "while",
        "work",
        "works",
    }
)


def retrieve_deep(
    query: str,
    session_id: str | None,
    limit: int,
    *,
    workspace_id: str | None = None,
) -> list[Evidence]:
    """Retrieve synthesis-ready context from community summaries and reflections."""
    if limit < 1:
        raise ValueError("limit must be a positive integer")
    if not query.strip():
        return []

    session_workspace = workspace_id_for_session(session_id) if session_id is not None else None
    if workspace_id is not None and session_workspace not in {None, workspace_id}:
        raise ValueError("session does not belong to the requested workspace")
    workspace_id = workspace_id or session_workspace or LEGACY_WORKSPACE_ID
    summaries = _community_candidates(query, limit, workspace_id)
    if not summaries:
        LOGGER.info("Deep Mode found no community summaries; falling back to Quick Mode")
        return _quick_fallback(query, session_id, limit, workspace_id)

    candidates = [
        *summaries,
        *_reflection_candidates(query, limit, workspace_id),
        *_supporting_observation_candidates(query, session_id),
    ]
    candidates.sort(key=_ranking_key)
    return candidates[:limit]


def deep_retrieve(query: str, limit: int = 8) -> list[Evidence]:
    """Retrieve graph-community summaries for broad synthesis without session scope."""
    return retrieve_deep(query, session_id=None, limit=limit)


def _quick_fallback(
    query: str, session_id: str | None, limit: int, workspace_id: str
) -> list[Evidence]:
    results = retrieve_quick(query, session_id, limit, workspace_id=workspace_id)
    for result in results:
        result["retrieval_mode"] = "deep"
        result["deep_mode_fallback"] = "no_communities"
    return results


def _community_candidates(query: str, limit: int, workspace_id: str) -> list[Evidence]:
    rows = _fetch_community_summaries(workspace_id)
    if not rows:
        return []
    query_tokens = _tokens(query)
    scored = sorted(
        ((row, _token_overlap(query_tokens, _summary_text(row))) for row in rows),
        key=lambda pair: (-pair[1], str(pair[0]["id"])),
    )

    similar = scored[:limit]
    selected_ids = {str(row["id"]) for row, _ in similar}
    candidates = [_community_evidence(row, relevance, "similar") for row, relevance in similar]

    # Surface a contrasting (least similar) community to support synthesis.
    contrast_added = 0
    for row, relevance in reversed(scored):
        if contrast_added >= DISSIMILAR_COMMUNITIES:
            break
        if str(row["id"]) not in selected_ids:
            candidates.append(_community_evidence(row, relevance, "contrast"))
            selected_ids.add(str(row["id"]))
            contrast_added += 1
    return candidates


def _reflection_candidates(query: str, limit: int, workspace_id: str) -> list[Evidence]:
    # Match reflections by meaning (embedding similarity), not literal token overlap: a
    # synthesized reflection rarely shares words with the question it answers ("what kind of
    # engineer am I?" vs "follows test-driven development"), so lexical matching dropped them.
    active_by_id = {str(row["id"]): row for row in _fetch_active_reflections(workspace_id)}
    if not active_by_id:
        return []
    candidates: list[Evidence] = []
    seen: set[str] = set()
    for pointer in vector_search(
        query, limit=limit, collections=("reflections",), workspace_id=workspace_id
    ):
        reflection_id = str(pointer.get("sqlite_id"))
        row = active_by_id.get(reflection_id)
        if row is None or reflection_id in seen:
            continue
        seen.add(reflection_id)
        relevance = max(0.0, 1.0 - _float(pointer.get("distance"), 1.0))
        candidates.append(
            {
                "source": "reflection",
                "source_id": reflection_id,
                "id": reflection_id,
                "content": str(row["content"]),
                "reflection_type": str(row["reflection_type"]),
                "relevance": relevance,
                "confidence": _float(row.get("confidence"), 1.0),
                "score": _score("reflection", relevance),
                "record": dict(row),
            }
        )
    return candidates[:limit]


def _supporting_observation_candidates(query: str, session_id: str | None) -> list[Evidence]:
    if session_id is None:
        return []
    query_tokens = _tokens(query)
    if not query_tokens:
        return []
    candidates: list[Evidence] = []
    for row in _fetch_session_observations(session_id):
        content = str(row["content"])
        relevance = _token_overlap(query_tokens, content)
        if relevance <= 0.0:
            continue
        candidates.append(
            {
                "source": "observation",
                "source_id": str(row["id"]),
                "id": str(row["id"]),
                "content": content,
                "relevance": relevance,
                "score": _score("observation", relevance),
                "record": dict(row),
            }
        )
    candidates.sort(key=lambda item: (-_float(item["relevance"]), str(item["source_id"])))
    return candidates[:SUPPORTING_OBSERVATIONS]


def _community_evidence(row: dict[str, object], relevance: float, relation: str) -> Evidence:
    title = str(row["title"])
    summary = str(row["summary"])
    return {
        "source": "community_summary",
        "source_id": str(row["id"]),
        "id": str(row["id"]),
        "community_id": str(row["community_id"]),
        "title": title,
        "content": f"{title}: {summary}",
        "member_node_ids": _json_list(row.get("member_nodes_json")),
        "relation": relation,
        "relevance": relevance,
        "score": _score("community_summary", relevance),
        "record": dict(row),
    }


def _fetch_community_summaries(workspace_id: str) -> list[dict[str, object]]:
    with repository_connection() as connection:
        rows = connection.execute(
            """
            SELECT * FROM community_summaries
            WHERE workspace_id = ? ORDER BY created_at ASC
            """,
            (workspace_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _fetch_active_reflections(workspace_id: str) -> list[dict[str, object]]:
    with repository_connection() as connection:
        rows = connection.execute(
            """
            SELECT * FROM reflections
            WHERE workspace_id = ? AND status = ? ORDER BY created_at ASC
            """,
            (workspace_id, "active"),
        ).fetchall()
    return [dict(row) for row in rows]


def _fetch_session_observations(session_id: str) -> list[dict[str, object]]:
    with repository_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM observations WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
            (session_id, SUPPORTING_OBSERVATIONS * 5),
        ).fetchall()
    return [dict(row) for row in rows]


def _summary_text(row: dict[str, object]) -> str:
    return f"{row['title']} {row['summary']}"


def _score(source: str, relevance: float) -> float:
    return round((SOURCE_WEIGHT.get(source, 0.5) * 0.6) + (_clamp(relevance) * 0.4), 6)


def _ranking_key(evidence: Evidence) -> tuple[int, float, float, str]:
    return (
        SOURCE_RANK.get(str(evidence.get("source")), 9),
        -_float(evidence.get("score")),
        -_float(evidence.get("relevance")),
        str(evidence.get("source_id")),
    )


def _token_overlap(query_tokens: set[str], content: str) -> float:
    content_tokens = _tokens(content)
    if not query_tokens or not content_tokens:
        return 0.0
    return len(query_tokens & content_tokens) / len(query_tokens)


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in TOKEN_PATTERN.findall(value.casefold())
        if len(token) > 1 and token not in STOPWORDS
    }


def _json_list(value: object) -> list[str]:
    if value is None:
        return []
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, list):
        return []
    return [item for item in decoded if isinstance(item, str)]


def _float(value: object, default: float = 0.0) -> float:
    if isinstance(value, int | float):
        return float(value)
    return default


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))
