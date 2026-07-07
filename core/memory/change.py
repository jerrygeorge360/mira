"""Contradiction versus supersession semantics for atomic memory changes.

Ownership: Jerry.
Related issue: ISSUE-027.
Architecture area: slow path.
"""

from __future__ import annotations

from datetime import datetime, timezone

from core.db.repositories import repository_connection
from core.memory.graph import create_graph_edge, create_graph_node

MemoryChange = dict[str, object]
AtomicFactRecord = dict[str, object]

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


def detect_memory_change(
    new_fact_id: str,
    candidate_prior_fact_ids: list[str],
) -> list[MemoryChange]:
    """Classify prior facts as superseded or contradicted by a new fact."""
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
    """Record unresolved incompatible claims as a CONTRADICTS graph edge."""
    fact_a = _fetch_atomic_fact(fact_a_id)
    fact_b = _fetch_atomic_fact(fact_b_id)
    return _create_fact_relation_edge(fact_a, fact_b, "CONTRADICTS", evidence)


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
    return create_graph_edge(
        source_node_id,
        target_node_id,
        edge_type,
        confidence=_minimum_confidence(source_fact, target_fact),
        source_observations=evidence,
    )


def _graph_node_for_fact(fact: AtomicFactRecord) -> str:
    fact_id = str(fact["id"])
    existing_node_id = _existing_fact_node_id(fact_id)
    if existing_node_id is not None:
        return existing_node_id
    return create_graph_node(
        node_type="atomic_fact",
        label=_fact_label(fact),
        source_table="atomic_facts",
        source_id=fact_id,
    )


def _existing_fact_node_id(fact_id: str) -> str | None:
    with repository_connection() as connection:
        row = connection.execute(
            """
            SELECT id
            FROM graph_nodes
            WHERE node_type = ? AND source_table = ? AND source_id = ?
            ORDER BY created_at ASC
            LIMIT 1
            """,
            ("atomic_fact", "atomic_facts", fact_id),
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
    """Pair facts by their canonical subject only.

    Candidate selection in the slow path already constrains predicate relevance: the
    exact query matches the same canonical predicate, and the embedding-similarity
    fallback matches a similar predicate under the same canonical subject. Comparing on
    the subject alone therefore lets fallback candidates (which by design have a
    different canonical predicate id) through instead of silently re-dropping them,
    while the curated candidate list keeps unrelated relations out. Facts predating the
    canonical registry (NULL id) fall back to the normalized raw subject.
    """
    canonical_subject_id = fact.get("canonical_subject_id")
    if canonical_subject_id:
        return (f"cs:{canonical_subject_id}", "")
    return (_normalize(str(fact["subject"])), "")


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
