# ADR-0002: SQLite over Postgres for the relational store

- **Status:** accepted
- **Date:** 2026-06-16
- **Deciders:** Jerry, Kelechi

## Context

MIRA needs a relational store for observations, consolidated memories, and the
knowledge graph (`core/db/schema.py`). At this stage MIRA runs as a
single-process agent (CLI/UI/Slack) per user, with the slow path as a background
worker in the same process. Write volume is modest and access is local.

## Decision

Use **SQLite** as the relational store, addressed via `MIRA_DB_PATH`.

## Consequences

- Zero operational overhead: no server to provision, secure, or back up — the
  database is a single file, which also makes demo seeding and test fixtures
  trivial (`scripts/seed_demo.py`).
- Embedding vectors live in Chroma (`core/db/chroma.py`), not SQLite, so we do
  not need Postgres extensions such as `pgvector`.
- Concurrency is limited to a single writer. This is acceptable for the
  single-process design; if MIRA later becomes a multi-tenant service we will
  revisit and likely supersede this ADR with a move to Postgres.

## Alternatives considered

- **Postgres** — richer concurrency, `pgvector`, and a clear path to
  multi-tenant scale, but it adds a server to operate and is overkill for the
  current single-process scope.
- **DuckDB** — excellent for analytics, but our workload is transactional
  read/write of small records, not analytical scans.
