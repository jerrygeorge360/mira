"""Contradiction versus supersession semantics for atomic memory changes.

Ownership: Jerry.
Related issue: ISSUE-027.
Architecture area: slow path.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from core.db.evidence import link_evidence, list_active_evidence
from core.db.repositories import repository_connection
from core.memory.graph import create_graph_edge, create_graph_node

MemoryChange = dict[str, object]
AtomicFactRecord = dict[str, object]

# An unresolved contradiction lowers confidence in both conflicting claims without
# retiring either; retrieval and the resolver use the reduced confidence to weigh them.
CONTRADICTION_CONFIDENCE_FACTOR = 0.7

TRANSITION_MARKERS = frozenset(
    {
        "actually",
        "switched from",
        "switch from",
        "moved from",
        "migrate from",
        "migrated from",
        "changed from",
        "correction",
        "used to",
        "previously",
        "now",
        "no longer",
        "instead",
    }
)

MULTI_VALUE_PREDICATES = frozenset(
    {
        "has",
        "include",
        "includes",
        "provides",
        "store",
        "stores",
        "support",
        "supports",
        "track",
        "tracks",
        "use",
        "uses",
    }
)


def detect_memory_change(
    new_fact_id: str,
    candidate_prior_fact_ids: list[str],
) -> list[MemoryChange]:
    """Classify prior facts as superseded or contradicted by a new fact.

    This is the deterministic fast path for same-canonical-subject candidates; the
    cross-subject hard cases are handled by the LLM verifier in the slow path.
    """
    new_fact = _fetch_atomic_fact(new_fact_id)
    changes: list[MemoryChange] = []
    for prior_fact_id in candidate_prior_fact_ids:
        prior_fact = _fetch_atomic_fact(prior_fact_id)
        if not _facts_are_comparable(prior_fact, new_fact):
            continue
        if _normalize(str(prior_fact["object"])) == _normalize(str(new_fact["object"])):
            continue
        relation = (
            "SUPERSEDED_BY" if _has_explicit_transition(prior_fact, new_fact) else "CONTRADICTS"
        )
        changes.append(
            {
                "relation": relation,
                "source_id": prior_fact_id,
                "target_id": new_fact_id,
                "confidence": _relation_confidence(prior_fact, new_fact, relation),
                "evidence": _source_observations(prior_fact, new_fact),
                "evidence_source_ids": _source_ids(prior_fact, new_fact),
                "reason": _change_reason(prior_fact, new_fact, relation),
            }
        )
    return changes


def apply_supersession(
    old_fact_id: str,
    new_fact_id: str,
    evidence: list[str],
    *,
    evidence_source_ids: list[str] | None = None,
) -> str:
    """Record acknowledged belief evolution as a SUPERSEDED_BY graph edge."""
    old_fact = _fetch_atomic_fact(old_fact_id)
    new_fact = _fetch_atomic_fact(new_fact_id)
    if _has_document_source(old_fact, new_fact) and (
        not _facts_are_comparable(old_fact, new_fact)
        or not _has_explicit_transition(old_fact, new_fact)
    ):
        raise ValueError("document supersession requires compatible claims and explicit transition")
    edge_id = _existing_fact_relation_edge(old_fact, new_fact, "SUPERSEDED_BY")
    if edge_id is None:
        edge_id = _create_fact_relation_edge(
            old_fact, new_fact, "SUPERSEDED_BY", evidence, evidence_source_ids
        )
    else:
        _link_edge_evidence(edge_id, old_fact, new_fact, evidence_source_ids)
    _close_old_fact(
        old_fact_id,
        valid_until=(str(new_fact["valid_from"]) if new_fact.get("valid_from") else None)
        if _has_document_source(old_fact, new_fact)
        else datetime.now(timezone.utc).isoformat(),  # noqa: UP017
    )
    return edge_id


def apply_contradiction(
    fact_a_id: str,
    fact_b_id: str,
    evidence: list[str],
    *,
    evidence_source_ids: list[str] | None = None,
) -> str:
    """Record unresolved incompatible claims as a CONTRADICTS graph edge.

    Both claims stay active -- no belief is retired -- but the unresolved conflict
    lowers confidence in each, so retrieval can prefer better-supported memory and the
    query-time resolver can weigh them (paper Design Requirement 5).
    """
    fact_a = _fetch_atomic_fact(fact_a_id)
    fact_b = _fetch_atomic_fact(fact_b_id)
    if _has_document_source(fact_a, fact_b) and not _facts_are_comparable(fact_a, fact_b):
        raise ValueError("document contradiction requires compatible claims and scope")
    edge_id = _existing_fact_relation_edge(fact_a, fact_b, "CONTRADICTS")
    if edge_id is None:
        edge_id = _create_fact_relation_edge(
            fact_a, fact_b, "CONTRADICTS", evidence, evidence_source_ids
        )
        _reduce_fact_confidence(fact_a_id, CONTRADICTION_CONFIDENCE_FACTOR)
        _reduce_fact_confidence(fact_b_id, CONTRADICTION_CONFIDENCE_FACTOR)
    else:
        _link_edge_evidence(edge_id, fact_a, fact_b, evidence_source_ids)
    return edge_id


def resolve_retrieved_contradictions(
    fact_ids: list[str],
    *,
    query: str | None = None,
) -> list[dict[str, object]]:
    """Emit unresolved-conflict notes for retrieved facts under an active CONTRADICTS edge.

    The prompt builder injects these so the model surfaces the conflict -- and, for a
    Quick answer, can prefer the most recent value while flagging it -- instead of
    asserting one contested value as settled. Relational Mode traverses the edge
    directly and already gets the fuller picture; this makes the conflict visible in
    the other modes too.
    """
    notes: list[dict[str, object]] = []
    seen: set[frozenset[str]] = set()
    for fact_id in fact_ids:
        for other_id in _contradicting_fact_ids(fact_id):
            pair = frozenset({fact_id, other_id})
            if pair in seen:
                continue
            seen.add(pair)
            if query is not None and not _conflict_relevant_to_query(query, fact_id, other_id):
                continue
            note = _contradiction_note(fact_id, other_id)
            if note is not None:
                notes.append(note)
    return notes


def _conflict_relevant_to_query(query: str, fact_a_id: str, fact_b_id: str) -> bool:
    normalized_query = _normalize(query)
    if any(
        marker in normalized_query
        for marker in (
            "conflict",
            "contradict",
            "contradiction",
            "inconsistent",
            "current",
            "now",
            "which one",
            "what changed",
            "use now",
            "using now",
        )
    ):
        return True
    try:
        fact_a = _fetch_atomic_fact(fact_a_id)
        fact_b = _fetch_atomic_fact(fact_b_id)
    except ValueError:
        return False
    query_tokens = _meaningful_tokens(normalized_query)
    if not query_tokens:
        return False
    subject_tokens = _meaningful_tokens(f"{fact_a['subject']} {fact_b['subject']}")
    predicate_tokens = _meaningful_tokens(f"{fact_a['predicate']} {fact_b['predicate']}")
    object_tokens = _meaningful_tokens(f"{fact_a['object']} {fact_b['object']}")
    property_overlap = bool(query_tokens & (subject_tokens | predicate_tokens))
    value_overlap = bool(query_tokens & object_tokens)
    return property_overlap or value_overlap


def _contradicting_fact_ids(fact_id: str) -> list[str]:
    fact = _fetch_atomic_fact(fact_id)
    workspace_id = str(fact["workspace_id"])
    with repository_connection() as connection:
        node = connection.execute(
            "SELECT id FROM graph_nodes "
            "WHERE workspace_id = ? AND node_type = 'atomic_fact' "
            "AND source_table = 'atomic_facts' AND source_id = ?",
            (workspace_id, fact_id),
        ).fetchone()
        if node is None:
            return []
        node_id = str(node["id"])
        edges = connection.execute(
            "SELECT source_node_id, target_node_id FROM graph_edges "
            "WHERE workspace_id = ? AND edge_type = 'CONTRADICTS' "
            "AND invalidated_at IS NULL "
            "AND (source_node_id = ? OR target_node_id = ?)",
            (workspace_id, node_id, node_id),
        ).fetchall()
        other_node_ids = [
            str(edge["target_node_id"])
            if str(edge["source_node_id"]) == node_id
            else str(edge["source_node_id"])
            for edge in edges
        ]
        if not other_node_ids:
            return []
        placeholders = ", ".join("?" for _ in other_node_ids)
        rows = connection.execute(
            "SELECT source_id FROM graph_nodes "  # nosec B608
            f"WHERE workspace_id = ? AND id IN ({placeholders}) AND node_type = 'atomic_fact'",
            (workspace_id, *other_node_ids),
        ).fetchall()
    return [str(row["source_id"]) for row in rows if row["source_id"]]


def _contradiction_note(fact_a_id: str, fact_b_id: str) -> dict[str, object] | None:
    try:
        fact_a = _fetch_atomic_fact(fact_a_id)
        fact_b = _fetch_atomic_fact(fact_b_id)
    except ValueError:
        return None
    older, newer = sorted((fact_a, fact_b), key=lambda fact: str(fact.get("created_at", "")))
    document_conflict = _has_document_source(fact_a, fact_b)
    resolution = (
        "Do not choose by upload time; assess authority, effective dates and applicability."
        if document_conflict
        else (
            "Surface the conflict; if forced to choose, prefer the later value "
            "but say it is unresolved."
        )
    )
    content = (
        "Unresolved conflict in memory: "
        f"'{older['subject']} {older['predicate']} {older['object']}' (earlier) "
        f"vs '{newer['subject']} {newer['predicate']} {newer['object']}' (later). "
        f"{resolution}"
    )
    note_id = f"contradiction:{fact_a_id}:{fact_b_id}"
    return {"source": "contradiction", "id": note_id, "source_id": note_id, "content": content}


def _create_fact_relation_edge(
    source_fact: AtomicFactRecord,
    target_fact: AtomicFactRecord,
    edge_type: str,
    evidence: list[str],
    evidence_source_ids: list[str] | None = None,
) -> str:
    source_ids = (
        evidence_source_ids
        if evidence_source_ids is not None
        else _source_ids(source_fact, target_fact)
    )
    if not evidence and not source_ids:
        raise ValueError("evidence must not be empty")
    if _has_document_source(source_fact, target_fact):
        source_support = set(_source_ids(source_fact))
        target_support = set(_source_ids(target_fact))
        supplied = set(source_ids)
        if (
            not supplied <= source_support | target_support
            or not supplied & source_support
            or not supplied & target_support
        ):
            raise ValueError("relation evidence must support both document claims")
    source_node_id = _graph_node_for_fact(source_fact)
    target_node_id = _graph_node_for_fact(target_fact)
    workspace_id = str(source_fact["workspace_id"])
    metadata: dict[str, object] = {}
    if edge_type == "SUPERSEDED_BY":
        metadata["supersession_rollback"] = {
            "fact_id": str(source_fact["id"]),
            "status": str(source_fact.get("status") or "active"),
            "valid_until": source_fact.get("valid_until"),
        }
    elif edge_type == "CONTRADICTS":
        metadata["contradiction_rollback"] = {
            "fact_ids": [str(source_fact["id"]), str(target_fact["id"])],
            "confidence_factor": CONTRADICTION_CONFIDENCE_FACTOR,
        }
    return create_graph_edge(
        source_node_id,
        target_node_id,
        edge_type,
        confidence=_minimum_confidence(source_fact, target_fact),
        source_observations=evidence,
        workspace_id=workspace_id,
        evidence_source_ids=source_ids,
        metadata=metadata,
    )


def _existing_fact_relation_edge(
    left: AtomicFactRecord, right: AtomicFactRecord, edge_type: str
) -> str | None:
    left_node = _graph_node_for_fact(left)
    right_node = _graph_node_for_fact(right)
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT id FROM graph_edges WHERE workspace_id = ? AND edge_type = ? "
            "AND invalidated_at IS NULL AND ((source_node_id = ? AND target_node_id = ?) "
            "OR (? = 'CONTRADICTS' AND source_node_id = ? AND target_node_id = ?)) "
            "ORDER BY created_at LIMIT 1",
            (
                left["workspace_id"],
                edge_type,
                left_node,
                right_node,
                edge_type,
                right_node,
                left_node,
            ),
        ).fetchone()
    return None if row is None else str(row[0])


def _link_edge_evidence(
    edge_id: str,
    left: AtomicFactRecord,
    right: AtomicFactRecord,
    supplied_source_ids: list[str] | None,
) -> None:
    source_ids = supplied_source_ids or _source_ids(left, right)
    for source_id in source_ids:
        link_evidence(
            source_id,
            "graph_edge",
            edge_id,
            workspace_id=str(left["workspace_id"]),
            confidence=_minimum_confidence(left, right),
        )


def _graph_node_for_fact(fact: AtomicFactRecord) -> str:
    fact_id = str(fact["id"])
    workspace_id = str(fact["workspace_id"])
    existing_node_id = _existing_fact_node_id(fact_id, workspace_id)
    if existing_node_id is not None:
        return existing_node_id
    return create_graph_node(
        node_type="atomic_fact",
        label=_fact_label(fact),
        source_table="atomic_facts",
        source_id=fact_id,
        workspace_id=workspace_id,
    )


def _existing_fact_node_id(fact_id: str, workspace_id: str) -> str | None:
    with repository_connection() as connection:
        row = connection.execute(
            """
            SELECT id
            FROM graph_nodes
            WHERE workspace_id = ? AND node_type = ? AND source_table = ? AND source_id = ?
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (workspace_id, "atomic_fact", "atomic_facts", fact_id),
        ).fetchone()
    return None if row is None else str(row["id"])


def _fetch_atomic_fact(fact_id: str) -> AtomicFactRecord:
    with repository_connection() as connection:
        row = connection.execute("SELECT * FROM atomic_facts WHERE id = ?", (fact_id,)).fetchone()
    if row is None:
        raise ValueError(f"Atomic fact not found: {fact_id}")
    return dict(row)


def _fetch_observation_content(observation_id: str) -> str:
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT content FROM observations WHERE id = ?",
            (observation_id,),
        ).fetchone()
    if row is None:
        raise ValueError(f"Observation not found: {observation_id}")
    return str(row["content"])


def _reduce_fact_confidence(fact_id: str, factor: float) -> None:
    """Scale a fact's confidence down (no status change) after a contradiction."""
    with repository_connection() as connection:
        connection.execute(
            "UPDATE atomic_facts SET confidence = confidence * ? WHERE id = ?",
            (factor, fact_id),
        )


def _close_old_fact(fact_id: str, *, valid_until: str | None) -> None:
    with repository_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE atomic_facts
            SET status = ?, valid_until = COALESCE(?, valid_until)
            WHERE id = ?
            """,
            ("superseded", valid_until, fact_id),
        )
    if cursor.rowcount == 0:
        raise ValueError(f"Atomic fact not found: {fact_id}")


def _facts_are_comparable(
    prior_fact: AtomicFactRecord,
    new_fact: AtomicFactRecord,
) -> bool:
    if prior_fact["workspace_id"] != new_fact["workspace_id"]:
        return False
    prior_scopes = _fact_scopes(prior_fact)
    new_scopes = _fact_scopes(new_fact)
    if len(prior_scopes) != 1 or prior_scopes != new_scopes:
        return False
    prior_document_kbs = _document_knowledge_base_ids(prior_fact)
    new_document_kbs = _document_knowledge_base_ids(new_fact)
    if prior_document_kbs and new_document_kbs and prior_document_kbs != new_document_kbs:
        return False
    if not _cross_source_scope_is_attached(prior_fact, new_fact):
        return False
    if _temporal_intervals_are_disjoint(prior_fact, new_fact) and not _has_explicit_transition(
        prior_fact, new_fact
    ):
        return False
    if _predicate_allows_multiple_values(prior_fact) or _predicate_allows_multiple_values(new_fact):
        return _has_explicit_transition(prior_fact, new_fact)
    return _fact_comparison_key(prior_fact) == _fact_comparison_key(new_fact)


def _cross_source_scope_is_attached(
    prior_fact: AtomicFactRecord, new_fact: AtomicFactRecord
) -> bool:
    """Require the conversation session to explicitly attach each compared KB."""
    prior_links = _fact_evidence(prior_fact)
    new_links = _fact_evidence(new_fact)
    prior_conversations = _evidence_sources_of_type(prior_links, "conversation_observation")
    new_conversations = _evidence_sources_of_type(new_links, "conversation_observation")
    prior_documents = _evidence_sources_of_type(prior_links, "document_chunk")
    new_documents = _evidence_sources_of_type(new_links, "document_chunk")
    if not prior_links and prior_fact.get("source_observation_id"):
        legacy = _conversation_source_for_observation(
            str(prior_fact["source_observation_id"]), str(prior_fact["workspace_id"])
        )
        if legacy is not None:
            prior_conversations.append(legacy)
    if not new_links and new_fact.get("source_observation_id"):
        legacy = _conversation_source_for_observation(
            str(new_fact["source_observation_id"]), str(new_fact["workspace_id"])
        )
        if legacy is not None:
            new_conversations.append(legacy)
    return all(
        _session_attached_to_document(conversation, document, str(prior_fact["workspace_id"]))
        for conversations, documents in (
            (prior_conversations, new_documents),
            (new_conversations, prior_documents),
        )
        for conversation in conversations
        for document in documents
    )


def _conversation_source_for_observation(
    observation_id: str, workspace_id: str
) -> dict[str, object] | None:
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT session_id FROM observations WHERE id = ? AND workspace_id = ?",
            (observation_id, workspace_id),
        ).fetchone()
    if row is None:
        return None
    return {"source_type": "conversation_observation", "provenance": {"session_id": row[0]}}


def _session_attached_to_document(
    conversation: dict[str, object], document: dict[str, object], workspace_id: str
) -> bool:
    provenance = conversation.get("provenance")
    if not isinstance(provenance, dict):
        return False
    session_id = provenance.get("session_id")
    knowledge_base_id = document.get("knowledge_base_id")
    if not session_id or not knowledge_base_id:
        return False
    with repository_connection() as connection:
        return (
            connection.execute(
                "SELECT 1 FROM session_knowledge_base_attachments AS a "
                "JOIN sessions AS s ON s.id = a.session_id AND s.workspace_id = a.workspace_id "
                "JOIN knowledge_bases AS k ON k.id = a.knowledge_base_id "
                "AND k.workspace_id = a.workspace_id "
                "WHERE a.workspace_id = ? AND a.session_id = ? AND a.knowledge_base_id = ? "
                "AND s.status != 'deleted' AND k.status = 'active'",
                (workspace_id, str(session_id), str(knowledge_base_id)),
            ).fetchone()
            is not None
        )


def _has_explicit_transition(
    prior_fact: AtomicFactRecord,
    new_fact: AtomicFactRecord,
) -> bool:
    if _new_source_authority(new_fact) < _new_source_authority(prior_fact):
        return False
    if (
        prior_fact.get("valid_from")
        and new_fact.get("valid_from")
        and str(new_fact["valid_from"]) < str(prior_fact["valid_from"])
    ):
        return False
    old_object = _normalize(str(prior_fact["object"]))
    new_object = _normalize(str(new_fact["object"]))
    for evidence_text in _fact_source_texts(new_fact):
        normalized_text = _normalize(evidence_text)
        if not any(marker in normalized_text for marker in TRANSITION_MARKERS):
            continue
        if old_object in normalized_text and new_object in normalized_text:
            return True
        if (
            _has_correction_marker(normalized_text)
            and _fact_comparison_key(prior_fact) == _fact_comparison_key(new_fact)
            and not _has_document_source(prior_fact, new_fact)
        ):
            return True
    return False


def _fact_comparison_key(fact: AtomicFactRecord) -> tuple[str, str]:
    """Pair facts by canonical subject and canonical predicate/property.

    A shared subject alone is not enough for contradiction detection. A project can use
    SQLite, expose traces, support MCP, and target a benchmark at the same time. Those
    are separate properties, not competing values. Facts predating the canonical
    registry fall back to normalized raw text.
    """
    canonical_subject_id = fact.get("canonical_subject_id")
    canonical_predicate_id = fact.get("canonical_predicate_id")
    predicate_key = (
        f"cp:{canonical_predicate_id}"
        if canonical_predicate_id
        else _normalize(str(fact["predicate"]))
    )
    if canonical_subject_id:
        return (f"cs:{canonical_subject_id}", predicate_key)
    return (_normalize(str(fact["subject"])), predicate_key)


def _predicate_allows_multiple_values(fact: AtomicFactRecord) -> bool:
    """Return true for broad additive predicates that do not imply exclusivity."""
    return _normalize(str(fact["predicate"])) in MULTI_VALUE_PREDICATES


def _has_correction_marker(normalized_text: str) -> bool:
    return any(
        marker in normalized_text
        for marker in ("actually", "correction", "instead", "no longer", "not ")
    )


def _source_observations(
    prior_fact: AtomicFactRecord,
    new_fact: AtomicFactRecord,
) -> list[str]:
    return list(
        dict.fromkeys(
            str(observation_id)
            for observation_id in (
                prior_fact.get("source_observation_id"),
                new_fact.get("source_observation_id"),
            )
            if observation_id
        )
    )


def _fact_evidence(fact: AtomicFactRecord) -> list[dict[str, object]]:
    return list_active_evidence(
        "atomic_fact", str(fact["id"]), workspace_id=str(fact["workspace_id"])
    )


def _source_ids(*facts: AtomicFactRecord) -> list[str]:
    return list(
        dict.fromkeys(str(link["source_id"]) for fact in facts for link in _fact_evidence(fact))
    )


def _evidence_source(link: dict[str, object]) -> dict[str, object] | None:
    source = link.get("source")
    return source if isinstance(source, dict) else None


def _evidence_sources_of_type(
    links: list[dict[str, object]], source_type: str
) -> list[dict[str, object]]:
    sources: list[dict[str, object]] = []
    for link in links:
        source = _evidence_source(link)
        if source is not None and source.get("source_type") == source_type:
            sources.append(source)
    return sources


def _fact_scopes(fact: AtomicFactRecord) -> set[tuple[object, object]]:
    links = _fact_evidence(fact)
    if not links and fact.get("source_observation_id"):
        return {(None, None)}
    return {
        (
            source.get("project_id"),
            source.get("namespace"),
        )
        for link in links
        if (source := _evidence_source(link)) is not None
    }


def _document_knowledge_base_ids(fact: AtomicFactRecord) -> set[str]:
    return {
        str(source["knowledge_base_id"])
        for link in _fact_evidence(fact)
        if (source := _evidence_source(link)) is not None
        and source.get("source_type") == "document_chunk"
        and source.get("knowledge_base_id")
    }


def _has_document_source(*facts: AtomicFactRecord) -> bool:
    return any(
        source.get("source_type") == "document_chunk"
        for fact in facts
        for link in _fact_evidence(fact)
        if (source := _evidence_source(link)) is not None
    )


def _fact_source_texts(fact: AtomicFactRecord) -> list[str]:
    links = _fact_evidence(fact)
    if links:
        return [
            str(source.get("content", ""))
            for link in links
            if (source := _evidence_source(link)) is not None
        ]
    observation_id = fact.get("source_observation_id")
    return [_fetch_observation_content(str(observation_id))] if observation_id else []


def _new_source_authority(fact: AtomicFactRecord) -> float:
    links = _fact_evidence(fact)
    authorities = []
    for link in links:
        source = _evidence_source(link)
        authority = source.get("authority") if source is not None else None
        if isinstance(authority, int | float):
            authorities.append(float(authority))
    return max(authorities, default=1.0)


def _temporal_intervals_are_disjoint(
    prior_fact: AtomicFactRecord, new_fact: AtomicFactRecord
) -> bool:
    prior_end = prior_fact.get("valid_until")
    new_start = new_fact.get("valid_from")
    new_end = new_fact.get("valid_until")
    prior_start = prior_fact.get("valid_from")
    return bool(
        (prior_end and new_start and str(prior_end) < str(new_start))
        or (new_end and prior_start and str(new_end) < str(prior_start))
    )


def _relation_confidence(
    prior_fact: AtomicFactRecord,
    new_fact: AtomicFactRecord,
    relation: str,
) -> float:
    base_confidence = _minimum_confidence(prior_fact, new_fact)
    if relation == "SUPERSEDED_BY":
        return base_confidence
    return min(base_confidence, 0.85)


def _minimum_confidence(
    source_fact: AtomicFactRecord,
    target_fact: AtomicFactRecord,
) -> float:
    return min(_confidence(source_fact["confidence"]), _confidence(target_fact["confidence"]))


def _confidence(value: object) -> float:
    if isinstance(value, int | float | str):
        return float(value)
    raise ValueError(f"Invalid fact confidence: {value!r}")


def _change_reason(
    prior_fact: AtomicFactRecord,
    new_fact: AtomicFactRecord,
    relation: str,
) -> str:
    if relation == "SUPERSEDED_BY":
        return (
            "New evidence acknowledges a transition from "
            f"{prior_fact['object']} to {new_fact['object']}."
        )
    return (
        "Facts share subject and predicate but assert incompatible objects "
        "without acknowledged transition language."
    )


def _fact_label(fact: AtomicFactRecord) -> str:
    return f"{fact['subject']} {fact['predicate']} {fact['object']}"


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def _meaningful_tokens(value: str) -> set[str]:
    value = _normalize(value)
    stopwords = {
        "a",
        "about",
        "am",
        "an",
        "and",
        "are",
        "do",
        "does",
        "for",
        "i",
        "in",
        "is",
        "it",
        "me",
        "my",
        "of",
        "on",
        "or",
        "our",
        "the",
        "to",
        "use",
        "uses",
        "what",
        "which",
        "with",
    }
    tokens: set[str] = set()
    for token in re.findall(r"[a-z0-9_]+", value):
        if token in stopwords:
            continue
        tokens.add(token)
        if len(token) > 3 and token.endswith("s"):
            tokens.add(token[:-1])
    return tokens
