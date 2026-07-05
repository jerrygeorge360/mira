# ADR-0004 — Quick, Deep, Relational, and Auto Retrieval Modes

## Status

Accepted

## Context

Direct facts, broad synthesis, and relationship questions need distinct retrieval behavior.

## Decision

Quick, Deep, Relational, and Auto are separate retrieval modes.
Auto returns a traceable routing decision, not just a mode string: `intent`, `route`,
`used_memory`, `reason`, `confidence`, and `needs_sufficiency_check`. General knowledge
questions may route to `direct_llm` / `mode=general` without memory retrieval, while personal
memory, procedural, mixed, and relationship questions remain memory-grounded.

## Consequences

The public router stays explicit, and Auto classification does not erase mode-specific contracts.
Every agent response should expose the routing decision and retrieval trace so failures can be
debugged before blaming the model answer.
