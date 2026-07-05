# ADR-0003 — SQLite Source of Truth and ChromaDB Vector Index

## Status

Accepted

## Context

Durable records and semantic indexes need an unambiguous authority.

## Decision

SQLite is the source of truth; ChromaDB is a vector index only.

## Consequences

The vector index must be rebuildable, while durable writes and corrections are anchored in SQLite.
Chroma records store embeddings plus SQLite pointers only; they are not authoritative memory.
Runtime diagnostics must therefore report pointer health. `make memory-search` embeds a query,
searches Chroma, and resolves each pointer back to SQLite with `record_found=true|false`, making
stale vectors visible after database resets or path changes.
