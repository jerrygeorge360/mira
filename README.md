# MIRA — Memory-Integrated Reasoning Architecture

MIRA is a reusable memory layer for AI agents that turns conversations into structured,
inspectable, cross-session memory.

It gives an agent more than a longer prompt. MIRA persists every turn, tracks current-session
corrections immediately, consolidates durable memory in the background, routes retrieval by
query intent, and returns traces that show which memory influenced an answer. The design is
described in the [MIRA paper](docs/mira-paper.md) and the engineering details live in the
[architecture overview](docs/architecture.md).

## Problem

Most LLM agents are still fragile around memory. They may answer well inside one prompt, but
they often fail when useful context spans days, sessions, corrections, and evolving decisions.
Common approaches also over-rely on stuffing raw history into the context window, which makes
memory expensive, opaque, and easy to lose when the prompt gets trimmed.

MIRA treats the context window as an execution buffer, not the memory store. The agent writes
conversation events to durable storage first, then reconstructs each prompt from session state,
cross-session memory, retrieval results, and ambient context under a token budget.

## What MIRA does

MIRA runs a memory loop around the agent:

```text
user message
  -> fast persistence
  -> session micro-path updates Session Working Set
  -> slow path builds durable memory
  -> graph / reflection / foresight updates
  -> retrieval-gated prompt construction
  -> structured tool call when an explicit workflow requires it
  -> LLM answer
  -> answer trace showing routing and memory used
```

The fast path stores raw observations immediately. The Session Working Set keeps active
corrections, constraints, decisions, and open questions available for the next response. The
slow path consolidates durable memory into atomic facts, graph edges, reflections, foresight
records, community summaries, and tiered memory candidates. Retrieval then chooses whether a
question should use Quick, Deep, Relational, or direct LLM answering.

## Core features

- **Session Working Set**: current goals, corrections, constraints, decisions, and unresolved
  questions are available immediately in the same conversation.
- **Durable cross-session memory**: observations, atomic facts, reflections, foresight records,
  community summaries, and tier metadata are persisted in SQLite.
- **Correction and contradiction handling**: acknowledged changes use `SUPERSEDED_BY`; unresolved
  conflicts use `CONTRADICTS`.
- **Structured atomic facts**: slow-path extraction turns raw observations into evidence-backed
  subject-predicate-object facts.
- **Graph-backed memory**: a single typed temporal graph stores entities, observations, evidence
  links, supersession, contradiction, and relationship edges.
- **Retrieval routing**: Auto routing selects direct LLM, Quick, Deep, or Relational retrieval
  based on the query.
- **Traceable answers**: responses include `routing_decision` and `retrieval_trace` objects so
  you can inspect why memory was or was not used.
- **Structured workflow tools**: explicit memory-inspection requests invoke a typed internal
  `inspect_memory` function and attach its result to the prompt and trace.
- **Local evaluation**: deterministic local cases test routing, memory use, corrections,
  contradiction, supersession, foresight, and retrieval sufficiency.
- **Runtime probes**: CLI commands inspect graph state, slow-path health, Chroma pointer health,
  and local regressions.
- **Product surfaces**: Streamlit demo UI, FastAPI backend, Slack bot, and MCP server skeleton
  are included.

## Example demo flow

One useful memory interaction looks like this:

```text
User: My project database is MongoDB.
MIRA: stores the observation and can retrieve it later.

User: Correction: we moved from MongoDB to PostgreSQL.
MIRA: updates the Session Working Set immediately and later records a SUPERSEDED_BY edge.

New session:
User: What database do I use now?
MIRA: retrieves the corrected memory, answers PostgreSQL, and returns a trace showing the
      route, retrieved records, and memory source.
```

The important behavior is not only that MIRA remembers the latest fact. It also keeps the older
fact as history, records the change, and can explain which memory path shaped the answer.

## Session memory vs. cross-session memory

MIRA separates two consolidation timelines that operate on different clocks.

| | Session continuity | Cross-session learning |
| --- | --- | --- |
| **Question it answers** | What matters now in this chat? | What should persist for next time? |
| **Mechanism** | session micro-path -> Session Working Set | asynchronous slow path |
| **Stores** | current goal, correction, active constraint, decision, open question | observations, atomic facts, graph edges, reflections, foresight, community summaries |
| **Latency** | immediate | deferred and batchable |
| **Status** | provisional until reviewed | confirmed durable memory |
| **Prompt priority** | high priority for current response | retrieved only when relevant |

A correction such as "Use 2026, not 2025" should affect the next answer before a background
worker finishes. The Session Working Set handles that immediate continuity. The slow path later
confirms, downgrades, expires, or rejects the provisional item and records durable graph updates
when needed.

## Architecture flow

```text
handle_user_message(session_id, message)
  -> persist observation and enqueue slow-path job
  -> run session micro-path
  -> hydrate relevant durable memory
  -> route retrieval: direct LLM | Quick | Deep | Relational
  -> merge recent turns, session items, hot memory, retrieved records, ambient context
  -> apply token budget
  -> call configured LLM provider
  -> persist assistant response
  -> return answer, routing_decision, retrieval_trace

slow-path worker
  -> generate embeddings
  -> extract atomic facts
  -> extract entities and graph edges
  -> detect contradiction or supersession
  -> synthesize reflections
  -> create foresight records
  -> refresh community summaries
  -> promote or demote tier candidates
  -> confirm or expire Session Working Set items
```

Core storage responsibilities:

- **SQLite** is the source of truth for observations, structured memory, graph records, traces,
  queue state, and evaluation logs.
- **ChromaDB** is a rebuildable vector index over SQLite record pointers.
- **Typed graph records** live in SQLite and are traversed by graph/retrieval helpers; NetworkX
  is available as a read-only algorithm projection.
- **Session Working Set** is temporary current-session state with high prompt priority.
- **Provider profiles** configure OpenAI-compatible chat and embedding endpoints.

See [docs/architecture.md](docs/architecture.md) for module-level details and [docs/adr](docs/adr)
for architectural decisions.

## Setup

Python 3.11 is required.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
make install
cp .env.example .env
make check
```

Choose a provider profile in `.env` and add the matching key. Supported profiles are
`dashscope`, `siliconflow`, `deepseek`, and `gemini`.

```bash
LLM_PROFILE=siliconflow
SILICONFLOW_API_KEY=your_siliconflow_key
LLM_RESPONSE_FORMAT=auto
EMBEDDING_MODE=auto
```

For Gemini chat with local CPU embeddings:

```bash
LLM_PROFILE=gemini
GEMINI_API_KEY=your_gemini_api_key
LLM_RESPONSE_FORMAT=auto
EMBEDDING_MODE=local
LOCAL_EMBEDDING_PROVIDER=fastembed
LOCAL_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
```

Load `.env` into your terminal when running Make targets:

```bash
set -a
source .env
set +a
```

Smoke-check provider wiring:

```bash
make provider-check
```

`LLM_RESPONSE_FORMAT=auto` uses strict `json_schema` when supported and `json_object` for
providers that require JSON mode. DeepSeek currently uses JSON-object mode; SiliconFlow and
Gemini can use schema mode through the configured adapter.

## Running locally

Seed demo data and start the Streamlit UI:

```bash
python -m scripts.seed_demo --reset
make run
```

Run the FastAPI backend:

```bash
make api
```

Run the slow-path worker:

```bash
make worker
```

Run the test suite and checks:

```bash
make test
make check
```

Run the local memory regression suite:

```bash
make local-eval
```

Inspect runtime state:

```bash
make slow-path-status
make graph-inspect
QUERY="what database do I use now?" make memory-search
```

The UI opens the Memory Command Center with chat, graph, Session Working Set, retrieval trace,
foresight, reflections, community summaries, and evaluation surfaces. The chat surface includes
a demo/real-agent toggle. Demo mode is deterministic; real-agent mode calls the MIRA runtime and
requires database, provider, and worker configuration.

The judge/user walkthrough is in [docs/demo-script.md](docs/demo-script.md).

## Demo

The quickest demo path is:

```bash
python -m scripts.seed_demo --reset
make run
```

Use the Streamlit app to show:

- Session Working Set updates after a correction.
- Graph Viewer nodes and evidence paths.
- Retrieval Trace explaining which memory records shaped an answer.
- Foresight Timeline for future-relevant constraints.
- Evaluation Dashboard for local and benchmark-oriented runs.

You can also call the runtime directly:

```python
from core.db.repositories import configure_database, create_session
from core.agent import handle_user_message

configure_database("mira.db")
session = create_session("jerry")
print(handle_user_message(session, "Use 2026, not 2025, for all dates."))
```

## API and integration surfaces

FastAPI:

```bash
make api
```

Endpoints:

- `GET /health`
- `POST /sessions`
- `GET /sessions/{session_id}`
- `POST /chat`
- `GET /sessions/{session_id}/working-set`
- `GET /memory/graph`
- `GET /retrieval/traces/{trace_id}`
- `GET /foresight`
- `GET /reflections`
- `GET /community-summaries`
- `GET /worker/status`

Slack:

```bash
make slack
```

The API and Slack layers are intentionally thin. Memory behavior remains in `core/` so other
agent surfaces can reuse the same infrastructure.

## Runtime inspection

Inspect the typed memory graph:

```bash
make graph-inspect
ENTITY=PostgreSQL make graph-inspect
```

Inspect slow-path health:

```bash
make slow-path-status
```

Search vector memory and verify Chroma pointers against SQLite:

```bash
QUERY="what did I say about oranges?" make memory-search
```

If `memory-search` returns `"record_found": false`, Chroma contains a stale pointer to a SQLite
record that is not present in the active `MIRA_DB_PATH`. Rebuild or clear Chroma after switching
databases.

## Evaluation

MIRA includes evaluation scripts and local regression cases. The repository does not ship invented
benchmark numbers; run the scripts against your configured provider and dataset.

Run local deterministic memory cases:

```bash
make local-eval
```

Run local cases with live provider calls:

```bash
python -m scripts.run_local_eval --live
```

Run local cases with inline slow-path distillation after each interaction:

```bash
python -m scripts.run_local_eval --live --run-slow-path --debug-trace --delay-s 15
```

Local eval prints `[local-eval]` progress messages to stderr so live runs show the active case
and interaction. Use `--delay-s 15` for rate-limited free-tier providers and `--quiet` if you
need machine-readable output only. `--run-slow-path` is closer to a long-running worker setup,
but it performs additional extraction/distillation model calls. `--debug-trace` writes
`evaluation/memory_cases.debug.md` with routing, retrieved records, session items, prompt
sections, and slow-path step output.

Prepare LongMemEval-style data:

```bash
python3 -m scripts.prepare_longmemeval --variant oracle
```

That writes:

```text
data/benchmarks/longmemeval.json
```

Estimate benchmark cost without live calls:

```bash
make benchmark-cost
```

Run a limited live benchmark:

```bash
LIMIT=20 make benchmark-subset
```

Run the configured live benchmark:

```bash
make benchmark
```

You can select another provider/model through environment variables:

```bash
LLM_PROFILE=deepseek \
DEEPSEEK_API_KEY=your_deepseek_key \
MODEL=deepseek-chat \
JUDGE_MODEL=deepseek-chat \
make benchmark-subset
```

## Use cases

MIRA is useful anywhere an agent needs inspectable memory beyond one chat window:

- personal AI assistants that remember preferences, projects, and corrections;
- Slack agents that preserve team context across threads and days;
- developer assistants that remember repository decisions and workflow constraints;
- customer-support agents that track durable account context and unresolved issues;
- research assistants that preserve evolving hypotheses, citations, and project plans;
- long-running workflow agents that need future constraints, reminders, and answer traces.

## Competition and demo context

MIRA can be evaluated in memory-agent benchmarks and hackathon settings, but the system is
designed as general-purpose agent memory infrastructure. The Qwen/DashScope path is one provider
profile and demo context, not the identity of the project. The current adapter supports multiple
OpenAI-compatible providers and local embeddings.

## Docker local development

Docker is optional, but it gives the team a repeatable clean-clone environment.

```bash
cp .env.example .env
docker compose build
docker compose run --rm app python -m scripts.seed_demo --reset
docker compose up app
```

Then open <http://localhost:8501>.

The Compose app service mounts durable local data into `.docker-data/`:

- SQLite: `.docker-data/sqlite/mira.db` mounted as `MIRA_DB_PATH=/data/sqlite/mira.db`
- Chroma: `.docker-data/chroma` mounted as `CHROMA_DB_PATH=/data/chroma`

Run checks inside the container:

```bash
docker compose run --rm app make check
```

## Makefile commands

- `install` — install development and production requirements.
- `run` — launch the Streamlit UI (`ui/app.py`).
- `api` — launch the FastAPI backend (`api.main:app`).
- `slack` — run the Slack bot.
- `worker` — run the slow-path background worker.
- `provider-check` — smoke-check configured chat and embedding providers.
- `graph-inspect` — print a JSON snapshot of graph nodes, edges, and provenance.
- `slow-path-status` — print queue health, failures, and slow-path artifact counts.
- `memory-search` — embed `QUERY` and search vector memory through Chroma pointers.
- `local-eval` — run the isolated local memory regression suite.
- `test` — run pytest.
- `lint`, `format`, `fix` — check or format with Ruff.
- `type` — run strict mypy.
- `security` — run Bandit.
- `check` — run lint, type, security, and tests.
- `precommit` — run all pre-commit hooks.
- `ablation` — run the ablation study and write results.
- `benchmark-cost` — estimate benchmark cost without paid calls.
- `benchmark` — run the live LongMemEval-style benchmark.
- `benchmark-subset` — run the live benchmark on a limited subset.
- `clean` — remove generated caches and reports.

## Repository layout

```text
core/
  agent.py          runtime loop: user message -> memory -> answer
  db/               SQLite source of truth, ChromaDB index, schema, repositories
  llm/              provider profiles, OpenAI-compatible client, prompts, embeddings
  memory/           observations, atomic facts, graph, reflections, foresight, tiers
  session/          session micro-path, Session Working Set, confirmation, hydration
  retrieval/        Quick, Deep, Relational, Auto routing, sufficiency
  context/          merger, token budget, ambient context
ui/                 Streamlit app and graph visualization
api/                FastAPI backend over the MIRA core runtime
slack/              Slack bot and MCP server skeleton
evaluation/         local cases, benchmark adapter, ablations, judge
docs/               paper, architecture, ADRs, demo script, issues
scripts/            setup, demo, provider, worker, benchmark, and inspection scripts
tests/              test suite
```

## Implementation status

MIRA has a working core memory loop today: persistence, session memory, slow-path memory
consolidation, graph records, retrieval routing, answer traces, local eval, UI, API, and Slack
surfaces. Public facades for retrieval dispatch, vector search, prompt building, hot-memory
listing, memory inspection, and concrete structured tool dispatch now delegate to the active
runtime/read-model modules.

## Roadmap

Next work is intentionally narrow:

- Add stronger benchmark result reporting once live runs are complete.
- Keep full procedural memory, multimodal memory, and multi-user memory as future research.

## Team ownership

- **Jerry** — architecture, core memory, retrieval, context, and LLM integration.
- **Kelechi** — database, deployment, infrastructure, and Slack/MCP.

## Architecture decision records

Major decisions are tracked in [docs/adr](docs/adr):

- [ADR-0001 — Session Working Set is Separate from Durable Hot Memory](docs/adr/0001-session-working-set.md)
- [ADR-0002 — Single Typed Graph Instead of Disconnected Graph Stores](docs/adr/0002-single-typed-graph.md)
- [ADR-0003 — SQLite Source of Truth and ChromaDB Vector Index](docs/adr/0003-sqlite-source-of-truth.md)
- [ADR-0004 — Quick, Deep, Relational, and Auto Retrieval Modes](docs/adr/0004-retrieval-modes.md)
- [ADR-0005 — Provisional vs Confirmed Memory](docs/adr/0005-provisional-confirmed-memory.md)
- [ADR-0006 — Session Micro-Path vs Cross-Session Slow Path](docs/adr/0006-session-micro-path-slow-path.md)
- [ADR-0007 — Prompt Builder as Integration Point](docs/adr/0007-prompt-builder-integration-point.md)
- [ADR-0008 — Foresight Lifecycle](docs/adr/0008-foresight-lifecycle.md)
- [ADR-0009 — Reflection Staleness Through Evidence Invalidation](docs/adr/0009-reflection-staleness-evidence-invalidation.md)
- [ADR-0010 — Sensa-Style Ambient Context as Prompt Signal, Not Memory Store](docs/adr/0010-ambient-context-prompt-signal.md)

## Further reading

- [MIRA paper](docs/mira-paper.md) — research framing and architecture summary.
- [Architecture overview](docs/architecture.md) — implementation map for engineers.
- [Demo script](docs/demo-script.md) — guided walkthrough for reviewers and teammates.
- [Contributing guide](CONTRIBUTING.md) — branch-per-issue workflow and PR expectations.

## License

[MIT](LICENSE)
