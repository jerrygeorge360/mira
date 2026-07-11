# ADR-0009 — Reflection Staleness Through Evidence Invalidation

## Status

Accepted

## Context

Reflections summarize evidence, but their source facts may later be corrected, superseded, or invalidated.

## Decision

Mark reflections stale when their supporting evidence is invalidated.

Invalidation is triggered not only for the incoming observation but for the source observations of any fact superseded or contradicted in the same slow-path pass, so a reflection built on an older observation is re-evaluated when a later turn collapses its evidence.

## Consequences

MIRA can preserve historical summaries while avoiding stale reflections in active prompt construction.
