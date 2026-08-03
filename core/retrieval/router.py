"""Public retrieval dispatcher for Quick, Deep, Relational, and Auto modes.

Ownership: Jerry.
Related issue: ISSUE-308.
Architecture area: retrieval.
"""

from __future__ import annotations

import re

from core.db.repositories import repository_connection, workspace_id_for_session
from core.db.schema import LEGACY_WORKSPACE_ID
from core.retrieval.auto import route_retrieval as choose_retrieval_mode
from core.retrieval.deep import retrieve_deep
from core.retrieval.quick import retrieve_quick
from core.retrieval.relational import relational_retrieve

SUPPORTED_MODES = frozenset({"auto", "quick", "deep", "relational"})
GRAPH_ANCHOR_STOPWORDS = frozenset(
    {
        "and",
        "about",
        "are",
        "can",
        "could",
        "did",
        "does",
        "for",
        "from",
        "have",
        "how",
        "just",
        "more",
        "not",
        "purpose",
        "should",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "would",
        "you",
        "your",
        "was",
        "were",
    }
)


def route_retrieval(
    query: str,
    mode: str = "auto",
    limit: int = 8,
    session_id: str | None = None,
) -> list[dict[str, object]]:
    """Route a query through the requested public retrieval mode."""
    if limit < 1:
        raise ValueError("limit must be a positive integer")
    selected_mode = mode.casefold().strip()
    if selected_mode not in SUPPORTED_MODES:
        raise ValueError("mode must be one of: auto, quick, deep, relational")
    if selected_mode == "auto":
        decision = choose_retrieval_mode(query, session_id)
        selected_mode = str(decision.get("mode", "quick"))
        if selected_mode == "general":
            return []
    workspace_id = (
        workspace_id_for_session(session_id) if session_id is not None else LEGACY_WORKSPACE_ID
    )
    if selected_mode == "deep":
        return retrieve_deep(query, session_id, limit)
    if selected_mode == "relational":
        anchors = _matching_graph_node_ids(query, limit, workspace_id)
        if anchors:
            return relational_retrieve(anchors, set(), limit, workspace_id=workspace_id)
        return retrieve_quick(query, session_id, limit)
    return retrieve_quick(query, session_id, limit)


def _matching_graph_node_ids(query: str, limit: int, workspace_id: str) -> list[str]:
    terms = [
        term
        for term in re.findall(r"[\w.+-]+", query.casefold())
        if len(term) > 2 and term not in GRAPH_ANCHOR_STOPWORDS
    ]
    if not terms:
        return []
    with repository_connection() as connection:
        matches: list[str] = []
        for term in terms:
            rows = connection.execute(
                """
                SELECT id FROM graph_nodes
                WHERE workspace_id = ? AND label LIKE ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (workspace_id, f"%{term}%", limit),
            ).fetchall()
            matches.extend(str(row["id"]) for row in rows)
    return list(dict.fromkeys(matches))[:limit]
