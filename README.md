# MIRA

**MIRA** is a cognitive memory framework for persistent AI agents. It gives an
agent a dual-stream memory: a synchronous **fast path** that observes every
turn, and an asynchronous **slow path** that consolidates those observations
into reflections, foresight, a knowledge graph, and topical communities. A
retrieval router then serves context from either the graph (formal) or the
embedding store (vector), or a blend of both.

> Status: **bootstrap**. Every module is scaffolded with typed signatures and
> docstrings; implementations land issue-by-issue. See [docs/architecture.md](docs/architecture.md).

## Architecture at a glance

```
        ┌──────────────┐
 turn → │  fast path   │ → working memory → LLM (Qwen) → reply
        │ (observation)│
        └──────┬───────┘
               │ enqueue
        ┌──────▼───────┐
        │  slow path   │ → reflection · foresight · graph · community
        └──────┬───────┘
               │
        ┌──────▼───────┐      ┌──────────────┐
        │ knowledge    │◄────►│  retrieval   │
        │ graph + chroma│      │   router     │
        └──────────────┘      └──────────────┘
```

| Area | Path | Owner |
| --- | --- | --- |
| Agent, memory, retrieval, LLM | `core/` | Jerry |
| Persistence & deployment | `core/db/` | Kelechi |
| UI & evaluation | `ui/`, `evaluation/` | Sarah |

## Quickstart

```bash
make install   # create .venv and install the dev toolchain
make check     # lint, type-check, security scan, and test
make run       # launch the UI (stub)
```

Copy `.env.example` to `.env` and fill in your credentials before running.

## Development

- `make fix` — auto-fix lint findings and format.
- `make test` — run the suite with coverage.
- See [CONTRIBUTING.md](CONTRIBUTING.md) for the branching model and workflow.
- Architecture decisions are recorded in [docs/adr/](docs/adr/).

## License

[MIT](LICENSE)
