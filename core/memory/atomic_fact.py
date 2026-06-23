"""Atomic fact extraction and persistence helpers.

Ownership: Jerry.
Related issue: ISSUE-024.
Architecture area: slow path.
"""

from __future__ import annotations

from core.db.repositories import create_atomic_fact as create_atomic_fact_record
from core.llm.prompts import PROMPT_TEMPLATES
from core.llm.qwen import call_qwen_json

AtomicFact = dict[str, object]

MAX_CONFIDENCE = 1.0
UNSUPPORTED_INFERENCE_MARKERS = frozenset(
    {
        "is careless",
        "is lazy",
        "is smart",
        "is emotional",
        "personality",
        "always",
        "never",
    }
)


def extract_atomic_facts(observation_id: str, content: str) -> list[AtomicFact]:
    """Extract direct subject-predicate-object claims from one observation."""
    if not observation_id:
        raise ValueError("observation_id must not be empty")
    if not content.strip():
        return []

    prompt = PROMPT_TEMPLATES["atomic_fact_extraction"].render({"evidence": content})
    response = call_qwen_json(
        [{"role": "user", "content": prompt}],
        schema_name="atomic_fact_extraction",
    )
    payload = response.get("json", {})
    facts = payload.get("facts") if isinstance(payload, dict) else None
    if not isinstance(facts, list):
        return []
    return [
        fact
        for raw_fact in facts
        if isinstance(raw_fact, dict)
        for fact in [_normalize_fact(raw_fact, observation_id, content)]
        if fact is not None
    ]


def store_atomic_facts(facts: list[AtomicFact]) -> list[str]:
    """Persist extracted atomic facts and return their SQLite identifiers."""
    return [create_atomic_fact_record(_validated_fact(fact)) for fact in facts]


def create_atomic_fact(
    subject: str,
    predicate: str,
    object_value: str,
    observation_ids: list[str],
) -> AtomicFact:
    """Create an in-memory source-backed atomic fact payload."""
    if not observation_ids:
        raise ValueError("observation_ids must not be empty")
    return {
        "subject": subject,
        "predicate": predicate,
        "object": object_value,
        "confidence": 1.0,
        "source_observation_id": observation_ids[0],
    }


def _normalize_fact(
    raw_fact: dict[object, object],
    observation_id: str,
    content: str,
) -> AtomicFact | None:
    subject = _string_field(raw_fact, "subject")
    predicate = _string_field(raw_fact, "predicate")
    object_value = _string_field(raw_fact, "object")
    evidence_span = _string_field(raw_fact, "evidence_span")
    confidence = _confidence(raw_fact.get("confidence"))
    if not all((subject, predicate, object_value, evidence_span)):
        return None
    if confidence <= 0.0:
        return None
    if not _evidence_is_grounded(evidence_span, content):
        return None
    if _looks_unsupported(subject, predicate, object_value, evidence_span):
        return None
    return {
        "subject": subject,
        "predicate": predicate,
        "object": object_value,
        "confidence": confidence,
        "source_observation_id": observation_id,
        "evidence_span": evidence_span,
    }


def _validated_fact(fact: AtomicFact) -> AtomicFact:
    required = {"subject", "predicate", "object", "confidence", "source_observation_id"}
    missing = sorted(field for field in required if not fact.get(field))
    if missing:
        raise ValueError(f"Missing atomic fact field(s): {', '.join(missing)}")
    confidence = _confidence(fact["confidence"])
    if confidence <= 0.0:
        raise ValueError("confidence must be greater than zero")
    return {
        "subject": str(fact["subject"]),
        "predicate": str(fact["predicate"]),
        "object": str(fact["object"]),
        "confidence": confidence,
        "source_observation_id": str(fact["source_observation_id"]),
    }


def _string_field(record: dict[object, object], field_name: str) -> str:
    value = record.get(field_name)
    if not isinstance(value, str):
        return ""
    return value.strip()


def _confidence(value: object) -> float:
    if not isinstance(value, int | float):
        return 0.0
    return min(MAX_CONFIDENCE, max(0.0, float(value)))


def _evidence_is_grounded(evidence_span: str, content: str) -> bool:
    normalized_span = _normalize(evidence_span)
    normalized_content = _normalize(content)
    return bool(normalized_span and normalized_span in normalized_content)


def _looks_unsupported(subject: str, predicate: str, object_value: str, evidence_span: str) -> bool:
    combined = _normalize(" ".join((subject, predicate, object_value, evidence_span)))
    return any(marker in combined for marker in UNSUPPORTED_INFERENCE_MARKERS)


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())
