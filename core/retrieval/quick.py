"""Quick Mode direct fact retrieval across vectors, keywords, and records.

Ownership: Jerry.
Related issue: ISSUE-034.
Architecture area: retrieval.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
from collections.abc import Collection
from datetime import UTC, datetime

from core.db.evidence import list_active_evidence
from core.db.repositories import repository_connection, workspace_id_for_session
from core.db.schema import LEGACY_WORKSPACE_ID
from core.evidence.source import resolve_source
from core.memory.lifecycle import (
    is_historical_query,
    lifecycle_for_retrieval,
    record_retrieval,
    retrieval_lifecycle_eligible,
    retrieval_source_type,
)
from core.retrieval.documents import retrieve_document_chunks
from core.retrieval.keyword import keyword_search_atomic_facts, keyword_search_observations
from core.retrieval.vector import vector_search

Evidence = dict[str, object]

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_'-]+")
ACTIVE_STATUS_SCORE = {"active": 1.0, "pending": 0.8, "resolved": 0.4}

# Reciprocal rank fusion constant (standard ~60): dampens the weight of top ranks so
# fusion is stable and scale-independent across the semantic and keyword retrievers.
RRF_K = 60
RECENCY_HALF_LIFE_DAYS = 30.0
RECENCY_HALF_LIFE_SECONDS = RECENCY_HALF_LIFE_DAYS * 24.0 * 60.0 * 60.0
# Structured-first: validated derived memory is the current answer surface; the raw
# observation log is fallback/evidence, so it is weighted down rather than dropped.
SOURCE_WEIGHT = {
    "atomic_facts": 1.0,
    "foresight_records": 1.0,
    "reflections": 0.9,
    "document_chunks": 1.05,
    "recent_observations": 0.6,
    "observations": 0.45,
}
DEFAULT_SOURCE_WEIGHT = 0.5
# Recall gate: drop tail candidates far below the best match so weak noise is not
# injected. Relative, so it adapts to how strong the top hit is.
RECALL_GATE_FRACTION = 0.1
FORESIGHT_QUERY_MARKERS = frozenset(
    {
        "deadline",
        "due",
        "time-sensitive",
        "time sensitive",
        "remind",
        "upcoming",
        "next",
        "schedule",
    }
)


def retrieve_quick(
    query: str,
    session_id: str | None,
    limit: int,
    *,
    workspace_id: str | None = None,
    historical: bool = False,
    include_documents: bool = True,
    allowed_knowledge_base_ids: Collection[str] | None = None,
) -> list[Evidence]:
    """Retrieve prompt-ready direct evidence for specific factual questions."""
    if limit < 1:
        raise ValueError("limit must be a positive integer")
    if not query.strip():
        return []

    session_workspace = workspace_id_for_session(session_id) if session_id is not None else None
    if workspace_id is not None and session_workspace not in {None, workspace_id}:
        raise ValueError("session does not belong to the requested workspace")
    workspace_id = workspace_id or session_workspace or LEGACY_WORKSPACE_ID
    historical = is_historical_query(query, historical=historical)
    candidates = [
        *_semantic_candidates(query, limit, workspace_id, historical=historical),
        *_keyword_observation_candidates(query, workspace_id, limit),
        *_atomic_fact_candidates(query, workspace_id, limit, historical=historical),
        *(
            _document_candidates(query, workspace_id, limit, allowed_knowledge_base_ids)
            if include_documents
            else []
        ),
        *_foresight_candidates(query, session_id, workspace_id, historical=historical),
        *_recent_observation_candidates(query, session_id, limit),
    ]
    if not include_documents or allowed_knowledge_base_ids is not None:
        candidates = [
            candidate
            for candidate in candidates
            if _candidate_source_allowed(
                candidate, workspace_id, include_documents, allowed_knowledge_base_ids
            )
        ]
    candidates = _enrich_lifecycle(candidates, workspace_id, query=query, historical=historical)
    deduplicated = _merge_duplicates(candidates)
    ranked = _rank_candidates(deduplicated)
    selected = ranked[:limit]
    for item in selected:
        item["relevance_score"] = _float(item.get("score"))
        source_type = _lifecycle_source_type(str(item.get("source", "")))
        if source_type is not None:
            record_retrieval(
                source_type,
                str(item["source_id"]),
                workspace_id,
                evidence={
                    "relevance_score": item.get("relevance_score"),
                    "freshness_score": item.get("freshness_score"),
                    "trust_score": item.get("trust_score"),
                },
            )
    return selected


def _candidate_source_allowed(
    candidate: Evidence,
    workspace_id: str,
    include_documents: bool,
    allowed_knowledge_base_ids: Collection[str] | None,
) -> bool:
    source = str(candidate.get("source", ""))
    if source == "document_chunks":
        return include_documents and (
            allowed_knowledge_base_ids is None
            or candidate.get("knowledge_base_id") in allowed_knowledge_base_ids
        )
    if source in {"observations", "recent_observations"}:
        return True
    target_type = {
        "atomic_facts": "atomic_fact",
        "reflections": "reflection",
        "foresight_records": "foresight",
    }.get(source)
    if target_type is None:
        return False
    return source_record_allowed(
        target_type,
        str(candidate.get("source_id", "")),
        workspace_id,
        include_documents,
        allowed_knowledge_base_ids,
        record=candidate.get("record"),
    )


def source_record_allowed(
    target_type: str,
    target_id: str,
    workspace_id: str,
    include_documents: bool,
    allowed_knowledge_base_ids: Collection[str] | None,
    *,
    record: object = None,
) -> bool:
    """Require active, authorized support for scoped derived evidence."""
    if include_documents and allowed_knowledge_base_ids is None:
        return True
    if not target_id:
        return False
    try:
        with repository_connection() as connection:
            links = connection.execute(
                """SELECT s.source_type, s.source_id, s.knowledge_base_id
                   FROM evidence_links AS l
                   JOIN evidence_sources AS s ON s.id = l.source_id
                   WHERE l.workspace_id = ? AND l.target_type = ? AND l.target_id = ?
                     AND l.stance = 'support' AND l.retracted_at IS NULL
                     AND s.workspace_id = ? AND s.retracted_at IS NULL""",
                (workspace_id, target_type, target_id, workspace_id),
            ).fetchall()
            if links:
                # The derived text can incorporate every support. One unauthorized source
                # makes the whole candidate unsafe to expose.
                return all(
                    _support_allowed(
                        connection,
                        link,
                        workspace_id,
                        include_documents,
                        allowed_knowledge_base_ids,
                    )
                    for link in links
                )
            return _legacy_support_allowed(connection, target_type, target_id, workspace_id, record)
    except Exception:
        # Missing provenance tables or a failed read cannot grant source access.
        return False


def graph_node_allowed(
    node_id: str,
    workspace_id: str,
    include_documents: bool,
    allowed_knowledge_base_ids: Collection[str] | None,
) -> bool:
    """Authorize a graph label through its source record, failing closed if unknown."""
    if include_documents and allowed_knowledge_base_ids is None:
        return True
    with repository_connection() as connection:
        node = connection.execute(
            "SELECT source_table, source_id FROM graph_nodes WHERE id = ? AND workspace_id = ?",
            (node_id, workspace_id),
        ).fetchone()
        if node is None or not node["source_id"]:
            return False
        source_table = str(node["source_table"])
        source_id = str(node["source_id"])
        if source_table == "observations":
            return (
                connection.execute(
                    "SELECT 1 FROM observations WHERE id = ? AND workspace_id = ?",
                    (source_id, workspace_id),
                ).fetchone()
                is not None
            )
        if source_table == "document_chunks":
            if not include_documents:
                return False
            row = connection.execute(
                """SELECT c.knowledge_base_id FROM document_chunks AS c
                   JOIN documents AS d ON d.id = c.document_id AND d.workspace_id = c.workspace_id
                   JOIN knowledge_bases AS k ON k.id = d.knowledge_base_id
                     AND k.workspace_id = d.workspace_id
                   WHERE c.id = ? AND c.workspace_id = ? AND d.status = 'ready'
                     AND d.deleted_at IS NULL AND k.status = 'active'
                     AND d.knowledge_base_id = c.knowledge_base_id""",
                (source_id, workspace_id),
            ).fetchone()
            return row is not None and (
                allowed_knowledge_base_ids is None
                or row["knowledge_base_id"] in allowed_knowledge_base_ids
            )
        if source_table == "entities":
            edges = connection.execute(
                "SELECT * FROM graph_edges WHERE workspace_id = ? AND invalidated_at IS NULL "
                "AND (source_node_id = ? OR target_node_id = ?)",
                (workspace_id, node_id, node_id),
            ).fetchall()
            return any(
                source_record_allowed(
                    "graph_edge",
                    str(edge["id"]),
                    workspace_id,
                    include_documents,
                    allowed_knowledge_base_ids,
                    record=dict(edge),
                )
                for edge in edges
            )
        target_type = {
            "atomic_facts": "atomic_fact",
            "reflections": "reflection",
            "foresight_records": "foresight",
            "graph_edges": "graph_edge",
        }.get(source_table)
        if target_type is None:
            return False
        row = connection.execute(
            f"SELECT * FROM {source_table} WHERE id = ? AND workspace_id = ?",  # nosec B608
            (source_id, workspace_id),
        ).fetchone()
    return row is not None and source_record_allowed(
        target_type,
        source_id,
        workspace_id,
        include_documents,
        allowed_knowledge_base_ids,
        record=dict(row),
    )


def _support_allowed(
    connection: sqlite3.Connection,
    link: sqlite3.Row,
    workspace_id: str,
    include_documents: bool,
    allowed_knowledge_base_ids: Collection[str] | None,
) -> bool:
    if link["source_type"] == "conversation_observation":
        return (
            connection.execute(
                "SELECT 1 FROM observations WHERE id = ? AND workspace_id = ?",
                (link["source_id"], workspace_id),
            ).fetchone()
            is not None
        )
    if link["source_type"] != "document_chunk" or not include_documents:
        return False
    knowledge_base_id = link["knowledge_base_id"]
    if not knowledge_base_id or (
        allowed_knowledge_base_ids is not None
        and knowledge_base_id not in allowed_knowledge_base_ids
    ):
        return False
    return (
        connection.execute(
            """SELECT 1 FROM document_chunks AS c
           JOIN documents AS d ON d.id = c.document_id AND d.workspace_id = c.workspace_id
           JOIN knowledge_bases AS k ON k.id = d.knowledge_base_id
             AND k.workspace_id = d.workspace_id
           WHERE c.id = ? AND c.workspace_id = ? AND c.knowledge_base_id = ?
             AND d.knowledge_base_id = ? AND d.status = 'ready'
             AND d.deleted_at IS NULL AND k.status = 'active'""",
            (link["source_id"], workspace_id, knowledge_base_id, knowledge_base_id),
        ).fetchone()
        is not None
    )


def _legacy_support_allowed(
    connection: sqlite3.Connection,
    target_type: str,
    target_id: str,
    workspace_id: str,
    record: object,
) -> bool:
    if not isinstance(record, dict):
        return False
    if target_type in {"atomic_fact", "foresight"}:
        observation_id = record.get("source_observation_id")
        return (
            bool(observation_id)
            and connection.execute(
                "SELECT 1 FROM observations WHERE id = ? AND workspace_id = ?",
                (observation_id, workspace_id),
            ).fetchone()
            is not None
        )
    if target_type == "reflection":
        rows = connection.execute(
            """SELECT o.id FROM reflection_evidence AS e
               JOIN observations AS o ON o.id = e.observation_id
               WHERE e.reflection_id = ? AND o.workspace_id = ?""",
            (target_id, workspace_id),
        ).fetchall()
        return bool(rows)
    if target_type == "graph_edge":
        try:
            observation_ids = json.loads(str(record.get("source_observations_json", "[]")))
        except ValueError:
            return False
        return bool(observation_ids) and all(
            connection.execute(
                "SELECT 1 FROM observations WHERE id = ? AND workspace_id = ?",
                (observation_id, workspace_id),
            ).fetchone()
            is not None
            for observation_id in observation_ids
        )
    return False


def quick_retrieve(query: str, limit: int = 8, *, historical: bool = False) -> list[Evidence]:
    """Retrieve direct fact candidates without session scoping."""
    return retrieve_quick(query, session_id=None, limit=limit, historical=historical)


def _semantic_candidates(
    query: str, limit: int, workspace_id: str, *, historical: bool = False
) -> list[Evidence]:
    candidates: list[Evidence] = []
    pointers = vector_search(
        query,
        limit=limit,
        collections=("observations", "reflections"),
        workspace_id=workspace_id,
    )
    for pointer in pointers:
        record = _fetch_record(
            str(pointer["sqlite_table"]), str(pointer["sqlite_id"]), workspace_id
        )
        if record is None:
            continue
        if not _semantic_record_is_active(
            str(pointer["sqlite_table"]), record, historical=historical
        ):
            continue
        candidates.append(
            _evidence(
                source=str(pointer["sqlite_table"]),
                source_id=str(pointer["sqlite_id"]),
                content=_record_content(str(pointer["sqlite_table"]), record),
                semantic_score=max(0.0, 1.0 - _float(pointer.get("distance"), 1.0)),
                keyword_score=0.0,
                recency=_recency_score(record),
                confidence=_confidence(record),
                status=str(record.get("status", "active")),
                record=record,
            )
        )
    return candidates


def _document_candidates(
    query: str,
    workspace_id: str,
    limit: int,
    allowed_knowledge_base_ids: Collection[str] | None,
) -> list[Evidence]:
    """Retrieve source-document evidence without creating lifecycle memory state."""
    if allowed_knowledge_base_ids is not None and not allowed_knowledge_base_ids:
        return []
    try:
        if allowed_knowledge_base_ids is None:
            matches = retrieve_document_chunks(query, workspace_id=workspace_id, limit=limit)
        else:
            matches = [
                match
                for knowledge_base_id in sorted(set(allowed_knowledge_base_ids))
                if knowledge_base_id
                for match in retrieve_document_chunks(
                    query,
                    workspace_id=workspace_id,
                    knowledge_base_id=knowledge_base_id,
                    limit=limit,
                )
                if match.get("knowledge_base_id") == knowledge_base_id
            ]
    except Exception:
        # A missing/temporarily unavailable document index must not break memory retrieval.
        return []
    tokens = _tokens(query)
    candidates: list[Evidence] = []
    for match in matches:
        record = match.get("record")
        if not isinstance(record, dict):
            continue
        content = str(match.get("content", ""))
        evidence = _evidence(
            source="document_chunks",
            source_id=str(match.get("chunk_id", record.get("id", ""))),
            content=content,
            semantic_score=_float(match.get("relevance_score")),
            keyword_score=_lexical_score(tokens, content),
            recency=_recency_score(record),
            confidence=1.0,
            status="active",
            record={**record, "status": "active"},
        )
        evidence["knowledge_base_id"] = match.get("knowledge_base_id")
        evidence["document_id"] = match.get("document_id")
        evidence["filename"] = match.get("filename")
        evidence["page_start"] = match.get("page_start")
        evidence["page_end"] = match.get("page_end")
        evidence["provenance"] = match.get("provenance", {})
        candidates.append(evidence)
    return candidates


def _keyword_observation_candidates(
    query: str,
    workspace_id: str,
    limit: int,
) -> list[Evidence]:
    results = keyword_search_observations(query, limit, workspace_id=workspace_id)
    return [
        _evidence(
            source="observations",
            source_id=str(record["id"]),
            content=str(record["content"]),
            semantic_score=0.0,
            keyword_score=_normalized_keyword_score(record),
            recency=_recency_score(record),
            confidence=1.0,
            status="active",
            record=record,
        )
        for record in results
        if record.get("workspace_id") == workspace_id
    ]


def _atomic_fact_candidates(
    query: str, workspace_id: str, limit: int, *, historical: bool = False
) -> list[Evidence]:
    results = keyword_search_atomic_facts(
        query, limit, workspace_id=workspace_id, include_inactive=historical
    )
    return [
        _evidence(
            source="atomic_facts",
            source_id=str(record["id"]),
            content=_fact_content(record),
            semantic_score=0.0,
            keyword_score=_normalized_keyword_score(record),
            recency=_recency_score(record),
            confidence=_confidence(record),
            status=str(record.get("status", "active")),
            record=record,
        )
        for record in results
        if record.get("workspace_id") == workspace_id
    ]


def _foresight_candidates(
    query: str,
    session_id: str | None,
    workspace_id: str,
    *,
    historical: bool = False,
) -> list[Evidence]:
    tokens = _tokens(query)
    if not tokens:
        return []
    is_foresight_query = _is_foresight_query(query)
    rows = _fetch_foresight_rows(session_id, workspace_id, historical=historical)
    candidates: list[Evidence] = []
    for record in rows:
        content = str(record["content"])
        keyword_score = _lexical_score(tokens, content)
        if keyword_score <= 0.0 and not is_foresight_query:
            continue
        candidates.append(
            _evidence(
                source="foresight_records",
                source_id=str(record["id"]),
                content=content,
                semantic_score=0.0,
                keyword_score=max(keyword_score, 0.9 if is_foresight_query else 0.0),
                recency=_recency_score(record),
                confidence=1.0,
                status=str(record["status"]),
                record=record,
            )
        )
    return candidates


def _recent_observation_candidates(
    query: str,
    session_id: str | None,
    limit: int,
) -> list[Evidence]:
    if session_id is None:
        return []
    tokens = _tokens(query)
    rows = _fetch_recent_observations(session_id, limit * 3)
    candidates: list[Evidence] = []
    for record in rows:
        content = str(record["content"])
        keyword_score = _lexical_score(tokens, content)
        if keyword_score <= 0.0:
            continue
        candidates.append(
            _evidence(
                source="recent_observations",
                source_id=str(record["id"]),
                content=content,
                semantic_score=0.0,
                keyword_score=keyword_score,
                recency=_recency_score(record),
                confidence=1.0,
                status="active",
                record=record,
            )
        )
    return candidates


def _merge_duplicates(candidates: list[Evidence]) -> list[Evidence]:
    merged: dict[str, Evidence] = {}
    for candidate in candidates:
        key = str(candidate["source_id"])
        existing = merged.get(key)
        if existing is None:
            candidate["sources"] = [candidate["source"]]
            merged[key] = candidate
            continue
        existing["semantic_score"] = max(
            _float(existing["semantic_score"]),
            _float(candidate["semantic_score"]),
        )
        existing["keyword_score"] = max(
            _float(existing["keyword_score"]),
            _float(candidate["keyword_score"]),
        )
        existing["recency_score"] = max(
            _float(existing["recency_score"]),
            _float(candidate["recency_score"]),
        )
        existing["confidence"] = max(
            _float(existing["confidence"]),
            _float(candidate["confidence"]),
        )
        existing["score"] = _combined_score(existing)
        existing_sources = _string_list(existing.get("sources"))
        source = str(candidate["source"])
        if source not in existing_sources:
            existing_sources.append(source)
        existing["sources"] = existing_sources
    return list(merged.values())


def _enrich_lifecycle(
    candidates: list[Evidence],
    workspace_id: str,
    *,
    query: str | None = None,
    historical: bool = False,
) -> list[Evidence]:
    """Attach lifecycle diagnostics and exclude archived/forgotten candidates."""
    enriched: list[Evidence] = []
    for candidate in candidates:
        source_type = _lifecycle_source_type(str(candidate.get("source", "")))
        if source_type is None:
            enriched.append(candidate)
            continue
        try:
            raw_record = candidate.get("record")
            lifecycle = lifecycle_for_retrieval(
                source_type,
                str(candidate["source_id"]),
                workspace_id,
                record=raw_record if isinstance(raw_record, dict) else None,
                query=query,
                historical=historical,
            )
        except ValueError:
            continue
        if not bool(lifecycle.get("eligible", True)):
            continue
        candidate["memory_state"] = lifecycle
        candidate["freshness_score"] = lifecycle.get("freshness_score", 0.0)
        candidate["trust_score"] = lifecycle.get("trust_score", 0.0)
        candidate["authority"] = {
            "class": lifecycle.get("source_authority", "unknown"),
            "score": _authority_score(str(lifecycle.get("source_authority", "unknown"))),
        }
        candidate["provenance"] = _provenance_for_candidate(source_type, candidate)
        candidate["prompt_eligible"] = True
        enriched.append(candidate)
    return enriched


def _lifecycle_source_type(source: str) -> str | None:
    return retrieval_source_type(source)


def _provenance_for_candidate(source_type: str, candidate: Evidence) -> dict[str, object]:
    record = candidate.get("record")
    record = record if isinstance(record, dict) else {}
    source_observation_ids: list[str] = []
    evidence_source_ids: list[str] = []
    source_descriptors: list[dict[str, object]] = []
    raw_source = record.get("source_observation_id")
    if isinstance(raw_source, str) and raw_source:
        source_observation_ids.append(raw_source)
    workspace_id = str(record.get("workspace_id") or "")
    candidate_id = str(candidate.get("source_id") or "")
    target_type = {
        "atomic_facts": "atomic_fact",
        "graph_edges": "graph_edge",
        "reflections": "reflection",
        "foresight_records": "foresight",
    }.get(source_type)
    linked_sources: list[dict[str, object]] = []
    if workspace_id and candidate_id and target_type is not None:
        try:
            for link in list_active_evidence(target_type, candidate_id, workspace_id=workspace_id):
                source = link.get("source")
                if isinstance(source, dict):
                    linked_sources.append(source)
        except (ValueError, KeyError):
            linked_sources = []
    elif workspace_id and candidate_id and source_type == "document_chunks":
        with repository_connection() as connection:
            rows = connection.execute(
                "SELECT id FROM evidence_sources WHERE workspace_id = ? "
                "AND source_type = 'document_chunk' AND source_id = ? "
                "AND retracted_at IS NULL",
                (workspace_id, candidate_id),
            ).fetchall()
        for row in rows:
            try:
                linked_sources.append(resolve_source(str(row[0]), workspace_id=workspace_id))
            except ValueError:
                continue
    for source in linked_sources[:12]:
        evidence_id = str(source.get("id") or "")
        if evidence_id:
            evidence_source_ids.append(evidence_id)
        if source.get("source_type") == "conversation_observation":
            provenance = source.get("provenance")
            observation_id = str(source.get("source_id") or "")
            if observation_id:
                source_observation_ids.append(observation_id)
        else:
            provenance = source.get("provenance")
        descriptor: dict[str, object] = {
            key: source[key]
            for key in (
                "id",
                "source_id",
                "source_type",
                "project_id",
                "namespace",
                "knowledge_base_id",
                "authority",
                "observed_at",
            )
            if source.get(key) is not None
        }
        if isinstance(provenance, dict):
            descriptor["provenance"] = provenance
        source_descriptors.append(descriptor)
    if source_type == "document_chunks" and not source_descriptors:
        document_provenance = candidate.get("provenance")
        descriptor = {
            "source_id": candidate_id,
            "source_type": "document_chunk",
        }
        for key in ("knowledge_base_id", "document_id", "filename", "page_start", "page_end"):
            if candidate.get(key) is not None:
                descriptor[key] = candidate[key]
        if isinstance(document_provenance, dict):
            descriptor["provenance"] = document_provenance
        source_descriptors.append(descriptor)
    return {
        "record_type": source_type,
        "record_id": str(candidate["source_id"]),
        "source_observation_ids": list(dict.fromkeys(source_observation_ids)),
        "evidence_source_ids": list(dict.fromkeys(evidence_source_ids)),
        "sources": source_descriptors,
    }


def _authority_score(authority: str) -> float:
    return {
        "direct_observation": 0.95,
        "structured_derivation": 0.82,
        "temporal_derivation": 0.78,
        "synthesized_reflection": 0.68,
        "community_synthesis": 0.62,
        "promoted_working_memory": 0.72,
        "untrusted_observation": 0.25,
        "unknown": 0.4,
    }.get(authority, 0.4)


def _evidence(
    *,
    source: str,
    source_id: str,
    content: str,
    semantic_score: float,
    keyword_score: float,
    recency: float,
    confidence: float,
    status: str,
    record: dict[str, object],
) -> Evidence:
    evidence = {
        "source": source,
        "source_id": source_id,
        "content": content,
        "semantic_score": semantic_score,
        "keyword_score": keyword_score,
        "recency_score": recency,
        "confidence": confidence,
        "status": status,
        "record": dict(record),
    }
    evidence["score"] = _combined_score(evidence)
    return evidence


def _combined_score(evidence: Evidence) -> float:
    status = str(evidence.get("status", "active"))
    status_score = ACTIVE_STATUS_SCORE.get(status, 0.6)
    return (
        (_float(evidence.get("semantic_score")) * 0.4)
        + (_float(evidence.get("keyword_score")) * 0.3)
        + (_float(evidence.get("recency_score")) * 0.1)
        + (_float(evidence.get("confidence")) * 0.15)
        + (status_score * 0.05)
    )


def _rank_candidates(candidates: list[Evidence]) -> list[Evidence]:
    """Rank Quick candidates: RRF fusion, structured-first weighting, decay, recall gate.

    Reciprocal rank fusion combines the semantic and keyword rankings by position
    (scale-independent), a source weight biases validated derived memory above the raw
    observation log, recency applies a mild decay, and a relative recall gate drops weak
    tail matches so noise is not injected (paper, Quick Mode).
    """
    if not candidates:
        return []
    fusion = _reciprocal_rank_fusion(candidates)
    for candidate in candidates:
        base = fusion.get(str(candidate["source_id"]), 0.0)
        source_weight = SOURCE_WEIGHT.get(str(candidate["source"]), DEFAULT_SOURCE_WEIGHT)
        decay = 0.5 + 0.5 * _float(candidate.get("recency_score"))
        status = ACTIVE_STATUS_SCORE.get(str(candidate.get("status", "active")), 0.6)
        candidate["score"] = base * source_weight * decay * status
    ranked = sorted(candidates, key=lambda item: (-_float(item["score"]), str(item["source_id"])))
    return _recall_gate(ranked)


def _reciprocal_rank_fusion(candidates: list[Evidence]) -> dict[str, float]:
    """Fuse the semantic and keyword rankings into one score per candidate via RRF."""
    scores: dict[str, float] = {}
    for signal in ("semantic_score", "keyword_score"):
        scored = [
            (_float(item.get(signal)), item)
            for item in candidates
            if _float(item.get(signal)) > 0.0
        ]
        scored.sort(key=lambda pair: -pair[0])
        for rank, (_signal_score, candidate) in enumerate(scored):
            source_id = str(candidate["source_id"])
            scores[source_id] = scores.get(source_id, 0.0) + 1.0 / (RRF_K + rank)
    return scores


def _recall_gate(ranked: list[Evidence]) -> list[Evidence]:
    """Drop tail candidates scoring far below the best match; keep everything if uniform."""
    if not ranked:
        return ranked
    top = _float(ranked[0]["score"])
    if top <= 0.0:
        return ranked
    floor = top * RECALL_GATE_FRACTION
    return [candidate for candidate in ranked if _float(candidate["score"]) >= floor]


def _fetch_record(table: str, record_id: str, workspace_id: str) -> dict[str, object] | None:
    if table not in {"observations", "reflections"}:
        return None
    with repository_connection() as connection:
        row = connection.execute(
            f"SELECT * FROM {table} WHERE id = ? AND workspace_id = ?",  # nosec B608
            (record_id, workspace_id),
        ).fetchone()
    return None if row is None else dict(row)


def _semantic_record_is_active(
    table: str, record: dict[str, object], *, historical: bool = False
) -> bool:
    """Keep observations (immutable evidence); drop non-active reflections.

    Stale, invalidated, or superseded reflections must stop controlling current
    reasoning (paper, Reflection Validity Update). The vector index still points at
    them, so they are filtered here rather than being surfaced with a soft penalty.
    """
    return retrieval_lifecycle_eligible(table, record=record, historical=historical)


def _fetch_foresight_rows(
    session_id: str | None, workspace_id: str, *, historical: bool = False
) -> list[dict[str, object]]:
    with repository_connection() as connection:
        if session_id is None:
            status_clause = "" if historical else "AND status IN (?, ?)"
            parameters: tuple[object, ...] = (workspace_id,)
            if not historical:
                parameters += ("active", "pending")
            rows = connection.execute(
                f"""
                SELECT * FROM foresight_records
                WHERE workspace_id = ? {status_clause}
                ORDER BY created_at DESC
                """,  # nosec B608
                parameters,
            ).fetchall()
        else:
            status_clause = "" if historical else "AND foresight_records.status IN (?, ?)"
            parameters = (workspace_id, session_id)
            if not historical:
                parameters = (workspace_id, "active", "pending", session_id)
            rows = connection.execute(
                f"""
                SELECT foresight_records.*
                FROM foresight_records
                JOIN observations ON observations.id = foresight_records.source_observation_id
                WHERE foresight_records.workspace_id = ?
                  {status_clause} AND observations.session_id = ?
                ORDER BY foresight_records.created_at DESC
                """,  # nosec B608
                parameters,
            ).fetchall()
    return [dict(row) for row in rows]


def _fetch_recent_observations(session_id: str, limit: int) -> list[dict[str, object]]:
    with repository_connection() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM observations
            WHERE session_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def _record_content(table: str, record: dict[str, object]) -> str:
    if table == "observations":
        return str(record["content"])
    if table == "reflections":
        return str(record["content"])
    return ""


def _fact_content(record: dict[str, object]) -> str:
    return f"{record['subject']} {record['predicate']} {record['object']}"


def _session_matches(record: dict[str, object], session_id: str | None) -> bool:
    return session_id is None or record.get("session_id") == session_id


def _fact_session_matches(record: dict[str, object], session_id: str | None) -> bool:
    if session_id is None:
        return True
    source_observation_id = str(record["source_observation_id"])
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT session_id FROM observations WHERE id = ?",
            (source_observation_id,),
        ).fetchone()
    return row is not None and row["session_id"] == session_id


def _normalized_keyword_score(record: dict[str, object]) -> float:
    return min(1.0, _float(record.get("score")) / 10.0)


def _recency_score(record: dict[str, object], *, as_of: datetime | None = None) -> float:
    """Return exponential freshness decay instead of a created-at presence flag.

    A 30-day half-life keeps recent context useful while allowing older, still
    authoritative memories to remain retrievable. Missing or malformed timestamps
    are treated as having no freshness signal; trust is assessed separately.
    """
    raw_timestamp = record.get("updated_at") or record.get("created_at")
    if not isinstance(raw_timestamp, str) or not raw_timestamp.strip():
        return 0.0
    try:
        timestamp = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    reference = as_of or datetime.now(UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    age_seconds = max(0.0, (reference - timestamp).total_seconds())
    return max(0.0, min(1.0, math.exp(-math.log(2.0) * age_seconds / RECENCY_HALF_LIFE_SECONDS)))


def _confidence(record: dict[str, object]) -> float:
    return _float(record.get("confidence", 1.0), 1.0)


def _lexical_score(query_tokens: set[str], content: str) -> float:
    content_tokens = _tokens(content)
    if not query_tokens or not content_tokens:
        return 0.0
    return len(query_tokens & content_tokens) / len(query_tokens)


def _tokens(value: str) -> set[str]:
    stopwords = {"a", "about", "did", "i", "is", "my", "the", "what", "when"}
    return {
        token
        for token in TOKEN_PATTERN.findall(value.casefold())
        if len(token) > 1 and token not in stopwords
    }


def _is_foresight_query(query: str) -> bool:
    normalized = query.casefold()
    return any(marker in normalized for marker in FORESIGHT_QUERY_MARKERS)


def _float(value: object, default: float = 0.0) -> float:
    if isinstance(value, int | float):
        return float(value)
    return default


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
