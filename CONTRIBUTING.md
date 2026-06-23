# Contributing to MIRA

## Branch strategy

`main`

- Protected.
- No direct pushes.
- Release-ready changes only.

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

Start every commit subject with one of these prefixes:

- `feat:` for a new capability.
- `fix:` for a defect correction.
- `docs:` for documentation-only changes.
- `test:` for test additions or corrections.
- `refactor:` for behavior-preserving code restructuring.
- `chore:` for tooling, maintenance, or repository administration.

Keep commits focused and reference the related issue where useful.

## Team ownership

- **Jerry:** architecture, core memory, retrieval, context, and LLM integration.
- **Kelechi:** database, queues, deployment, infrastructure, and CI hardening.
- **Sarah:** UI, graph visualization, evaluation, and demo tooling.

Ownership identifies the first reviewer and coordinator; it does not prevent
cross-team contribution. Changes spanning ownership areas should involve every affected
owner before merge.

## Code quality expectations

- Use Python 3.11, complete type hints, and useful public API docstrings.
- Use standard-library imports only until an implementation issue approves dependencies.
- Keep fast-path code free of model calls.
- Keep the Session Working Set separate from durable tiered memory.
- Add tests with business logic and run `make check` before every pull request.

## Pull request checklist

- [ ] The related issue is linked and the pull request is narrowly scoped.
- [ ] Tests are added or updated for the change.
- [ ] `make check` passes.
- [ ] Documentation is updated if the architecture or public contract changed.
- [ ] An ADR is added or superseded if a major architectural decision changed.
- [ ] No secrets are committed.
- [ ] The relevant owner has reviewed the change; architecture changes require Jerry's
      manual review.
- [ ] Review feedback is resolved.

## Architecture decisions

New architecture decisions must go into `docs/adr/` with title, status, context,
decision, and consequences. Superseding decisions must link prior ADRs.
