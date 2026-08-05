# MIRA

<p align="center">
  <img src="docs/assets/mira-readme-banner.png" alt="MIRA, inspectable memory for AI agents" width="100%" />
</p>

**MIRA is an inspectable memory layer for AI agents. It retrieves the smallest useful set of
memories for each turn, builds a bounded prompt, and measures what every model call costs.**

[Live product](https://mira.ninja) | [Architecture](docs/architecture.md) |
[Technical report](docs/mira-paper.md) | [Apache 2.0 License](LICENSE)

Built with [Paritok](https://github.com/Paritok-official/paritok-4b-v1).

## Token-Efficiency Hackathon

Most agent requests carry more context than the model needs. MIRA attacks that problem at two
different boundaries:

1. **Memory selection:** scope-first routing chooses recent conversation, session memory, or
   durable memory, then runs Quick, Deep, or Relational retrieval only when required.
2. **Context compression:** optional [Paritok](https://github.com/Paritok-official/paritok-4b-v1)
   compression reduces eligible context after retrieval and before the provider call.

Paritok does not replace MIRA's memory architecture or model provider. MIRA still handles
corrections, temporal validity, graph relationships, sufficiency checks, prompt construction,
answer persistence, and traces. Paritok sits at the final provider boundary.

## What MIRA Does

```text
User message
  -> persist immediately
  -> update the Session Working Set
  -> decide the required context scope
  -> retrieve relevant durable memory when needed
  -> verify that evidence answers the actual question
  -> build a prompt under a token budget
  -> optionally compress eligible context with Paritok
  -> call the selected model provider
  -> save the answer, trace, and measured token usage

Background worker
  -> extract atomic facts and entities
  -> update the typed temporal graph
  -> resolve supersession and contradiction
  -> produce reflection, foresight, communities, and memory tiers
  -> record every slow-path model call and its token usage
```

SQLite is the source of truth. ChromaDB is a rebuildable semantic index. NetworkX and igraph are
read-only algorithm views over the persisted graph.

<p align="center">
  <img src="docs/assets/mira-c4-achitecturaldiagram.png" alt="MIRA C4 container architecture" width="100%" />
</p>

## Measuring Token Use

MIRA records each model request at the shared OpenAI-compatible client boundary, including
classifiers, routing checks, sufficiency checks, answer generation, structured extraction, and
the asynchronous slow path.

For each call, the ledger records:

- provider, model, operation, gateway, status, and latency;
- provider-reported input, output, cached, and reasoning tokens when available;
- Paritok's request-scoped original, compressed, and saved token counts;
- workspace, session, observation, and logical run identifiers; and
- a SHA-256 prompt fingerprint for paired comparisons.

Prompt and response contents are not stored in the usage ledger. Provider-reported counts are
treated as authoritative. Estimates are labeled and are not presented as measured savings.

### Where to see the numbers

- **Chat:** total foreground usage for the completed user turn, plus Paritok savings when active.
- **Memory Pipeline:** asynchronous slow-path calls grouped by observation and operation. It
  refreshes while the worker is processing the observation.
- **Administration:** aggregate provider and gateway usage across the workspace.
- **Comparison report:** controlled direct-versus-Paritok answer-generation calls using identical
  prompt fingerprints.

This separation matters. The chat badge does not hide worker costs, and worker calls are not
incorrectly attributed to an earlier foreground response.

## Run With Docker

Requirements: Docker Compose, a supported model-provider key, and a Paritok API key.

```bash
git clone --branch feat/paritok-token-efficiency --single-branch \
  https://github.com/jerrygeorge360/mira.git
cd mira
```

Create `.env` from `.env.example` if you do not already have one, then configure the minimum
local values:

```env
MIRA_AUTH_MODE=development
MIRA_DEVELOPMENT_WORKSPACE_ID=workspace_legacy_default

LLM_PROFILE=deepseek
DEEPSEEK_API_KEY=your_deepseek_key

EMBEDDING_MODE=local
LOCAL_EMBEDDING_PROVIDER=fastembed
LOCAL_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5

PARITOK_API_KEY=your_paritok_key
PARITOK_UPSTREAM_PROFILE=deepseek
PARITOK_UPSTREAM_ENDPOINT=https://api.deepseek.com/chat/completions
MIRA_PARITOK_ENABLED=false
```

The Paritok upstream profile must match `LLM_PROFILE`. Start the complete stack:

```bash
make mira-paritok-up
```

Open [http://localhost:5173](http://localhost:5173). In **Administration**:

1. Select the model provider.
2. Switch **Paritok compression** on or off without changing the provider.
3. Send a chat message and inspect its usage line.
4. Open **Memory Pipeline** to watch the worker and slow-path token usage.

Useful runtime commands:

```bash
docker compose --profile paritok ps
docker compose --profile paritok logs -f api worker paritok
make paritok-stats
make mira-paritok-down
```

The first semantic request may download the local FastEmbed model. Its Docker cache is persisted
under `.docker-data/model-cache`, so normal container restarts do not download it again.

## Controlled Comparison

The comparison runner sends the same MIRA answer-generation messages once directly and once
through Paritok. It requires provider-reported usage from both runs, verifies matching prompt
fingerprints, and checks required answer terms.

```bash
LIMIT=1 OUT=tmp/token-comparison.json make token-compare
```

Increase `LIMIT` after the first case succeeds:

```bash
LIMIT=3 OUT=tmp/token-comparison.json make token-compare
```

The generated report contains direct and compressed input tokens, tokens saved, reduction
percentage, latency, and a basic output-quality check for each case. The comparison measures
**answer generation only**. The live ledger and Administration view account for the complete
agent and worker pipeline.

No aggregate hackathon result is claimed in this README until the controlled suite has completed.

## Memory Demo

Try this sequence with Paritok enabled and disabled:

```text
My project database is MongoDB.
Correction: we migrated to PostgreSQL.
Which database does my project currently use?
Why did we migrate?
```

MIRA should recall PostgreSQL, retain MongoDB as historical evidence, and avoid inventing a reason
for the migration. Inspect:

- **Retrieval Trace** for context scope, retrieval mode, evidence, and sufficiency;
- **Memory Graph** for `SUPERSEDED_BY` or `CONTRADICTS` relationships;
- **Memory Pipeline** for background artifacts and slow-path token consumption; and
- **Administration** for direct-versus-Paritok usage totals.

## Evaluation

MIRA's local suite checks mechanisms as well as answer text. Cases can require a routing scope,
retrieval mode, working-set item, graph edge, or specific evidence source.

| Evaluation | Saved result |
| --- | ---: |
| Local behavioural suite | 13/13 |
| Targeted ablation, full system | 7/7 |
| Vector-only baseline | 2/7 |
| Full-transcript baseline | 1/7 |

Evidence and limitations are documented in [docs/evaluation-story.md](docs/evaluation-story.md).
These memory evaluations are separate from the new Paritok token comparison.

```bash
make local-eval
python -m pytest -o addopts="" --tb=short -q tests/test_llm_usage.py
make lint
make type
```

## Core Components

| Area | Implementation |
| --- | --- |
| Agent flow | `core/agent.py` |
| Prompt budget and construction | `core/context/` |
| Provider adapter and usage capture | `core/llm/qwen.py`, `core/llm/usage.py` |
| Retrieval | `core/retrieval/` |
| Session and durable memory | `core/session/`, `core/memory/` |
| Canonical storage and vector index | `core/db/` |
| API and worker | `api/`, `scripts/run_worker.py` |
| Product interface | `frontend/` |
| Token comparison | `scripts/compare_token_usage.py` |

## Current Limits

- MIRA is a single-server prototype using SQLite and a local worker queue.
- Provider usage metadata varies; missing counts remain clearly marked as estimates.
- The paired comparison currently tests answer generation, not every internal model call.
- Paritok integration is pinned to version 1.2.7 with narrow compatibility patches that should be
  removed when equivalent upstream fixes are released.
- A larger memory benchmark and a completed token-comparison report remain separate evaluation
  work.

## Team

- **Jerry George:** architecture, memory runtime, retrieval, prompt construction, evaluation,
  model integration, and product direction.
- **Kelechi (deltron-fr):** fast observation path, ChromaDB wrapper, structured JSON repair,
  response evidence logging, database work, and production infrastructure.

## Further Reading

- [Implementation architecture](docs/architecture.md)
- [Technical report](docs/mira-paper.md)
- [Token accounting decision](docs/adr/0017-llm-usage-and-compression-gateway.md)
- [Evaluation methodology](docs/evaluation-story.md)

## License

This submission branch is licensed under the
[Apache License 2.0](LICENSE). See [NOTICE](NOTICE) for the retained notice covering earlier
MIT-licensed distributions. Other Git branches retain their own license files unless this license
commit is merged into them.
