# ADR-0006 — Session Micro-Path vs Cross-Session Slow Path

## Status

Accepted

## Context

MIRA needs immediate session continuity without blocking each turn on durable enrichment.

## Decision

Use a lightweight session micro-path during interaction and an asynchronous cross-session slow
path for durable synthesis.

The micro-path records explicit corrections and transitions provisionally so they can influence
the next answer before durable processing finishes. It recognizes named transitions such as
"moved my caching layer from Redis to Memcached," explicit invalidations such as "the interview
is not next Tuesday anymore," and bounded temporal amendments such as "it moved to the following
week" when recent turns identify the event. A targetless correction such as "actually that's
wrong" produces no Session Working Set mutation until the user identifies the affected claim.

Memory-changing references are resolved against a bounded candidate set drawn from recent user
turns, the active Session Working Set, and workspace-scoped durable retrieval. Explicit references
such as "what I just said" bind to the preceding user turn. Other references use structured model
selection, but the model may choose only a supplied candidate identifier. Low-confidence,
provider-failed, and out-of-set decisions ask the user to identify the target and leave both
session and durable memory unchanged. The validated resolution is stored as observation metadata
so the slow path can enforce the same boundary and bind Foresight reconciliation to the selected
source statement.

Turn-purpose detection does not depend on an expanding list of amendment verbs. Clear questions,
updates, and conversational turns retain deterministic fast-path handling. An otherwise
unclassified turn with recent context is sent to the structured purpose classifier, which may
identify it as a resolution before reference selection begins. This separates the semantic
decision to change memory from the constrained decision about which existing statement is being
changed.

The slow path independently extracts facts from every persisted user observation, including
assertions embedded in conversational reactions. It owns durable transition edges, temporal
reconciliation, confirmation, and provenance.

## Consequences

The micro-path stays fast and provisional; the slow path owns confirmation, enrichment, and tier
movement. Clear amendments remain immediate, unfamiliar phrasing uses structured classification,
and ambiguous references fail closed instead of modifying several candidate memories.
Resolution instructions are evidence about a lifecycle action, not new user facts: they may
reconcile an existing Foresight record but do not create atomic facts, entities, or new Foresight
records themselves. When the selected source already produced active atomic facts, the slow path
expires those facts and their hot-memory projections while retaining both raw observations as
historical provenance. Quick retrieval derives the same lifecycle state from the resolution
metadata and does not return the withdrawn source as current evidence.
Slow-path health must be inspectable independently of answer generation. `make slow-path-status`
reports queue counts, recent failures, unprocessed observations, and durable artifact counts so
worker stalls, failed enrichment, and missing graph/fact outputs are visible without opening
SQLite manually.
