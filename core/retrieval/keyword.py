"""Lightweight keyword retrieval over SQLite source records.

Ownership: Kelechi.
Related issue: ISSUE-033.
Architecture area: retrieval.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from core.db.repositories import repository_connection

Record = dict[str, object]

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_'-]+")


def keyword_search_observations(query: str, limit: int) -> list[Record]:
    """Search raw observations with exact phrase and token scoring."""
    terms = _query_terms(query)
    _validate_limit(limit)
    if not terms.normalized_query:
        return []

    rows = _fetch_observation_candidates(terms)
    scored = [
        _with_score(dict(row), _score_text(str(row["content"]), terms), "observation")
        for row in rows
    ]
    return _top_results(scored, limit)


def keyword_search_atomic_facts(query: str, limit: int) -> list[Record]:
    """Search atomic facts by subject, predicate, and object text."""
    terms = _query_terms(query)
    _validate_limit(limit)
    if not terms.normalized_query:
        return []

    rows = _fetch_atomic_fact_candidates(terms)
    scored = [
        _with_score(
            dict(row),
            _score_text(_fact_search_text(dict(row)), terms),
            "atomic_fact",
        )
        for row in rows
    ]
    return _top_results(scored, limit)


def keyword_search(query: str, limit: int = 8) -> list[Record]:
    """Search observations and atomic facts for compatibility callers."""
    _validate_limit(limit)
    results = [
        *keyword_search_observations(query, limit),
        *keyword_search_atomic_facts(query, limit),
    ]
    return _top_results(results, limit)


class _QueryTerms:
    """Normalized query phrase and tokens used by the keyword scorer."""

    def __init__(self, query: str) -> None:
        self.normalized_query = _normalize(query)
        self.tokens = tuple(dict.fromkeys(TOKEN_PATTERN.findall(self.normalized_query)))


def _query_terms(query: str) -> _QueryTerms:
    return _QueryTerms(query)


def _validate_limit(limit: int) -> None:
    if limit < 1:
        raise ValueError("limit must be a positive integer")


def _fetch_observation_candidates(terms: _QueryTerms) -> list[Record]:
    clauses, parameters = _like_clauses(("content",), terms)
    if not clauses:
        return []
    statement = f"""
        SELECT id, session_id, role, content, source, metadata_json, created_at, processed_at
        FROM observations
        WHERE {" OR ".join(clauses)}
        ORDER BY created_at DESC
        """  # nosec B608
    with repository_connection() as connection:
        rows = connection.execute(statement, parameters).fetchall()
    return [dict(row) for row in rows]


def _fetch_atomic_fact_candidates(terms: _QueryTerms) -> list[Record]:
    clauses, parameters = _like_clauses(("subject", "predicate", "object"), terms)
    if not clauses:
        return []
    statement = f"""
        SELECT id, subject, predicate, object, confidence, status,
               source_observation_id, created_at, valid_from, valid_until
        FROM atomic_facts
        WHERE status = ? AND ({" OR ".join(clauses)})
        ORDER BY created_at DESC
        """  # nosec B608
    with repository_connection() as connection:
        rows = connection.execute(statement, ("active", *parameters)).fetchall()
    return [dict(row) for row in rows]


def _like_clauses(
    columns: Iterable[str],
    terms: _QueryTerms,
) -> tuple[list[str], tuple[object, ...]]:
    clauses: list[str] = []
    parameters: list[object] = []
    patterns = (terms.normalized_query, *terms.tokens)
    for column in columns:
        for pattern in patterns:
            clauses.append(f"LOWER({column}) LIKE ? ESCAPE '\\'")  # nosec B608
            parameters.append(f"%{_escape_like(pattern)}%")
    return clauses, tuple(parameters)


def _score_text(text: str, terms: _QueryTerms) -> float:
    normalized_text = _normalize(text)
    if not normalized_text:
        return 0.0

    score = 0.0
    if terms.normalized_query and terms.normalized_query in normalized_text:
        score += 10.0
    for token in terms.tokens:
        if token in normalized_text:
            score += 1.0
    return score


def _with_score(record: Record, score: float, record_type: str) -> Record:
    enriched = dict(record)
    enriched["score"] = score
    enriched["record_type"] = record_type
    return enriched


def _top_results(results: list[Record], limit: int) -> list[Record]:
    nonzero_results = [result for result in results if _record_score(result) > 0.0]
    return sorted(
        nonzero_results,
        key=lambda result: (
            -_record_score(result),
            str(result.get("created_at", "")),
            str(result["id"]),
        ),
    )[:limit]


def _record_score(record: Record) -> float:
    value = record.get("score", 0.0)
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def _fact_search_text(record: Record) -> str:
    return " ".join(str(record[field]) for field in ("subject", "predicate", "object"))


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
