"""Quick Mode direct fact retrieval across vectors, keywords, and records.

Ownership: Jerry.
Related issue: ISSUE-034.
Architecture area: retrieval.
"""

from __future__ import annotations

import re

from core.db.repositories import repository_connection
from core.retrieval.keyword import keyword_search_atomic_facts, keyword_search_observations
from core.retrieval.vector import vector_search

Evidence = dict[str, object]

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_'-]+")
ACTIVE_STATUS_SCORE = {"active": 1.0, "pending": 0.8, "resolved": 0.4}
FORESIGHT_QUERY_MARKERS = frozenset(
    {
        "deadline",
        "due",
        "time-sensitive",
        "time sensitive",
        "remind",
        "upcoming",
        "next",
        "schedule",
    }
)


def retrieve_quick(query: str, session_id: str | None, limit: int) -> list[Evidence]:
    """Retrieve prompt-ready direct evidence for specific factual questions."""
    if limit < 1:
        raise ValueError("limit must be a positive integer")
    if not query.strip():
        return []

    candidates = [
        *_semantic_candidates(query, limit),
        *_keyword_observation_candidates(query, session_id, limit),
        *_atomic_fact_candidates(query, session_id, limit),
        *_foresight_candidates(query, session_id),
        *_recent_observation_candidates(query, session_id, limit),
    ]
    deduplicated = _merge_duplicates(candidates)
    ranked = sorted(deduplicated, key=_ranking_key)
    return ranked[:limit]


def quick_retrieve(query: str, limit: int = 8) -> list[Evidence]:
    """Retrieve direct fact candidates without session scoping."""
    return retrieve_quick(query, session_id=None, limit=limit)


def _semantic_candidates(query: str, limit: int) -> list[Evidence]:
    candidates: list[Evidence] = []
    pointers = vector_search(query, limit=limit, collections=("observations", "reflections"))
    for pointer in pointers:
        record = _fetch_record(str(pointer["sqlite_table"]), str(pointer["sqlite_id"]))
        if record is None:
            continue
        if not _semantic_record_is_active(str(pointer["sqlite_table"]), record):
            continue
        candidates.append(
            _evidence(
                source=str(pointer["sqlite_table"]),
                source_id=str(pointer["sqlite_id"]),
                content=_record_content(str(pointer["sqlite_table"]), record),
                semantic_score=max(0.0, 1.0 - _float(pointer.get("distance"), 1.0)),
                keyword_score=0.0,
                recency=_recency_score(record),
                confidence=_confidence(record),
                status=str(record.get("status", "active")),
                record=record,
            )
        )
    return candidates


def _keyword_observation_candidates(
    query: str,
    session_id: str | None,
    limit: int,
) -> list[Evidence]:
    results = keyword_search_observations(query, limit)
    return [
        _evidence(
            source="observations",
            source_id=str(record["id"]),
            content=str(record["content"]),
            semantic_score=0.0,
            keyword_score=_normalized_keyword_score(record),
            recency=_recency_score(record),
            confidence=1.0,
            status="active",
            record=record,
        )
        for record in results
        if _session_matches(record, session_id)
    ]


def _atomic_fact_candidates(query: str, session_id: str | None, limit: int) -> list[Evidence]:
    results = keyword_search_atomic_facts(query, limit)
    return [
        _evidence(
            source="atomic_facts",
            source_id=str(record["id"]),
            content=_fact_content(record),
            semantic_score=0.0,
            keyword_score=_normalized_keyword_score(record),
            recency=_recency_score(record),
            confidence=_confidence(record),
            status=str(record.get("status", "active")),
            record=record,
        )
        for record in results
        if _fact_session_matches(record, session_id)
    ]


def _foresight_candidates(query: str, session_id: str | None) -> list[Evidence]:
    tokens = _tokens(query)
    if not tokens:
        return []
    is_foresight_query = _is_foresight_query(query)
    rows = _fetch_foresight_rows(session_id)
    candidates: list[Evidence] = []
    for record in rows:
        content = str(record["content"])
        keyword_score = _lexical_score(tokens, content)
        if keyword_score <= 0.0 and not is_foresight_query:
            continue
        candidates.append(
            _evidence(
                source="foresight_records",
                source_id=str(record["id"]),
                content=content,
                semantic_score=0.0,
                keyword_score=max(keyword_score, 0.9 if is_foresight_query else 0.0),
                recency=_recency_score(record),
                confidence=1.0,
                status=str(record["status"]),
                record=record,
            )
        )
    return candidates


def _recent_observation_candidates(
    query: str,
    session_id: str | None,
    limit: int,
) -> list[Evidence]:
    if session_id is None:
        return []
    tokens = _tokens(query)
    rows = _fetch_recent_observations(session_id, limit * 3)
    candidates: list[Evidence] = []
    for record in rows:
        content = str(record["content"])
        keyword_score = _lexical_score(tokens, content)
        if keyword_score <= 0.0:
            continue
        candidates.append(
            _evidence(
                source="recent_observations",
                source_id=str(record["id"]),
                content=content,
                semantic_score=0.0,
                keyword_score=keyword_score,
                recency=_recency_score(record),
                confidence=1.0,
                status="active",
                record=record,
            )
        )
    return candidates


def _merge_duplicates(candidates: list[Evidence]) -> list[Evidence]:
    merged: dict[str, Evidence] = {}
    for candidate in candidates:
        key = str(candidate["source_id"])
        existing = merged.get(key)
        if existing is None:
            candidate["sources"] = [candidate["source"]]
            merged[key] = candidate
            continue
        existing["semantic_score"] = max(
            _float(existing["semantic_score"]),
            _float(candidate["semantic_score"]),
        )
        existing["keyword_score"] = max(
            _float(existing["keyword_score"]),
            _float(candidate["keyword_score"]),
        )
        existing["recency_score"] = max(
            _float(existing["recency_score"]),
            _float(candidate["recency_score"]),
        )
        existing["confidence"] = max(
            _float(existing["confidence"]),
            _float(candidate["confidence"]),
        )
        existing["score"] = _combined_score(existing)
        existing_sources = _string_list(existing.get("sources"))
        source = str(candidate["source"])
        if source not in existing_sources:
            existing_sources.append(source)
        existing["sources"] = existing_sources
    return list(merged.values())


def _evidence(
    *,
    source: str,
    source_id: str,
    content: str,
    semantic_score: float,
    keyword_score: float,
    recency: float,
    confidence: float,
    status: str,
    record: dict[str, object],
) -> Evidence:
    evidence = {
        "source": source,
        "source_id": source_id,
        "content": content,
        "semantic_score": semantic_score,
        "keyword_score": keyword_score,
        "recency_score": recency,
        "confidence": confidence,
        "status": status,
        "record": dict(record),
    }
    evidence["score"] = _combined_score(evidence)
    return evidence


def _combined_score(evidence: Evidence) -> float:
    status = str(evidence.get("status", "active"))
    status_score = ACTIVE_STATUS_SCORE.get(status, 0.6)
    return (
        (_float(evidence.get("semantic_score")) * 0.4)
        + (_float(evidence.get("keyword_score")) * 0.3)
        + (_float(evidence.get("recency_score")) * 0.1)
        + (_float(evidence.get("confidence")) * 0.15)
        + (status_score * 0.05)
    )


def _ranking_key(evidence: Evidence) -> tuple[float, float, float, float, str]:
    return (
        -_float(evidence["score"]),
        -_float(evidence["semantic_score"]),
        -_float(evidence["keyword_score"]),
        -_float(evidence["confidence"]),
        str(evidence["source_id"]),
    )


def _fetch_record(table: str, record_id: str) -> dict[str, object] | None:
    if table not in {"observations", "reflections"}:
        return None
    with repository_connection() as connection:
        row = connection.execute(
            f"SELECT * FROM {table} WHERE id = ?",  # nosec B608
            (record_id,),
        ).fetchone()
    return None if row is None else dict(row)


def _semantic_record_is_active(table: str, record: dict[str, object]) -> bool:
    """Keep observations (immutable evidence); drop non-active reflections.

    Stale, invalidated, or superseded reflections must stop controlling current
    reasoning (paper, Reflection Validity Update). The vector index still points at
    them, so they are filtered here rather than being surfaced with a soft penalty.
    """
    if table != "reflections":
        return True
    return str(record.get("status", "active")) == "active"


def _fetch_foresight_rows(session_id: str | None) -> list[dict[str, object]]:
    with repository_connection() as connection:
        if session_id is None:
            rows = connection.execute(
                "SELECT * FROM foresight_records WHERE status IN (?, ?) ORDER BY created_at DESC",
                ("active", "pending"),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT foresight_records.*
                FROM foresight_records
                JOIN observations ON observations.id = foresight_records.source_observation_id
                WHERE foresight_records.status IN (?, ?) AND observations.session_id = ?
                ORDER BY foresight_records.created_at DESC
                """,
                ("active", "pending", session_id),
            ).fetchall()
    return [dict(row) for row in rows]


def _fetch_recent_observations(session_id: str, limit: int) -> list[dict[str, object]]:
    with repository_connection() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM observations
            WHERE session_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def _record_content(table: str, record: dict[str, object]) -> str:
    if table == "observations":
        return str(record["content"])
    if table == "reflections":
        return str(record["content"])
    return ""


def _fact_content(record: dict[str, object]) -> str:
    return f"{record['subject']} {record['predicate']} {record['object']}"


def _session_matches(record: dict[str, object], session_id: str | None) -> bool:
    return session_id is None or record.get("session_id") == session_id


def _fact_session_matches(record: dict[str, object], session_id: str | None) -> bool:
    if session_id is None:
        return True
    source_observation_id = str(record["source_observation_id"])
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT session_id FROM observations WHERE id = ?",
            (source_observation_id,),
        ).fetchone()
    return row is not None and row["session_id"] == session_id


def _normalized_keyword_score(record: dict[str, object]) -> float:
    return min(1.0, _float(record.get("score")) / 10.0)


def _recency_score(record: dict[str, object]) -> float:
    return 1.0 if record.get("created_at") else 0.0


def _confidence(record: dict[str, object]) -> float:
    return _float(record.get("confidence", 1.0), 1.0)


def _lexical_score(query_tokens: set[str], content: str) -> float:
    content_tokens = _tokens(content)
    if not query_tokens or not content_tokens:
        return 0.0
    return len(query_tokens & content_tokens) / len(query_tokens)


def _tokens(value: str) -> set[str]:
    stopwords = {"a", "about", "did", "i", "is", "my", "the", "what", "when"}
    return {
        token
        for token in TOKEN_PATTERN.findall(value.casefold())
        if len(token) > 1 and token not in stopwords
    }


def _is_foresight_query(query: str) -> bool:
    normalized = query.casefold()
    return any(marker in normalized for marker in FORESIGHT_QUERY_MARKERS)


def _float(value: object, default: float = 0.0) -> float:
    if isinstance(value, int | float):
        return float(value)
    return default


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
