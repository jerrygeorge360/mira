# Session Working Set

## Status

Accepted

## Context

Current-session continuity needs immediate structured state without prematurely granting durability.

## Decision

The Session Working Set is a temporary runtime store separate from durable hot memory.

## Consequences

Prompt construction may prioritize provisional state while durable tiers remain evidence-controlled.

