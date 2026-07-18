# MIRA Implementation Architecture

This document explains **how the code works** for engineers extending MIRA. It maps each
subsystem to the modules that implement it. For the research framing and contributions, see
the [MIRA paper](mira-paper.md); for the decisions behind each subsystem, see the
[ADRs](adr). This document does not repeat the paper.

The runtime entry point is [`core/agent.py`](../core/agent.py) (`handle_user_message`). One
turn flows through the subsystems below:

```text
handle_user_message(session_id, user_message)
  1. fast path        core/memory/observation.py     persist + enqueue user turn
  2. session micro-path core/session/micro_path.py    extract -> validate -> Session Working Set
  3. hydration        core/session/hydration.py       seed durable memory on new/continue sessions
  4. routing          core/retrieval/auto.py          choose direct_llm | Quick | Deep | Relational
  5. retrieval        core/retrieval/{quick,deep,relational}.py
  6. structured tools core/llm/functions.py           invoke only explicit workflow tools
  7. context merge    core/context/merger.py          recent turns + SWS + hot + retrieved + ambient
  8. budget + prompt  core/context/budget.py          trim to token budget, render answer prompt
  9. generation       core/llm/qwen.py                call configured LLM (answer_generation schema)
 10. persist reply    core/memory/observation.py      persist + enqueue assistant turn
 11. trace + logs     core/memory/trace.py, retrieval_log.sufficiency_json, observability
```

A note on framing: **the LLM context window is an execution buffer, not the memory store.**
Memory lives in SQLite, the vector index, the typed graph, the Session Working Set, and the
tiers. Context overflow is *not* the primary memory event — every turn is already persisted
by the fast path, so a long conversation is handled by retrieval-gated prompt reconstruction
(steps 4–7), not by treating the transcript as memory.

## Store responsibilities (SQLite / Chroma / NetworkX)

| Store | Module(s) | Responsibility |
| --- | --- | --- |
| **SQLite** (source of truth) | [`core/db/sqlite.py`](../core/db/sqlite.py), [`core/db/schema.py`](../core/db/schema.py), [`core/db/repositories.py`](../core/db/repositories.py) | Authoritative text + structured records: observations, atomic facts, reflections, foresight, communities, working memory, session items, graph nodes/edges, logs. All writes go through typed repository functions with enum validation. |
| **ChromaDB** (vector index) | [`core/db/chroma.py`](../core/db/chroma.py) | Rebuildable embedding index whose entries point back to SQLite row IDs. Deleting a collection must never delete canonical records. Lazy-imported; absent Chroma degrades gracefully. `vector_store_status()` reports backend/path/counts; `make memory-search` verifies query embeddings and SQLite pointer health. |
| **Typed graph** | [`core/memory/graph.py`](../core/memory/graph.py) | The single typed temporal graph is **persisted in SQLite** (`graph_nodes` / `graph_edges`) and traversed with repository queries (`get_neighbors`, `find_edges_by_type`). Community detection loads edges into an in-process `igraph` view for Leiden. `build_networkx_memory_graph()` exposes a read-only NetworkX `MultiDiGraph` projection for algorithms and diagnostics; SQLite remains the source of truth. |

Engineering rule: nothing except `core/db/` writes SQL directly. Other modules call
repository functions or the per-subsystem helpers below.

## Workspace ownership boundary

`users`, `workspaces`, `workspace_members`, and server-side `auth_sessions` establish the
ownership boundary. Durable records carry `workspace_id`; child records derive ownership from
their parent session or observation rather than accepting it from an untrusted caller. SQLite
triggers reject mismatched queue records, graph endpoints, and reflection evidence.

The active workspace is resolved once at the HTTP boundary and passed through scoped repository
facades. Hydration, keyword/vector/deep/relational retrieval, graph projections, communities,
reflections, foresight, and slow-path semantic passes filter before ranking or traversal. Chroma
stores `workspace_id` as first-class metadata and applies a `where` prefilter, so candidate
vectors from another workspace never reach reranking. SQLite remains the canonical authority if
the disposable index is rebuilt.

## Fast path

Module: [`core/memory/observation.py`](../core/memory/observation.py).

The fast path does raw persistence and queueing only — **no model calls, no enrichment**.
`persist_turn_fast_path(session_id, role, content)` saves an observation
([`save_observation`](../core/db/repositories.py)) and enqueues its id for the slow path
([`enqueue_observation`](../core/db/repositories.py), queue in
[`core/db/queue.py`](../core/db/queue.py)).

```text
completed turn -> save_observation -> enqueue_observation -> return observation_id
```

## Session micro-path

Modules: [`core/session/micro_path.py`](../core/session/micro_path.py),
[`core/session/extractor.py`](../core/session/extractor.py),
[`core/session/validator.py`](../core/session/validator.py).

`run_session_micro_path(session_id, observation_id, message, recent_turns)` runs after the
fast path and before prompt construction. It loads the current Session Working Set,
calls the rule-assisted `extract_session_operations`, validates each operation with the
deterministic `validate_session_operation`, applies valid ones, logs rejects for slow-path
review, and returns the changed item ids.

```text
message -> extract_session_operations -> [validate_session_operation] -> apply -> SWS
                                          rejected -> log (no state change)
```

Operations are `upsert | supersede | resolve | expire | no_op`; item types are
`current_goal | active_constraint | correction | decision | open_question | resolution`. The
validator enforces structure/scope/priority and blocks attempts to touch system or safety
rules; it is **not** a model call and does not check semantics (handled later by the slow
path).

## Session Working Set

Modules: [`core/session/working_set.py`](../core/session/working_set.py),
[`core/session/confirmation.py`](../core/session/confirmation.py),
[`core/session/hydration.py`](../core/session/hydration.py).

The Session Working Set (`session_working_set` table) is temporary current-chat state with
hot-level prompt priority — it is **not** a cold/warm/hot tier.
`working_set.py` provides `upsert_session_item`, `supersede_session_item`,
`resolve_session_item`, `expire_session_item`, `reject_session_item`, and
`export_prompt_ready_session_items` (deterministic priority order).

`confirmation.py` is the lifecycle gate the slow path uses: `confirm_session_item`,
`reject_session_item_after_review`, `downgrade_session_item_scope`,
`mark_session_item_forward_only`, and `promote_session_item_to_durable_candidate`.
`hydration.py`'s `hydrate_session_from_memory` seeds a new/continuing session from durable
memory, writing items with `status=hydrated`, `origin=cross_session_hydration`, and skipping
anything that conflicts with a current-session correction.

## Provisional vs confirmed memory

See [ADR-0005](adr/0005-provisional-confirmed-memory.md). Session items are **provisional**
until the slow path confirms them. Confirmation re-reads the source observation, evidence
span, and nearby turns, then confirms, downgrades scope, keeps session-only, expires, or
rejects. Only confirmed `project`/`cross_session` items are eligible for durable promotion
([`tiers.py`](../core/memory/tiers.py)).

Corrections are **forward-only**: a later downgrade/reject removes the item from future
prompts but never rewrites prior turns. The slow path records the durable change with a
`SUPERSEDED_BY` or `CONTRADICTS` edge instead.

## Cross-session slow path

Orchestrator and worker runtime: [`core/memory/slow_path.py`](../core/memory/slow_path.py).
`run_slow_path_batch`, `run_slow_path_for_observation`, `run_worker`, and
`run_worker_once` claim queue records, chain the memory-processing steps, mark queue items
done/failed independently, and expose worker counts for diagnostics. The older async
adapters (`run_slow_path` / `enrich_observation`) delegate into this orchestrator path.

The orchestrator chains these implemented per-observation steps:

| Step | Module | Function(s) |
| --- | --- | --- |
| Atomic fact extraction | [`core/memory/atomic_fact.py`](../core/memory/atomic_fact.py) | `extract_atomic_facts`, `store_atomic_facts` |
| Entity + graph edges | [`core/memory/graph.py`](../core/memory/graph.py) | `extract_entities`, `canonicalize_entity`, `create_graph_edge` |
| Contradiction vs supersession | [`core/memory/change.py`](../core/memory/change.py) | distinguishes `CONTRADICTS` from `SUPERSEDED_BY` |
| Reflection | [`core/memory/reflection.py`](../core/memory/reflection.py) | `should_reflect`, `synthesize_reflections`, `store_reflection_with_evidence` |
| Foresight | [`core/memory/foresight.py`](../core/memory/foresight.py) | `detect_foresight`, `create_foresight` |
| Community detection | [`core/memory/community.py`](../core/memory/community.py) | `detect_graph_communities`, `summarize_community` |
| Tier promotion/demotion | [`core/memory/tiers.py`](../core/memory/tiers.py) | `evaluate_promotion_candidate`, `promote_to_hot_memory` |
| Session item confirmation | [`core/session/confirmation.py`](../core/session/confirmation.py) | `confirm_session_item`, ... |

Work is claimed from the queue via `claim_pending_batch`, then completed with `mark_done` or
`mark_failed` ([`core/db/repositories.py`](../core/db/repositories.py)). One failed
observation does not stop the rest of the batch.

Before processing, the worker cross-checks the queue, observation, and session workspace and
requires an active workspace. Ownership failures move the job to `quarantined`; they are never
automatically retried or repaired. `slow_path_step_journal` records each existing pipeline step
by workspace and observation. A retry skips completed steps and resumes from the failed step,
which preserves the observation-level queue architecture without introducing a scheduler.

Runtime inspection:

```bash
WORKSPACE_ID=workspace_legacy_default make slow-path-status PYTHON=.venv/bin/python
```

This calls `get_slow_path_health()` and reports queue counts, unprocessed observations,
recent failed/dead-letter jobs, and durable artifact counts. It is the first command to run
when the worker appears quiet or when answers are not reflecting newly saved observations.

## Graph model

Module: [`core/memory/graph.py`](../core/memory/graph.py); contradiction logic in
[`core/memory/change.py`](../core/memory/change.py).

One typed graph over `graph_nodes` (types: `observation`, `entity`, `reflection`,
`community`, `foresight`, `atomic_fact`) and `graph_edges` (typed, with bi-temporal
`valid_from`/`valid_until`, confidence, and `source_observations`). Edge families include
`MENTIONS`, `DERIVED_FROM`, `SUPERSEDED_BY`, `CONTRADICTS`, and causal/relational types.
Traversal: `get_neighbors(node_id, edge_types, depth)` and `find_edges_by_type`.
Algorithm view: `build_networkx_memory_graph()` loads active SQLite nodes/edges into a
NetworkX `MultiDiGraph`, and `graph_algorithm_summary()` reports small diagnostics such as
weakly connected components, largest component size, and high-degree nodes. This projection is
read-only: writes still go through SQLite/repository helpers.

- `SUPERSEDED_BY` — acknowledged change ("switched from Python to Rust"); old belief kept as
  history, no longer current.
- `CONTRADICTS` — unresolved conflict between coexisting claims; lowers confidence and is
  surfaced by Relational Mode.

`DERIVED_FROM` edges from reflections to their evidence observations let the reflection
staleness pass ([`reflection.py`](../core/memory/reflection.py)
`find_reflections_derived_from`) propagate invalidation when evidence is superseded.

Runtime inspection:

```bash
WORKSPACE_ID=workspace_legacy_default make graph-inspect PYTHON=.venv/bin/python
WORKSPACE_ID=workspace_legacy_default ENTITY=SQLite make graph-inspect PYTHON=.venv/bin/python
```

This calls `inspect_memory_graph()` and returns graph counts, visible nodes/edges,
source/target labels, metadata, and `source_observations`. It is intentionally read-only:
the graph remains a SQLite-backed memory structure, not a UI-only visualization.

## Retrieval modes

Modules: [`core/retrieval/quick.py`](../core/retrieval/quick.py),
[`core/retrieval/deep.py`](../core/retrieval/deep.py),
[`core/retrieval/relational.py`](../core/retrieval/relational.py),
[`core/retrieval/auto.py`](../core/retrieval/auto.py),
[`core/retrieval/sufficiency.py`](../core/retrieval/sufficiency.py). Helpers:
[`keyword.py`](../core/retrieval/keyword.py), [`vector.py`](../core/retrieval/vector.py).

- **Quick** (`retrieve_quick`) — direct facts: vector + keyword + atomic-fact + recent +
  foresight candidates, fused and ranked. No graph traversal.
- **Deep** (`retrieve_deep`) — broad synthesis from cached community summaries + relevant
  reflections; falls back to Quick (with a logged reason) when no communities exist. Never
  runs community detection live.
- **Relational** (`relational_retrieve`) — bounded graph traversal of `MENTIONS`,
  `DERIVED_FROM`, `CAUSED_BY`, `SUPERSEDED_BY`, `CONTRADICTS` from anchor entities.
- **Auto** (`route_retrieval`) — deterministic or LLM-assisted classifier that returns a
  traceable decision object. General knowledge questions route to `mode=general`,
  `route=direct_llm`, `intent=general_knowledge`, and `used_memory=false`. Personal,
  procedural, mixed, and relationship questions route through memory with `used_memory=true`.
  Relational remains ordered before Deep, and ambiguous memory queries set
  `needs_sufficiency_check`.
- **Sufficiency** (`check_retrieval_sufficiency`, `resolve_with_one_retry`) — reports
  missing terms and a rewrite query; permits exactly one retry, then answers with
  uncertainty.

The public dispatcher [`router.py`](../core/retrieval/router.py) (`route_retrieval(query,
mode, limit, session_id=None)`) is the reusable facade the agent uses for evidence retrieval
after Auto has selected a mode. The vector search boundary
[`vector.py`](../core/retrieval/vector.py) embeds the query and searches Chroma-backed SQLite
pointers; Quick Mode calls this facade for observation/reflection semantic candidates.

Every agent response includes the routing decision and retrieval trace:

```json
{
  "routing_decision": {
    "intent": "personal_memory",
    "used_memory": true,
    "route": "quick",
    "mode": "quick",
    "reason": "specific factual lookup ('what is my')"
  },
  "retrieval_trace": {
    "retrieval_mode": "quick",
    "retrieved": [{"source": "atomic_facts", "id": "...", "score": 0.8}]
  }
}
```

Use this trace before debugging the model answer: it says whether MIRA intentionally used
memory, which route it selected, why, and which SQLite-backed records entered retrieval.

## Structured workflow functions

Module: [`core/llm/functions.py`](../core/llm/functions.py).

MIRA does not expose a broad provider-side tool-calling abstraction by default. Structured
functions are added only when there is a concrete agent workflow that needs a typed runtime call.
The implemented workflow is `inspect_memory`: explicit requests such as "what do you remember?"
or "show memory status" produce a structured memory snapshot from the active read models. The
agent converts that result into a `structured_tool` context record, includes it in
`retrieval_trace.retrieved`, and returns the raw result under `tool_calls`.

## Prompt builder

Modules: [`core/context/merger.py`](../core/context/merger.py),
[`core/context/budget.py`](../core/context/budget.py),
[`core/context/prompt_builder.py`](../core/context/prompt_builder.py).

`merge_context_sources(current_message, recent_turns, session_items, durable_memory_items,
ambient_context, retrieved_items)` is the integration point between session and
cross-session memory; it applies session-conflict rules so corrections win. `budget.py`
(`allocate_prompt_budget`, `trim_context_sections`, `estimate_tokens`) trims low-priority
retrieved memories and old turns first — never the current message, safety instructions, or
critical session corrections. `prompt_builder.build_prompt` is a reusable facade that merges
legacy inputs, trims them to budget, and renders the centralized `answer_generation` template.
The agent uses `build_prompt_from_context` after it has already built and traced the context
pack ([`core/llm/prompts.py`](../core/llm/prompts.py)).

## Memory tiers

Modules: [`core/memory/tiers.py`](../core/memory/tiers.py) and
[`core/memory/working.py`](../core/memory/working.py).

Tiers decide what *competes for prompt injection*, not what exists.
`evaluate_promotion_candidate(record_type, record_id)` scores importance, relevance, scope,
validity, confidence, explicitness, and foresight urgency; `promote_to_hot_memory`,
`demote_hot_memory_item`, and `list_hot_memory_for_context` manage the hot pool.
`working.py` exposes a small compatibility facade for promoting and listing hot memory. Demotion
triggers include stale/resolved/expired/superseded/low-relevance and capacity limits. Cold
history is never deleted.

## Foresight

Module: [`core/memory/foresight.py`](../core/memory/foresight.py).

Future-relevant constraints with a lifecycle: `pending -> active -> resolved | expired`, and
`pending|active -> cancelled`. `update_foresight_status(record_id, now)` drives time-based
transitions (activation/expiration) against `valid_from`/`valid_until`; `resolve_foresight`
and `cancel_foresight` are the explicit, evidence-backed exits. `list_relevant_foresight(query,
now)` returns active, temporally-valid records that match the query or are `always_inject`.

## Reflection

Module: [`core/memory/reflection.py`](../core/memory/reflection.py).

Cross-session, graph-decoupled synthesis from recent observations: `should_reflect`,
`synthesize_reflections` (keeps only source-backed, non-overclaiming results),
`store_reflection_with_evidence` (writes `reflection_evidence` rows **and** `DERIVED_FROM`
edges). Staleness: `find_reflections_derived_from`, `recompute_reflection_confidence`, and
`invalidate_reflection_if_unsupported` mark a reflection `stale` (partial evidence loss) or
`invalidated` (evidence collapsed) without deleting history.

## Community summaries

Module: [`core/memory/community.py`](../core/memory/community.py).

Background, graph-derived warm memory — **not** transcript compression.
`detect_graph_communities` clusters the typed graph (Leiden via `leidenalg`/`igraph`, with a
deterministic connected-components fallback), `summarize_community` produces a title +
summary linked to member nodes, and `store_community_summary` persists it and indexes
`title + summary` in Chroma for Deep Mode. Detection never runs during a query.

## Vector memory inspection

Module: [`core/db/chroma.py`](../core/db/chroma.py); CLI:
[`scripts/search_memory.py`](../scripts/search_memory.py).

Chroma stores embeddings and SQLite pointers only. It can drift from SQLite when a developer
switches `MIRA_DB_PATH`, resets SQLite, or reuses an old `CHROMA_DB_PATH`. The inspection
command makes that drift explicit:

```bash
WORKSPACE_ID=workspace_legacy_default \
WORKSPACE_ID=workspace_legacy_default \
QUERY="what did I say about oranges?" make memory-search PYTHON=.venv/bin/python
```

Output includes `embedding_dimensions`, vector-store backend/path/counts, Chroma distances,
SQLite pointer ids, metadata, and `record_found`. If `record_found=false`, Chroma has a
stale pointer and should be rebuilt or cleared for the active SQLite database.

Runtime Chroma operations require a workspace for indexing, querying, deletion, and rebuild.
Workspace deletion uses `delete_workspace_vectors`; `reset_vector_store` and
`delete_collection_admin` are explicitly global administrative/test operations. Entries without
workspace metadata are excluded by both Chroma and the in-process fallback.

## UI and demo surfaces

Modules: [`ui/app.py`](../ui/app.py), [`ui/landing.py`](../ui/landing.py),
[`ui/command_center.py`](../ui/command_center.py), and
[`ui/command_center_styles.py`](../ui/command_center_styles.py).

The Streamlit app has two layers:

1. **Landing page** — a product/research narrative for MIRA: capabilities, architecture,
   official benchmark tracks, and ablation studies. Its purpose is orientation and demo
   setup, not runtime memory logic.
2. **Memory Command Center** — the inspectable application shell used for the demo. It has a
   collapsible Claude-style sidebar, clickable chat history, central chat workspace, graph
   inspector, Session Working Set, retrieval trace, reflections, community summaries,
   timeline, and evaluation dashboard.

The command center is deliberately **demo-first**. Static/mock data keeps the UI usable while
the backend is incomplete or expensive to run. This is a UI contract, not a memory contract:
frontend demo data must never be treated as durable memory or source of truth.

The chat surface is the bridge to actual usage. Demo mode calls
[`MockChatAgent`](../ui/chat.py); real mode calls
`core.agent.Agent(DEFAULT_SESSION_ID).respond(...)`, which enters the runtime path described
at the top of this document. Real mode therefore requires a configured SQLite database,
provider credentials, and the relevant retrieval/memory components.

The graph panel is an inspectable representation of the typed memory graph. Clicking a node
opens a detail inspector with type/status, summary, evidence IDs, and connected paths. This
matches the architecture goal that graph edges are read paths for Relational Mode, not just a
decorative visualization.

## Bound local and integration surfaces

Streamlit resolves `MIRA_STREAMLIT_WORKSPACE_ID` at real application startup, validates that the
workspace is active, and creates one deterministic session inside it. The real-agent toggle,
memory inspector, graph, foresight, and trace views all use that binding. Missing configuration
stops the application instead of falling back to the legacy workspace.

Slack parses `MIRA_SLACK_TEAM_WORKSPACES` as a JSON mapping from immutable Slack `team_id` values
to MIRA workspace IDs. Unknown teams are rejected, and Slack user identity remains separate from
GitHub identity.

MCP has two runtime layers. `integrations/mcp/server.py` is the transport-independent tool registry
over the core memory modules. `integrations/mcp/service.py` exposes those tools through the
official MCP SDK's Streamable HTTP transport at `/mcp`. Tool arguments can select records and
owned sessions but cannot change the authenticated workspace.

The FastAPI service is MIRA's OAuth 2.1 authorization server. GitHub authenticates the person,
but MIRA issues its own opaque, resource-bound MCP tokens. Authorization codes require PKCE
`S256`, are short-lived and single-use, and follow an explicit workspace consent page. Access and
refresh tokens are stored only as SHA-256 hashes; refresh tokens rotate on use. The MCP token
verifier resolves the token to an active user membership and constructs the trusted
`WorkspaceContext`. The relevant source-of-truth tables are `oauth_clients`,
`oauth_authorization_requests`, `oauth_access_tokens`, and `oauth_refresh_tokens`.

First-party public clients are seeded from `MIRA_OAUTH_FIRST_PARTY_CLIENTS`. Open clients discover
the authorization server through RFC 9728/RFC 8414 metadata and may use the dynamic registration
endpoint. Registration accepts only public clients, exact HTTPS redirects or HTTP loopback
redirects, authorization code and refresh grants, and the `mira:memory` scope. Static
`MIRA_MCP_API_KEY` bindings remain as a trusted administrative compatibility path.

Operational inspection and seed scripts require `--workspace-id` or `WORKSPACE_ID`. The worker,
demo cleanup, migrations, and isolated evaluation runners are explicitly administrative/system
surfaces and may operate across or create workspaces by design.

## FastAPI product backend

Modules: [`api/main.py`](../api/main.py), [`api/routes/`](../api/routes), and
[`api/schemas/`](../api/schemas).

The API server is MIRA's HTTP product boundary for Streamlit-as-client, future React/vanilla
frontends, Slack/MCP adapters, and live validation harnesses. It is intentionally thin:

```text
HTTP request -> FastAPI route -> core.agent / repositories / memory read model
```

Routes must not own memory semantics. They validate/serialize request and response payloads,
call existing core functions, and return clean API errors. The current server exposes GitHub
OAuth with opaque server sessions, health, chat, sessions, Session Working Set, memory graph,
retrieval traces, foresight, reflections, community summaries, and worker status.

In `github` mode, `/auth/github/callback` provisions one personal workspace per immutable GitHub
user id. Product routes resolve that workspace from a hashed session cookie and ignore legacy
client-supplied user identifiers. Mutating routes use a double-submit CSRF token. In explicit
`development` mode, the server binds requests to `MIRA_DEVELOPMENT_WORKSPACE_ID` (the migrated
legacy workspace by default) without OAuth; this mode is for local development only.

`POST /auth/demo` issues an opaque session for a newly created demo workspace. The canonical demo
seed is non-interactive; visitor data is seeded with fresh IDs into an isolated workspace. SQLite
limits active demos and issuance frequency. Demo sessions and workspaces share an expiry, and
`make demo-cleanup` quarantines pending work, removes workspace vectors, deletes canonical rows
in dependency order, and finally removes the disposable identity. General personal-workspace
deletion is intentionally not implemented by this workflow.

`DELETE /workspace/data` is the self-service reset path for an authenticated workspace. It keeps
the user, workspace, membership, and active login session, but deletes product records in
dependency order: traces, prompt/retrieval logs, queue state, session working set, graph edges,
durable memory records, observations, sessions, and workspace-scoped Chroma pointers.

`DELETE /sessions/{session_id}` is narrower. It tombstones one chat, scrubs its raw observation
text, removes observation vectors, quarantines pending slow-path work, and deactivates derived
facts, foresight, reflections, working memory, and graph edges whose evidence comes only from
that session. Derived memory supported by other sessions can remain active.

The product API has a lightweight in-process rate limiter keyed by client address and route. It
is suitable for local and single-process Docker use. A hosted multi-replica deployment should
move this policy to a shared limiter or edge gateway.

The server runs locally with:

```bash
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

or:

```bash
make api
```

## Evaluation reporting

Modules: [`evaluation/`](../evaluation), landing evaluation sections in
[`ui/landing.py`](../ui/landing.py), and the Evaluation Dashboard in
[`ui/app.py`](../ui/app.py).

MIRA keeps **official benchmark results** separate from **ablation studies**:

- Official benchmark results evaluate the complete system on external/standard memory tasks
  such as LongMemEval and LoCoMo-style temporal conversational memory.
- Ablation studies remove one MIRA component at a time and measure the drop. Example
  components include Session Working Set, keyword retrieval, typed graph traversal,
  foresight records, and reflections/community summaries.
- Ablation uses the shared case-execution runtime from local eval, but keeps its own
  comparison table and result files. By default it isolates each config/case pair with a
  fresh SQLite database, cleared vector store, and explicit evaluation workspace. With
  `--shared-db`, one workspace is shared by the cases in a configuration, while configurations
  remain isolated. Add `--run-slow-path` when comparing durable-memory components so every
  configuration gets the same workspace-scoped ingestion opportunity before scoring.
- Local regressions run a small isolated suite against a temporary SQLite database and
  deterministic answer stub by default:

  ```bash
  make local-eval PYTHON=.venv/bin/python
  ```

  These cases check routing intent, memory usage, retrieval mode, session corrections,
  contradiction/supersession behavior, foresight, and retrieval sufficiency. Use
  `python -m scripts.run_local_eval --live` only when you explicitly want provider calls. The
  runner prints `[local-eval]` progress logs to stderr by default; pass `--quiet` for automation.
  Add `--run-slow-path` to drain the worker queue after each interaction when you want local eval
  to resemble a long-running system with background distillation enabled. Add `--debug-trace` to
  write a Markdown forensic report with routing, prompt sections, session items, and slow-path
  step outputs for each interaction.

- Official benchmark examples use the same boundary: each example gets an isolated database,
  cleared vector store, and explicit evaluation workspace. Import, queue claiming, slow-path
  processing, retrieval, and answering carry that workspace ID end to end. This prevents
  cross-example memory leakage while exercising production ownership constraints instead of a
  privileged global fallback.

This separation matters because a benchmark score answers "how well does MIRA work as a
whole?", while an ablation answers "which architectural component caused the improvement?".

## Sensa-style ambient context

Module: [`core/context/ambient.py`](../core/context/ambient.py).

Ambient context is a prompt signal, **not** a memory tier or retrieval mode
([ADR-0010](adr/0010-ambient-context-prompt-signal.md)). `build_ambient_context(session_id)`
supplies current date/time, timezone, and session gap (`calculate_session_gap`). The prompt
builder injects a compact form, and the foresight layer uses the same `now` signal to decide
whether a time-bounded constraint is active, urgent, or expired.

## Where to start

To implement a new turn end-to-end, read [`core/agent.py`](../core/agent.py) top to bottom —
it calls every subsystem above in order. To extend the cross-session intelligence, implement
the slow-path orchestrator in [`core/memory/slow_path.py`](../core/memory/slow_path.py) using
the step functions listed in the slow-path table.

## Architecture decision records

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
- [ADR-0011 — Structured-First Retrieval Weighting](adr/0011-structured-first-retrieval-weighting.md)
- [ADR-0012 — Hybrid Contradiction and Supersession Detection](adr/0012-hybrid-contradiction-supersession-detection.md)
- [ADR-0013 — Workspace-Bound Data Ownership](adr/0013-workspace-bound-data-ownership.md)
- [ADR-0014 — Provenance-Aware Conversation Deletion](adr/0014-provenance-aware-conversation-deletion.md)
- [ADR-0015 — Provider Profiles and Capability-Aware Structured Output](adr/0015-provider-profiles-and-structured-output.md)
- [ADR-0016 — Authenticated Standalone MCP Service](adr/0016-authenticated-standalone-mcp-service.md)
