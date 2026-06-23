# MIRA Architecture

Architecture decisions are recorded in:

- [ADR-0001 — Session Working Set is Separate from Durable Hot Memory](adr/0001-session-working-set.md)
- [ADR-0002 — Single Typed Graph Instead of Disconnected Graph Stores](adr/0002-single-typed-graph.md)
- [ADR-0003 — SQLite Source of Truth and ChromaDB Vector Index](adr/0003-sqlite-source-of-truth.md)
- [ADR-0004 — Quick, Deep, Relational, and Auto Retrieval Modes](adr/0004-retrieval-modes.md)
- [ADR-0005 — Provisional vs Confirmed Memory](adr/0005-provisional-confirmed-memory.md)
- [ADR-0006 — Session Micro-Path vs Cross-Session Slow Path](adr/0006-session-micro-path-slow-path.md)
- [ADR-0007 — Prompt Builder as Integration Point](adr/0007-prompt-builder-integration-point.md)
- [ADR-0008 — Foresight Lifecycle](adr/0008-foresight-lifecycle.md)
- [ADR-0009 — Reflection Staleness Through Evidence Invalidation](adr/0009-reflection-staleness-evidence-invalidation.md)
- [ADR-0010 — Sensa-Style Ambient Context as Prompt Signal, Not Memory Store](adr/0010-ambient-context-prompt-signal.md)

## Fast path

The fast path saves each raw observation and queues its identifier. It performs no model
calls or enrichment.

## Session micro-path

A rule-assisted extractor proposes operations for a new turn, a deterministic validator
checks them, and validated operations update temporary current-session state.

## Session Working Set

The Session Working Set stores provisional active-session items. It is not a cold, warm,
or hot tier. Prompt construction gives it hot-level priority for immediate continuity.

## Cross-session slow path

The asynchronous slow path creates durable atomic facts, typed temporal graph edges,
foresight, reflections, community summaries, and tier changes. It confirms, rejects,
expires, narrows, or promotes provisional session items.

## Prompt builder

The prompt builder merges recent turns, Session Working Set items, cross-session memory,
retrieval results, and Sensa-style ambient context under a token budget. Ambient context
includes date, time, timezone, session gap, and optional location or weather signals.

## Retrieval modes

- **Quick:** vector, keyword, and atomic-fact lookup.
- **Deep:** graph-derived community summaries.
- **Relational:** graph traversal for entities, contradiction, supersession, causality,
  and evidence.
- **Auto:** route classification.

A structured sufficiency check permits one retry.

## Durable tiers and persistence

Confirmed memory may move among cold, warm, and hot tiers. SQLite is the source of truth.
ChromaDB is a rebuildable vector index only. NetworkX will provide an in-process view and
algorithms for the single typed temporal graph, not another source of truth.
Chroma collections store embeddings and SQLite record pointers only; deleting a collection must
never delete canonical memory records.
Collection rebuilds derive deterministic canonical index text from SQLite records before calling
an external embedder; observations index `content`, reflections index `content`, and community
summaries index `title + summary`.

## Provisional and confirmed memory

Session items remain provisional until the slow path confirms them. Corrections apply
forward without rewriting raw observations; only confirmed candidates may become durable.
