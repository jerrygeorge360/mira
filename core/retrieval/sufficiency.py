"""Structured retrieval sufficiency check with a single bounded retry.

Ownership: Jerry.
Related issue: ISSUE-038.
Architecture area: retrieval.

A sufficiency check reduces overconfident answers when retrieval misses key
evidence. It is deterministic and cheap: it compares the salient terms of the
query against the retrieved context, reports what is missing, and proposes a
rewritten query. The pipeline is allowed exactly one retry -- never an
indefinite loop; if context is still insufficient after the retry, the caller
should answer with explicit uncertainty.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable

from core.llm.prompts import render_prompt
from core.llm.qwen import LLMClientError, call_qwen_json

Sufficiency = dict[str, object]
RetrievedContext = list[dict[str, object]]
RetrieveFn = Callable[[str], RetrievedContext]

LOGGER = logging.getLogger(__name__)

CONTEXT_TEXT_FIELDS = ("content", "title", "summary", "reason")
ENTITY_PATTERN = re.compile(r"[A-Z][A-Za-z0-9.+#-]{2,}")
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_'+#-]+")
MIN_CONTENT_TERM_LENGTH = 4
QUESTION_WORDS = frozenset(
    {
        "what",
        "what's",
        "when",
        "where",
        "who",
        "why",
        "how",
        "which",
        "did",
        "do",
        "does",
        "are",
        "is",
    }
)
STOPWORDS = frozenset(
    {"a", "an", "the", "to", "of", "for", "on", "in", "and", "my", "me", "i", "we", "about", "with"}
)


def check_retrieval_sufficiency(query: str, retrieved_context: RetrievedContext) -> Sufficiency:
    """Assess whether retrieved context is enough to answer the query."""
    requirements = extract_query_requirements(query)
    requirement_results = [
        _evaluate_requirement(requirement, retrieved_context) for requirement in requirements
    ]
    missing = sorted(
        {
            missing_term
            for result in requirement_results
            if not result["supported"]
            for missing_term in _string_list(result.get("missing"))
        }
    )
    is_sufficient = bool(retrieved_context) and bool(requirement_results) and not missing
    rewrite_query = None if is_sufficient else _rewrite_query(query, missing)
    if not is_sufficient:
        LOGGER.info("Insufficient retrieval for %r; missing=%s", query, missing)
    return {
        "is_sufficient": is_sufficient,
        "missing": missing,
        "rewrite_query": rewrite_query,
        "requirements": requirements,
        "requirement_results": requirement_results,
    }


def extract_query_requirements(query: str) -> list[dict[str, object]]:
    """Extract answer requirements without turning topical similarity into sufficiency."""
    clauses = [
        clause.strip() for clause in re.split(r"\s*(?:,|;|\band\b)\s*", query) if clause.strip()
    ]
    requirements = [_requirement_for_clause(clause) for clause in clauses]
    return requirements or [_requirement_for_clause(query)]


def check_grounded_sufficiency(
    query: str,
    retrieved_context: RetrievedContext,
) -> Sufficiency:
    """Use structured semantic verification for the final evidence decision."""
    deterministic = check_retrieval_sufficiency(query, retrieved_context)
    if not retrieved_context:
        return deterministic

    semantic = _semantic_sufficiency_verdict(query, retrieved_context)
    if semantic is None:
        return deterministic
    semantic_missing = _string_list(semantic.get("missing"))
    return {
        **deterministic,
        "is_sufficient": semantic["is_sufficient"],
        "missing": semantic_missing,
        "rewrite_query": (
            None if semantic["is_sufficient"] else _rewrite_query(query, semantic_missing)
        ),
        "evidence_ids": semantic["evidence_ids"],
        "reason": semantic["reason"],
        "assessment_source": "semantic_grounding",
    }


def resolve_with_one_retry(
    query: str,
    retrieve: RetrieveFn,
    *,
    semantic: bool = False,
) -> Sufficiency:
    """Retrieve, check sufficiency, and retry at most once with a rewritten query.

    Returns the (possibly merged) context, the final sufficiency verdict, the
    number of retries performed (0 or 1), and whether the answer should be given
    with uncertainty because context is still insufficient.
    """
    context = list(retrieve(query))
    check = check_grounded_sufficiency if semantic else check_retrieval_sufficiency
    sufficiency = check(query, context)
    retries = 0

    if not sufficiency["is_sufficient"]:
        rewrite_query = str(sufficiency["rewrite_query"] or query)
        LOGGER.info("Retrying retrieval once with rewrite %r", rewrite_query)
        context = _merge_context(context, list(retrieve(rewrite_query)))
        retries = 1
        sufficiency = check(query, context)

    answered_with_uncertainty = not sufficiency["is_sufficient"]
    if answered_with_uncertainty:
        LOGGER.warning(
            "Context still insufficient after one retry; answering with uncertainty (missing=%s)",
            sufficiency["missing"],
        )
    return {
        "context": context,
        "sufficiency": sufficiency,
        "retries": retries,
        "answered_with_uncertainty": answered_with_uncertainty,
    }


def check_sufficiency(query: str, results: RetrievedContext) -> Sufficiency:
    """Backward-compatible alias for :func:`check_retrieval_sufficiency`."""
    return check_retrieval_sufficiency(query, results)


def _semantic_sufficiency_verdict(
    query: str,
    retrieved_context: RetrievedContext,
) -> dict[str, object] | None:
    evidence = _semantic_evidence_payload(retrieved_context)
    allowed_ids = {
        str(item["id"]) for item in evidence if isinstance(item.get("id"), str) and item["id"]
    }
    if not allowed_ids:
        return None
    prompt = render_prompt(
        "sufficiency_check",
        {
            "query": query,
            "retrieved_context": json.dumps(evidence, ensure_ascii=True),
        },
    )
    try:
        response = call_qwen_json(
            [{"role": "user", "content": prompt}],
            schema_name="sufficiency_check",
        )
    except LLMClientError:
        LOGGER.warning("Semantic sufficiency check failed; retaining deterministic verdict")
        return None
    payload = response.get("json")
    if not isinstance(payload, dict):
        return None
    sufficient = payload.get("sufficient")
    missing = payload.get("missing")
    evidence_ids = payload.get("evidence_ids")
    reason = payload.get("reason")
    if (
        not isinstance(sufficient, bool)
        or not isinstance(missing, list)
        or not isinstance(evidence_ids, list)
        or not isinstance(reason, str)
    ):
        return None
    valid_evidence_ids = [
        identifier
        for identifier in evidence_ids
        if isinstance(identifier, str) and identifier in allowed_ids
    ]
    if sufficient and not valid_evidence_ids:
        LOGGER.warning("Semantic sufficiency verdict cited no valid evidence")
        return None
    return {
        "is_sufficient": sufficient,
        "missing": [item for item in missing if isinstance(item, str)],
        "evidence_ids": valid_evidence_ids,
        "reason": reason,
    }


def _semantic_evidence_payload(
    retrieved_context: RetrievedContext,
) -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []
    for item in retrieved_context[:12]:
        identifier = _evidence_id(item)
        if identifier is None:
            continue
        record = item.get("record")
        record = record if isinstance(record, dict) else {}
        text_parts = [
            str(value).strip()
            for value in (
                item.get("content"),
                item.get("title"),
                item.get("summary"),
                item.get("reason"),
                record.get("content"),
                record.get("subject"),
                record.get("predicate"),
                record.get("object"),
                item.get("relation"),
            )
            if isinstance(value, str) and value.strip()
        ]
        payload.append(
            {
                "id": identifier,
                "source": str(item.get("source", "")),
                "status": str(record.get("status") or item.get("status") or "current_candidate"),
                "text": " | ".join(dict.fromkeys(text_parts))[:1600],
            }
        )
    return payload


def _key_terms(query: str) -> set[str]:
    entities = {
        match.group(0).casefold()
        for match in ENTITY_PATTERN.finditer(query)
        if match.group(0).casefold() not in QUESTION_WORDS
    }
    if entities:
        return entities
    return {
        token
        for token in _tokens(query)
        if len(token) >= MIN_CONTENT_TERM_LENGTH and token not in QUESTION_WORDS
    }


def _requirement_for_clause(clause: str) -> dict[str, object]:
    terms = sorted(_key_terms(clause))
    return {
        "clause": clause,
        "kind": "lexical",
        "attribute": None,
        "relation": None,
        "terms": terms,
    }


def _evaluate_requirement(
    requirement: dict[str, object],
    retrieved_context: RetrievedContext,
) -> dict[str, object]:
    matching_evidence = [
        item for item in retrieved_context if _evidence_supports(requirement, item)
    ]
    evidence_ids = [
        identifier
        for item in matching_evidence
        for identifier in [_evidence_id(item)]
        if identifier is not None
    ]
    supported = bool(matching_evidence)
    return {
        **requirement,
        "supported": supported,
        "evidence_ids": evidence_ids,
        "missing": [] if supported else _requirement_missing(requirement),
    }


def _evidence_supports(requirement: dict[str, object], item: dict[str, object]) -> bool:
    evidence_tokens = _evidence_tokens(item)
    terms = set(_string_list(requirement.get("terms")))
    return bool(terms) and terms <= evidence_tokens


def _evidence_tokens(item: dict[str, object]) -> set[str]:
    tokens: set[str] = set()
    for field in (*CONTEXT_TEXT_FIELDS, "relation", "related_label"):
        value = item.get(field)
        if isinstance(value, str):
            tokens |= _tokens(value)
    record = item.get("record")
    if isinstance(record, dict):
        for field in ("subject", "predicate", "object", "label", "edge_type"):
            value = record.get(field)
            if isinstance(value, str):
                tokens |= _tokens(value)
    return tokens


def _requirement_missing(requirement: dict[str, object]) -> list[str]:
    terms = _string_list(requirement.get("terms"))
    return terms or ["supporting evidence"]


def _evidence_id(item: dict[str, object]) -> str | None:
    for field in ("id", "source_id"):
        value = item.get(field)
        if isinstance(value, str) and value:
            return value
    return None


def _context_tokens(retrieved_context: RetrievedContext) -> set[str]:
    tokens: set[str] = set()
    for item in retrieved_context:
        for field in CONTEXT_TEXT_FIELDS:
            value = item.get(field)
            if isinstance(value, str):
                tokens |= _tokens(value)
    return tokens


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _rewrite_query(query: str, missing: list[str]) -> str:
    if not missing:
        return query.strip()
    return f"{' '.join(missing)} {query.strip()}"


def _merge_context(primary: RetrievedContext, extra: RetrievedContext) -> RetrievedContext:
    merged = list(primary)
    seen = {_dedupe_key(item) for item in primary}
    for item in extra:
        key = _dedupe_key(item)
        if key not in seen:
            seen.add(key)
            merged.append(item)
    return merged


def _dedupe_key(item: dict[str, object]) -> str:
    for field in ("id", "source_id"):
        value = item.get(field)
        if isinstance(value, str) and value:
            return value
    content = item.get("content")
    return content if isinstance(content, str) else repr(sorted(item.items(), key=lambda kv: kv[0]))


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in TOKEN_PATTERN.findall(value.casefold())
        if len(token) > 1 and token not in STOPWORDS
    }
