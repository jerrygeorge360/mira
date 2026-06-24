"""Relational Mode retrieval over the single typed temporal graph.

Ownership: Jerry.
Related issue: ISSUE-035.
Architecture area: retrieval.

Relational Mode answers relationship questions -- "what changed", "what
contradicts what", "what caused this", "what is the evidence" -- by traversing
typed graph edges directly rather than ranking loose text. It starts from
caller-supplied graph anchors (entity, atomic-fact, or raw node identifiers),
walks contradiction, supersession, causality, and evidence edges in both
directions, and returns deterministic, prompt-ready relationship evidence.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from core.db.repositories import enum_values, repository_connection

RelationEvidence = dict[str, object]

# The relation families Relational Mode is responsible for. Empty caller input
# falls back to this set so a bare anchor still surfaces its key relationships.
DEFAULT_RELATION_TYPES = frozenset(
    {"CONTRADICTS", "SUPERSEDED_BY", "CAUSED_BY", "LEADS_TO", "DERIVED_FROM"}
)


def relational_retrieve(
    entity_ids: list[str],
    relation_types: set[str],
    limit: int = 20,
) -> list[RelationEvidence]:
    """Traverse contradiction, supersession, causality, and evidence relations.

    ``entity_ids`` may be graph-node identifiers or the source identifiers of the
    records those nodes point at (entities, atomic facts). ``relation_types`` is
    restricted to valid graph edge types; an empty set means "all relational
    families". Results are deduplicated per edge and ranked deterministically by
    confidence, recency, and identifier.
    """
    if limit < 1:
        raise ValueError("limit must be a positive integer")
    if not entity_ids:
        return []

    allowed_relations = _resolve_relation_types(relation_types)
    node_cache: dict[str, dict[str, object] | None] = {}
    origin_node_ids = _resolve_origin_nodes(entity_ids, node_cache)

    evidence: list[RelationEvidence] = []
    seen_edges: set[str] = set()
    for origin_node_id in origin_node_ids:
        for edge in _incident_edges(origin_node_id, allowed_relations):
            edge_id = str(edge["id"])
            if edge_id in seen_edges:
                continue
            item = _relation_evidence(origin_node_id, edge, node_cache)
            if item is None:
                continue
            seen_edges.add(edge_id)
            evidence.append(item)

    evidence.sort(key=_ranking_key)
    return evidence[:limit]


def _resolve_relation_types(relation_types: set[str]) -> frozenset[str]:
    valid_edge_types = enum_values("graph_edge_type")
    if not relation_types:
        return frozenset(DEFAULT_RELATION_TYPES)
    unknown = sorted(relation for relation in relation_types if relation not in valid_edge_types)
    if unknown:
        raise ValueError(f"Unknown relation type(s): {', '.join(unknown)}")
    return frozenset(relation_types)


def _resolve_origin_nodes(
    entity_ids: list[str],
    node_cache: dict[str, dict[str, object] | None],
) -> list[str]:
    origin_ids: list[str] = []
    seen: set[str] = set()
    for entity_id in entity_ids:
        for node_id in _node_ids_for_anchor(entity_id, node_cache):
            if node_id not in seen:
                seen.add(node_id)
                origin_ids.append(node_id)
    return origin_ids


def _node_ids_for_anchor(
    anchor_id: str,
    node_cache: dict[str, dict[str, object] | None],
) -> list[str]:
    direct_node = _fetch_node(anchor_id, node_cache)
    if direct_node is not None:
        return [anchor_id]
    with repository_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM graph_nodes WHERE source_id = ? ORDER BY created_at ASC",
            (anchor_id,),
        ).fetchall()
    node_ids: list[str] = []
    for row in rows:
        record = dict(row)
        node_id = str(record["id"])
        node_cache[node_id] = record
        node_ids.append(node_id)
    return node_ids


def _incident_edges(node_id: str, allowed_relations: frozenset[str]) -> list[dict[str, object]]:
    relation_placeholders = ", ".join("?" for _ in allowed_relations)
    parameters = (node_id, node_id, *sorted(allowed_relations))
    with repository_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT *
            FROM graph_edges
            WHERE (source_node_id = ? OR target_node_id = ?)
              AND invalidated_at IS NULL
              AND edge_type IN ({relation_placeholders})
            ORDER BY created_at ASC
            """,  # nosec B608
            parameters,
        ).fetchall()
    return [dict(row) for row in rows]


def _relation_evidence(
    origin_node_id: str,
    edge: dict[str, object],
    node_cache: dict[str, dict[str, object] | None],
) -> RelationEvidence | None:
    source_node = _fetch_node(str(edge["source_node_id"]), node_cache)
    target_node = _fetch_node(str(edge["target_node_id"]), node_cache)
    if source_node is None or target_node is None:
        return None

    relation = str(edge["edge_type"])
    direction = "outgoing" if str(edge["source_node_id"]) == origin_node_id else "incoming"
    related_node = target_node if direction == "outgoing" else source_node
    confidence = _float(edge.get("confidence"))

    return {
        "source": "graph_edge",
        "source_id": str(edge["id"]),
        "id": str(edge["id"]),
        "relation": relation,
        "direction": direction,
        "content": f"{source_node['label']} {relation} {target_node['label']}",
        "origin_node_id": origin_node_id,
        "related_node_id": str(related_node["id"]),
        "related_node_type": str(related_node.get("node_type", "")),
        "related_source_table": related_node.get("source_table"),
        "related_source_id": related_node.get("source_id"),
        "related_label": str(related_node["label"]),
        "confidence": confidence,
        "score": confidence,
        "status": "active",
        "valid_from": edge.get("valid_from"),
        "valid_until": edge.get("valid_until"),
        "source_observations": _json_list(edge.get("source_observations_json")),
        "created_at": edge.get("created_at"),
        "record": dict(edge),
    }


def _fetch_node(
    node_id: str,
    node_cache: dict[str, dict[str, object] | None],
) -> dict[str, object] | None:
    if node_id in node_cache:
        return node_cache[node_id]
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT * FROM graph_nodes WHERE id = ?",
            (node_id,),
        ).fetchone()
    record = None if row is None else dict(row)
    node_cache[node_id] = record
    return record


def _ranking_key(evidence: RelationEvidence) -> tuple[float, float, str]:
    return (
        -_float(evidence.get("score")),
        -_timestamp(evidence.get("created_at")),
        str(evidence.get("source_id")),
    )


def _timestamp(value: object) -> float:
    if not isinstance(value, str) or not value:
        return 0.0
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)  # noqa: UP017
    return parsed.timestamp()


def _float(value: object, default: float = 0.0) -> float:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _json_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    if not isinstance(value, str):
        return []
    decoded = json.loads(value)
    if not isinstance(decoded, list):
        return []
    return [item for item in decoded if isinstance(item, str)]
