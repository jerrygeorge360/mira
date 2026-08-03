# ADR-0008 — Foresight Lifecycle

## Status

Accepted

## Context

Future-facing reminders and predictions can become stale, satisfied, or contradicted over time.

## Decision

Model foresight with an explicit lifecycle for creation, activation, fulfillment, expiration, and invalidation.
Deadline extraction preserves an ISO 8601 `valid_until` boundary. The background worker sweeps
non-terminal records on every poll, including idle polls, while retrieval refreshes the relevant
workspace before selecting foresight. When a record becomes terminal, any hot-memory projection
of it is demoted in the same transaction.

Reconcile user lifecycle updates across sessions at the workspace boundary. Active and pending
records are embedding-ranked and supplied to a structured LLM resolver together with their IDs,
source statements, validity windows, and bounded recent conversation context. Embeddings select
candidates but cannot mutate state. A verdict may cancel, resolve, modify, retain, or reject a
relationship as unrelated; mutations require a supplied ID and high confidence. A modification
retires the prior record and creates a replacement linked to the new observation. Invalid,
low-confidence, and ambiguous verdicts leave lifecycle state unchanged. Provider failures are
logged and may use only the narrow explicit-cancellation fallback.

## Consequences

Foresight remains useful without becoming permanent truth; lifecycle state must be evidence-backed.
Calendar-bound records expire automatically. Event-triggered records without a calendar boundary
remain active until explicit resolution or cancellation.

This adds one structured provider call whenever a user turn is reconciled while active Foresight
exists. Candidate ranking bounds prompt size, and fail-closed validation prevents semantic
similarity or an invented identifier from becoming destructive authority.
