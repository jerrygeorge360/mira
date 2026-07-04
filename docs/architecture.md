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
  4. routing          core/retrieval/auto.py          choose Quick | Deep | Relational
  5. retrieval        core/retrieval/{quick,deep,relational}.py
  6. context merge    core/context/merger.py          recent turns + SWS + hot + retrieved + ambient
  7. budget + prompt  core/context/budget.py          trim to token budget, render answer prompt
  8. generation       core/llm/qwen.py                call configured LLM (answer_generation schema)
  9. persist reply    core/memory/observation.py      persist + enqueue assistant turn
 10. trace + logs     core/memory/trace.py, core/observability.py
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
| **ChromaDB** (vector index) | [`core/db/chroma.py`](../core/db/chroma.py) | Rebuildable embedding index whose entries point back to SQLite row IDs. Deleting a collection must never delete canonical records. Lazy-imported; absent Chroma degrades gracefully. |
| **Typed graph** | [`core/memory/graph.py`](../core/memory/graph.py) | The single typed temporal graph is **persisted in SQLite** (`graph_nodes` / `graph_edges`) and traversed with repository queries (`get_neighbors`, `find_edges_by_type`). Community detection loads edges into an in-process `igraph` view for Leiden; a NetworkX view (per the paper) is the planned in-process algorithm layer. |

Engineering rule: nothing except `core/db/` writes SQL directly. Other modules call
repository functions or the per-subsystem helpers below.

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

## Graph model

Module: [`core/memory/graph.py`](../core/memory/graph.py); contradiction logic in
[`core/memory/change.py`](../core/memory/change.py).

One typed graph over `graph_nodes` (types: `observation`, `entity`, `reflection`,
`community`, `foresight`, `atomic_fact`) and `graph_edges` (typed, with bi-temporal
`valid_from`/`valid_until`, confidence, and `source_observations`). Edge families include
`MENTIONS`, `DERIVED_FROM`, `SUPERSEDED_BY`, `CONTRADICTS`, and causal/relational types.
Traversal: `get_neighbors(node_id, edge_types, depth)` and `find_edges_by_type`.

- `SUPERSEDED_BY` — acknowledged change ("switched from Python to Rust"); old belief kept as
  history, no longer current.
- `CONTRADICTS` — unresolved conflict between coexisting claims; lowers confidence and is
  surfaced by Relational Mode.

`DERIVED_FROM` edges from reflections to their evidence observations let the reflection
staleness pass ([`reflection.py`](../core/memory/reflection.py)
`find_reflections_derived_from`) propagate invalidation when evidence is superseded.

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
- **Auto** (`route_retrieval`) — deterministic classifier: Relational first
  (entity-centered change/conflict/causal/comparison), Deep second (broad/identity), Quick
  default; ambiguous queries set `needs_sufficiency_check`.
- **Sufficiency** (`check_retrieval_sufficiency`, `resolve_with_one_retry`) — reports
  missing terms and a rewrite query; permits exactly one retry, then answers with
  uncertainty.

The public dispatcher [`router.py`](../core/retrieval/router.py) (`route_retrieval(query,
mode, limit)`) is still a **stub**; the agent currently dispatches inline via
`_dispatch_retrieval`. The vector search boundary [`vector.py`](../core/retrieval/vector.py)
is also a **stub**; Chroma indexing and rebuild helpers live in
[`core/db/chroma.py`](../core/db/chroma.py).

## Prompt builder

Modules: [`core/context/merger.py`](../core/context/merger.py),
[`core/context/budget.py`](../core/context/budget.py),
[`core/context/prompt_builder.py`](../core/context/prompt_builder.py).

`merge_context_sources(current_message, recent_turns, session_items, durable_memory_items,
ambient_context, retrieved_items)` is the integration point between session and
cross-session memory; it applies session-conflict rules so corrections win. `budget.py`
(`allocate_prompt_budget`, `trim_context_sections`, `estimate_tokens`) trims low-priority
retrieved memories and old turns first — never the current message, safety instructions, or
critical session corrections. The standalone `prompt_builder.build_prompt` is a **stub**;
the agent assembles the answer prompt inline from the merged pack via the centralized
`answer_generation` template ([`core/llm/prompts.py`](../core/llm/prompts.py)).

## Memory tiers

Module: [`core/memory/tiers.py`](../core/memory/tiers.py); durable hot pool
[`core/memory/working.py`](../core/memory/working.py) is a **stub**.

Tiers decide what *competes for prompt injection*, not what exists.
`evaluate_promotion_candidate(record_type, record_id)` scores importance, relevance, scope,
validity, confidence, explicitness, and foresight urgency; `promote_to_hot_memory`,
`demote_hot_memory_item`, and `list_hot_memory_for_context` manage the hot pool. Demotion
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

## FastAPI product backend

Modules: [`api/main.py`](../api/main.py), [`api/routes/`](../api/routes), and
[`api/schemas/`](../api/schemas).

The API server is MIRA's HTTP product boundary for Streamlit-as-client, future React/vanilla
frontends, Slack/MCP adapters, and live validation harnesses. It is intentionally thin:

```text
HTTP request -> FastAPI route -> core.agent / repositories / memory read model
```

Routes must not own memory semantics. They validate/serialize request and response payloads,
call existing core functions, and return clean API errors. The current server exposes health,
chat, sessions, Session Working Set, memory graph, retrieval traces, foresight, reflections,
community summaries, and worker status.

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
