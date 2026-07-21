# MIRA - Memory-Integrated Reasoning Architecture

<p align="center">
  <img src="docs/assets/mira-readme-banner.png" alt="MIRA - inspectable memory for AI agents" width="100%" />
</p>

MIRA is a memory layer for AI agents. It keeps useful context across sessions, handles
corrections without erasing history, and shows developers why a memory affected an answer.

[Live demo](https://mira.ninja) · [Architecture](docs/architecture.md) ·
[Technical report](docs/mira-paper.md) · [MIT License](LICENSE)

## OpenAI Build Week

- **Category:** Developer Tools
- **Build tools:** Codex with GPT-5.6
- **Live demo:** [mira.ninja](https://mira.ninja)
- **Demo video:** OpenAI-specific walkthrough link pending

MIRA existed before OpenAI Build Week began on July 13, 2026. The memory engine is the
baseline. I am submitting the work added from July 13 through July 21: workspace isolation,
the product frontend, better runtime inspection, provenance-aware deletion, an authenticated
MCP service, production deployment, provider controls, and several memory-correctness fixes.

The last pre-Build Week commit was
[`dc33e2c`](https://github.com/jerrygeorge360/mira/commit/dc33e2ccaeac6d865b747d089c550d7e2a25c3be).
A pull request merged on July 13 contained commits authored before the eligibility window, so
I count that work as baseline rather than Build Week work.

MIRA fits Developer Tools because it gives agent builders both a memory runtime and a way to
inspect it. Developers can see session state, durable facts, graph relationships, retrieval
routes, evidence traces, worker progress, memory health, provider settings, and evaluation
results.

## The Problem

Long-running agents have a problem that a larger prompt does not solve:

- they forget decisions and preferences between sessions;
- an old fact can keep influencing answers after the user corrects it;
- vector similarity finds related text but does not decide which fact is current;
- raw transcript history wastes context on irrelevant turns; and
- developers cannot easily see why a memory was retrieved.

MIRA treats the prompt as an execution buffer, not the memory store. It persists evidence,
structures it, and builds a bounded prompt from the information needed for the current turn.

## Who MIRA Is For

MIRA is for developers building long-running assistants, copilots, support systems, research
tools, workflow agents, and MCP clients that need memory with provenance and user boundaries.

## What MIRA Does

```text
User message
  -> persist the turn
  -> update the Session Working Set
  -> route and retrieve memory
  -> check whether the evidence is sufficient
  -> build a prompt under a token budget
  -> generate and save the answer
  -> save the retrieval trace

Background worker
  -> atomic facts and entities
  -> typed temporal graph
  -> SUPERSEDED_BY or CONTRADICTS relationships
  -> reflection and foresight
  -> community summaries and memory tiers
```

The immediate path protects current-session goals, decisions, constraints, and corrections.
The worker builds durable cross-session memory without making the user wait for every
enrichment step.

## Session memory vs. cross-session memory

The **Session Working Set** is temporary, high-priority state for the current conversation.
The session micro-path can apply a correction before the background worker finishes.

The **cross-session slow path** confirms and structures durable memory. Corrections are
forward-only: MIRA can stop an old value from influencing future answers without rewriting
the historical conversation.

This separation lets MIRA react quickly while keeping durable memory deliberate and traceable.

## Project Status Before Build Week

Before July 13, MIRA already had:

- fast observation persistence and a Session Working Set;
- atomic facts, a typed graph, reflection, foresight, community summaries, and memory tiers;
- SQLite as canonical storage and ChromaDB as a rebuildable vector index;
- Quick, Deep, Relational, and Auto retrieval;
- correction, `SUPERSEDED_BY`, and `CONTRADICTS` semantics;
- structured-first retrieval, one sufficiency retry, prompt construction, and answer traces;
- configurable OpenAI-compatible model providers;
- FastAPI, Streamlit, a worker, evaluation, ablation, and benchmark code; and
- ADRs 0001 through 0012.

The saved 13/13 local evaluation and the seven-case ablation were also run before Build Week.
I report them as baseline evidence, not as new Build Week results.

## What Changed During OpenAI Build Week

| Contribution | What changed | Why it matters | Evidence |
| --- | --- | --- | --- |
| Workspace ownership and product frontend | Added GitHub auth, disposable demo workspaces, scoped repositories, schema checks, and a React interface | Memory belonging to different users is separated below the UI | [`f31e026`](https://github.com/jerrygeorge360/mira/commit/f31e0265c7b5d5ff59865f118bb4a55b676a538e) |
| Runtime inspection | Added live pipeline, graph, retrieval, working-set, memory-health, community, reflection, foresight, and results views | Reviewers can see the architecture working instead of trusting a diagram | [`ee42942`](https://github.com/jerrygeorge360/mira/commit/ee4294297600c726d3662d3289156738192cc174) |
| Provenance-aware deletion | Deleting a conversation now prunes its support from facts, entities, graph records, reflections, communities, hot memory, and vectors | Deleted conversations no longer remain as hidden sources of recall | [`012d0a7`](https://github.com/jerrygeorge360/mira/commit/012d0a7283c7a9db2771613f3f8a654a59763ac8) |
| Workspace-scoped graph reads | Tightened graph, change-edge, working-set, and SQLite concurrency behaviour | Inspection and retrieval cannot cross workspace boundaries | [`67d1c16`](https://github.com/jerrygeorge360/mira/commit/67d1c16c95a20ad1b37c7cc3379f8cfce478922c) |
| Authenticated MCP | Added Streamable HTTP, OAuth discovery, PKCE, consent, token rotation, revocation, and workspace-bound tools | External agents can use MIRA without direct database access or a shared master token | [`9162568`](https://github.com/jerrygeorge360/mira/commit/9162568c612cdc63eee9c193e246295b6ab97bf9) |
| Production operations | Added production Compose services, Nginx/TLS routing, CI-gated deployment, persistent volumes, and quieter health logs | The deployed system follows the same separated API, worker, frontend, and MCP topology used locally | [`7ce97ad`](https://github.com/jerrygeorge360/mira/commit/7ce97ad), [`32984da`](https://github.com/jerrygeorge360/mira/commit/32984da) |
| Memory correctness | Improved turn-purpose classification, contradiction pairing, conflict surfacing, and reflection gating | Declarative updates and unrelated facts are less likely to produce irrelevant or false-conflict answers | [`cb8c6f1`](https://github.com/jerrygeorge360/mira/commit/cb8c6f1a0eec7fb237ecb9374455410723792623) |
| Admin and evaluation visibility | Added a read-only platform overview, provider selection, and a tracked evaluation fallback | Operators can inspect the service and production does not lose its results screen after a rebuild | [`ec3c8ee`](https://github.com/jerrygeorge360/mira/commit/ec3c8eea19400e85aa495e5aaad5e10628b9814a), [`c621e11`](https://github.com/jerrygeorge360/mira/commit/c621e1178acdcd756a25f6dd42d85c8b82700b3e) |

## How I Collaborated With Codex

MIRA started from my research and architecture decisions. Codex did not invent the whole
system. I used it as an engineering partner while turning the research design into software
that had to survive real users, Docker, provider failures, authentication, deletion, and
background processing.

The system is spread across the API, worker, SQLite, ChromaDB, graph logic, retrieval router,
prompt builder, frontend, and evaluation harness. Codex was particularly useful for debugging
operations across those boundaries. It helped me follow failures from a browser error or worker
log back to the exact storage, retrieval, or model call that caused it. Examples included stale
Chroma pointers, malformed provider JSON, false contradiction edges, reflection overproduction,
workspace leakage risks, and memory that survived conversation deletion.

It was also useful as a brainstorming partner. I gave it the research paper and asked it to
challenge the gap between the paper and the running product. We worked through questions such as:

- How does a two-speed memory architecture behave when the worker is delayed or restarted?
- How should SQLite remain the source of truth while ChromaDB and graph projections stay
  rebuildable?
- What does correction provenance mean when a user deletes one of several supporting chats?
- Which paper mechanisms deserve a visible product surface, and which should remain internal?
- Where should deterministic checks stop and model-assisted classification begin?
- How can MCP and workspace authentication expose memory without weakening ownership rules?

I made the final decisions, selected the trade-offs, tested the behaviour, and rejected changes
that did not match the architecture. Codex helped inspect the repository, plan small passes,
implement selected changes, review diffs, interpret test failures, and update the documentation.

| Example | Codex's role | My decision | Evidence |
| --- | --- | --- | --- |
| Workspace isolation | Traced ownership through storage, retrieval, worker, graph, and UI paths | Enforce workspace identity below the HTTP layer | [`tests/test_workspace_ownership.py`](tests/test_workspace_ownership.py) |
| Conversation deletion | Found derived records that outlived their source conversation | Retain memory only when another valid source supports it | [`core/session_deletion.py`](core/session_deletion.py) |
| False contradictions | Followed a bad classification through graph creation and later retrieval | Use model assistance with deterministic guards and same-property checks | [`tests/test_memory_change.py`](tests/test_memory_change.py) |
| MCP access | Reviewed transport, token, redirect, and workspace boundaries | Use standalone MCP with OAuth and PKCE | [`tests/test_mcp_oauth.py`](tests/test_mcp_oauth.py) |
| Runtime inspection | Mapped UI claims to implemented read models | Show only information the runtime can support | [`ee42942`](https://github.com/jerrygeorge360/mira/commit/ee4294297600c726d3662d3289156738192cc174) |

## How GPT-5.6 Was Used

I used GPT-5.6 through Codex at build time for repository-wide reasoning, debugging, design
trade-offs, patch review, tests, and documentation grounded in the code and research paper.

MIRA does **not** claim GPT-5.6 as its deployed runtime model. Runtime generation goes through a
configurable OpenAI-compatible adapter with profiles for DashScope/Qwen, DeepSeek, Gemini, and
SiliconFlow.

## Key Product and Engineering Decisions

| Decision | Reason | Evidence |
| --- | --- | --- |
| Session Working Set and durable memory are separate | Immediate corrections should not wait for consolidation | [ADR-0001](docs/adr/0001-session-working-set.md), [ADR-0006](docs/adr/0006-session-micro-path-slow-path.md) |
| SQLite is canonical; ChromaDB is rebuildable | The semantic index must not become a second source of truth | [ADR-0003](docs/adr/0003-sqlite-source-of-truth.md) |
| One typed graph | Facts, entities, evidence, changes, and synthesis need shared provenance | [ADR-0002](docs/adr/0002-single-typed-graph.md) |
| Supersession differs from contradiction | A confirmed change is not the same as an unresolved conflict | [ADR-0012](docs/adr/0012-hybrid-contradiction-supersession-detection.md) |
| Structured-first retrieval | Validated records should outrank matching raw transcript fragments | [ADR-0011](docs/adr/0011-structured-first-retrieval-weighting.md) |
| One sufficiency retry | Retrieval can repair a weak query without entering a loop | [`core/retrieval/sufficiency.py`](core/retrieval/sufficiency.py) |
| Traces are part of correctness | A plausible answer is not enough if the intended mechanism did not run | [`core/memory/trace.py`](core/memory/trace.py) |
| Workspace ownership is enforced before ranking | Filtering after retrieval is too late | [ADR-0013](docs/adr/0013-workspace-bound-data-ownership.md) |

## Demo

### Live demo

[https://mira.ninja](https://mira.ninja)

Any judge credentials are provided privately in the Devpost testing field.

### Suggested test

1. Start a conversation.
2. Enter: `My project database is MongoDB.`
3. Enter: `Correction: we migrated to PostgreSQL.`
4. Ask: `Which database does my project currently use?`
5. Inspect the retrieval trace and graph relationship.
6. Open another session in the same workspace.
7. Ask the database question again.

MIRA should answer PostgreSQL, preserve MongoDB as historical evidence, retrieve the current
fact in the new session, and show the records that influenced the answer. The worker is
asynchronous, so wait for the pipeline view to show durable processing before testing the new
session.

## Setup

### Docker local development

Docker is the recommended way to run MIRA. It starts the API, worker, and frontend with persistent
storage and a shared embedding-model cache.

Requirements: Docker and Docker Compose, an API key for one configured provider, and internet
access for the first image build and local embedding-model download.

```bash
git clone https://github.com/jerrygeorge360/mira.git
cd mira
cp .env.example .env
```

Set the local auth mode, provider, and embedding mode in `.env`:

```env
MIRA_AUTH_MODE=development
MIRA_DEVELOPMENT_WORKSPACE_ID=workspace_legacy_default

LLM_PROFILE=dashscope
DASHSCOPE_API_KEY=your_provider_key

EMBEDDING_MODE=local
LOCAL_EMBEDDING_PROVIDER=fastembed
LOCAL_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
EMBEDDING_FALLBACK=error
```

Build and start the product:

```bash
docker compose build
docker compose up api worker frontend
```

Open [http://localhost:5173](http://localhost:5173), then verify the API:

```bash
curl http://localhost:8000/health
```

Persistent data is stored in:

- `.docker-data/sqlite/mira.db`
- `.docker-data/chroma`
- `.docker-data/model-cache`

Use alternate host ports when the defaults are occupied:

```bash
API_PORT=18000 FRONTEND_PORT=15173 docker compose up api worker frontend
```

The first semantic request can be slow while FastEmbed downloads its model. The model-cache
volume prevents that download on every restart.

### Docker logs and inspection

```bash
docker compose logs -f api worker frontend
```

Start the log viewer separately and open [http://localhost:8080](http://localhost:8080):

```bash
docker compose up logs
```

Useful checks from another terminal:

```bash
docker compose ps
docker compose exec api python -m scripts.check_provider --require-live-embeddings
docker compose exec worker python -m scripts.slow_path_status \
  --workspace-id workspace_legacy_default
```

### Common Docker problems

- **No durable memory appears:** confirm the `worker` container is running and inspect its logs.
- **The provider rejects a request:** check that `LLM_PROFILE` matches the configured API key.
- **The first query takes time:** FastEmbed may still be downloading the local embedding model.
- **The frontend cannot reach the API:** check the API health endpoint and Compose ports.
- **ChromaDB reports a stale internal ID:** rebuild the disposable index from SQLite with
  `REBUILD=1 WORKSPACE_ID=workspace_legacy_default QUERY="health check" make memory-search`.

### Native development

Python 3.11 and Node.js 18+ are expected.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
make install
cp .env.example .env
make frontend-install
make check
```

Load `.env` before starting native processes:

```bash
set -a
source .env
set +a
```

## Running Locally

MIRA's main product uses three processes:

```bash
make api           # FastAPI on :8000
make worker        # durable memory processing
make frontend-dev  # Vite on :5173
```

Run each command in a separate terminal. The MCP service and Streamlit inspector are optional:

```bash
make mcp
make run
```

## Makefile commands

| Command | Purpose |
| --- | --- |
| `make install` | Install Python dependencies |
| `make api` | Start FastAPI |
| `make worker` | Start durable memory processing |
| `make frontend-dev` | Start the browser application |
| `make mcp` | Start the standalone MCP service |
| `make provider-check` | Check chat and embedding providers |
| `make slow-path-status` | Inspect queue and artifact health |
| `make graph-inspect` | Print a workspace graph snapshot |
| `make memory-search` | Test embedding and vector pointer health |
| `make local-eval` | Run local behavioural cases |
| `make ablation-live` | Run live component ablations |
| `make benchmark` | Run the LongMemEval-compatible harness |
| `make check` | Run lint, typing, security checks, and tests |

## Architecture flow

SQLite is the source of truth. ChromaDB is a rebuildable index that points back to SQLite
records. The typed graph is persisted in SQLite. NetworkX and igraph are read-only in-process
views used for algorithms and community detection.

<p align="center">
  <img src="docs/assets/mira-c4-achitecturaldiagram.png" alt="MIRA C4 architecture diagram" width="100%" />
</p>

```text
Frontend / Streamlit / MCP client
              |
       FastAPI or MCP service
              |
         core/agent.py
      +-------+--------+
      |                |
Session Working Set  retrieval router
      |         Quick / Deep / Relational
      +-------+--------+
              |
  context merge + token budget
              |
 configurable runtime provider
              |
  answer + retrieval trace

Background worker
  -> facts -> graph -> reflection / foresight / communities -> tiers

SQLite: canonical records
ChromaDB: semantic index
NetworkX / igraph: algorithm views
```

See [docs/architecture.md](docs/architecture.md) for the full implementation path.

## Core Features

- Session Working Set for current goals, corrections, constraints, decisions, and questions.
- Durable facts, graph edges, reflection, foresight, community summaries, and memory tiers.
- Quick, Deep, Relational, and Auto retrieval with structured-first ranking.
- Prompt construction under a token budget and one focused sufficiency retry.
- Retrieval traces, graph provenance, pipeline status, and memory-health read models.
- Workspace-scoped storage, retrieval, worker processing, and conversation deletion.
- FastAPI, React, Streamlit, MCP, Docker, authentication, and evaluation tools.
- Provider profiles for DashScope/Qwen, DeepSeek, Gemini, and SiliconFlow.
- ambient runtime context that can influence a prompt without becoming durable memory.

## Supported Platforms

The verified path is Linux with Python 3.11, Docker Compose, and a modern Chromium-based browser.
macOS and Windows may work through Python or Docker, but this repository does not claim them as
tested platforms.

## Sample Data and Reproducible Scenarios

- [`evaluation/local/memory_cases.json`](evaluation/local/memory_cases.json) contains behavioural
  conversations and mechanism expectations.
- [`evaluation/ablation/ablation_cases.json`](evaluation/ablation/ablation_cases.json) contains
  focused component cases.
- [`evaluation/benchmarks/sample_longmemeval.json`](evaluation/benchmarks/sample_longmemeval.json)
  is a small LongMemEval-format sample.

## Evaluation

MIRA's local cases check mechanisms as well as answer text. They can require a retrieval mode,
source type, Session Working Set item, graph edge, or top-ranked record. This catches an answer
that sounds correct even when the intended memory mechanism did not run.

| Evaluation | Result | Evidence |
| --- | ---: | --- |
| Local behavioural suite | 13/13 | [`evaluation/local/published_summary.json`](evaluation/local/published_summary.json) |
| Targeted ablation, full system | 7/7 | [`docs/evaluation-story.md`](docs/evaluation-story.md) |
| Vector-only baseline | 2/7 | [`docs/evaluation-story.md`](docs/evaluation-story.md) |
| Full-transcript baseline | 1/7 | [`docs/evaluation-story.md`](docs/evaluation-story.md) |
| LongMemEval subset | 5 examples, 0.4 LLM-judge pass rate | [`docs/evaluation-story.md`](docs/evaluation-story.md) |

These numbers have limits. The local and ablation runs were completed before Build Week. The
ablation has seven focused cases, and the LongMemEval result is only a five-example subset. They
are useful evidence that the mechanisms run, not a claim of broad statistical performance.

```bash
make local-eval

python -m scripts.run_local_eval \
  --cases evaluation/local/memory_cases.json \
  --live \
  --run-slow-path

RUN_SLOW_PATH=1 PARALLEL=2 LIMIT=1 \
OUT=tmp/evaluation/results make ablation-live
```

## What Makes MIRA Different

MIRA is not saved chat history, vector search over transcripts, or an ever-growing prompt. It
combines immediate session memory with durable structured memory, preserves correction history,
routes different questions through different retrieval modes, tracks provenance, budgets prompt
context, and makes those choices visible.

## Implementation status

The full memory loop is implemented: persistence, Session Working Set, queued slow path, durable
facts and graph records, retrieval, prompt construction, provider calls, answer persistence, and
traces. The product also includes authentication, workspace ownership, conversation deletion,
MCP, Docker, and evaluation tools.

MIRA is still a single-server prototype. It uses SQLite, an in-process rate limiter, and a local
worker queue. Distributed storage, distributed queues, and a complete LongMemEval run are not yet
implemented. Provider-backed stages still depend on provider latency and structured-output
behaviour.

## Build Week Evidence

| Evidence | What it shows |
| --- | --- |
| [`dc33e2c`](https://github.com/jerrygeorge360/mira/commit/dc33e2ccaeac6d865b747d089c550d7e2a25c3be) | Last pre-Build Week baseline commit |
| [`f31e026`](https://github.com/jerrygeorge360/mira/commit/f31e0265c7b5d5ff59865f118bb4a55b676a538e) | Product frontend, auth, and workspace ownership |
| [`012d0a7`](https://github.com/jerrygeorge360/mira/commit/012d0a7283c7a9db2771613f3f8a654a59763ac8) | Provenance-aware deletion and runtime hardening |
| [`9162568`](https://github.com/jerrygeorge360/mira/commit/9162568c612cdc63eee9c193e246295b6ab97bf9) | Authenticated standalone MCP service |
| [`cb8c6f1`](https://github.com/jerrygeorge360/mira/commit/cb8c6f1a0eec7fb237ecb9374455410723792623) | Turn classification and memory-synthesis fixes |
| [`tests/test_workspace_ownership.py`](tests/test_workspace_ownership.py) | Cross-workspace isolation tests |
| [`tests/test_api_sessions.py`](tests/test_api_sessions.py) | Deletion and provenance tests |
| [`tests/test_mcp_oauth.py`](tests/test_mcp_oauth.py) | OAuth, PKCE, token, and workspace tests |
| [ADR-0013](docs/adr/0013-workspace-bound-data-ownership.md) | Workspace ownership decision |
| [ADR-0016](docs/adr/0016-authenticated-standalone-mcp-service.md) | MCP service and authentication decision |
| [`docs/alibaba-cloud-deployment.md`](docs/alibaba-cloud-deployment.md) | Production topology and deployment evidence |
| [`docs/checkpoint-auth-ui.md`](docs/checkpoint-auth-ui.md) | Repository-level record of Codex-assisted product work |

Private Codex transcripts and session identifiers are not published.

## Team ownership

- **Jerry George:** architecture, memory runtime, retrieval, prompt construction, evaluation,
  model integration, product direction, and Build Week product and correctness work.
- **Kelechi (deltron-fr):** fast observation path, ChromaDB wrapper, structured JSON repair,
  response evidence logging, database work, and production infrastructure including deployment,
  Nginx, TLS, and log access controls.

## Architecture decision records

- [ADR-0001: Session Working Set](docs/adr/0001-session-working-set.md)
- [ADR-0002: Single Typed Graph](docs/adr/0002-single-typed-graph.md)
- [ADR-0003: SQLite Source of Truth](docs/adr/0003-sqlite-source-of-truth.md)
- [ADR-0004: Retrieval Modes](docs/adr/0004-retrieval-modes.md)
- [ADR-0006: Session Micro-Path and Slow Path](docs/adr/0006-session-micro-path-slow-path.md)
- [ADR-0011: Structured-First Retrieval](docs/adr/0011-structured-first-retrieval-weighting.md)
- [ADR-0012: Contradiction and Supersession](docs/adr/0012-hybrid-contradiction-supersession-detection.md)
- [ADR-0013: Workspace Ownership](docs/adr/0013-workspace-bound-data-ownership.md)
- [ADR-0014: Provenance-Aware Deletion](docs/adr/0014-provenance-aware-conversation-deletion.md)
- [ADR-0015: Provider Profiles and Structured Output](docs/adr/0015-provider-profiles-and-structured-output.md)
- [ADR-0016: Authenticated MCP Service](docs/adr/0016-authenticated-standalone-mcp-service.md)

## Roadmap

- Run and publish a larger LongMemEval evaluation.
- Replace process-local limits and queues when multi-server deployment requires it.
- Add procedural and multimodal memory as separately tested capabilities.

## Further Reading

- [MIRA technical report](docs/mira-paper.md)
- [Implementation architecture](docs/architecture.md)
- [Evaluation story](docs/evaluation-story.md)
- [Alibaba Cloud deployment proof](docs/alibaba-cloud-deployment.md)
- [Contributing guide](CONTRIBUTING.md)

## License

MIRA is licensed under the [MIT License](LICENSE).
