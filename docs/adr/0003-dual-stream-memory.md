# ADR-0003: Dual-stream (fast/slow) memory

- **Status:** accepted
- **Date:** 2026-06-16
- **Deciders:** Jerry

## Context

Consolidating memory well is expensive: reflection, foresight, entity/relation
extraction, and community detection all involve LLM calls and graph work. If
that happens inline with a user turn, the agent feels slow. But if we skip it,
memory never gains structure. We need both responsiveness and rich memory.

## Decision

Split memory into a **dual stream**:

- a synchronous **fast path** (`core/memory/observation.py`,
  `core/memory/working.py`) that captures the turn, updates working memory, and
  returns immediately; and
- an asynchronous **slow path** (`core/memory/slow_path.py`) that consolidates
  enqueued observations in the background.

## Consequences

- The user-facing response latency is bounded by the fast path only; heavy
  consolidation never blocks a reply.
- The slow path is async and runs as a background worker — hence
  `pytest-asyncio` in the dev toolchain from day one, so the first async test
  does not trip over toolchain setup.
- We accept **eventual consistency**: a just-mentioned fact may not be fully
  consolidated into the graph for the very next turn. Working memory covers the
  short-term gap until consolidation catches up.

## Alternatives considered

- **Single synchronous path** — simplest, but consolidation latency lands
  directly on every user turn. Rejected.
- **Batch/offline consolidation only** — cheap during conversation, but memory
  would be stale for the whole session. The async slow path gives most of the
  freshness without the inline cost.
