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
from datetime import datetime, timezone

from core.db import chroma
from core.db.repositories import (
    create_reflection,
    link_reflection_evidence,
    repository_connection,
    validate_enum_value,
    workspace_id_for_observation,
)
from core.llm.embeddings import embed_text
from core.llm.prompts import render_prompt
from core.llm.qwen import call_qwen_json
from core.memory.graph import create_graph_edge, create_graph_node

Reflection = dict[str, object]

ACTIVE_FACT_STATUS = "active"
TERMINAL_REFLECTION_STATUSES = frozenset({"invalidated", "superseded"})

LOGGER = logging.getLogger(__name__)

REFLECTION_TYPES = frozenset({"user_knowledge", "world_knowledge", "self_knowledge"})
SYNTHESIZED_REFLECTION_TYPES = frozenset({"user_knowledge", "self_knowledge"})
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
WORLD_KNOWLEDGE_MARKERS = frozenset(
    {
        "principles of",
        "definition of",
        "defined as",
        "refers to",
        "is a concept",
        "is the practice",
        "is the process",
        "in general",
        "generally means",
    }
)
FACT_RESTATEMENT_PREFIXES = (
    "chromadb is ",
    "mira distinguishes ",
    "mira exposes ",
    "mira is ",
    "mira keeps ",
    "mira shows ",
    "mira stores ",
    "mira supports ",
    "mira uses ",
    "quick retrieval ",
    "raw observations ",
    "sqlite is ",
    "the prompt is ",
    "the session working set ",
)
REFLECTION_PATTERN_MARKERS = frozenset(
    {
        "across",
        "approach",
        "consistently",
        "pattern",
        "strategy",
        "tendency",
        "tends",
        "tradeoff",
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
        reflection = _normalize_reflection(raw_reflection, valid_evidence_ids, observations)
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
    workspace_id = workspace_id_for_observation(grounded_observation_ids[0])
    if any(
        workspace_id_for_observation(observation_id) != workspace_id
        for observation_id in grounded_observation_ids[1:]
    ):
        raise ValueError("reflection evidence cannot cross workspaces")

    reflection_id = create_reflection(
        {
            "workspace_id": workspace_id,
            "reflection_type": reflection_type,
            "content": content,
            "confidence": confidence,
            "status": "active",
        }
    )
    # Index the reflection in the vector store so it is retrievable by meaning (Quick and
    # Deep both search the reflections collection). Without this the collection stays empty
    # and reflections can never be retrieved semantically -- only by brittle token overlap.
    chroma.add_embedding(
        "reflections",
        "reflections",
        reflection_id,
        embed_text(content),
        metadata={"reflection_type": reflection_type},
        workspace_id=workspace_id,
    )
    reflection_node_id = create_graph_node(
        node_type="reflection",
        label=_label(content) or reflection_type,
        source_table="reflections",
        source_id=reflection_id,
        workspace_id=workspace_id,
    )
    for observation_id in grounded_observation_ids:
        link_reflection_evidence(reflection_id, observation_id)
        create_graph_edge(
            reflection_node_id,
            _observation_node_id(observation_id, workspace_id),
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


def find_reflections_derived_from(observation_id: str) -> list[str]:
    """Return ids of reflections whose evidence includes this observation."""
    if not observation_id:
        return []
    rows = _fetch_rows(
        "SELECT DISTINCT reflection_id FROM reflection_evidence WHERE observation_id = ?",
        (observation_id,),
    )
    return [str(row["reflection_id"]) for row in rows]


def mark_reflection_stale(reflection_id: str, reason: str) -> None:
    """Mark a reflection stale when supporting evidence changes (no history deleted).

    A stale reflection is retained but excluded from hot-tier eligibility. A
    reflection already invalidated or superseded is left at its more severe status.
    """
    if not reason:
        raise ValueError("reason must not be empty")
    status = _reflection_status(reflection_id)
    if status in TERMINAL_REFLECTION_STATUSES:
        return
    _set_reflection_status(reflection_id, "stale", reason)
    LOGGER.info("Marked reflection %s stale: %s", reflection_id, reason)


def recompute_reflection_confidence(reflection_id: str) -> float:
    """Recompute confidence from the fraction of evidence that is still valid."""
    total, valid = _evidence_counts(reflection_id)
    current = _reflection_confidence(reflection_id)
    if total == 0:
        return current
    new_confidence = round(current * (valid / total), 6)
    _update_reflection_confidence(reflection_id, new_confidence)
    return new_confidence


def invalidate_reflection_if_unsupported(reflection_id: str) -> None:
    """Stale or invalidate a reflection based on how much evidence still holds.

    No remaining valid evidence -> invalidated for future use; partial evidence
    loss -> stale with reduced confidence; fully supported -> unchanged. History
    is never deleted and prior answers are never rewritten.
    """
    total, valid = _evidence_counts(reflection_id)
    if total == 0:
        return
    if valid == 0:
        _set_reflection_status(reflection_id, "invalidated", "all supporting evidence collapsed")
        LOGGER.info("Invalidated reflection %s: evidence collapsed", reflection_id)
        return
    if valid < total:
        recompute_reflection_confidence(reflection_id)
        mark_reflection_stale(
            reflection_id,
            f"{total - valid} of {total} evidence observations superseded or contradicted",
        )


def _evidence_counts(reflection_id: str) -> tuple[int, int]:
    observation_ids = [
        str(row["observation_id"])
        for row in _fetch_rows(
            "SELECT observation_id FROM reflection_evidence WHERE reflection_id = ?",
            (reflection_id,),
        )
    ]
    valid = sum(
        1 for observation_id in observation_ids if _evidence_observation_valid(observation_id)
    )
    return len(observation_ids), valid


def _evidence_observation_valid(observation_id: str) -> bool:
    statuses = [
        str(row["status"])
        for row in _fetch_rows(
            "SELECT status FROM atomic_facts WHERE source_observation_id = ?",
            (observation_id,),
        )
    ]
    if not statuses:
        return True
    return any(status == ACTIVE_FACT_STATUS for status in statuses)


def _reflection_status(reflection_id: str) -> str:
    rows = _fetch_rows("SELECT status FROM reflections WHERE id = ?", (reflection_id,))
    if not rows:
        raise ValueError(f"Reflection not found: {reflection_id}")
    return str(rows[0]["status"])


def _reflection_confidence(reflection_id: str) -> float:
    rows = _fetch_rows("SELECT confidence FROM reflections WHERE id = ?", (reflection_id,))
    if not rows:
        raise ValueError(f"Reflection not found: {reflection_id}")
    return _score(rows[0]["confidence"])


def _set_reflection_status(reflection_id: str, status: str, reason: str) -> None:
    validate_enum_value("reflection_status", status)
    with repository_connection() as connection:
        cursor = connection.execute(
            "UPDATE reflections SET status = ?, stale_reason = ?, updated_at = ? WHERE id = ?",
            (status, reason, _now(), reflection_id),
        )
        if cursor.rowcount == 0:
            raise ValueError(f"Reflection not found: {reflection_id}")


def _update_reflection_confidence(reflection_id: str, confidence: float) -> None:
    with repository_connection() as connection:
        cursor = connection.execute(
            "UPDATE reflections SET confidence = ?, updated_at = ? WHERE id = ?",
            (confidence, _now(), reflection_id),
        )
        if cursor.rowcount == 0:
            raise ValueError(f"Reflection not found: {reflection_id}")


def _fetch_rows(statement: str, parameters: tuple[object, ...]) -> list[dict[str, object]]:
    with repository_connection() as connection:
        rows = connection.execute(statement, parameters).fetchall()
    return [dict(row) for row in rows]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()  # noqa: UP017


def _normalize_reflection(
    raw_reflection: dict[object, object],
    valid_evidence_ids: set[str],
    observations: dict[str, str],
) -> Reflection | None:
    reflection_type = _string(raw_reflection.get("reflection_type"))
    content = _string(raw_reflection.get("content"))
    confidence = _score(raw_reflection.get("confidence"))
    evidence_ids = [
        evidence_id
        for evidence_id in _string_list(raw_reflection.get("evidence_ids"))
        if evidence_id in valid_evidence_ids
    ]

    if reflection_type not in SYNTHESIZED_REFLECTION_TYPES or not content:
        if reflection_type == "world_knowledge":
            LOGGER.info("Rejected world-knowledge reflection: %s", content)
        return None
    if len(evidence_ids) < 2:
        LOGGER.info("Rejected thin reflection with fewer than two evidence records: %s", content)
        return None
    if not _has_diverse_evidence(evidence_ids, observations):
        LOGGER.info("Rejected reflection backed by near-duplicate evidence: %s", content)
        return None
    if _too_similar_to_any_evidence(content, evidence_ids, observations):
        LOGGER.info("Rejected reflection too similar to source evidence: %s", content)
        return None
    if confidence <= 0.0:
        LOGGER.info("Rejected zero-confidence reflection: %s", content)
        return None
    if _looks_unsupported(content):
        LOGGER.info("Rejected unsupported personality reflection: %s", content)
        return None
    if _looks_like_world_knowledge(content):
        LOGGER.info("Rejected fact-like reflection: %s", content)
        return None
    if _looks_like_atomic_fact_restatement(content):
        LOGGER.info("Rejected atomic-fact restatement reflection: %s", content)
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


def _observation_node_id(observation_id: str, workspace_id: str) -> str:
    with repository_connection() as connection:
        row = connection.execute(
            """
            SELECT id FROM graph_nodes
            WHERE workspace_id = ? AND node_type = ? AND source_table = ? AND source_id = ?
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (workspace_id, "observation", "observations", observation_id),
        ).fetchone()
    if row is not None:
        return str(row["id"])
    content = _fetch_observations([observation_id]).get(observation_id, "")
    return create_graph_node(
        node_type="observation",
        label=_label(content) or observation_id,
        source_table="observations",
        source_id=observation_id,
        workspace_id=workspace_id,
    )


def _format_evidence_records(observations: dict[str, str]) -> str:
    return "\n".join(
        f"- {observation_id}: {content}" for observation_id, content in observations.items()
    )


def _looks_unsupported(content: str) -> bool:
    normalized = _normalize(content)
    return any(marker in normalized for marker in UNSUPPORTED_PERSONALITY_MARKERS)


def _looks_like_world_knowledge(content: str) -> bool:
    normalized = _normalize(content)
    return any(marker in normalized for marker in WORLD_KNOWLEDGE_MARKERS)


def _looks_like_atomic_fact_restatement(content: str) -> bool:
    normalized = _normalize(content)
    if any(marker in normalized for marker in REFLECTION_PATTERN_MARKERS):
        return False
    return normalized.startswith(FACT_RESTATEMENT_PREFIXES)


def _has_diverse_evidence(evidence_ids: list[str], observations: dict[str, str]) -> bool:
    normalized_evidence = [
        _normalize(observations.get(evidence_id, "")) for evidence_id in evidence_ids
    ]
    unique_evidence = {evidence for evidence in normalized_evidence if evidence}
    if len(unique_evidence) < 2:
        return False
    for index, left in enumerate(normalized_evidence):
        for right in normalized_evidence[index + 1 :]:
            if left and right and _token_jaccard(left, right) < 0.82:
                return True
    return False


def _too_similar_to_any_evidence(
    content: str,
    evidence_ids: list[str],
    observations: dict[str, str],
) -> bool:
    normalized_content = _normalize(content)
    for evidence_id in evidence_ids:
        evidence = _normalize(observations.get(evidence_id, ""))
        if not evidence:
            continue
        if normalized_content == evidence:
            return True
        if _token_jaccard(normalized_content, evidence) >= 0.86:
            return True
    return False


def _token_jaccard(left: str, right: str) -> float:
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


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
