"""Deterministic runtime trust checks kept separate from retrieval relevance."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import TypedDict

AUTHORITY_DIRECT_USER = "direct_user"
AUTHORITY_EXTERNAL_UNVERIFIED = "external_unverified"
AUTHORITY_MODEL_GENERATED = "model_generated"
AUTHORITY_PROVISIONAL_SESSION = "provisional_session"
AUTHORITY_DERIVED_VALIDATED = "derived_validated"
FRESHNESS_CURRENT = "current"
FRESHNESS_EXPIRED = "expired"
FRESHNESS_FUTURE = "future"
FRESHNESS_STALE = "stale"
FRESHNESS_UNSPECIFIED = "unspecified"
RUNTIME_TRUSTED = "trusted"
RUNTIME_CONDITIONAL = "conditional"
RUNTIME_UNTRUSTED = "untrusted"
RUNTIME_INELIGIBLE = "ineligible"
VERDICT_VERIFIED = "verified"
VERDICT_UNCERTAIN = "uncertain"
VERDICT_INSUFFICIENT = "insufficient"


class TrustAssessment(TypedDict):
    relevance_score: float
    trust_score: float
    authority_class: str
    provenance_complete: bool
    freshness_state: str
    verification_state: str
    prompt_eligible: bool
    reason: str


AUTHORITY_SCORES = {
    "direct_observation": 0.95,
    "structured_derivation": 0.82,
    "temporal_derivation": 0.78,
    "promoted_working_memory": 0.72,
    "session_context": 0.70,
    "synthesized_reflection": 0.68,
    "community_synthesis": 0.62,
    "document_source": 0.88,
    "untrusted_observation": 0.25,
    "unknown": 0.40,
}
INACTIVE_STATUSES = frozenset(
    {"archived", "forgotten", "stale", "invalidated", "superseded", "expired"}
)


def assess_evidence(item: dict[str, object]) -> TrustAssessment:
    """Assess whether a relevant candidate is safe to place in an answer prompt."""
    record = {**item, **_mapping(item.get("record"))}
    authority = _mapping(item.get("authority"))
    authority_class = str(
        authority.get("class")
        or item.get("authority_class")
        or _authority_for_source(str(item.get("source", "")), record)
    )
    authority_score = _number(authority.get("score"), AUTHORITY_SCORES.get(authority_class, 0.4))
    freshness = _number(item.get("freshness_score"), _number(item.get("recency_score"), 0.0))
    relevance = _number(item.get("relevance_score"), _number(item.get("score"), 0.0))
    lifecycle = _mapping(item.get("memory_state"))
    lifecycle_status = str(lifecycle.get("lifecycle_status", item.get("status", "active")))
    provenance = _mapping(item.get("provenance"))
    provenance_complete = _provenance_complete(str(item.get("source", "")), record, provenance)
    freshness_state = "fresh" if freshness >= 0.5 else ("aging" if freshness >= 0.2 else "stale")
    verification_state = (
        "verified" if _number(lifecycle.get("verification_count")) > 0 else "unverified"
    )
    trust = _number(item.get("trust_score"), _fallback_trust(authority_score, freshness, lifecycle))
    eligible = lifecycle_status not in INACTIVE_STATUSES and provenance_complete and trust >= 0.25
    reason = "eligible"
    if lifecycle_status in INACTIVE_STATUSES:
        reason = f"inactive_status:{lifecycle_status}"
    elif not provenance_complete:
        reason = "incomplete_provenance"
    elif trust < 0.25:
        reason = "low_runtime_trust"
    return {
        "relevance_score": relevance,
        "trust_score": trust,
        "authority_class": authority_class,
        "provenance_complete": provenance_complete,
        "freshness_state": freshness_state,
        "verification_state": verification_state,
        "prompt_eligible": eligible,
        "reason": reason,
    }


def verify_before_answer(
    query_or_items: str | list[dict[str, object]],
    evidence: list[dict[str, object]] | None = None,
    *,
    now: object = None,
    expected_workspace_id: str | None = None,
    max_age_seconds: float | None = None,
    require_query_coverage: bool = True,
    min_prompt_evidence: int = 1,
    allow_conditional: bool = False,
    require_evidence: bool | None = None,
) -> dict[str, object]:
    """Return eligible evidence and an explicit uncertainty verdict.

    This is bounded and deterministic. It does not make another model call, and it
    never changes the relevance ordering supplied by retrieval.
    """
    if isinstance(query_or_items, str):
        query = query_or_items
        items = evidence or []
    else:
        query = ""
        items = query_or_items
    assessed: list[dict[str, object]] = []
    eligible: list[dict[str, object]] = []
    for item in items:
        enriched = annotate_evidence(
            item,
            now=now,
            expected_workspace_id=expected_workspace_id,
            max_age_seconds=max_age_seconds,
        )
        assessment = enriched.get("trust", {})
        if not isinstance(assessment, dict):
            assessment = assess_evidence(item)
            enriched.update(assessment)
        assessed.append(enriched)
        if bool(assessment.get("prompt_eligible")) or (
            allow_conditional and assessment.get("runtime_trust") == RUNTIME_CONDITIONAL
        ):
            eligible.append(enriched)
    missing: list[str] = []
    if require_query_coverage and query.strip() and eligible:
        query_tokens = {
            token.casefold()
            for token in re.findall(r"[A-Za-z0-9_]+", query)
            if len(token) > 2
            and token.casefold()
            not in {
                "what",
                "which",
                "who",
                "where",
                "when",
                "does",
                "the",
                "are",
                "use",
                "uses",
                "using",
                "do",
            }
        }
        content_tokens = {
            token.casefold()
            for item in eligible
            for token in re.findall(r"[A-Za-z0-9_]+", str(item.get("content", "")))
            if len(token) > 2
        }
        missing = sorted(query_tokens - content_tokens)
    minimum = 0 if require_evidence is False else max(0, min_prompt_evidence)
    if len(eligible) < minimum:
        verdict = VERDICT_INSUFFICIENT
    elif missing or any(
        _mapping(item.get("trust")).get("runtime_trust") == RUNTIME_CONDITIONAL for item in eligible
    ):
        verdict = VERDICT_UNCERTAIN
    else:
        verdict = VERDICT_VERIFIED
    sufficient = verdict == VERDICT_VERIFIED or (not require_query_coverage and bool(eligible))
    if require_evidence is False:
        sufficient = True
    uncertainty = (
        None if sufficient else "No retrieved memory passed runtime trust and provenance checks."
    )
    return {
        "verdict": verdict,
        "uncertain": not sufficient,
        "sufficient": sufficient,
        "verified": True,
        "uncertainty": uncertainty,
        "assessed": assessed,
        "eligible": eligible,
        "prompt_eligible": bool(eligible) and not missing,
        "eligible_count": len(eligible),
        "missing": missing,
        "reasons": [item.get("reason") for item in assessed if item.get("reason") != "eligible"],
        "excluded_count": len(assessed) - len(eligible),
        "instruction": (
            "Use only eligible memory evidence. If it is insufficient, say what is uncertain "
            "and do not state an unverified memory as fact."
        ),
    }


def assess_source_authority(evidence: dict[str, object]) -> str:
    """Classify source authority without changing its relevance score."""
    source = str(evidence.get("source", ""))
    role = str(evidence.get("role") or _record(evidence).get("role", ""))
    if source in {"observations", "recent_observations"}:
        return AUTHORITY_DIRECT_USER if role == "user" else AUTHORITY_MODEL_GENERATED
    if source == "structured_tool" or role == "tool":
        return AUTHORITY_EXTERNAL_UNVERIFIED
    if source == "session_working_set" or str(evidence.get("explicitness_label", "")).lower() in {
        "provisional",
        "ambiguous",
    }:
        return AUTHORITY_PROVISIONAL_SESSION
    if source in {"atomic_facts", "foresight_records", "graph_edge", "graph_path"}:
        return AUTHORITY_DERIVED_VALIDATED
    if source == "document_chunks":
        return "document_source"
    return {
        "reflections": "derived_conditional",
        "reflection": "derived_conditional",
        "community_summary": "derived_conditional",
        "working_memory": "derived_conditional",
    }.get(source, "unknown")


def assess_provenance_completeness(
    evidence: dict[str, object], *, expected_workspace_id: str | None = None
) -> dict[str, object]:
    record = {**evidence, **_record(evidence)}
    source = str(evidence.get("source", ""))
    workspace = evidence.get("workspace_id") or record.get("workspace_id")
    workspace_match = expected_workspace_id is None or workspace == expected_workspace_id
    missing: list[str] = []
    if source in {"observations", "recent_observations"}:
        for key in ("id", "workspace_id"):
            if not record.get(key) and not evidence.get(key):
                missing.append(key)
    elif source == "atomic_facts":
        for key in ("id", "workspace_id"):
            if not record.get(key) and not evidence.get(key):
                missing.append(key)
        if not record.get("source_observation_id") and not _has_active_support(
            record, "atomic_fact"
        ):
            missing.extend(("source_observation_id", "evidence_source"))
    elif source in {"graph_edge", "graph_path"}:
        if not _has_live_observation_support(record, "graph_edge") and not _has_active_support(
            record, "graph_edge"
        ):
            missing.extend(("source_observations", "evidence_source"))
    elif source in {"reflections", "reflection"}:
        if not record.get("id") or not record.get("workspace_id"):
            missing.append("reflection_identity")
        elif not _has_legacy_reflection_support(record) and not _has_active_support(
            record, "reflection"
        ):
            missing.append("evidence_source")
    elif source in {"foresight_records", "foresight"}:
        if not record.get("id") or not record.get("workspace_id"):
            missing.append("foresight_identity")
        elif not _has_live_observation_support(record, "foresight") and not _has_active_support(
            record, "foresight"
        ):
            missing.append("evidence_source")
    elif source == "community_summary" and not (
        evidence.get("member_node_ids") or evidence.get("provenance")
    ):
        missing.append("member_node_ids")
    elif source == "document_chunks":
        provenance = evidence.get("provenance")
        if not isinstance(provenance, dict):
            provenance = {}
        for key in ("chunk_id", "document_id", "knowledge_base_id"):
            if not (evidence.get(key) or record.get(key) or provenance.get(key)):
                missing.append(key)
    if not workspace_match:
        missing.append("workspace_match")
    return {"complete": not missing, "missing": missing, "workspace_match": workspace_match}


def assess_freshness(
    evidence: dict[str, object], *, now: object = None, max_age_seconds: float | None = None
) -> dict[str, object]:
    current = _as_datetime(now)
    valid_from = _parse_datetime(_value(evidence, "valid_from"))
    valid_until = _parse_datetime(_value(evidence, "valid_until") or _value(evidence, "expires_at"))
    if valid_from and valid_from > current:
        value = FRESHNESS_FUTURE
    elif valid_until and valid_until < current:
        value = FRESHNESS_EXPIRED
    else:
        created = _parse_datetime(_value(evidence, "updated_at") or _value(evidence, "created_at"))
        if valid_from or valid_until:
            value = FRESHNESS_CURRENT
        elif created is None:
            value = FRESHNESS_UNSPECIFIED
        elif max_age_seconds is not None and (current - created).total_seconds() > max_age_seconds:
            value = FRESHNESS_STALE
        else:
            value = FRESHNESS_CURRENT
    return {"freshness": value, "as_of": current.isoformat()}


def assess_stability(evidence: dict[str, object]) -> str:
    source = str(evidence.get("source", ""))
    if source in {
        "atomic_facts",
        "graph_edge",
        "community_summary",
        "reflections",
        "reflection",
        "document_chunks",
    }:
        return "durable_derived"
    if source == "session_working_set":
        return "current_session"
    return "direct_statement"


def assess_runtime_trust(
    evidence: dict[str, object],
    *,
    now: object = None,
    expected_workspace_id: str | None = None,
    max_age_seconds: float | None = None,
) -> dict[str, object]:
    authority = assess_source_authority(evidence)
    provenance = assess_provenance_completeness(
        evidence, expected_workspace_id=expected_workspace_id
    )
    freshness = assess_freshness(evidence, now=now, max_age_seconds=max_age_seconds)
    status = str(evidence.get("status") or _record(evidence).get("status", "active"))
    if status in INACTIVE_STATUSES:
        runtime = RUNTIME_INELIGIBLE
        freshness = {**freshness, "freshness": "invalid"}
    elif not provenance["complete"]:
        runtime = (
            RUNTIME_INELIGIBLE if provenance["workspace_match"] is False else RUNTIME_CONDITIONAL
        )
    elif authority in {AUTHORITY_MODEL_GENERATED, AUTHORITY_EXTERNAL_UNVERIFIED}:
        runtime = RUNTIME_UNTRUSTED
    elif authority in {AUTHORITY_PROVISIONAL_SESSION, "derived_conditional"}:
        runtime = RUNTIME_CONDITIONAL
    else:
        runtime = RUNTIME_TRUSTED
    prompt_eligible = runtime == RUNTIME_TRUSTED and freshness["freshness"] not in {
        FRESHNESS_EXPIRED,
        FRESHNESS_FUTURE,
        FRESHNESS_STALE,
        "invalid",
    }
    return {
        "runtime_trust": runtime,
        "prompt_eligible": prompt_eligible,
        "relevance_score": _number(evidence.get("score"), _number(evidence.get("relevance_score"))),
        "source_authority_class": "derived_validated"
        if authority == AUTHORITY_DERIVED_VALIDATED
        else authority,
        "provenance": provenance,
        "freshness": freshness,
        "stability_class": assess_stability(evidence),
    }


def is_prompt_eligible(
    evidence: dict[str, object],
    *,
    now: object = None,
    expected_workspace_id: str | None = None,
    max_age_seconds: float | None = None,
    allow_conditional: bool = False,
) -> bool:
    assessment = assess_runtime_trust(
        evidence,
        now=now,
        expected_workspace_id=expected_workspace_id,
        max_age_seconds=max_age_seconds,
    )
    return bool(assessment["prompt_eligible"]) or (
        allow_conditional and assessment["runtime_trust"] == RUNTIME_CONDITIONAL
    )


def annotate_evidence(
    evidence: dict[str, object],
    *,
    now: object = None,
    expected_workspace_id: str | None = None,
    max_age_seconds: float | None = None,
) -> dict[str, object]:
    annotated = dict(evidence)
    annotated["trust"] = assess_runtime_trust(
        annotated,
        now=now,
        expected_workspace_id=expected_workspace_id,
        max_age_seconds=max_age_seconds,
    )
    return annotated


def _record(evidence: dict[str, object]) -> dict[str, object]:
    record = evidence.get("record")
    return record if isinstance(record, dict) else {}


def _mapping(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _value(evidence: dict[str, object], key: str) -> object:
    value = evidence.get(key)
    if value is not None:
        return value
    return _record(evidence).get(key)


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _as_datetime(value: object) -> datetime:
    parsed = _parse_datetime(value)
    return parsed or datetime.now(UTC)


def _authority_for_source(source: str, record: dict[str, object]) -> str:
    if source in {"observations", "recent_observations"}:
        return (
            "direct_observation"
            if str(record.get("role", "user")) == "user"
            else "untrusted_observation"
        )
    return {
        "atomic_facts": "structured_derivation",
        "foresight_records": "temporal_derivation",
        "reflections": "synthesized_reflection",
        "community_summary": "community_synthesis",
        "working_memory": "promoted_working_memory",
    }.get(source, "unknown")


def _provenance_complete(
    source: str,
    record: dict[str, object],
    provenance: dict[str, object],
) -> bool:
    if source in {"observations", "recent_observations"}:
        return bool(record.get("id") and record.get("workspace_id") and record.get("session_id"))
    if source == "atomic_facts":
        return bool(
            record.get("id")
            and record.get("workspace_id")
            and (record.get("source_observation_id") or _has_active_support(record, "atomic_fact"))
        )
    if source == "graph_edge":
        return bool(
            record.get("id")
            and record.get("workspace_id")
            and (
                _has_live_observation_support(record, "graph_edge")
                or _has_active_support(record, "graph_edge")
            )
        )
    if source in {"reflections", "reflection"}:
        return bool(
            record.get("id")
            and record.get("workspace_id")
            and (
                _has_legacy_reflection_support(record) or _has_active_support(record, "reflection")
            )
        )
    if source in {"foresight_records", "foresight"}:
        return bool(
            record.get("id")
            and record.get("workspace_id")
            and (
                _has_live_observation_support(record, "foresight")
                or _has_active_support(record, "foresight")
            )
        )
    if source in {"working_memory", "community_summary"}:
        return bool(provenance.get("record_id") or record.get("id"))
    return True


def _has_active_support(record: dict[str, object], target_type: str) -> bool:
    record_id = record.get("id")
    workspace_id = record.get("workspace_id")
    if not isinstance(record_id, str) or not isinstance(workspace_id, str):
        return False
    try:
        from core.db.evidence import list_active_evidence

        return any(
            item.get("stance") == "support"
            for item in list_active_evidence(target_type, record_id, workspace_id=workspace_id)
        )
    except Exception:
        return False


def _has_live_observation_support(record: dict[str, object], target_type: str) -> bool:
    workspace_id = record.get("workspace_id")
    if not isinstance(workspace_id, str):
        return False
    identifiers: list[str] = []
    if target_type == "foresight" and record.get("source_observation_id"):
        identifiers.append(str(record["source_observation_id"]))
    raw = record.get("source_observations_json")
    if isinstance(raw, str):
        try:
            values = json.loads(raw)
        except ValueError:
            values = []
        if isinstance(values, list):
            identifiers.extend(str(value) for value in values if value)
    else:
        source_observations = record.get("source_observations")
        if isinstance(source_observations, list):
            identifiers.extend(str(value) for value in source_observations if value)
    if not identifiers:
        return False
    from core.db.repositories import repository_connection

    placeholders = ", ".join("?" for _ in set(identifiers))
    with repository_connection() as connection:
        return (
            connection.execute(
                "SELECT 1 FROM observations AS o JOIN sessions AS s "
                "ON s.id = o.session_id AND s.workspace_id = o.workspace_id "
                f"WHERE o.workspace_id = ? AND s.status != 'deleted' AND o.id IN ({placeholders}) "  # nosec B608 - IDs remain bound below
                "LIMIT 1",
                (workspace_id, *sorted(set(identifiers))),
            ).fetchone()
            is not None
        )


def _has_legacy_reflection_support(record: dict[str, object]) -> bool:
    record_id = record.get("id")
    workspace_id = record.get("workspace_id")
    if not isinstance(record_id, str) or not isinstance(workspace_id, str):
        return False
    from core.db.repositories import repository_connection

    with repository_connection() as connection:
        return (
            connection.execute(
                "SELECT 1 FROM reflection_evidence AS e "
                "JOIN observations AS o ON o.id = e.observation_id "
                "AND o.workspace_id = ? JOIN sessions AS s ON s.id = o.session_id "
                "AND s.workspace_id = o.workspace_id AND s.status != 'deleted' "
                "WHERE e.reflection_id = ? LIMIT 1",
                (workspace_id, record_id),
            ).fetchone()
            is not None
        )


def _fallback_trust(authority: float, freshness: float, state: dict[str, object]) -> float:
    success = _number(state.get("successful_uses"))
    failure = _number(state.get("failed_uses"))
    outcome = success / (success + failure) if success + failure else 0.5
    return round(
        max(
            0.0,
            min(
                1.0,
                0.45 * authority
                + 0.25 * freshness
                + 0.2 * outcome
                + 0.1 * _number(state.get("retention_score"), 0.5),
            ),
        ),
        6,
    )


def _number(value: object, default: float = 0.0) -> float:
    return float(value) if isinstance(value, int | float) else default
