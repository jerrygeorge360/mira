"""Entity canonicalization primitives for the durable typed graph.

Ownership: Jerry.
Related issue: ISSUE-025.
Architecture area: slow path.
"""

from __future__ import annotations

import json
from typing import Any

from core.db.repositories import (
    create_entity,
    repository_connection,
)
from core.db.repositories import (
    create_graph_edge as create_graph_edge_record,
)
from core.db.repositories import (
    create_graph_node as create_graph_node_record,
)
from core.llm.prompts import PROMPT_TEMPLATES
from core.llm.qwen import call_qwen_json

Entity = dict[str, object]
NetworkXGraph = Any

DEFAULT_ENTITY_TYPE = "unknown"


def extract_entities(text: str) -> list[Entity]:
    """Extract and canonicalize stable named entities from text."""
    if not text.strip():
        return []
    prompt = PROMPT_TEMPLATES["entity_extraction"].render({"evidence": text})
    response = call_qwen_json(
        [{"role": "user", "content": prompt}],
        schema_name="entity_extraction",
    )
    payload = response.get("json", {})
    raw_entities = payload.get("entities") if isinstance(payload, dict) else None
    if not isinstance(raw_entities, list):
        return []

    entities: list[Entity] = []
    for raw_entity in raw_entities:
        if not isinstance(raw_entity, dict):
            continue
        name = _string_field(raw_entity, "name")
        if not name:
            continue
        aliases = _string_list(raw_entity.get("aliases"))
        entity_id = canonicalize_entity(name, aliases)
        entities.append(
            {
                "id": entity_id,
                "name": _canonical_name(name),
                "entity_type": _string_field(raw_entity, "entity_type") or DEFAULT_ENTITY_TYPE,
                "aliases": aliases,
            }
        )
    return entities


def canonicalize_entity(name: str, aliases: list[str] | None = None) -> str:
    """Return a stable entity ID using exact matches, aliases, then conservative creation."""
    canonical_name = _canonical_name(name)
    if not canonical_name:
        raise ValueError("name must not be empty")
    alias_values = [_canonical_name(alias) for alias in aliases or [] if _canonical_name(alias)]

    existing_id = _find_entity_by_name(canonical_name)
    if existing_id is not None:
        _merge_aliases(existing_id, alias_values)
        return existing_id

    existing_id = _find_entity_by_alias(canonical_name)
    if existing_id is not None:
        _merge_aliases(existing_id, [canonical_name, *alias_values])
        return existing_id

    for alias in alias_values:
        existing_id = _find_entity_by_name(alias) or _find_entity_by_alias(alias)
        if existing_id is not None:
            _merge_aliases(existing_id, [canonical_name, *alias_values])
            return existing_id

    return create_entity(
        {
            "name": canonical_name,
            "entity_type": _infer_entity_type(canonical_name),
            "aliases_json": alias_values,
        }
    )


def link_entity_mention(entity_id: str, observation_id: str) -> str:
    """Create a graph node linking an entity mention to an observation."""
    if not entity_id:
        raise ValueError("entity_id must not be empty")
    if not observation_id:
        raise ValueError("observation_id must not be empty")
    entity = _require_entity(entity_id)
    _ensure_observation_exists(observation_id)
    return create_graph_node(
        node_type="entity",
        source_table="entities",
        source_id=entity_id,
        label=str(entity["name"]),
    )


def create_graph_node(
    node_type: str,
    label: str,
    source_table: str | None = None,
    source_id: str | None = None,
) -> str:
    """Create a typed graph node over a canonical source record."""
    if not label.strip():
        raise ValueError("label must not be empty")
    return create_graph_node_record(
        {
            "node_type": node_type,
            "source_table": source_table,
            "source_id": source_id,
            "label": label,
        }
    )


def create_graph_edge(
    source_node_id: str,
    target_node_id: str,
    edge_type: str,
    confidence: float,
    source_observations: list[str],
) -> str:
    """Create a typed graph edge with confidence and source observation evidence."""
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be in [0, 1]")
    if not source_observations:
        raise ValueError("source_observations must not be empty")
    _ensure_graph_node_exists(source_node_id)
    _ensure_graph_node_exists(target_node_id)
    for observation_id in source_observations:
        _ensure_observation_exists(observation_id)
    return create_graph_edge_record(
        {
            "source_node_id": source_node_id,
            "target_node_id": target_node_id,
            "edge_type": edge_type,
            "confidence": confidence,
            "source_observations_json": list(source_observations),
            "metadata_json": {},
        }
    )


def get_neighbors(
    node_id: str,
    edge_types: list[str] | None = None,
    depth: int = 1,
) -> list[dict[str, object]]:
    """Traverse outgoing typed graph edges from a node up to the requested depth."""
    if depth < 1:
        raise ValueError("depth must be a positive integer")
    _ensure_graph_node_exists(node_id)
    allowed_edge_types = set(edge_types or [])
    visited_nodes = {node_id}
    frontier = [(node_id, 0)]
    neighbors: list[dict[str, object]] = []

    while frontier:
        current_node_id, current_depth = frontier.pop(0)
        if current_depth >= depth:
            continue
        for edge in _outgoing_edges(current_node_id, allowed_edge_types):
            target_node = _fetch_graph_node(str(edge["target_node_id"]))
            if target_node is None:
                continue
            result = {
                "depth": current_depth + 1,
                "edge": edge,
                "node": target_node,
            }
            neighbors.append(result)
            target_node_id = str(target_node["id"])
            if target_node_id not in visited_nodes:
                visited_nodes.add(target_node_id)
                frontier.append((target_node_id, current_depth + 1))
    return neighbors


def find_edges_by_type(edge_type: str) -> list[dict[str, object]]:
    """List active graph edges of one type."""
    with repository_connection() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM graph_edges
            WHERE edge_type = ? AND invalidated_at IS NULL
            ORDER BY created_at ASC
            """,
            (edge_type,),
        ).fetchall()
    return [_public_edge(dict(row)) for row in rows]


def inspect_memory_graph(
    *,
    entity: str | None = None,
    limit: int = 50,
) -> dict[str, object]:
    """Return a read-only graph snapshot with provenance-focused edge details."""
    if limit < 1:
        raise ValueError("limit must be a positive integer")
    node_filter = ""
    parameters: list[object] = []
    if entity:
        node_filter = "WHERE label LIKE ?"
        parameters.append(f"%{entity}%")
    with repository_connection() as connection:
        node_rows = connection.execute(
            f"""
            SELECT *
            FROM graph_nodes
            {node_filter}
            ORDER BY created_at DESC
            LIMIT ?
            """,  # nosec B608
            (*parameters, limit),
        ).fetchall()
        total_nodes = connection.execute("SELECT COUNT(*) AS count FROM graph_nodes").fetchone()
        total_edges = connection.execute(
            "SELECT COUNT(*) AS count FROM graph_edges WHERE invalidated_at IS NULL"
        ).fetchone()
    nodes = [_public_node(dict(row)) for row in node_rows]
    node_ids = {str(node["id"]) for node in nodes}
    edges = _edges_for_nodes(node_ids, limit) if node_ids else []
    return {
        "counts": {
            "nodes": 0 if total_nodes is None else int(total_nodes["count"]),
            "active_edges": 0 if total_edges is None else int(total_edges["count"]),
            "visible_nodes": len(nodes),
            "visible_edges": len(edges),
        },
        "nodes": nodes,
        "edges": edges,
    }


def build_networkx_memory_graph(
    *,
    include_invalidated: bool = False,
) -> NetworkXGraph:
    """Build a read-only NetworkX MultiDiGraph projection from SQLite graph tables."""
    try:
        import networkx as nx
    except ModuleNotFoundError as error:  # pragma: no cover - dependency installed in normal envs
        raise RuntimeError("Install networkx to build the in-memory graph view") from error

    graph = nx.MultiDiGraph()
    for node in _all_graph_nodes():
        node_id = str(node.pop("id"))
        graph.add_node(node_id, **node)
    for edge in _all_graph_edges(include_invalidated=include_invalidated):
        edge_id = str(edge.pop("id"))
        source_node_id = str(edge.pop("source_node_id"))
        target_node_id = str(edge.pop("target_node_id"))
        graph.add_edge(source_node_id, target_node_id, key=edge_id, id=edge_id, **edge)
    return graph


def graph_algorithm_summary() -> dict[str, object]:
    """Return small NetworkX-derived diagnostics while keeping SQLite as source of truth."""
    try:
        import networkx as nx
    except ModuleNotFoundError as error:  # pragma: no cover - dependency installed in normal envs
        raise RuntimeError("Install networkx to run graph algorithm diagnostics") from error

    graph = build_networkx_memory_graph()
    if graph.number_of_nodes() == 0:
        return {
            "nodes": 0,
            "edges": 0,
            "weakly_connected_components": 0,
            "largest_component_size": 0,
            "top_degree_nodes": [],
        }
    components = list(nx.weakly_connected_components(graph))
    degrees = sorted(graph.degree(), key=lambda item: (-int(item[1]), str(item[0])))
    labels = {node_id: str(data.get("label", node_id)) for node_id, data in graph.nodes(data=True)}
    return {
        "nodes": graph.number_of_nodes(),
        "edges": graph.number_of_edges(),
        "weakly_connected_components": len(components),
        "largest_component_size": max(len(component) for component in components),
        "top_degree_nodes": [
            {"id": str(node_id), "label": labels.get(str(node_id), str(node_id)), "degree": degree}
            for node_id, degree in degrees[:5]
        ],
    }


def traverse_graph(entity_id: str, relation_types: set[str]) -> list[dict[str, object]]:
    """Traverse durable graph relationships from an entity."""
    return get_neighbors(entity_id, sorted(relation_types), depth=1)


def _find_entity_by_name(name: str) -> str | None:
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT id FROM entities WHERE lower(name) = lower(?) ORDER BY created_at ASC LIMIT 1",
            (name,),
        ).fetchone()
    return None if row is None else str(row["id"])


def _find_entity_by_alias(alias: str) -> str | None:
    with repository_connection() as connection:
        rows = connection.execute("SELECT id, aliases_json FROM entities").fetchall()
    normalized_alias = _normalize(alias)
    for row in rows:
        if normalized_alias in {_normalize(value) for value in _json_list(row["aliases_json"])}:
            return str(row["id"])
    return None


def _merge_aliases(entity_id: str, aliases: list[str]) -> None:
    if not aliases:
        return
    entity_name = str(_require_entity(entity_id)["name"])
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT aliases_json FROM entities WHERE id = ?",
            (entity_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Entity not found: {entity_id}")
        merged = sorted(
            {
                alias
                for alias in [*_json_list(row["aliases_json"]), *aliases]
                if alias and _normalize(alias) != _normalize(entity_name)
            }
        )
        connection.execute(
            "UPDATE entities SET aliases_json = ? WHERE id = ?",
            (_json_dump(merged), entity_id),
        )


def _require_entity(entity_id: str) -> Entity:
    with repository_connection() as connection:
        row = connection.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone()
    if row is None:
        raise ValueError(f"Entity not found: {entity_id}")
    return dict(row)


def _ensure_observation_exists(observation_id: str) -> None:
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT id FROM observations WHERE id = ?",
            (observation_id,),
        ).fetchone()
    if row is None:
        raise ValueError(f"Observation not found: {observation_id}")


def _ensure_graph_node_exists(node_id: str) -> None:
    if _fetch_graph_node(node_id) is None:
        raise ValueError(f"Graph node not found: {node_id}")


def _fetch_graph_node(node_id: str) -> dict[str, object] | None:
    with repository_connection() as connection:
        row = connection.execute("SELECT * FROM graph_nodes WHERE id = ?", (node_id,)).fetchone()
    if row is None:
        return None
    record = dict(row)
    if record.get("metadata_json") is not None:
        record["metadata_json"] = _json_object(record["metadata_json"])
    return record


def _outgoing_edges(node_id: str, edge_types: set[str]) -> list[dict[str, object]]:
    parameters: list[object] = [node_id]
    edge_type_filter = ""
    if edge_types:
        edge_type_filter = f"AND edge_type IN ({', '.join('?' for _ in edge_types)})"
        parameters.extend(sorted(edge_types))
    with repository_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT *
            FROM graph_edges
            WHERE source_node_id = ?
              AND invalidated_at IS NULL
              {edge_type_filter}
            ORDER BY created_at ASC
            """,  # nosec B608
            tuple(parameters),
        ).fetchall()
    return [_public_edge(dict(row)) for row in rows]


def _public_edge(row: dict[str, object]) -> dict[str, object]:
    edge = dict(row)
    edge["source_observations"] = _json_list(edge.pop("source_observations_json", None))
    metadata = edge.get("metadata_json")
    edge["metadata_json"] = _json_object(metadata) if metadata is not None else {}
    return edge


def _public_node(row: dict[str, object]) -> dict[str, object]:
    node = dict(row)
    metadata = node.get("metadata_json")
    node["metadata_json"] = _json_object(metadata) if metadata is not None else {}
    return node


def _edges_for_nodes(node_ids: set[str], limit: int) -> list[dict[str, object]]:
    placeholders = ", ".join("?" for _ in node_ids)
    sorted_ids = sorted(node_ids)
    with repository_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT edge.*,
                   source.label AS source_label,
                   target.label AS target_label
            FROM graph_edges AS edge
            JOIN graph_nodes AS source ON source.id = edge.source_node_id
            JOIN graph_nodes AS target ON target.id = edge.target_node_id
            WHERE edge.invalidated_at IS NULL
              AND (
                edge.source_node_id IN ({placeholders})
                OR edge.target_node_id IN ({placeholders})
              )
            ORDER BY edge.created_at DESC
            LIMIT ?
            """,  # nosec B608
            (*sorted_ids, *sorted_ids, limit),
        ).fetchall()
    edges: list[dict[str, object]] = []
    for row in rows:
        record = dict(row)
        source_label = record.pop("source_label")
        target_label = record.pop("target_label")
        edge = _public_edge(record)
        edge["source_label"] = source_label
        edge["target_label"] = target_label
        edges.append(edge)
    return edges


def _all_graph_nodes() -> list[dict[str, object]]:
    with repository_connection() as connection:
        rows = connection.execute("SELECT * FROM graph_nodes ORDER BY created_at ASC").fetchall()
    return [_public_node(dict(row)) for row in rows]


def _all_graph_edges(*, include_invalidated: bool) -> list[dict[str, object]]:
    where = "" if include_invalidated else "WHERE invalidated_at IS NULL"
    with repository_connection() as connection:
        rows = connection.execute(
            f"SELECT * FROM graph_edges {where} ORDER BY created_at ASC"  # nosec B608
        ).fetchall()
    return [_public_edge(dict(row)) for row in rows]


def _infer_entity_type(name: str) -> str:
    if name in {"SQLite", "ChromaDB"}:
        return "technology"
    if name in {"MIRA", "Session Working Set", "Relational Mode"}:
        return "system_concept"
    if name in {"Jerry"}:
        return "person"
    if name.endswith("Hackathon"):
        return "event"
    return DEFAULT_ENTITY_TYPE


def _canonical_name(name: str) -> str:
    return " ".join(name.strip().split())


def _normalize(value: str) -> str:
    return _canonical_name(value).casefold()


def _string_field(record: dict[object, object], field_name: str) -> str:
    value = record.get(field_name)
    return value.strip() if isinstance(value, str) else ""


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_canonical_name(item) for item in value if isinstance(item, str) and item.strip()]


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


def _json_object(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    if not isinstance(value, str):
        return {}
    decoded = json.loads(value)
    if not isinstance(decoded, dict):
        return {}
    return {str(key): item for key, item in decoded.items()}


def _json_dump(value: object) -> str:
    return json.dumps(value, sort_keys=True)
