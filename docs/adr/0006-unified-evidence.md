# ADR 0006: Source-aware evidence for MIRA memory

Status: Proposed

## Context

Conversation observations enter the slow path and can produce facts, graph edges,
reflections, and foresight. Documents are stored privately, chunked, indexed, and
retrieved, but do not enter that enrichment path. Several derived tables require an
observation ID, so writing document-derived knowledge there currently requires a
false conversation source.

SQLite remains authoritative. Chroma is a rebuildable index, and the graph is
persisted in SQLite. Each existing observation or document chunk keeps its
content in its current table.

## Decision

Introduce a normalized evidence-source reference with a stable ID, source type,
original record ID, workspace, optional project/namespace/Knowledge Base scope,
authority, time fields, content hash, metadata, and active/retracted state. A
resolver reads the original content and validates its workspace and scope. The
first adapters are `conversation_observation` and `document_chunk`.

Use one workspace-scoped association model for claims and their evidence. An
association names a derived target (`atomic_fact`, `graph_edge`, `reflection`, or
`foresight`), its source, whether it supports or contradicts the target, and its
confidence. The source is validated before the association is written. Duplicate
active links are rejected. Legacy observation provenance fields remain readable;
existing rows are backfilled into the association model. Observation-only foreign
keys on facts and foresight become optional for new document-derived records.

Keep document upload synchronous through S3, extraction, SQLite chunks, and
Chroma indexing. Mark the document ready before creating an independent, durable
enrichment job. The job has bounded retries, lease recovery, a pipeline version,
and per-unit progress. A failed enrichment job leaves the ready document
searchable. It never enters the observation queue or Session Working Set.

Reuse MIRA's grounded fact, entity, canonicalization, graph, change, reflection,
and foresight components through source-aware adapters. Document text is data,
not an instruction. Document foresight starts as a candidate, remains scoped to
its project/Knowledge Base, and is never an automatic personal reminder.

Retrieval validates project, namespace, workspace, and explicit Knowledge Base
attachment before reading candidates. Personal memory stays in its namespace
workspace. Shared project knowledge stays in a separate project scope. Raw chunks
remain retrievable and can be combined with eligible derived knowledge through
the existing retrieval, trust, context budget, and trace pipeline.

Deleting a document retracts its source links before deleting chunks and vectors.
A derived target remains active when another valid source supports it. Targets
with no valid support are invalidated according to their existing lifecycle.
Original source retention is separate from derived-memory decay and sleep.

Rollout starts disabled for document enrichment and source-aware retrieval.
Activation is scoped to selected projects or workspaces. Conversation-only paths
continue through their existing interfaces.

## Migration and rollback

Use additive SQLite migrations with repeat-safe DDL and backfill. Rebuild only
tables whose observation foreign key must become nullable; retain all legacy
columns and row IDs. Validate foreign keys and counts before activating flags.
Before production migration, take an application-consistent SQLite backup and
verify it can be opened. On failure, disable the new flags and restore the
backup; do not reset the database or delete source documents.

## Consequences

The worker, API, MCP, and retrieval paths share one source and scope contract.
Cross-source reasoning is permitted only within authorized scopes. The added
queue and association records increase SQLite writes, so processing is bounded
and incremental for the Contabo deployment.
