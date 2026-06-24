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

import logging
import re
from collections.abc import Callable

Sufficiency = dict[str, object]
RetrievedContext = list[dict[str, object]]
RetrieveFn = Callable[[str], RetrievedContext]

LOGGER = logging.getLogger(__name__)

CONTEXT_TEXT_FIELDS = ("content", "title", "summary", "reason")
ENTITY_PATTERN = re.compile(r"[A-Z][A-Za-z0-9.+#-]{2,}")
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_'+#-]+")
MIN_CONTENT_TERM_LENGTH = 4
QUESTION_WORDS = frozenset(
    {"what", "when", "where", "who", "why", "how", "which", "did", "do", "does", "are", "is"}
)
STOPWORDS = frozenset(
    {"a", "an", "the", "to", "of", "for", "on", "in", "and", "my", "me", "i", "we", "about", "with"}
)


def check_retrieval_sufficiency(query: str, retrieved_context: RetrievedContext) -> Sufficiency:
    """Assess whether retrieved context is enough to answer the query."""
    key_terms = _key_terms(query)
    context_tokens = _context_tokens(retrieved_context)
    missing = sorted(term for term in key_terms if term not in context_tokens)

    is_sufficient = bool(retrieved_context) and not missing
    rewrite_query = None if is_sufficient else _rewrite_query(query, missing)
    if not is_sufficient:
        LOGGER.info("Insufficient retrieval for %r; missing=%s", query, missing)
    return {"is_sufficient": is_sufficient, "missing": missing, "rewrite_query": rewrite_query}


def resolve_with_one_retry(query: str, retrieve: RetrieveFn) -> Sufficiency:
    """Retrieve, check sufficiency, and retry at most once with a rewritten query.

    Returns the (possibly merged) context, the final sufficiency verdict, the
    number of retries performed (0 or 1), and whether the answer should be given
    with uncertainty because context is still insufficient.
    """
    context = list(retrieve(query))
    sufficiency = check_retrieval_sufficiency(query, context)
    retries = 0

    if not sufficiency["is_sufficient"]:
        rewrite_query = str(sufficiency["rewrite_query"] or query)
        LOGGER.info("Retrying retrieval once with rewrite %r", rewrite_query)
        context = _merge_context(context, list(retrieve(rewrite_query)))
        retries = 1
        sufficiency = check_retrieval_sufficiency(query, context)

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


def _context_tokens(retrieved_context: RetrievedContext) -> set[str]:
    tokens: set[str] = set()
    for item in retrieved_context:
        for field in CONTEXT_TEXT_FIELDS:
            value = item.get(field)
            if isinstance(value, str):
                tokens |= _tokens(value)
    return tokens


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
