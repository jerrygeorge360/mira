"""Atomic fact extraction and persistence helpers.

Ownership: Jerry.
Related issue: ISSUE-024.
Architecture area: slow path.
"""

from __future__ import annotations

import re

from core.db.repositories import create_atomic_fact as create_atomic_fact_record
from core.llm.prompts import PROMPT_TEMPLATES
from core.llm.qwen import call_qwen_json

AtomicFact = dict[str, object]
TransitionFact = dict[str, str]

MAX_CONFIDENCE = 1.0

# Explicit "from X to Y" transition language. Each pattern captures the prior value in
# group 1 and the current value in group 2, stopping the current value before a trailing
# purpose/reason clause ("... for storage", "... because ...") or sentence punctuation.
_VALUE = r"(.+?)"
_STOP = r"(?=\s+for\b|\s+because\b|\s+since\b|[.!?]|$)"
_TRANSITION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(rf"\bswitched\s+from\s+{_VALUE}\s+to\s+{_VALUE}{_STOP}", re.IGNORECASE),
    re.compile(rf"\bmigrated\s+from\s+{_VALUE}\s+to\s+{_VALUE}{_STOP}", re.IGNORECASE),
    re.compile(rf"\bmoved\s+from\s+{_VALUE}\s+to\s+{_VALUE}{_STOP}", re.IGNORECASE),
    re.compile(rf"\bchanged\s+from\s+{_VALUE}\s+to\s+{_VALUE}{_STOP}", re.IGNORECASE),
    re.compile(rf"\breplaced\s+{_VALUE}\s+with\s+{_VALUE}{_STOP}", re.IGNORECASE),
    re.compile(
        rf"\bused\s+to\s+use\s+{_VALUE}[,.]?\s+(?:but\s+)?now\s+"
        rf"(?:i\s+|we\s+|they\s+|you\s+)?use[sd]?\s+{_VALUE}{_STOP}",
        re.IGNORECASE,
    ),
)
# Canonical predicate assigned to transition pairs; resolves against the seeded registry
# so both facts share a matchable canonical form.
_TRANSITION_PREDICATE = "uses"
_TRANSITION_SUBJECT = "user"
_TRANSITION_CONFIDENCE = 0.9
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


def detect_transitions(content: str) -> list[TransitionFact]:
    """Detect explicit "from X to Y" transitions and return prior/current value pairs.

    This handles only explicit transition language, where a single sentence names both
    the old and the new value. Such sentences would otherwise be extracted as one fact
    with both values crammed into the object, giving change detection nothing to pair.
    Implicit conflicts across separate statements are left to the general canonical
    pairing path. Returns an empty list when no transition pattern is present, so the
    ordinary extraction path is unaffected.
    """
    if not content.strip():
        return []
    transitions: list[TransitionFact] = []
    seen: set[tuple[str, str]] = set()
    for pattern in _TRANSITION_PATTERNS:
        for match in pattern.finditer(content):
            prior = _clean_transition_value(match.group(1))
            current = _clean_transition_value(match.group(2))
            if not prior or not current:
                continue
            key = (prior.casefold(), current.casefold())
            if key in seen or prior.casefold() == current.casefold():
                continue
            seen.add(key)
            transitions.append(
                {
                    "subject": _TRANSITION_SUBJECT,
                    "predicate": _TRANSITION_PREDICATE,
                    "prior_object": prior,
                    "current_object": current,
                }
            )
    return transitions


def _clean_transition_value(value: str) -> str:
    cleaned = value.strip().strip(".,;:!?")
    lowered = cleaned.casefold()
    for article in ("the ", "a ", "an "):
        if lowered.startswith(article):
            cleaned = cleaned[len(article) :]
            break
    return cleaned.strip()


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
