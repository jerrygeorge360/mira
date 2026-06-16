# ADR-0001: Leiden over Louvain for community detection

- **Status:** accepted
- **Date:** 2026-06-16
- **Deciders:** Jerry

## Context

The slow path partitions the knowledge graph into communities and summarises
each one to give retrieval a coarse, topical index (`core/memory/community.py`).
We need a community-detection algorithm. The two obvious candidates are Louvain
and Leiden, both modularity-based and both with mature Python implementations.

A known failure mode of Louvain is that it can produce **badly connected — even
internally disconnected — communities**: a node can end up in a community it is
no longer well attached to after a move. For a memory graph that we re-cluster
repeatedly as it grows, that instability degrades the quality of the summaries
retrieval depends on.

## Decision

Use the **Leiden** algorithm for community detection.

## Consequences

- Leiden guarantees well-connected communities and converges to a stable
  partition, which keeps community summaries coherent across re-clustering.
- It is typically faster to converge than Louvain on larger graphs.
- We take a dependency on a Leiden implementation (e.g. `leidenalg`/`igraph` or
  `cdlib`); this is added to `requirements.txt` when ISSUE-010 is implemented.

## Alternatives considered

- **Louvain** — simpler and widely used, but susceptible to poorly connected
  communities, which is exactly the instability we want to avoid here.
- **Label propagation** — very fast but non-deterministic and lower quality
  partitions; not worth the loss in summary coherence.
