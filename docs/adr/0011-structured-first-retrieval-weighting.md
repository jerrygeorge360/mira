# ADR-0011 — Structured-First Retrieval Weighting

## Status

Accepted

## Context

Quick retrieval draws candidates from both validated derived memory (atomic facts, foresight, reflections) and the raw observation log. Ranking them equally lets stale or verbose raw observations mask validated memory, so the answer surface is the transcript rather than what the system actually learned.

## Decision

Rank Quick candidates with reciprocal rank fusion plus a source-tier weight that places validated derived memory above the raw observation log, then apply decay and a relative recall gate. Observations remain retrievable as fallback and evidence, not as the primary answer surface.

## Consequences

Derived memory drives answers while observations back them with provenance. This diverges from the paper's Quick spec (RRF and decay without source priority) and should be reconciled in the paper. The `flat_memory` ablation disables the source weighting to measure its contribution.
