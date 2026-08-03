"""Bounded discourse-reference resolution for memory-changing turns."""

from __future__ import annotations

import re
from typing import TypedDict

from core.llm.prompts import render_prompt
from core.llm.qwen import LLMClientError, call_qwen_json
from core.retrieval.quick import retrieve_quick
from core.session.working_set import list_active_session_items

ReferenceCandidate = dict[str, object]


class ReferenceResolution(TypedDict):
    """A validated decision about what a deictic memory operation targets."""

    status: str
    target_observation_id: str | None
    target_content: str | None
    source: str | None
    confidence: float
    reason: str
    clarification: str | None
    candidate_ids: list[str]


_EXPLICIT_IMMEDIATE_RE = re.compile(
    r"\b(?:"
    r"what\s+i\s+just\s+(?:said|told\s+you)|"
    r"(?:my|the)\s+(?:last|previous)\s+(?:message|remark|statement|thing)|"
    r"last\s+thing\s+i\s+said|"
    r"just\s+said"
    r")\b",
    re.IGNORECASE,
)


def resolve_discourse_reference(
    session_id: str,
    message: str,
    recent_turns: list[dict[str, object]],
) -> ReferenceResolution:
    """Resolve a memory-changing reference against a bounded, explicit candidate set."""
    recent_candidates = _recent_user_candidates(recent_turns)
    if _explicitly_targets_immediate_turn(message):
        if recent_candidates:
            return _resolved(
                recent_candidates[0],
                confidence=0.99,
                reason="The user explicitly referred to their immediately preceding turn.",
                candidates=recent_candidates,
            )
        return _unresolved([], "There is no preceding user turn to resolve.")

    candidates = _deduplicate_candidates(
        [
            *recent_candidates,
            *_working_set_candidates(session_id),
            *_durable_candidates(session_id, message),
        ]
    )
    if not candidates:
        return _unresolved([], "No prior statement matching the reference was found.")

    if len(candidates) == 1 and _reference_has_named_subject(message, candidates[0]):
        return _resolved(
            candidates[0],
            confidence=0.9,
            reason="Only one candidate matches the subject named by the user.",
            candidates=candidates,
        )

    return _resolve_with_llm(message, recent_turns, candidates)


def _recent_user_candidates(recent_turns: list[dict[str, object]]) -> list[ReferenceCandidate]:
    candidates: list[ReferenceCandidate] = []
    for turn in reversed(recent_turns[-6:]):
        if turn.get("role") != "user":
            continue
        observation_id = turn.get("id")
        content = turn.get("content")
        if not isinstance(observation_id, str) or not isinstance(content, str):
            continue
        candidates.append(
            {
                "id": f"observation:{observation_id}",
                "target_observation_id": observation_id,
                "content": content,
                "source": "recent_conversation",
            }
        )
    return candidates


def _working_set_candidates(session_id: str) -> list[ReferenceCandidate]:
    candidates: list[ReferenceCandidate] = []
    for item in list_active_session_items(session_id):
        sources = item.get("source_observations")
        source_ids = (
            [value for value in sources if isinstance(value, str)]
            if isinstance(sources, list)
            else []
        )
        content = item.get("content")
        item_id = item.get("id")
        if not source_ids or not isinstance(content, str) or not isinstance(item_id, str):
            continue
        candidates.append(
            {
                "id": f"working_set:{item_id}",
                "target_observation_id": source_ids[-1],
                "content": content,
                "source": "session_working_set",
            }
        )
    return candidates


def _durable_candidates(session_id: str, message: str) -> list[ReferenceCandidate]:
    candidates: list[ReferenceCandidate] = []
    try:
        evidence = retrieve_quick(message, session_id, limit=6)
    except Exception:  # noqa: BLE001 - reference resolution must fail closed
        return []
    for record in evidence:
        target_id = _source_observation_id(record)
        source_id = record.get("source_id")
        content = record.get("content")
        if target_id is None or not isinstance(source_id, str) or not isinstance(content, str):
            continue
        candidates.append(
            {
                "id": f"{record.get('source', 'memory')}:{source_id}",
                "target_observation_id": target_id,
                "content": content,
                "source": str(record.get("source", "durable_memory")),
            }
        )
    return candidates


def _source_observation_id(record: dict[str, object]) -> str | None:
    source = str(record.get("source", ""))
    source_id = record.get("source_id")
    if source in {"observations", "recent_observations"} and isinstance(source_id, str):
        return source_id
    raw_record = record.get("record")
    if isinstance(raw_record, dict):
        source_observation_id = raw_record.get("source_observation_id")
        if isinstance(source_observation_id, str):
            return source_observation_id
    return None


def _deduplicate_candidates(candidates: list[ReferenceCandidate]) -> list[ReferenceCandidate]:
    deduplicated: dict[str, ReferenceCandidate] = {}
    for candidate in candidates:
        target_id = candidate.get("target_observation_id")
        if isinstance(target_id, str) and target_id not in deduplicated:
            deduplicated[target_id] = candidate
    return list(deduplicated.values())[:10]


def _resolve_with_llm(
    message: str,
    recent_turns: list[dict[str, object]],
    candidates: list[ReferenceCandidate],
) -> ReferenceResolution:
    public_candidates = [
        {
            "id": candidate["id"],
            "source": candidate["source"],
            "content": candidate["content"],
        }
        for candidate in candidates
    ]
    prompt = render_prompt(
        "discourse_reference_resolution",
        {
            "latest_message": message,
            "recent_turns": recent_turns[-6:],
            "candidates": public_candidates,
        },
    )
    try:
        response = call_qwen_json(
            [{"role": "user", "content": prompt}],
            schema_name="discourse_reference_resolution",
        )
    except LLMClientError:
        return _unresolved(candidates, "The reference could not be resolved safely.")
    payload = response.get("json")
    if not isinstance(payload, dict):
        return _unresolved(candidates, "The reference resolver returned an invalid decision.")

    status = str(payload.get("status", "")).casefold()
    selected_id = str(payload.get("target_id", "")).strip()
    confidence = _bounded_confidence(payload.get("confidence"))
    selected = next(
        (candidate for candidate in candidates if candidate.get("id") == selected_id),
        None,
    )
    if status == "resolved" and selected is not None and confidence >= 0.82:
        return _resolved(
            selected,
            confidence=confidence,
            reason=str(payload.get("reason", "The bounded resolver selected this candidate.")),
            candidates=candidates,
        )
    reason = str(payload.get("reason", "The reference is ambiguous."))
    return _ambiguous(candidates, reason)


def _explicitly_targets_immediate_turn(message: str) -> bool:
    normalized = " ".join(message.casefold().strip(" .!?").split())
    return bool(_EXPLICIT_IMMEDIATE_RE.search(normalized))


def _reference_has_named_subject(message: str, candidate: ReferenceCandidate) -> bool:
    message_tokens = _content_tokens(message)
    candidate_tokens = _content_tokens(str(candidate.get("content", "")))
    return len(message_tokens & candidate_tokens) >= 2


def _content_tokens(value: str) -> set[str]:
    ignored = {
        "actually",
        "and",
        "disregard",
        "drop",
        "forget",
        "ignore",
        "it",
        "please",
        "that",
        "the",
        "this",
        "what",
    }
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.casefold())
        if len(token) > 2 and token not in ignored
    }


def _resolved(
    candidate: ReferenceCandidate,
    *,
    confidence: float,
    reason: str,
    candidates: list[ReferenceCandidate],
) -> ReferenceResolution:
    return {
        "status": "resolved",
        "target_observation_id": str(candidate["target_observation_id"]),
        "target_content": str(candidate["content"]),
        "source": str(candidate["source"]),
        "confidence": confidence,
        "reason": reason,
        "clarification": None,
        "candidate_ids": [str(value["id"]) for value in candidates],
    }


def _ambiguous(
    candidates: list[ReferenceCandidate],
    reason: str,
) -> ReferenceResolution:
    descriptions = [str(candidate["content"]).strip() for candidate in candidates[:2]]
    if len(descriptions) >= 2:
        clarification = (
            f'Which statement should I disregard: "{descriptions[0]}" or "{descriptions[1]}"?'
        )
    else:
        clarification = "Which earlier statement should I disregard?"
    return {
        "status": "ambiguous",
        "target_observation_id": None,
        "target_content": None,
        "source": None,
        "confidence": 0.0,
        "reason": reason,
        "clarification": clarification,
        "candidate_ids": [str(value["id"]) for value in candidates],
    }


def _unresolved(
    candidates: list[ReferenceCandidate],
    reason: str,
) -> ReferenceResolution:
    return {
        "status": "unresolved",
        "target_observation_id": None,
        "target_content": None,
        "source": None,
        "confidence": 0.0,
        "reason": reason,
        "clarification": "Which earlier statement should I disregard?",
        "candidate_ids": [str(value["id"]) for value in candidates],
    }


def _bounded_confidence(value: object) -> float:
    try:
        return max(0.0, min(1.0, float(str(value))))
    except ValueError:
        return 0.0
