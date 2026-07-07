# Architecture Issue Map

Module docstrings use issue-family placeholders until final tracker numbers are assigned.

- ISSUE-100: fast path and durable memory.
- ISSUE-200: session micro-path.
- ISSUE-300: retrieval.
- ISSUE-400: prompt construction.
- ISSUE-500: persistence.
- ISSUE-600–900: UI, Slack, evaluation, tests, and scripts.
- ISSUE-1200+: runtime inspection surfaces (`graph-inspect`, `slow-path-status`,
  `memory-search`, `local-eval`) and local architecture diagnostics.

Deferred follow-ups from the canonicalization change are tracked in
[canonicalization-followups.md](canonicalization-followups.md): transition
clause-splitting for supersession, and confidence-gated canonical merging with an
audit trail.
