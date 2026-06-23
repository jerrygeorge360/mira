# SQLite Source of Truth

## Status

Accepted

## Context

Durable records and semantic indexes need an unambiguous authority.

## Decision

SQLite is the source of truth; ChromaDB is a vector index only.

## Consequences

The vector index must be rebuildable, while durable writes and corrections are anchored in SQLite.

