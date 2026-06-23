# ADR-0009 — Reflection Staleness Through Evidence Invalidation

## Status

Accepted

## Context

Reflections summarize evidence, but their source facts may later be corrected, superseded, or invalidated.

## Decision

Mark reflections stale when their supporting evidence is invalidated.

## Consequences

MIRA can preserve historical summaries while avoiding stale reflections in active prompt construction.
