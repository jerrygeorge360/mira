# Contributing to MIRA

## Branch strategy

`main`

- Protected.
- No direct pushes.
- Release-ready branch.

`dev`

- Integration branch.
- Feature branches merge here first.

`feature/issue-XXX-short-description`

- One branch per issue.
- Must link to the issue.
- Must pass `make check` before a pull request.

Create feature branches from `dev`, merge them into `dev` through review, and promote
release-ready integration changes to `main` through a separate reviewed pull request.

## Commit convention

Use `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, or `chore:`. Keep commits
focused and reference the issue where useful.

## Code quality expectations

- Use Python 3.11, complete type hints, and useful public API docstrings.
- Use standard-library imports only until an implementation issue approves dependencies.
- Keep fast-path code free of model calls.
- Keep the Session Working Set separate from durable tiered memory.
- Add tests with business logic and run `make check` before every pull request.

## Pull request checklist

- [ ] The pull request links its issue and is narrowly scoped.
- [ ] Interfaces and documentation are updated.
- [ ] Tests are added or scaffold-only status is explained.
- [ ] `make check` passes.
- [ ] No secrets, databases, caches, or indexes are committed.
- [ ] Review feedback is resolved.

## Architecture decisions

New architecture decisions must go into `docs/adr/` with title, status, context,
decision, and consequences. Superseding decisions must link prior ADRs.
