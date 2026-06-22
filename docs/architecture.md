# MIRA Architecture

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

## Provisional and confirmed memory

Session items remain provisional until the slow path confirms them. Corrections apply
forward without rewriting raw observations; only confirmed candidates may become durable.
