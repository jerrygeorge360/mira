# Memory lifecycle

MIRA keeps SQLite as the source of truth and adds a generic sidecar lifecycle
layer. Existing observations, facts, reflections, foresight, graph, and working
memory tables remain responsible for content, provenance, validity, and
contradiction semantics.

## Lifecycle state

`memory_state` is keyed by `(workspace_id, source_type, source_id)` and records
authority, access, verification, successful/failed uses, retention, stability,
pinned state, and a reversible lifecycle status (`active`, `weakened`,
`archived`, or `forgotten`). `memory_reviews` is append-only evidence for
retrieval, answer feedback, verification, refutation, sleep reviews, and
duplicate consolidation. Source rows are never hard-deleted by a sleep cycle.

The lifecycle score is not retrieval relevance. Quick Mode continues to rank by
its relevance score, while each candidate also receives freshness, source
authority, provenance, and runtime-trust diagnostics. Archived and forgotten
sidecar state is excluded from current retrieval but the source and review
history remain available for audit.

## Sleep

`run_memory_sleep(workspace_id, max_items=100)` is deterministic and bounded. It:

1. reviews at most `max_items` lifecycle rows;
2. reinforces or weakens state from observed answer outcomes;
3. archives low-value duplicate state without deleting source evidence;
4. marks negatively evidenced, very-low-retention state forgotten;
5. refreshes reflection validity using existing provenance checks; and
6. records a `memory_sleep_runs` summary.

Memories without feedback are not forgotten merely because they were not
recently accessed. Pinned memories are never archived by this pass.

## Interfaces

Authenticated API routes:

- `GET /memory/states`
- `POST /memory/sleep`
- `POST /retrieval/traces/{trace_id}/feedback`

MCP tools:

- `inspect_memory_state`
- `memory_sleep`
- `answer_feedback`

The feedback path is append-only and workspace-scoped. Corrections should still
be expressed as new user observations so the existing supersession and
contradiction pipeline remains authoritative.

## Verification and traces

Before answer generation, retrieved evidence is assessed for provenance,
authority, freshness, lifecycle status, and runtime trust. Relevance and trust
are persisted as separate fields. If no memory evidence passes the bounded
verification gate, the answer prompt receives an explicit uncertainty guardrail.
Retrieval logs now retain source, relevance, freshness, trust, authority,
provenance, validity, and prompt-eligibility diagnostics while preserving the
legacy ID arrays used by the UI and API.

## Migration and compatibility

The additive schema marker is `0003_memory_lifecycle`. Existing records are
lazily initialized when retrieved or persisted through the fast path, so legacy
databases do not need a destructive backfill. Workspace ownership triggers and
workspace cleanup include all lifecycle tables.

The initial freshness policy uses a 30-day exponential half-life. This is a
deterministic baseline, not a claim that every domain has a 30-day fact lifetime;
future work can tune stability per source or memory type using the sidecar.
