# MIRA Architecture

MIRA is a cognitive memory framework for persistent AI agents. This document
describes the moving parts and how a turn flows through them. It is a living
document; sections firm up as each issue is implemented.

## Design goals

- **Persistence** — memory survives across sessions and accumulates structure.
- **Responsiveness** — the agent never blocks on heavy consolidation work.
- **Explainability** — retrieval can justify *why* a memory was surfaced.

## Dual-stream memory

MIRA splits memory work into two streams so the user-facing path stays fast.

### Fast path (synchronous)

`core/memory/observation.py` captures each incoming turn as a raw observation,
persists it, and enqueues it for consolidation. `core/memory/working.py` holds
the bounded in-session buffer the agent reasons over directly.

### Slow path (asynchronous)

`core/memory/slow_path.py` drains the consolidation queue off the critical path
and runs the heavier operations:

- **Reflection** (`reflection.py`) — distil insights and stable facts.
- **Foresight** (`foresight.py`) — anticipate what the user will need next.
- **Knowledge graph** (`graph.py`) — extract entities and typed relations.
- **Community detection** (`community.py`) — partition the graph and summarise.

## Retrieval

`core/retrieval/router.py` classifies each query and dispatches it to:

- **Formal retrieval** (`formal.py`) — precise, explainable graph traversal.
- **Vector retrieval** (`vector.py`) — semantic nearest-neighbour search over
  the Chroma embedding store.

…or a hybrid blend, then merges and ranks the results.

## Persistence

- **SQLite** (`core/db/schema.py`) — observations, consolidated memories, and
  the knowledge graph (nodes and edges).
- **Chroma** (`core/db/chroma.py`) — the embedding store backing vector search.

## LLM layer

`core/llm/qwen.py` wraps the Qwen chat API (via DashScope);
`core/llm/functions.py` builds the tool schemas and dispatches model-requested
calls.

## Surfaces

- `ui/` — chat front-end plus a live knowledge-graph visualisation.
- `slack/` — a Slack bot and an MCP server exposing MIRA as tools.
- `evaluation/` — an LLM-as-judge harness for measuring quality.

## Decisions

Key architectural decisions are recorded as ADRs in [adr/](adr/):

- [0001](adr/0001-leiden-over-louvain.md) — Leiden over Louvain for communities.
- [0002](adr/0002-sqlite-over-postgres.md) — SQLite over Postgres for the store.
- [0003](adr/0003-dual-stream-memory.md) — dual-stream (fast/slow) memory.
