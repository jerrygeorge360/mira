# MIRA - Memory-Integrated Reasoning Architecture

<p align="center">
  <img src="docs/assets/mira-readme-banner.png" alt="MIRA - inspectable memory for AI agents" width="100%" />
</p>

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
- **Interfaces**: FastAPI backend, web interface, Streamlit inspection UI, Slack bot, and an
  authenticated MCP Streamable HTTP service.
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

<p align="center">
  <img src="docs/assets/mira-c4-achitecturaldiagram.png" alt="MIRA architecture diagram" width="100%" />
</p>

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
slack/              Slack entry point
integrations/mcp/   MCP tool registry, authentication, and Streamable HTTP service
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
For DeepSeek, `auto` uses DeepSeek's documented JSON object mode and MIRA validates
the required schema locally.

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

For the read-only platform dashboard, explicitly allow GitHub logins:

```bash
MIRA_ADMIN_GITHUB_LOGINS=jerrygeorge360,deltron-fr
```

Allowed users see **Administration** in the application rail. `/admin/overview` reports aggregate
registration, workspace, activity, slow-path queue, and OAuth/MCP counts. It does not return user
messages or memory content. Workspace `owner` and `admin` roles do not grant platform access.

Demo accounts use short-lived demo workspaces:

```bash
make demo-cleanup
```

The API also exposes a self-service workspace reset for logged-in users:

```text
DELETE /workspace/data
```

It deletes sessions, observations, memory records, traces, queue state, and Chroma pointers for
the authenticated workspace while keeping the account/workspace login intact.

Local/Docker deployments include a small in-process rate limiter:

```bash
MIRA_RATE_LIMIT_ENABLED=true
MIRA_RATE_LIMIT_REQUESTS=120
MIRA_CHAT_RATE_LIMIT_REQUESTS=30
MIRA_RATE_LIMIT_WINDOW_S=60
```

For a multi-instance production deployment, replace this with a shared Redis or edge limiter.

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
- `DELETE /workspace/data`
- `POST /sessions`
- `GET /sessions/{session_id}`
- `DELETE /sessions/{session_id}`
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

The MCP service is a separate process and uses the standard Streamable HTTP transport. For local
trusted use, generate a static bearer token and bind it to one workspace:

```bash
export MIRA_MCP_API_KEY="$(openssl rand -hex 32)"
export MIRA_MCP_WORKSPACE_ID=workspace_legacy_default
make mcp
```

The MCP endpoint is `http://localhost:8090/mcp`; `http://localhost:8090/health` is public for
container health checks. For Docker Compose:

```bash
docker compose up -d mcp
docker compose logs -f mcp
```

Configure an MCP client with the endpoint URL and an `Authorization: Bearer <token>` header. For
multiple clients, set `MIRA_MCP_TOKEN_WORKSPACES` to a JSON token-to-workspace map instead of the
single-token variables. The workspace comes from the authenticated token, not tool arguments, so
clients cannot select another workspace in a call.

### MCP OAuth

For a first-party MCP client, pre-register its exact callback URI in `.env`:

```env
MIRA_AUTH_MODE=github
MIRA_OAUTH_ISSUER_URL=http://localhost:8000
MIRA_MCP_PUBLIC_URL=http://localhost:8090/mcp
MIRA_OAUTH_FIRST_PARTY_CLIENTS=[{"client_id":"mira-desktop","client_name":"MIRA Desktop","redirect_uris":["http://127.0.0.1:43110/callback"]}]
```

Start the API and MCP service, then configure the client with
`http://localhost:8090/mcp`. The MCP client discovers MIRA's authorization server, opens GitHub
login and a workspace consent page, uses an authorization code with PKCE, and receives a
workspace-bound access token. Access tokens expire after 15 minutes by default; refresh tokens
are single-use and rotate on every refresh.

Open consumer clients can register themselves through the advertised dynamic registration
endpoint. MIRA accepts public clients only, requires PKCE with `S256`, requires HTTPS callback
URIs except for local loopback addresses, and exposes only the `mira:memory` scope. Discovery is
available at:

```text
GET /.well-known/oauth-authorization-server
GET /.well-known/oauth-protected-resource/mcp
```

For the bundled production Nginx topology, use public HTTPS values:

```env
MIRA_OAUTH_ISSUER_URL=https://mira.ninja
MIRA_MCP_PUBLIC_URL=https://mira.ninja/mcp
COOKIE_SECURE=true
GITHUB_CALLBACK_URL=https://mira.ninja/api/auth/github/callback
```

Nginx routes `/mcp`, `/oauth/*`, the two discovery documents, and the GitHub authorization
handoff to the correct containers. Static MCP keys remain available for administrative and
backward-compatible integrations; OAuth is the consumer-facing path.

### MCP model behavior

MIRA publishes usage policy with its MCP server and tool descriptions. A connected model is told
to retrieve before answering questions that depend on conversation history, use the Session
Working Set for active session constraints, inspect the graph for conflicts or evidence lineage,
and consult foresight only for relevant temporal requests. `run_retrieval_query` is the general
retrieval entry point; `retrieve_memory` is the narrower direct-fact lookup.

The model is also told to save only explicit user-authored facts, durable preferences, decisions,
commitments, and corrections. It must not store credentials, its own speculation, retrieved text,
or transient requests. Corrections are appended as new observations so MIRA's slow path can retain
provenance and resolve supersession. A successful `save_observation` call confirms immediate
fast-path persistence; it does not claim that background extraction has finished.

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

### Latest local evaluation story

The latest saved local run is published in `evaluation/local/published_summary.json`. It passed
13 of 13 cases, or 100%. Fresh local runs still write the generated artifact
`evaluation/local/memory_cases.results.json`; when that file exists, the API dashboard reads it
first. In Docker or production, where generated artifacts are intentionally ignored, the dashboard
falls back to the tracked published summary so the Evaluation screen remains available.

The run is useful because it checks both final answers and mechanism evidence such as routing mode,
retrieved sources, session items, and graph edges.

| Area | Passed | Total | What it showed |
| --- | ---: | ---: | --- |
| Direct fact recall | 1 | 1 | Quick retrieval can recall a simple saved fact. |
| Session correction handling | 1 | 1 | Direct corrections enter the Session Working Set with the right labels. |
| Cross-session recall | 1 | 1 | A later session can recover relevant project context without pulling in unrelated deadline memory. |
| Supersession handling | 1 | 1 | A migration from MongoDB to PostgreSQL produced relational evidence and a `SUPERSEDED_BY` path. |
| Foresight activation | 1 | 1 | Time-sensitive hackathon memory was retrieved from `foresight_records`. |
| Deep mode synthesis | 3 | 3 | Deep retrieval surfaced reflections, community summaries, and broader identity/context records. |
| Retrieval sufficiency | 1 | 1 | The system could answer from available memory when retrieval was sufficient. |
| Routing intent | 2 | 2 | General questions bypassed memory, while personal-memory questions used memory. |
| Contradiction handling | 2 | 2 | Preference correction and deadline-conflict checks both preserve explicit graph evidence. |
| **Total** | **13** | **13** | **The core memory loop passes the saved local suite.** |

The most important signal is not only the pass rate. The mechanism checks show that the system is
not just getting lucky from prompt text: relational retrieval returned graph evidence, Deep Mode
returned synthesis records, general knowledge avoided memory, and session corrections were visible
before waiting on long-term memory.

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

### Latest ablation story

The latest saved ablation run is in `evaluation/results/ablation_results.json`. It was a live run
with slow-path processing enabled. The full system passed all 7 ablation cases. Removing individual
components caused targeted drops, which is the result you want from an ablation: each subsystem
should matter for the behavior it claims to support.

| Configuration | Disabled component(s) | Passed | Total | Pass rate | Readout |
| --- | --- | ---: | ---: | ---: | --- |
| Full system | none | 7 | 7 | 1.00 | Baseline memory stack passed every targeted case. |
| Without Session Working Set | session working set | 6 | 7 | 0.86 | Immediate session correction handling lost one case. |
| Without Relational Mode | relational mode | 6 | 7 | 0.86 | Supersession/migration evidence weakened when graph traversal was disabled. |
| Without Deep Mode | deep mode | 5 | 7 | 0.71 | Reflection and community-summary synthesis failed. |
| Without Foresight | foresight | 6 | 7 | 0.86 | Time-sensitive recall degraded. |
| Without Reflection | reflection | 6 | 7 | 0.86 | User-habit synthesis lost direct reflection support. |
| Without Community Summaries | community summaries | 5 | 7 | 0.71 | Broad architecture synthesis degraded. |
| Without Correction/Supersession | contradiction and supersession logic | 6 | 7 | 0.86 | Migration/correction semantics weakened. |
| Vector-only baseline | graph, deep mode, foresight, reflection, community summaries, session working set | 2 | 7 | 0.29 | Flat vector recall kept simple facts but lost most architecture-specific behavior. |
| Flat-memory baseline | flat memory mode | 6 | 7 | 0.86 | Mostly held up, but structured-first recall lost evidence quality. |
| Full-transcript baseline | transcript-only baseline | 1 | 7 | 0.14 | Raw transcript context did not replace structured memory. |

The ablation result supports the architecture story: simple fact recall can survive with less
machinery, but correction handling, relational migration, foresight, and synthesis depend on the
specialized memory layers. The weak baselines are also useful: they show why MIRA is not just
"put everything in a vector store" or "paste the whole transcript."

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

If your machine uses the older standalone Compose binary, replace `docker compose` with
`docker-compose`:

```bash
docker-compose build
docker-compose run --rm devtools python -m scripts.seed_demo \
  --workspace-id workspace_legacy_default --reset
docker-compose up api worker frontend
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
# or:
API_PORT=18000 FRONTEND_PORT=15173 docker-compose up api worker frontend
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
- Local embedding model cache: `.docker-data/model-cache`

Inside the containers these are mounted as:

- `MIRA_DB_PATH=/data/sqlite/mira.db`
- `CHROMA_DB_PATH=/data/chroma`
- `LOCAL_EMBEDDING_CACHE_DIR=/data/model-cache`

Run checks inside Docker:

```bash
docker compose run --rm devtools make check
# or:
docker-compose run --rm devtools make check
```

## Docker production

Production Compose reads the DevOps-managed `.env` file on the remote host. The ignored local
`.env.production` file is only a private reference for tracking the expected production values;
Compose and the deployment workflow do not read it.

```bash
docker compose -f docker-compose.prod.yml config --quiet
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d --remove-orphans
```

The remote `.env` should use `https://mira.ninja` for `APP_BASE_URL` and
`MIRA_OAUTH_ISSUER_URL`, `https://mira.ninja/mcp` for `MIRA_MCP_PUBLIC_URL`, and
`https://mira.ninja/api/auth/github/callback` for `GITHUB_CALLBACK_URL`. Production Compose
persists SQLite, Chroma, and the FastEmbed model cache under `.docker-data/`.

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
- [ADR-0011: Structured-First Retrieval Weighting](docs/adr/0011-structured-first-retrieval-weighting.md)
- [ADR-0012: Hybrid Contradiction and Supersession Detection](docs/adr/0012-hybrid-contradiction-supersession-detection.md)
- [ADR-0013: Workspace-Bound Data Ownership](docs/adr/0013-workspace-bound-data-ownership.md)
- [ADR-0014: Provenance-Aware Conversation Deletion](docs/adr/0014-provenance-aware-conversation-deletion.md)
- [ADR-0015: Provider Profiles and Capability-Aware Structured Output](docs/adr/0015-provider-profiles-and-structured-output.md)
- [ADR-0016: Authenticated Standalone MCP Service](docs/adr/0016-authenticated-standalone-mcp-service.md)

## Further reading

- [MIRA paper](docs/mira-paper.md)
- [Architecture overview](docs/architecture.md)
- [Alibaba Cloud deployment proof](docs/alibaba-cloud-deployment.md)
- [Demo script](docs/demo-script.md)
- [Contributing guide](CONTRIBUTING.md)

## License

[MIT](LICENSE)
