"""Evidence-backed reflection synthesis from recent important observations.

Ownership: Jerry.
Related issue: ISSUE-028.
Architecture area: slow path.

Reflections move MIRA from raw memory to interpreted memory. Synthesis is
graph-decoupled: it reads recent observations (not Leiden communities), asks the
model for compact higher-level reflections, and keeps only source-backed,
non-overclaiming results. Storage records evidence twice -- through
``reflection_evidence`` rows and through typed ``DERIVED_FROM`` graph edges -- so
every reflection can be traced back to the observations that justify it.
"""

from __future__ import annotations

import logging

from core.db.repositories import (
    create_reflection,
    link_reflection_evidence,
    repository_connection,
)
from core.llm.prompts import render_prompt
from core.llm.qwen import call_qwen_json
from core.memory.graph import create_graph_edge, create_graph_node

Reflection = dict[str, object]

LOGGER = logging.getLogger(__name__)

REFLECTION_TYPES = frozenset({"user_knowledge", "world_knowledge", "self_knowledge"})
HOT_MEMORY_TYPES = frozenset({"self_knowledge"})

IMPORTANCE_THRESHOLD = 0.5
HIGH_IMPORTANCE = 0.8
MIN_IMPORTANT_OBSERVATIONS = 2
LABEL_MAX_LENGTH = 120

UNSUPPORTED_PERSONALITY_MARKERS = frozenset(
    {
        "is lazy",
        "is careless",
        "is smart",
        "is stupid",
        "is emotional",
        "is rude",
        "personality",
    }
)


def should_reflect(observation_ids: list[str], importance_scores: dict[str, float]) -> bool:
    """Decide whether recent observations are important enough to reflect on."""
    if not observation_ids:
        return False
    scores = [_score(importance_scores.get(observation_id)) for observation_id in observation_ids]
    if any(score >= HIGH_IMPORTANCE for score in scores):
        return True
    important = [score for score in scores if score >= IMPORTANCE_THRESHOLD]
    return len(important) >= MIN_IMPORTANT_OBSERVATIONS


def synthesize_reflections(observation_ids: list[str]) -> list[Reflection]:
    """Synthesize compact, source-backed reflections from recent observations."""
    if not observation_ids:
        return []
    observations = _fetch_observations(observation_ids)
    if not observations:
        return []

    prompt = render_prompt(
        "reflection_synthesis",
        {"evidence_records": _format_evidence_records(observations)},
    )
    response = call_qwen_json(
        [{"role": "user", "content": prompt}],
        schema_name="reflection_synthesis",
    )
    payload = response.get("json", {})
    raw_reflections = payload.get("reflections") if isinstance(payload, dict) else None
    if not isinstance(raw_reflections, list):
        return []

    valid_evidence_ids = set(observations)
    reflections: list[Reflection] = []
    for raw_reflection in raw_reflections:
        if not isinstance(raw_reflection, dict):
            continue
        reflection = _normalize_reflection(raw_reflection, valid_evidence_ids)
        if reflection is not None:
            reflections.append(reflection)
    return reflections


def store_reflection_with_evidence(
    reflection: Reflection,
    evidence_observation_ids: list[str],
) -> str:
    """Persist a reflection plus its evidence rows and DERIVED_FROM graph edges."""
    reflection_type = _string(reflection.get("reflection_type"))
    content = _string(reflection.get("content"))
    confidence = _score(reflection.get("confidence"))
    if reflection_type not in REFLECTION_TYPES:
        raise ValueError(f"invalid reflection_type: {reflection_type!r}")
    if not content:
        raise ValueError("reflection content must not be empty")
    if confidence <= 0.0:
        raise ValueError("reflection confidence must be greater than zero")

    grounded_observation_ids = _existing_observation_ids(evidence_observation_ids)
    if not grounded_observation_ids:
        raise ValueError("reflections must be source-backed by at least one existing observation")

    reflection_id = create_reflection(
        {
            "reflection_type": reflection_type,
            "content": content,
            "confidence": confidence,
            "status": "active",
        }
    )
    reflection_node_id = create_graph_node(
        node_type="reflection",
        label=_label(content) or reflection_type,
        source_table="reflections",
        source_id=reflection_id,
    )
    for observation_id in grounded_observation_ids:
        link_reflection_evidence(reflection_id, observation_id)
        create_graph_edge(
            reflection_node_id,
            _observation_node_id(observation_id),
            "DERIVED_FROM",
            confidence=confidence,
            source_observations=[observation_id],
        )
    LOGGER.info(
        "Stored %s reflection %s backed by %d observation(s)",
        reflection_type,
        reflection_id,
        len(grounded_observation_ids),
    )
    return reflection_id


def mark_reflection_stale(reflection_id: str, reason: str) -> None:
    """Mark a reflection stale when supporting memory changes (see ISSUE-029)."""
    raise NotImplementedError


def _normalize_reflection(
    raw_reflection: dict[object, object],
    valid_evidence_ids: set[str],
) -> Reflection | None:
    reflection_type = _string(raw_reflection.get("reflection_type"))
    content = _string(raw_reflection.get("content"))
    confidence = _score(raw_reflection.get("confidence"))
    evidence_ids = [
        evidence_id
        for evidence_id in _string_list(raw_reflection.get("evidence_ids"))
        if evidence_id in valid_evidence_ids
    ]

    if reflection_type not in REFLECTION_TYPES or not content:
        return None
    if not evidence_ids:
        LOGGER.info("Rejected ungrounded reflection: %s", content)
        return None
    if confidence <= 0.0:
        LOGGER.info("Rejected zero-confidence reflection: %s", content)
        return None
    if _looks_unsupported(content):
        LOGGER.info("Rejected unsupported personality reflection: %s", content)
        return None

    return {
        "reflection_type": reflection_type,
        "content": content,
        "confidence": confidence,
        "evidence_ids": evidence_ids,
        "status": "active",
        "hot_memory_candidate": reflection_type in HOT_MEMORY_TYPES,
    }


def _fetch_observations(observation_ids: list[str]) -> dict[str, str]:
    observations: dict[str, str] = {}
    with repository_connection() as connection:
        for observation_id in observation_ids:
            if observation_id in observations:
                continue
            row = connection.execute(
                "SELECT content FROM observations WHERE id = ?",
                (observation_id,),
            ).fetchone()
            if row is not None:
                observations[observation_id] = str(row["content"])
    return observations


def _existing_observation_ids(observation_ids: list[str]) -> list[str]:
    existing: list[str] = []
    seen: set[str] = set()
    with repository_connection() as connection:
        for observation_id in observation_ids:
            if observation_id in seen:
                continue
            seen.add(observation_id)
            row = connection.execute(
                "SELECT id FROM observations WHERE id = ?",
                (observation_id,),
            ).fetchone()
            if row is not None:
                existing.append(observation_id)
    return existing


def _observation_node_id(observation_id: str) -> str:
    with repository_connection() as connection:
        row = connection.execute(
            """
            SELECT id FROM graph_nodes
            WHERE node_type = ? AND source_table = ? AND source_id = ?
            ORDER BY created_at ASC
            LIMIT 1
            """,
            ("observation", "observations", observation_id),
        ).fetchone()
    if row is not None:
        return str(row["id"])
    content = _fetch_observations([observation_id]).get(observation_id, "")
    return create_graph_node(
        node_type="observation",
        label=_label(content) or observation_id,
        source_table="observations",
        source_id=observation_id,
    )


def _format_evidence_records(observations: dict[str, str]) -> str:
    return "\n".join(
        f"- {observation_id}: {content}" for observation_id, content in observations.items()
    )


def _looks_unsupported(content: str) -> bool:
    normalized = _normalize(content)
    return any(marker in normalized for marker in UNSUPPORTED_PERSONALITY_MARKERS)


def _label(content: str) -> str:
    return " ".join(content.split())[:LABEL_MAX_LENGTH].strip()


def _string(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _score(value: object) -> float:
    if not isinstance(value, int | float):
        return 0.0
    return min(1.0, max(0.0, float(value)))


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())
