# ADR-0012 — Hybrid Contradiction and Supersession Detection

## Status

Accepted

## Context

Extraction fragments subjects and predicates (for example `Project` vs `project deadline`), so canonical-id equality alone misses many contradictory or superseding fact pairs. Pure heuristics tried earlier were unreliable: entity-graph pairing extracted the wrong anchor, and token containment was brittle.

## Decision

Pair facts in two stages. A deterministic canonical scan handles exact same-subject-and-predicate pairs cheaply. Everything else is embedding-shortlisted (top-k similar recent facts) and verified by a single structured-JSON LLM call (`contradiction_supersession_detection`) that judges entity identity, value equivalence, and change-versus-conflict. Verdicts are validated against the ids supplied and gated on confidence before an edge is created, and the call degrades to a no-op when no provider is configured.

## Consequences

Detection is robust to extraction inconsistency while running at most one LLM call per new fact, and offline runs and tests stay deterministic. `SUPERSEDED_BY` retires the prior fact; `CONTRADICTS` keeps both facts active with lowered confidence and is surfaced at answer time (see ADR-0005).
