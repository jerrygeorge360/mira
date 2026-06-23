# MIRA

MIRA is a cognitive memory framework for persistent AI agents. Its session-aware
architecture immediately preserves raw observations, maintains lightweight provisional
state for the current session, synthesizes durable cross-session memory asynchronously,
and builds prompts from recent, ambient, session, and retrieved context.

> **Warning:** this repository is a scaffold only. No business logic or model integration
> is implemented yet.

## Architecture overview

```text
new turn -> fast-path persistence and queueing
         -> session extraction -> validation -> temporary Session Working Set
         -> budgeted prompt construction
         -> later slow-path confirmation and durable enrichment
```

The fast path never calls a model. The Session Working Set is temporary runtime state,
not a cold/warm/hot tier, though it receives hot-level prompt priority. The slow path
produces confirmed facts, graph edges, foresight, reflections, community summaries, and
tier changes. Retrieval offers Quick, Deep, Relational, and Auto modes. See
[docs/architecture.md](docs/architecture.md).

## Folder structure

```text
core/
  memory/      raw observation and durable cross-session memory contracts
  session/     session micro-path and Session Working Set contracts
  retrieval/   Quick, Deep, Relational, and Auto retrieval
  context/     prompt budgeting, merging, and ambient context
  llm/         future model integration
  db/          SQLite truth and ChromaDB indexing
ui/            app and graph visualization
slack/         bot and MCP server
evaluation/    judge, LongMemEval, and ablation
tests/         test scaffold
docs/          architecture, issues, and ADRs
scripts/       integration and demo-seeding stubs
```

## Development setup

Python 3.11 is required.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
make install
cp .env.example .env
make check
```

## Makefile commands

- `install`: install requirements.
- `run`: invoke the UI stub.
- `test`: run pytest and core coverage.
- `lint`, `format`, `fix`: check or format with Ruff.
- `type`: run strict mypy.
- `security`: run Bandit.
- `check`: run lint, type, security, and tests.
- `precommit`: run all hooks.
- `clean`: remove generated caches and reports.

## Branch workflow

`main` is protected and release-ready. Feature branches named
`feature/issue-XXX-short-description` merge into `dev` first. Pull requests must link
their issue and pass `make check`. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Team ownership

- **Jerry:** architecture, core memory, retrieval, and LLM integration.
- **Kelechi:** database, deployment, and infrastructure.
- **Sarah:** UI, graph visualization, evaluation, and demo mode.

## Current implementation status

Scaffold only. The repository defines architecture boundaries and typed interfaces, but
contains no business logic, persistence behavior, retrieval algorithms, or model calls.

## License

[MIT](LICENSE)
