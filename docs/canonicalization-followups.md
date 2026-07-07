# Canonicalization Follow-up Issues

These are deferred from the PR that introduced the canonical subject/predicate
registry and fixed contradiction/supersession pairing (`core/memory/change.py`,
`core/db/schema.py`, `slow_path._active_prior_fact_ids`). They are intentionally
**not** built yet; this file records scope and rationale so they can be filed as
tracker issues.

## FOLLOWUP-1: transition clause-splitting for "switched/migrated from X to Y"

**Problem.** `supersession-migration` ("I switched from MongoDB to PostgreSQL")
still produces no `SUPERSEDED_BY` edge. Extraction packs the whole transition into
a single fact object (e.g. `object = "MongoDB to PostgreSQL for storage"`) instead
of emitting an old→new pair, so there are never two comparable facts (same canonical
subject+predicate, different object) for change detection to pair.

**Scope.** Detect transition patterns (`switched/migrated/moved/changed from X to Y`)
during atomic-fact extraction and split them into two facts — a prior fact with
object `X` and a new fact with object `Y` sharing subject+predicate — so the existing
canonical pairing + `detect_memory_change` produce the `SUPERSEDED_BY` edge.

**Why separate from the canonicalization PR.** This is a different bug (single fact
never split into a pair), not an inconsistent-wording bug. Mixing it in would blur
what the canonical registry change is responsible for.

## FOLLOWUP-3: transition markers lost when facts are sourced from assistant echoes

**Problem.** In `contradiction-preferences` ("I prefer Python." → "Actually I prefer
Rust."), canonical pairing now works and an edge is created, but live it comes out
`CONTRADICTS` instead of `SUPERSEDED_BY`. The paired facts are extracted from the
**assistant's echo** observations ("You prefer Python." / "You prefer Rust."), not the
user turns. `change._has_explicit_transition` only inspects the new fact's single source
observation, so the user's "Actually" transition marker never reaches it. Both paired
facts are assistant-sourced, so neither carries the marker.

**Scope options.** Either (a) stop extracting atomic facts from assistant-echo
observations (they are paraphrases, not ground truth), or (b) widen transition detection
to consider the conversational context / both facts' evidence rather than one
observation. Distinct from FOLLOWUP-1 (explicit clause-splitting) and from the
canonicalization pairing fix.

## FOLLOWUP-2: canonicalization — confidence-gated merging + audit trail

**Problem.** Today, wording that matches no seeded alias creates a new low-confidence
canonical bucket from the raw form (e.g. `prefers_language`). That is deliberately
visible and reviewable, but it means near-synonyms stay unpaired until a human adds
the alias. Automatically merging them is risky: a wrong auto-merge silently corrupts
which facts supersede which.

**Scope.**
- Embedding-similarity fallback matching so a new raw form can be proposed as an alias
  of an existing canonical bucket instead of spawning its own.
- A confidence gate: only auto-merge above a threshold; below it, record a pending
  merge for review rather than applying it.
- A merge audit/reversal table so any auto-merge is inspectable and reversible.

**Why separate.** Low-confidence auto-merges must be reversible, not silent. Shipping
similarity matching without the audit/reversal trail would reintroduce the exact class
of silent-failure this work set out to eliminate.
