# ADR-0007 — Prompt Builder as Integration Point

## Status

Accepted

## Context

Recent turns, session state, durable memory, retrieval, and ambient signals compete for limited prompt budget.

## Decision

Make the prompt builder the integration point for assembling budgeted context.

## Consequences

Upstream systems expose candidates instead of writing directly to prompts; token policy remains centralized.
