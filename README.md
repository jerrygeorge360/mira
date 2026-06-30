# MIRA — Memory-Integrated Reasoning Architecture

MIRA is a session-aware, cross-session memory framework for persistent personalized LLM
agents. It treats the model's context window as a temporary execution buffer rather than a
memory store: every turn is persisted immediately, a lightweight **Session Working Set**
keeps the current conversation's corrections and constraints usable on the very next reply,
an asynchronous slow path consolidates durable cross-session memory (atomic facts, a typed
temporal graph, reflections, foresight, and community summaries), and a retrieval-gated
prompt builder merges session and cross-session memory under a strict token budget before
each model call. The design and its terminology are described in the
[MIRA paper](docs/mira-paper.md) and the [architecture overview](docs/architecture.md).

## Session memory vs. cross-session memory

MIRA separates two consolidation timelines that operate on different clocks. This split is
the architecture's central idea.

| | Session continuity (fast) | Cross-session learning (slow) |
| --- | --- | --- |
| **Question it answers** | What matters *now* in this chat? | What should persist for next time? |
| **Mechanism** | Session micro-path → Session Working Set | Asynchronous slow path |
| **Holds** | Current goal, corrections, active constraints, decisions, open questions | Atomic facts, typed graph edges, reflections, foresight, community summaries, tiers |
| **Latency** | Immediate (no model call on the fast path) | Deferred, batchable |
| **Status** | Provisional until confirmed | Confirmed, durable |
| **Prompt priority** | High (hot-level), but not durable | High when retrieved within budget |

A correction like *"Use 2026, not 2025"* is extracted by the session micro-path and shapes
the **next** response immediately — before the slow path has synthesized anything. The slow
path later confirms, downgrades, expires, or rejects that provisional item, and records
durable updates with `SUPERSEDED_BY` or `CONTRADICTS` edges. Corrections apply forward
only; prior turns are never rewritten.

## Architecture flow

```text
user turn
  └─ fast path: persist observation + enqueue        (no model call)
  └─ session micro-path: extract → validate → Session Working Set
  └─ hydrate durable memory (new session / "continue …")
  └─ route retrieval (Auto → Quick | Deep | Relational) + sufficiency check
  └─ merge context (recent turns · session items · hot memory · retrieved · ambient)
  └─ build prompt under token budget → call Qwen
  └─ persist assistant turn + enqueue → structured response + trace

asynchronous slow path (per queued observation)
  └─ embeddings · atomic facts · entities · typed graph edges
  └─ contradiction vs. supersession · reflections · foresight
  └─ community detection/summaries · tier promotion/demotion
  └─ confirm / expire / reject Session Working Set candidates
```

The Session Working Set has hot-level prompt priority but is **not** a cold/warm/hot tier.
Retrieval offers **Quick**, **Deep**, **Relational**, and **Auto** modes; the prompt
builder is the integration point between session and cross-session memory. See the
[ADRs](docs/adr) for the reasoning behind each decision.

## Setup

Python 3.11 is required.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
make install
cp .env.example .env      # add your DASHSCOPE_API_KEY
make check
```

`.env` is documented in [.env.example](.env.example). The DashScope key must match its
region: MIRA defaults the endpoint to the international host
(`DASHSCOPE_CHAT_ENDPOINT=https://dashscope-intl.aliyuncs.com/...`).

## Demo

Seed deterministic data, then run the Streamlit app:

```bash
python -m scripts.seed_demo --reset
make run
```

The app opens on a polished landing page and then launches the **Memory Command Center**:

- collapsible Claude-style sidebar with chat history and memory surfaces;
- central chat workspace with a demo/real-agent toggle;
- graph viewer with click-to-inspect memory nodes, evidence IDs, and connected paths;
- Session Working Set, Retrieval Trace, Reflections, Community Summaries, Timeline, and
  Evaluation Dashboard surfaces;
- separate UI sections for official benchmark tracks and ablation studies.

Most visual panels are intentionally backed by deterministic demo data so the team can
rehearse the story without waiting for organic long conversations. The chat surface has an
explicit **Use real MIRA agent** toggle: demo mode calls a deterministic mock agent; real
mode calls `core.agent.Agent(DEFAULT_SESSION_ID).respond(...)` and therefore requires the
database, DashScope/Qwen credentials, and runtime memory components to be configured.

The judge/user walkthrough is in [docs/demo-script.md](docs/demo-script.md). You can also
drive the runtime directly without the UI:

```python
from core.db.repositories import configure_database, create_session
from core.agent import handle_user_message

configure_database("mira.db")
session = create_session("jerry")
print(handle_user_message(session, "Use 2026, not 2025, for all dates."))
```

## FastAPI product backend

MIRA also exposes a product API boundary for non-Streamlit clients:

```bash
set -a
source .env
set +a
make api
```

The server runs:

```bash
uvicorn api.main:app --reload --host 0.0.0.0 --port ${PORT:-8000}
```

Initial endpoints:

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

The API is intentionally thin: routes call `core.agent`, repositories, graph/retrieval
read models, and worker status helpers. Memory logic remains in `core/`, not in HTTP route
handlers.

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

To run checks inside the container:

```bash
docker compose run --rm app make check
```

Environment variables are documented in [.env.example](.env.example). Docker Compose uses
safe defaults for local paths and reads secrets such as `DASHSCOPE_API_KEY` from your shell
or `.env`; secrets are not baked into the image.

## Makefile commands

- `install` — install requirements.
- `run` — launch the Streamlit UI (`ui/app.py`).
- `api` — launch the FastAPI product backend (`api.main:app`).
- `test` — run pytest.
- `lint`, `format`, `fix` — check or format with Ruff.
- `type` — run strict mypy.
- `security` — run Bandit.
- `check` — run lint, type, security, and tests.
- `precommit` — run all pre-commit hooks.
- `clean` — remove generated caches and reports.

## Repository layout

```text
core/
  agent.py     runtime loop: user message -> answer (handle_user_message)
  observability.py   structured logging and secret redaction
  memory/      observations, atomic facts, typed graph, reflections, foresight, tiers, community
  session/     session micro-path, Session Working Set, confirmation, hydration
  retrieval/   Quick, Deep, Relational, Auto router, sufficiency
  context/     prompt builder, budget, merger, ambient context
  llm/         Qwen client, prompts, JSON parsing
  db/          SQLite source of truth, ChromaDB index, schema, repositories
ui/            Streamlit app and graph visualization
api/           FastAPI product backend adapter over the MIRA core runtime
slack/         Slack bot and MCP memory server
evaluation/    cases harness, LongMemEval/LoCoMo adapter, ablations, judge
docs/          paper, architecture, ADRs, demo script, issues
scripts/       demo seeding and integration scripts
tests/         test suite
```

## Implementation status

This reflects the repository honestly — implemented behavior vs. work that is still a
typed stub. (Run `make check` to validate everything marked implemented.)

| Area | Status |
| --- | --- |
| Fast path: observation persistence + queueing | ✅ Implemented |
| Session micro-path, Session Working Set, confirmation, hydration | ✅ Implemented |
| Atomic facts, entities, single typed temporal graph | ✅ Implemented |
| Contradiction vs. supersession (`CONTRADICTS` / `SUPERSEDED_BY`) | ✅ Implemented |
| Reflection synthesis + evidence-based staleness/invalidation | ✅ Implemented |
| Foresight records + lifecycle | ✅ Implemented |
| Community detection (Leiden, with fallback) + summaries | ✅ Implemented |
| Tier policy (cold/warm/hot promotion & demotion) | ✅ Implemented |
| Retrieval: Quick, Deep, Relational, Auto router, sufficiency check | ✅ Implemented |
| Context merge, token budget, ambient context | ✅ Implemented |
| Agent runtime (`handle_user_message`) + answer trace | ✅ Implemented |
| Structured logging / secret redaction | ✅ Implemented |
| Evaluation: cases harness, LongMemEval/LoCoMo adapter, ablations | ✅ Implemented |
| Evaluation judge: deterministic, LLM, and hybrid judge modes | ✅ Implemented |
| Premium Streamlit UI shell + Memory Command Center | ✅ Implemented (demo-first, real-agent chat toggle) |
| MCP memory server skeleton, Slack bot, Docker setup | ✅ Implemented |
| Cross-session slow-path **step** functions | ✅ Implemented |
| Async slow-path **orchestrator**, worker loop, and queue status helpers | ✅ Implemented |
| Public retrieval **dispatcher** (`router.route_retrieval`) | 🟡 Stub — classifier done in `retrieval/auto.py` |
| Vector search boundary (`retrieval/vector.py`) | 🟡 Stub — Chroma index helpers live in `core/db/chroma.py` |
| Standalone prompt builder facade (`context/prompt_builder.py`) | 🟡 Stub — agent renders centralized prompts inline |
| Durable hot working-memory pool (`memory/working.py`) | 🟡 Stub |
| Function-calling helper and memory-inspector UI contract | 🟡 Stub |
| Full procedural memory, multimodal, multi-user | ⛔ Out of scope (future work) |

## Team ownership

- **Jerry** — architecture, core memory, retrieval, context, and LLM integration.
- **Kelechi** — database, deployment, infrastructure, and Slack/MCP.
- **Sarah** — UI, graph visualization, evaluation, and demo mode.

## Evaluation surfaces

MIRA separates two evaluation stories:

- **Official benchmark results** — whole-system runs against external/standard memory tasks
  such as LongMemEval and LoCoMo-style temporal conversational memory.
- **Ablation studies** — internal component-removal runs that measure what degrades when one
  MIRA subsystem is disabled, such as the Session Working Set, keyword retrieval, typed graph
  traversal, foresight records, or reflections/community summaries.

The landing page introduces both categories. The in-app Evaluation Dashboard is the place to
record the actual numbers once runs are complete.

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

- [MIRA paper](docs/mira-paper.md) — abstract, contributions, and architecture summary.
- [Architecture overview](docs/architecture.md).
- [Contributing guide](CONTRIBUTING.md) — branch-per-issue workflow; PRs link their issue and must pass `make check`.

## License

[MIT](LICENSE)
