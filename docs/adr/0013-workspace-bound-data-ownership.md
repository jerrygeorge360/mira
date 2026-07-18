# ADR-0013 - Workspace-Bound Data Ownership

## Status

Accepted

## Context

MIRA serves authenticated users, temporary demo users, API clients, workers, and MCP clients over
the same persistence layer. Passing a session id alone is not a sufficient ownership boundary: ids
can be guessed, leaked, or supplied by another integration, and derived records can outlive the
session that created them.

## Decision

Treat the workspace as the data-isolation boundary. Authentication resolves a trusted
`WorkspaceContext`; API, retrieval, graph, memory, worker, evaluation, Slack, and MCP operations
must carry that context into repository queries. Durable SQLite records store `workspace_id`, and
Chroma entries include workspace metadata that is applied as a query prefilter. User-supplied
workspace ids do not establish authority.

GitHub authentication creates server-side sessions bound to a workspace membership. Demo access
uses a separate, expiring workspace. Development mode may bind an explicit local workspace, but it
is not a production authentication mechanism.

## Consequences

Users cannot retrieve or mutate another workspace's sessions or derived memory through normal
runtime paths. New tables, read models, scripts, and integrations must include workspace ownership
in their contracts and tests. Legacy records remain available through the explicit legacy
workspace, and migrations must backfill ownership before enforcing scoped reads.
