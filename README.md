# MIRA - Memory-Integrated Reasoning Architecture

<p align="center">
  <img src="docs/assets/mira-readme-banner.png" alt="MIRA - inspectable memory for AI agents" width="100%" />
</p>

MIRA is a structured memory system for AI agents. Instead of treating the prompt as memory, it stores conversation events, extracts durable knowledge, builds a typed memory graph, and reconstructs prompts from the right information at runtime.

The result is an inspectable memory layer that survives across sessions, tracks corrections instead of overwriting history, and explains why a memory was retrieved.

For deeper design notes, see [docs/mira-paper.md](docs/mira-paper.md) and [docs/architecture.md](docs/architecture.md).

---

## The problem

Most AI agents rely on the current conversation as their memory. That works for short interactions, but breaks down once conversations become long-lived.

Agents struggle to:

- remember information across sessions;
- handle user corrections without losing history;
- explain why something was remembered;
- scale beyond the model's context window.

MIRA separates memory from prompting. Conversations become structured records that can be searched, linked, updated, and inspected independently of any single LLM.

---

## What MIRA does

The runtime loop is straightforward:

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

The background worker continuously enriches memory:

```text
queued observation
  -> embeddings
  -> atomic facts
  -> entities and graph edges
  -> contradiction / supersession handling
  -> reflections
  -> foresight
  -> community summaries
```

---

## Core features

- **Session Working Set** for immediate goals, corrections, decisions, constraints, and open questions.
- **Durable memory** backed by SQLite with observations, facts, graph records, reflections, foresight, and retrieval traces.
- **Correction-aware memory** where newer facts supersede older ones without deleting history.
- **Typed memory graph** connecting observations, entities, evidence, contradictions, and relationships.
- **Multiple retrieval modes** including Quick, Deep, Relational, and Auto routing.
- **Inspectable traces** showing what memory was retrieved and why.
- **Ambient runtime context** without permanently storing transient information.
- **Multiple LLM providers** including DeepSeek, Gemini, DashScope, SiliconFlow, and local embeddings.
- **Multiple interfaces** including FastAPI, Web UI, Streamlit, Slack, and MCP.

---

## Example

```text
User: My project database is MongoDB.
MIRA: saves the observation.

User: Correction: we migrated to PostgreSQL.
MIRA: updates the active session immediately and later records a SUPERSEDED_BY relationship.

Later...

User: What database does my project use?
MIRA: answers PostgreSQL and returns the retrieval trace explaining why.
```

The previous MongoDB record is preserved as historical context rather than deleted.

---

## Why MIRA?

Unlike traditional memory systems that store embeddings and retrieve similar text, MIRA treats memory as structured infrastructure.

- Conversations are stored as durable observations.
- Facts, entities, and relationships are extracted into a typed graph.
- Corrections preserve history instead of overwriting it.
- Retrieval combines vectors, graph traversal, reflections, and temporal reasoning.
- Every answer can return an inspectable retrieval trace.

This allows agents to reason over long-lived memory while preserving provenance and explainability.

---

# Architecture

SQLite is the source of truth.

ChromaDB provides a rebuildable vector index over SQLite records, while NetworkX is used as a read-only projection for graph algorithms rather than primary storage.

<p align="center">
  <img src="docs/assets/mira-c4-achitecturaldiagram.png" alt="MIRA architecture diagram" width="100%" />
</p>

```text
core/
  agent.py          runtime loop
  db/               SQLite schema and Chroma index
  llm/              providers, prompts, embeddings
  memory/           observations, facts, graph, reflections
  session/          Session Working Set
  retrieval/        routing and retrieval strategies
  context/          prompt construction

api/                FastAPI backend
frontend/           React web interface
ui/                 Streamlit inspection UI
slack/              Slack integration
integrations/mcp/   MCP server
evaluation/         evaluation and benchmarks
docs/               architecture and design notes
tests/              test suite
```

More detail: [docs/architecture.md](docs/architecture.md).

---

# Quick Start

Python 3.11 is expected.

```bash
python3.11 -m venv .venv
source .venv/bin/activate

make install
cp .env.example .env

make check
```

Load environment variables:

```bash
set -a
source .env
set +a
```

Choose a provider profile:

```bash
LLM_PROFILE=deepseek
DEEPSEEK_API_KEY=your_key

LLM_RESPONSE_FORMAT=auto

EMBEDDING_MODE=local
LOCAL_EMBEDDING_PROVIDER=fastembed
LOCAL_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
```

Other supported profiles include `dashscope`, `siliconflow`, and `gemini`.

Verify the configuration:

```bash
make provider-check
```

---

## Running locally

Start the API:

```bash
make api
```

Start the background worker:

```bash
make worker
```

Start the frontend:

```bash
make frontend-dev
```

Open:

```text
http://localhost:5173
```

The frontend communicates with the API at:

```text
http://localhost:8000
```

The API handles requests while the worker continuously processes durable memory in the background.

---

# Authentication & Workspaces

MIRA isolates memory by workspace.

For local development without GitHub OAuth:

```bash
MIRA_AUTH_MODE=development
MIRA_DEVELOPMENT_WORKSPACE_ID=workspace_legacy_default
```

To use GitHub OAuth instead, configure the required environment variables in `.env`:

```env
MIRA_AUTH_MODE=github
GITHUB_CLIENT_ID=your_client_id
GITHUB_CLIENT_SECRET=your_client_secret
GITHUB_CALLBACK_URL=http://localhost:8000/auth/github/callback
APP_BASE_URL=http://localhost:5173
COOKIE_SECURE=false
```

See the deployment documentation for the complete production configuration.

---

# Docker

Run the complete development environment:

```bash
docker compose build
docker compose up api worker frontend
```

Open:

```text
http://localhost:5173
```

Persistent data is stored under:

- `.docker-data/sqlite/`
- `.docker-data/chroma/`
- `.docker-data/model-cache/`

Production deployment details are documented separately.

---

# Runtime Inspection

Inspect the memory graph:

```bash
WORKSPACE_ID=workspace_legacy_default make graph-inspect
```

Search durable memory:

```bash
WORKSPACE_ID=workspace_legacy_default \
QUERY="what database do I use now?" \
make memory-search
```

Inspect slow-path processing:

```bash
WORKSPACE_ID=workspace_legacy_default make slow-path-status
```

---

# Evaluation

MIRA includes built-in tooling for regression testing, component ablations, and LongMemEval-style benchmarking.

Run the local evaluation suite:

```bash
make local-eval
```

Run the benchmark:

```bash
make benchmark
```

Run offline ablation:

```bash
make ablation
```

The latest evaluation summary is published in:

```text
evaluation/local/published_summary.json
```

Additional benchmark and evaluation commands are documented under `evaluation/`.

---

# Use Cases

MIRA is designed for applications that need long-lived, inspectable memory, including:

- personal AI assistants
- developer copilots
- research assistants
- Slack agents
- support agents
- workflow automation
- MCP-powered applications

---

# Implementation Status

MIRA includes a complete end-to-end memory pipeline:

- persistent conversation storage
- Session Working Set
- durable memory extraction
- typed memory graph
- retrieval routing
- answer traces
- FastAPI backend
- web interface
- Streamlit inspection UI
- Slack integration
- MCP server
- local evaluation and benchmarks
- Docker support

Some areas remain prototype-grade and are being actively improved, but the core runtime, retrieval pipeline, and memory infrastructure are fully functional.

---

# Roadmap

Current priorities include:

- improving benchmark reporting
- expanding worker observability
- procedural memory
- multimodal memory
- advanced multi-user memory policies

---

# Architecture Decision Records

Major design decisions are documented in [`docs/adr`](docs/adr):

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

---

# Team

- **Jerry** — Architecture, memory runtime, retrieval, prompt construction, and LLM integration.
- **Kelechi** — Database, infrastructure, deployment, Slack integration, and MCP.

---

# Further Reading

- [MIRA paper](docs/mira-paper.md)
- [Architecture overview](docs/architecture.md)
- [Alibaba Cloud deployment proof](docs/alibaba-cloud-deployment.md)
- [Demo script](docs/demo-script.md)
- [Contributing guide](CONTRIBUTING.md)

---

# License

Licensed under the [MIT License](LICENSE).