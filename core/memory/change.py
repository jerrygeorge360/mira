"""Contradiction versus supersession semantics for atomic memory changes.

Ownership: Jerry.
Related issue: ISSUE-027.
Architecture area: slow path.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

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
                "reason": _change_reason(prior_fact, new_fact, relation),
            }
        )
    return changes


def apply_supersession(old_fact_id: str, new_fact_id: str, evidence: list[str]) -> str:
    """Record acknowledged belief evolution as a SUPERSEDED_BY graph edge."""
    old_fact = _fetch_atomic_fact(old_fact_id)
    new_fact = _fetch_atomic_fact(new_fact_id)
    edge_id = _create_fact_relation_edge(old_fact, new_fact, "SUPERSEDED_BY", evidence)
    _close_old_fact(old_fact_id)
    return edge_id


def apply_contradiction(fact_a_id: str, fact_b_id: str, evidence: list[str]) -> str:
    """Record unresolved incompatible claims as a CONTRADICTS graph edge.

    Both claims stay active -- no belief is retired -- but the unresolved conflict
    lowers confidence in each, so retrieval can prefer better-supported memory and the
    query-time resolver can weigh them (paper Design Requirement 5).
    """
    fact_a = _fetch_atomic_fact(fact_a_id)
    fact_b = _fetch_atomic_fact(fact_b_id)
    edge_id = _create_fact_relation_edge(fact_a, fact_b, "CONTRADICTS", evidence)
    _reduce_fact_confidence(fact_a_id, CONTRADICTION_CONFIDENCE_FACTOR)
    _reduce_fact_confidence(fact_b_id, CONTRADICTION_CONFIDENCE_FACTOR)
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
    content = (
        "Unresolved conflict in memory: "
        f"'{older['subject']} {older['predicate']} {older['object']}' (earlier) "
        f"vs '{newer['subject']} {newer['predicate']} {newer['object']}' (later). "
        "Surface the conflict; if forced to choose, prefer the later value but say it is "
        "unresolved."
    )
    note_id = f"contradiction:{fact_a_id}:{fact_b_id}"
    return {"source": "contradiction", "id": note_id, "source_id": note_id, "content": content}


def _create_fact_relation_edge(
    source_fact: AtomicFactRecord,
    target_fact: AtomicFactRecord,
    edge_type: str,
    evidence: list[str],
) -> str:
    if not evidence:
        raise ValueError("evidence must not be empty")
    source_node_id = _graph_node_for_fact(source_fact)
    target_node_id = _graph_node_for_fact(target_fact)
    workspace_id = str(source_fact["workspace_id"])
    return create_graph_edge(
        source_node_id,
        target_node_id,
        edge_type,
        confidence=_minimum_confidence(source_fact, target_fact),
        source_observations=evidence,
        workspace_id=workspace_id,
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


def _close_old_fact(fact_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()  # noqa: UP017
    with repository_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE atomic_facts
            SET status = ?, valid_until = ?
            WHERE id = ?
            """,
            ("superseded", now, fact_id),
        )
    if cursor.rowcount == 0:
        raise ValueError(f"Atomic fact not found: {fact_id}")


def _facts_are_comparable(
    prior_fact: AtomicFactRecord,
    new_fact: AtomicFactRecord,
) -> bool:
    if _predicate_allows_multiple_values(prior_fact) or _predicate_allows_multiple_values(new_fact):
        return _has_explicit_transition(prior_fact, new_fact)
    return _fact_comparison_key(prior_fact) == _fact_comparison_key(new_fact)


def _has_explicit_transition(
    prior_fact: AtomicFactRecord,
    new_fact: AtomicFactRecord,
) -> bool:
    evidence_text = _fetch_observation_content(str(new_fact["source_observation_id"]))
    normalized_text = _normalize(evidence_text)
    old_object = _normalize(str(prior_fact["object"]))
    new_object = _normalize(str(new_fact["object"]))
    mentions_both_objects = old_object in normalized_text and new_object in normalized_text
    has_transition_marker = any(marker in normalized_text for marker in TRANSITION_MARKERS)
    if not has_transition_marker:
        return False
    if mentions_both_objects:
        return True
    return _has_correction_marker(normalized_text) and _fact_comparison_key(
        prior_fact
    ) == _fact_comparison_key(new_fact)


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
            [
                str(prior_fact["source_observation_id"]),
                str(new_fact["source_observation_id"]),
            ]
        )
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
