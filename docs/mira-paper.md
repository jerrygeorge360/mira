# MIRA: Memory-Integrated Reasoning Architecture

*A Session-Aware and Cross-Session Memory Framework for Persistent Personalized Agents*

Author: Jerry George — June 2026

> This is the repository copy of the MIRA paper, kept in sync with the
> implementation terminology. Figures referenced in the arXiv build are omitted
> here; see the architecture overview in [architecture.md](architecture.md) and
> the [ADRs](adr) for the decisions behind each component.

## Abstract

Large language model (LLM)-based conversational agents are often deployed with limited
durable state: new sessions may begin without an evidence-backed model of the user, their
preferences, their projects, or their prior decisions. Recent production assistants have
introduced cross-session memory, but these memories are commonly represented as flat fact
lists without explicit evidence chains, temporal validity, contradiction handling,
graph-based pattern synthesis, or a clear distinction between what matters inside the
current conversation and what should persist across future conversations.

**MIRA (Memory-Integrated Reasoning Architecture)** is a cognitive memory framework for
persistent personalized agents. It implements three of the four CoALA memory types —
episodic, semantic, and working memory — while treating full procedural memory adaptation
as future work. The architecture emphasizes a distinction between **session continuity**
and **cross-session memory**: session continuity requires immediate tracking of the
current goal, corrections, constraints, decisions, and unresolved questions before
asynchronous memory synthesis completes; cross-session memory requires slower
consolidation into atomic facts, graph edges, foresight records, reflections, community
summaries, and tiered long-term memory.

MIRA introduces a lightweight **Session Working Set** maintained by a fast session
micro-path, alongside a full asynchronous cross-session slow path. Before each model
response, a retrieval-gated prompt builder merges the Session Working Set with relevant
cross-session memories under a strict token budget. The architecture uses SQLite as source
of truth, ChromaDB as a vector index, a single typed temporal graph, background community
detection for Deep Mode, Relational retrieval for query-time graph traversal, and a
foresight layer for time-bounded future constraints. It treats the LLM context window as
an execution buffer rather than a memory store, and separates provisional session state
from confirmed durable memory.

**Keywords:** Agent Memory, Persistent Memory, Session Memory, Cross-Session Memory,
Knowledge Graph, Temporal Reasoning, Retrieval-Augmented Generation, Cognitive
Architecture, Foresight, Qwen.

## Primary Contributions

1. **Session / cross-session separation.** A Session Working Set handles provisional
   current-chat state, while the full slow path builds durable memory structures.
2. **Single typed temporal graph.** One typed graph represents observations, entities,
   evidence links, temporal changes, contradictions, and communities, instead of multiple
   incompatible graph stores.
3. **Contradiction-aware memory evolution.** Acknowledged belief evolution (`SUPERSEDED_BY`)
   is distinguished from unresolved conflict (`CONTRADICTS`), and both are exposed through
   Relational retrieval.
4. **Foresight with temporal and contextual gating.** Future-relevant constraints are
   tracked using validity windows, a status lifecycle, relevance filtering, and a
   safety bypass. Cross-session lifecycle updates use embedding-ranked candidates and
   a constrained, provenance-checked LLM verdict to resolve synonyms without granting
   semantic similarity direct mutation authority.

## Architecture Summary

MIRA has two consolidation timelines and one prompt-construction layer:

- **Session continuity** — current goal, active corrections, current constraints,
  provisional decisions, and unresolved questions, maintained by the session micro-path in
  the Session Working Set.
- **Cross-session learning** — raw observations, atomic facts, typed graph edges, foresight
  records, reflections, community summaries, and tier lifecycle, produced by the
  asynchronous slow path.
- **Prompt construction** — a retrieval-gated prompt builder merges both sources before
  each model call and injects only the subset that fits the token budget.

Retrieval offers four modes: **Quick** (direct facts via vector + keyword + atomic-fact
lookup), **Deep** (graph-derived community summaries for broad synthesis), **Relational**
(query-time graph traversal for change, conflict, causality, and evidence), and **Auto**
(routing among the three with a structured sufficiency check that permits one retry).
In the implementation, Auto first classifies the required context scope (`general_knowledge`,
`recent_conversation`, `session_memory`, `durable_memory`, or `mixed`) and then selects a
retrieval mode only when durable evidence is required. It emits a traceable routing decision
(`intent`, `context_scope`, `route`, `used_memory`, confidence, and reason), allowing general
knowledge and recent conversational follow-ups to bypass durable retrieval while personal,
mixed, and relational questions remain memory-grounded.

Stores: **SQLite** is the source of truth for text content; **ChromaDB** is a rebuildable
vector index that points back to SQLite row IDs; the **typed temporal graph** stores node
types, edge types, bi-temporal validity, and evidence links; the **Session Working Set** is
temporary runtime state with hot-level prompt priority but is not durable until the slow
path confirms it.

The repository includes runtime inspection commands for implementation validation:
`graph-inspect` exposes typed graph provenance, `slow-path-status` reports worker and queue
health, `memory-search` verifies Chroma pointers against SQLite records, and `local-eval`
runs a small isolated regression suite before larger external benchmarks.

## Scope

MIRA implements episodic, semantic, and working memory. Full procedural memory remains
future work; MIRA instead implements proto-procedural self-knowledge reflections that can
influence behavior once promoted into working memory. The project scope is a text-only,
single-user memory system using OpenAI-compatible model providers, SQLite, ChromaDB, an
in-process typed graph, Streamlit/Pyvis visualization, and a Slack/MCP interface, evaluated on
LongMemEval/LoCoMo-style tasks. It excludes multimodal memory, multi-user memory sharing,
per-user adapters, and production-scale deployment.

For the full literature review, design requirements, memory-object schemas, evaluation
strategy, build plan, and references, see the canonical arXiv build of this paper.
