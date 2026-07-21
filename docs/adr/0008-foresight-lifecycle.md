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

## Consequences

Foresight remains useful without becoming permanent truth; lifecycle state must be evidence-backed.
Calendar-bound records expire automatically. Event-triggered records without a calendar boundary
remain active until explicit resolution or cancellation.
