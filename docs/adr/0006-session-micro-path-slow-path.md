# ADR-0006 — Session Micro-Path vs Cross-Session Slow Path

## Status

Accepted

## Context

MIRA needs immediate session continuity without blocking each turn on durable enrichment.

## Decision

Use a lightweight session micro-path during interaction and an asynchronous cross-session slow path for durable synthesis.

## Consequences

The micro-path stays fast and provisional; the slow path owns confirmation, enrichment, and tier movement.
