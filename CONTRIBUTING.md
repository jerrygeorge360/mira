# Contributing to MIRA

Thanks for working on MIRA. This guide covers the branching model, the local
workflow, and the conventions every change is expected to follow.

## Getting set up

```bash
make install                 # create .venv and install the dev toolchain
.venv/bin/pre-commit install # enable the git hooks
make check                   # confirm a clean baseline
```

## Branching model

We are a small team, so the rules are deliberately simple and enforced from day
one (this was flagged HIGH risk in the issue tracker — cheap to fix now).

- **`main`** — protected. No direct pushes. Only updated via reviewed pull
  requests from `dev`. Always releasable.
- **`dev`** — integration branch. Feature branches merge here first and soak
  before promotion to `main`.
- **`feature/issue-XXX-short-description`** — one branch per issue, cut from
  `dev`. Example: `feature/issue-010-leiden-communities`.

Fix branches follow the same shape: `fix/issue-XXX-short-description`.

### Flow

```
feature/issue-XXX  ──PR──►  dev  ──PR──►  main
```

1. Cut `feature/issue-XXX-...` from an up-to-date `dev`.
2. Open a PR into `dev`. CI (`make check`) must pass and one teammate must
   approve.
3. Periodically, `dev` is promoted to `main` via a reviewed PR.

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/):
`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`. Reference the issue
where relevant, e.g. `feat(memory): add Leiden community detection (ISSUE-010)`.

## Code conventions

- Every module starts with a docstring naming what it does and its `ISSUE-XXX`.
- Full type hints on every function and method; `make type` runs mypy `--strict`.
- Public functions and classes carry docstrings.
- Keep lines within 100 columns; `make format` handles layout.
- New code lands with tests. `make check` must be green before you open a PR.

## Before you push

```bash
make check   # lint + types + security + tests, exactly what CI runs
```

## Architecture decisions

Significant decisions are logged as ADRs in [docs/adr/](docs/adr/). If your
change reverses or extends a decision, add or supersede the relevant ADR in the
same PR.
