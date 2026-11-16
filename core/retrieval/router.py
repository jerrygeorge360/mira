"""Public retrieval dispatcher for Quick, Deep, Relational, and Auto modes.

Ownership: Jerry.
Related issue: ISSUE-308.
Architecture area: retrieval.
"""

from __future__ import annotations

from collections.abc import Collection

from core.db.repositories import (
    list_session_knowledge_base_ids,
    repository_connection,
    workspace_id_for_session,
)
from core.db.schema import LEGACY_WORKSPACE_ID
from core.evidence.config import source_aware_retrieval_enabled
from core.memory.lifecycle import is_historical_query
from core.retrieval.auto import route_retrieval as choose_retrieval_mode
from core.retrieval.deep import retrieve_deep
from core.retrieval.quick import graph_node_allowed, retrieve_quick, source_record_allowed
from core.retrieval.relational import relational_retrieve

SUPPORTED_MODES = frozenset({"auto", "quick", "deep", "relational"})


def route_retrieval(
    query: str,
    mode: str = "auto",
    limit: int = 8,
    session_id: str | None = None,
    *,
    workspace_id: str | None = None,
    include_documents: bool = True,
    allowed_knowledge_base_ids: Collection[str] | None = None,
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
    workspace_id = workspace_id or (
        workspace_id_for_session(session_id) if session_id is not None else LEGACY_WORKSPACE_ID
    )
    if include_documents and allowed_knowledge_base_ids is None:
        if session_id is None or not source_aware_retrieval_enabled_for_workspace(
            workspace_id=workspace_id
        ):
            allowed_knowledge_base_ids = ()
        else:
            allowed_knowledge_base_ids = tuple(
                list_session_knowledge_base_ids(session_id, workspace_id=workspace_id)
            )
    historical = is_historical_query(query)
    if selected_mode == "deep":
        return retrieve_deep(
            query,
            session_id,
            limit,
            workspace_id=workspace_id,
            historical=historical,
            include_documents=include_documents,
            allowed_knowledge_base_ids=allowed_knowledge_base_ids,
        )
    if selected_mode == "relational":
        anchors = _matching_graph_node_ids(query, limit, workspace_id)
        if not include_documents or allowed_knowledge_base_ids is not None:
            anchors = [
                node_id
                for node_id in anchors
                if graph_node_allowed(
                    node_id, workspace_id, include_documents, allowed_knowledge_base_ids
                )
            ]
        if anchors:
            results = relational_retrieve(
                anchors, set(), limit, workspace_id=workspace_id, historical=historical, query=query
            )
            if include_documents and allowed_knowledge_base_ids is None:
                return results
            return [
                item
                for item in results
                if source_record_allowed(
                    "graph_edge",
                    str(item.get("source_id", "")),
                    workspace_id,
                    include_documents,
                    allowed_knowledge_base_ids,
                    record=item.get("record"),
                )
                and graph_node_allowed(
                    str(item.get("origin_node_id", "")),
                    workspace_id,
                    include_documents,
                    allowed_knowledge_base_ids,
                )
                and graph_node_allowed(
                    str(item.get("related_node_id", "")),
                    workspace_id,
                    include_documents,
                    allowed_knowledge_base_ids,
                )
            ]
        return retrieve_quick(
            query,
            session_id,
            limit,
            workspace_id=workspace_id,
            historical=historical,
            include_documents=include_documents,
            allowed_knowledge_base_ids=allowed_knowledge_base_ids,
        )
    return retrieve_quick(
        query,
        session_id,
        limit,
        workspace_id=workspace_id,
        historical=historical,
        include_documents=include_documents,
        allowed_knowledge_base_ids=allowed_knowledge_base_ids,
    )


def source_aware_retrieval_enabled_for_workspace(*, workspace_id: str) -> bool:
    """Apply workspace/project rollout controls to normal chat document retrieval."""
    if source_aware_retrieval_enabled(workspace_id=workspace_id):
        return True
    with repository_connection() as connection:
        rows = connection.execute(
            "SELECT project_id FROM project_namespaces WHERE workspace_id = ? "
            "UNION SELECT project_id FROM project_knowledge_workspaces WHERE workspace_id = ?",
            (workspace_id, workspace_id),
        ).fetchall()
    return any(
        source_aware_retrieval_enabled(workspace_id=workspace_id, project_id=str(row[0]))
        for row in rows
    )


def _matching_graph_node_ids(query: str, limit: int, workspace_id: str) -> list[str]:
    terms = [term for term in query.split() if len(term) > 2]
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
