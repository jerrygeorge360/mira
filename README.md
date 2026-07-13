# MIRA - Memory-Integrated Reasoning Architecture

MIRA is a memory layer for AI agents. It turns conversations into structured,
inspectable memory that can survive across sessions.

It is built around a simple idea: the prompt is not the memory store. MIRA stores
conversation events first, then builds prompts from session state, durable memory,
retrieval results, and a token budget.

For deeper design notes, see [docs/mira-paper.md](docs/mira-paper.md) and
[docs/architecture.md](docs/architecture.md).

## The problem

Most agents can only remember what fits in the current prompt. That breaks down when:

- useful context spans many sessions;
- the user corrects old information;
- the agent needs to explain why it remembered something;
- raw chat history becomes too large or too noisy to paste into every prompt.

MIRA handles memory as infrastructure. It records turns, extracts durable facts, tracks
corrections, builds a typed graph, and returns traces that show what memory was used.

## Session memory vs. cross-session memory

MIRA keeps short-term session state separate from durable cross-session memory.

| Layer | Job | Timing |
| --- | --- | --- |
| Session Working Set | current goals, corrections, constraints, decisions, open questions | immediate |
| Durable memory | observations, atomic facts, graph edges, reflection, foresight, community summaries | background worker |

This matters for corrections. If the user says "Use 2026, not 2025", the next answer should use
2026 immediately. The slow path can later confirm the change and write durable `SUPERSEDED_BY` or
`CONTRADICTS` graph edges.

## What MIRA does

The runtime loop is:

```text
user message
  -> save observation
  -> update Session Working Set
  -> enqueue slow-path memory work
  -> retrieve relevant durable memory
  -> build prompt under budget
  -> call configured model
  -> save answer and trace
```

The slow-path worker runs separately:

```text
queued observation
  -> embeddings
  -> atomic facts
  -> entities and graph edges
  -> correction / contradiction handling
  -> reflections
  -> foresight records
  -> community summaries
  -> tier updates
```

## Core features

- **Session Working Set**: current goals, corrections, constraints, decisions, and open
  questions are available immediately.
- **Durable memory**: observations, atomic facts, graph records, reflections, foresight,
  community summaries, and answer traces are stored in SQLite.
- **Corrections**: newer facts can supersede older facts without deleting history.
- **Contradictions**: unresolved conflicts are tracked separately from accepted corrections.
- **Typed graph**: entities, observations, evidence links, supersession edges, contradiction
  edges, and relationship edges live in one graph model.
- **Retrieval routing**: Auto routing can choose direct answering, Quick retrieval, Deep
  retrieval, or Relational retrieval.
- **Answer traces**: responses include routing and retrieval details for inspection.
- **Ambient context**: optional runtime context can be added to the prompt without becoming
  durable memory.
- **Provider profiles**: DashScope/Qwen, SiliconFlow, DeepSeek, Gemini, and local FastEmbed
  embeddings can be configured through `.env`.
- **Interfaces**: FastAPI backend, web interface, Streamlit inspection UI, Slack bot, and MCP
  server skeleton.
- **Evaluation**: local regression cases, ablation runs, and LongMemEval-style benchmark tools.

## Example

```text
User: My project database is MongoDB.
MIRA: saves the observation.

User: Correction: we moved from MongoDB to PostgreSQL.
MIRA: updates the current session immediately and later records a SUPERSEDED_BY edge.

New session:
User: What database do I use now?
MIRA: answers PostgreSQL and returns a trace showing the memory path.
```

The old MongoDB fact is not erased. It remains as history, but the active memory points to
PostgreSQL.

## Architecture flow

SQLite is the source of truth. ChromaDB is a rebuildable vector index over SQLite records.
NetworkX is used as a read-only graph projection when graph algorithms need it; it is not the
main storage layer.

```text
core/
  agent.py          main runtime loop
  db/               SQLite schema, repositories, Chroma index
  llm/              provider profiles, client adapter, prompts, embeddings
  memory/           observations, facts, graph, reflections, foresight, tiers
  session/          session micro-path, working set, hydration
  retrieval/        quick, deep, relational, routing
  context/          prompt merging and token budgeting

api/                FastAPI backend
frontend/           web interface
ui/                 Streamlit inspection app
slack/              Slack and MCP entry points
evaluation/         local eval, ablation, benchmark adapters
scripts/            provider checks, worker, demo seeding, inspection commands
docs/               architecture notes, ADRs, paper, demo script
tests/              test suite
```

More detail: [docs/architecture.md](docs/architecture.md).

## Setup

Python 3.11 is expected.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
make install
cp .env.example .env
make check
```

Load `.env` into your terminal before running commands that need provider keys:

```bash
set -a
source .env
set +a
```

Choose a provider profile in `.env`:

```bash
LLM_PROFILE=deepseek
DEEPSEEK_API_KEY=your_key
LLM_RESPONSE_FORMAT=auto
EMBEDDING_MODE=local
LOCAL_EMBEDDING_PROVIDER=fastembed
LOCAL_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
```

Other supported profiles include `dashscope`, `siliconflow`, and `gemini`.

Check provider wiring:

```bash
make provider-check
```

## Run locally

Run the API:

```bash
make api
```

Run the worker in another terminal:

```bash
make worker
```

Run the web interface:

```bash
make frontend-dev
```

Open:

```text
http://localhost:5173
```

The frontend talks to the API at:

```text
http://localhost:8000
```

The API queues memory work. The worker drains the queue and creates durable memory artifacts.
Keep both running when testing the full memory pipeline.

## Auth and workspaces

MIRA separates user data by workspace. Product API routes resolve the workspace from server-side
auth, not from arbitrary request payloads.

For local development without GitHub OAuth:

```bash
MIRA_AUTH_MODE=development
MIRA_DEVELOPMENT_WORKSPACE_ID=workspace_legacy_default
```

For GitHub OAuth:

```bash
MIRA_AUTH_MODE=github
GITHUB_CLIENT_ID=your_client_id
GITHUB_CLIENT_SECRET=your_client_secret
GITHUB_CALLBACK_URL=http://localhost:8000/auth/github/callback
APP_BASE_URL=http://localhost:5173
COOKIE_SECURE=false
```

Demo accounts use short-lived demo workspaces:

```bash
make demo-cleanup
```

## Demo

The older Streamlit UI is still useful for inspection and demos:

```bash
python -m scripts.seed_demo --workspace-id workspace_legacy_default --reset
make run
```

Open:

```text
http://localhost:8501
```

The demo walkthrough is in [docs/demo-script.md](docs/demo-script.md).

## API

Run:

```bash
make api
```

Useful endpoints:

- `GET /health`
- `GET /auth/github/start`
- `GET /auth/github/callback`
- `GET /auth/me`
- `POST /auth/logout`
- `POST /auth/demo`
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

Most product endpoints require an authenticated workspace. Cookie-authenticated mutations also
require the readable `mira_csrf` cookie value in the `X-CSRF-Token` header.

## Slack and MCP

Run Slack:

```bash
make slack
```

Bind non-browser surfaces to explicit workspaces:

```bash
MIRA_STREAMLIT_WORKSPACE_ID=workspace_legacy_default
MIRA_MCP_WORKSPACE_ID=workspace_legacy_default
MIRA_SLACK_TEAM_WORKSPACES={"T01234567":"workspace_legacy_default"}
```

Slack user IDs stay inside the workspace selected by the verified Slack team mapping.

## Runtime inspection

Graph snapshot:

```bash
WORKSPACE_ID=workspace_legacy_default make graph-inspect
WORKSPACE_ID=workspace_legacy_default ENTITY=PostgreSQL make graph-inspect
```

Slow-path queue and artifact health:

```bash
WORKSPACE_ID=workspace_legacy_default make slow-path-status
```

Vector search through Chroma pointers:

```bash
WORKSPACE_ID=workspace_legacy_default QUERY="what database do I use now?" make memory-search
```

If `memory-search` returns `"record_found": false`, Chroma has a pointer to a SQLite record that
is not present in the active database. Rebuild or clear Chroma after switching databases.

## Evaluation

Run local deterministic cases:

```bash
make local-eval
```

Run local cases with live provider calls:

```bash
python -m scripts.run_local_eval --live
```

Run live local cases with inline slow-path processing:

```bash
python -m scripts.run_local_eval --live --run-slow-path --debug-trace --delay-s 15
```

Useful notes:

- `--run-slow-path` is closer to the real worker setup, but it makes more model calls.
- `--debug-trace` writes `evaluation/local/memory_cases.debug.md`.
- `--delay-s` helps with free-tier provider rate limits.
- By default, each case gets an isolated SQLite database, cleared vector store, and evaluation
  workspace.

## Ablation

Offline ablation:

```bash
make ablation
```

Live ablation:

```bash
set -a; source .env; set +a
LLM_PROFILE=deepseek OUT=evaluation/ablation/results make ablation-live
```

Slow-path-aware live ablation:

```bash
LLM_PROFILE=deepseek \
OUT=evaluation/ablation/results \
RUN_SLOW_PATH=1 \
SLOW_PATH_BATCH_SIZE=20 \
COMPONENTS="foresight reflection contradiction_supersession vector_only" \
LIMIT=3 \
make ablation-live
```

Direct Python form:

```bash
python -m scripts.run_ablation \
  --live \
  --run-slow-path \
  --slow-path-batch-size 20 \
  --components foresight reflection contradiction_supersession vector_only \
  --limit 3 \
  --out evaluation/ablation/results
```

By default, ablation isolates each config/case pair. Use `--shared-db` only when you intentionally
want continuity inside a run.

## Benchmark

Prepare LongMemEval-style data:

```bash
python3 -m scripts.prepare_longmemeval --variant oracle
```

Output:

```text
data/benchmarks/longmemeval.json
```

Estimate cost:

```bash
make benchmark-cost
```

Run a small live subset:

```bash
LIMIT=20 make benchmark-subset
```

Run the configured live benchmark:

```bash
make benchmark
```

Use another provider/model:

```bash
LLM_PROFILE=deepseek \
DEEPSEEK_API_KEY=your_deepseek_key \
MODEL=deepseek-chat \
JUDGE_MODEL=deepseek-chat \
make benchmark-subset
```

Benchmark examples are isolated by database, vector store, and workspace.

## Docker local development

Docker gives you the API, worker, frontend, and dev tools in containers:

```bash
cp .env.example .env
docker compose build
docker compose run --rm devtools python -m scripts.seed_demo \
  --workspace-id workspace_legacy_default --reset
docker compose up api worker frontend
```

Open:

```text
http://localhost:5173
```

API:

```text
http://localhost:8000
```

If ports are busy:

```bash
API_PORT=18000 FRONTEND_PORT=15173 docker compose up api worker frontend
```

Then open:

```text
http://localhost:15173
```

For GitHub OAuth on custom ports, set the OAuth callback URL to:

```text
http://localhost:18000/auth/github/callback
```

Persistent Docker data:

- SQLite: `.docker-data/sqlite/mira.db`
- Chroma: `.docker-data/chroma`

Inside the containers these are mounted as:

- `MIRA_DB_PATH=/data/sqlite/mira.db`
- `CHROMA_DB_PATH=/data/chroma`

Run checks inside Docker:

```bash
docker compose run --rm devtools make check
```

## Tests and checks

```bash
make test
make check
```

Focused commands:

```bash
make lint
make type
make security
make frontend-build
```

## Makefile commands

- `install`: install Python requirements.
- `run`: start the Streamlit UI.
- `api`: start FastAPI.
- `frontend-dev`: start the web interface.
- `frontend-build`: build the web interface.
- `worker`: run slow-path worker.
- `provider-check`: test configured provider and embeddings.
- `graph-inspect`: print graph state.
- `slow-path-status`: print worker queue and artifact health.
- `memory-search`: search vector memory.
- `local-eval`: run local memory cases.
- `ablation`: run offline ablation.
- `ablation-live`: run live ablation.
- `benchmark-cost`: estimate benchmark cost.
- `benchmark-subset`: run a limited benchmark.
- `benchmark`: run the configured benchmark.
- `test`: run pytest.
- `check`: run lint, type, security, and tests.
- `clean`: remove caches and reports.

## Use cases

- personal assistants that remember preferences and corrections;
- Slack agents with team memory;
- developer assistants that remember repository decisions;
- support agents that track unresolved account context;
- research assistants that preserve project context;
- workflow agents that need future constraints and traces.

## Implementation status

MIRA has a working core memory loop: persistence, session memory, slow-path processing, graph
records, retrieval routing, traces, local evaluation, API routes, web UI, Streamlit inspection,
Slack, and Docker setup.

Some parts are still prototype-grade. The goal is to keep the runtime honest: working features
should be visible in tests and traces, and unfinished work should stay in the roadmap.

## Roadmap

- Improve benchmark reporting after more live runs.
- Tighten long-running worker observability.
- Keep procedural memory, multimodal memory, and advanced multi-user policies as future work.

## Team ownership

- **Jerry**: architecture, memory runtime, retrieval, context, and LLM integration.
- **Kelechi**: database, deployment, infrastructure, and Slack/MCP.

## Architecture decision records

Major decisions are tracked in [docs/adr](docs/adr):

- [ADR-0001: Session Working Set is Separate from Durable Hot Memory](docs/adr/0001-session-working-set.md)
- [ADR-0002: Single Typed Graph Instead of Disconnected Graph Stores](docs/adr/0002-single-typed-graph.md)
- [ADR-0003: SQLite Source of Truth and ChromaDB Vector Index](docs/adr/0003-sqlite-source-of-truth.md)
- [ADR-0004: Quick, Deep, Relational, and Auto Retrieval Modes](docs/adr/0004-retrieval-modes.md)
- [ADR-0005: Provisional vs Confirmed Memory](docs/adr/0005-provisional-confirmed-memory.md)
- [ADR-0006: Session Micro-Path vs Cross-Session Slow Path](docs/adr/0006-session-micro-path-slow-path.md)
- [ADR-0007: Prompt Builder as Integration Point](docs/adr/0007-prompt-builder-integration-point.md)
- [ADR-0008: Foresight Lifecycle](docs/adr/0008-foresight-lifecycle.md)
- [ADR-0009: Reflection Staleness Through Evidence Invalidation](docs/adr/0009-reflection-staleness-evidence-invalidation.md)
- [ADR-0010: Sensa-Style Ambient Context as Prompt Signal, Not Memory Store](docs/adr/0010-ambient-context-prompt-signal.md)

## Further reading

- [MIRA paper](docs/mira-paper.md)
- [Architecture overview](docs/architecture.md)
- [Demo script](docs/demo-script.md)
- [Contributing guide](CONTRIBUTING.md)

## License

[MIT](LICENSE)
