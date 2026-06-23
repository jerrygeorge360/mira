"""Entity canonicalization primitives for the durable typed graph.

Ownership: Jerry.
Related issue: ISSUE-025.
Architecture area: slow path.
"""

from __future__ import annotations

import json

from core.db.repositories import create_entity, create_graph_node, repository_connection
from core.llm.prompts import PROMPT_TEMPLATES
from core.llm.qwen import call_qwen_json

Entity = dict[str, object]

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
        {
            "node_type": "entity",
            "source_table": "entities",
            "source_id": entity_id,
            "label": str(entity["name"]),
            "metadata_json": {"observation_id": observation_id},
        }
    )


def add_typed_edge(
    source_id: str,
    target_id: str,
    edge_type: str,
    valid_at: str | None = None,
) -> str:
    """Add a future typed temporal edge and return its identifier."""
    raise NotImplementedError


def traverse_graph(entity_id: str, relation_types: set[str]) -> list[dict[str, object]]:
    """Traverse durable graph relationships from an entity."""
    raise NotImplementedError


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


def _json_dump(value: object) -> str:
    return json.dumps(value, sort_keys=True)
