# MIRA Spec-Alignment Plan

Working tracker reconciling the codebase against the research paper
(`MIRA: Memory-Integrated Reasoning Architecture`, June 2026).

## How to read this doc

The paper is the **design intent**, not a contract the code must follow verbatim.
The implementation has made practical decisions that may intentionally diverge, and
the paper may be updated later to match the code. So every gap below is a **decision
point**, categorized by how to reconcile it:

- **bug** — code contradicts its own intent / a layer silently doesn't work. Fix the code.
- **decide** — code diverges from the paper for a possibly-good practical reason. Choose: align code, or keep the choice and update the paper.
- **verify** — likely fine; confirm it actually works end-to-end.

Nothing here is "the code is wrong because the paper says X." Several of these may end
up as paper edits rather than code changes.

## Status of the six demo scenarios (live-audited)

See `docs/demo-scenario-audit.md` for the full audit. Summary: #1 ok, #2 fixed, #4 ok;
#3 broken, #5/#6 dormant.

## What the full paper resolved (previously "open" questions)

| Question | Paper's position | Section |
| --- | --- | --- |
| Reflection trigger | recent observations + cumulative importance, not queue batch | p7, p27 |
| Community detection trigger | background job over the entity graph | p27 |
| CONTRADICTS behavior | pair → edge → lower confidence, keep both, surface via Relational | p21, DR5 |
| Stale memory in retrieval | "stale beliefs stop controlling current reasoning" | p9, p21 |
| Quick ranking | RRF + decay-aware reranking + recall gating | p23 |
| Assistant text as memory | `agent_response` is a FIELD of the observation, not a separate searchable observation | p12 |
| Preference/change routing | Relational first (Auto rule 1) | p24 |
| Prompt-build priority | session > hot > recent turns > retrieved warm/cold; raw turns trimmed first | p25-26 |

## Problems found (this investigation)

1. **Reflection + community detection never run** in one-at-a-time draining (batch-count gated). Dormant. *This corrupted the ablation: `without_reflection` = 10/10 because reflection never fired.*
2. **CONTRADICTS never fires** for contradictory deadlines — extraction fragments the subject (`Project` vs `project deadline`), so facts never pair.
3. **Canonicalization fragmentation** — FIXED (determiner + snake_case normalization; supersession now 4/4 live).
4. **Retrieval prefers raw/stale memory**: (a) superseded facts not status-filtered, (b) assistant observations pollute candidates, (c) flat weighted-sum ranking (no RRF/recall-gating), (d) preference queries route to Quick not Relational.

## Plan

Checkboxes track progress. `[reconcile]` = bug / decide / verify.

### Phase A — correctness that unblocks the ablation (DONE)

- [x] **A1. Reflection trigger** → now drawn from recent observations in the store (accumulated across batches). Also relocated reflection+community into `run_slow_path_batch` (the eval/demo drain never called them — the deeper reason they were dormant). Batch-scoped test updated. Verified live: 1 reflection vs 0 before. Paper p7, p27.
- [x] **A2. Community detection trigger** → DB-derived cumulative counter (`_observations_since_last_community_refresh`: observations processed since the last summary), default lowered 50→8. Verified live: 8 summaries created naturally during drain, Deep Mode retrieves them. Paper p27.
- [x] **A3. Agent attribution** (full, per decision) — assistant turns contribute only facts about themselves (`subject=assistant`, re-attributed); user-echoes and third-party/world assertions dropped. Verified live: 0 user/world facts leaked from assistant turns. Retrieval de-prioritization of raw assistant observations deferred to **B1** (ranking, not exclusion — keeps provenance/continuity). Paper p12.
- [x] **A4. Status-aware retrieval** — narrower than expected: atomic facts were *already* `status='active'`-filtered and foresight `active/pending`-filtered; the real gap was **stale reflections via vector search**, now excluded (`_semantic_record_is_active`). Contradicted-fact treatment deferred to Phase C (none exist until CONTRADICTS fires). Paper p9, p21.

### Phase B — spec-conformant retrieval (DONE)

- [x] **B2. Hybrid router** (per decision) — deterministic route first; escalate to the existing LLM classifier (`_llm_route_retrieval`) only when the route is low-confidence (<0.65) or ambiguous, and only when a provider key is configured (so unit tests / offline stay deterministic). Agent defaults to `strategy="hybrid"`. Threshold lowered 0.72→0.65 and a personal→general downgrade guard added after the benchmark showed the LLM escalation flipping a correct deterministic personal-memory route (conf 0.70) to general_knowledge and abstaining. Paper p24.
- [x] **B1. Quick ranking = RRF + structured-first** (per decision) — reciprocal rank fusion over the semantic + keyword retrievers, a source-tier weight so validated derived memory (facts/foresight/reflections) outranks the raw observation log (observations = fallback), decay-aware rerank, and a relative recall gate. Replaces the flat weighted sum. **Divergence from paper p23** (RRF but no source priority) — reconcile in the paper. Verified live: for "what do I prefer?" the Rust fact/foresight rank top-2, stale Python observations demoted to fallback.
- [x] **B3. Sufficiency wiring** — the check existed but was never executed (agent only flagged it). Ambiguous routes now run `resolve_with_one_retry` (retrieve → sufficiency check → one rewrite+retry) instead of answering on thin context. Verified: resolver runs when flagged, skipped when confident. Paper p24.

Design note (observations): retrieved as **fallback/evidence**, not a primary answer source — needed for the latency gap, extraction misses, provenance, and evidence chains. Structured-first weighting + recall gating implement this.

### Phase C — contradiction (Problem 2) (DONE)

- [x] **C1. Contradiction pairing — hybrid: deterministic fast path + LLM verifier.** Two earlier heuristics were tried and dropped: **entity-graph** (entity extraction too unreliable — extracts the date, not "project") and **subject-containment** (brittle token overlap). Final design (per user): the deterministic canonical scan handles **exact** same-subject+predicate pairs cheaply; everything else is **embedding-shortlisted** (top-k similar recent facts) and **verified by one LLM call** (`contradiction_supersession_detection` schema — already existed, unused) that judges entity identity, value equivalence, and change-vs-conflict semantically. Verdicts are id-validated + confidence-gated (≥0.5); the call degrades to no-op without a provider (tests stay offline). Verified live: **3/3 fire** on same-entity conflicting deadlines (subject *and* predicate fragmentation), **0/3 false positives** across different entities. Design Req 3/4.
- [x] **C2. CONTRADICTS outcome** — `apply_contradiction` lowers both facts' confidence (×0.7) and keeps both active. Verified live (conf 0.7, both active). Paper p21.
- [x] **C3. Mode-dependent resolver** — Relational already traverses CONTRADICTS; added `resolve_retrieved_contradictions`, wired into the agent so retrieved contradicted facts inject an unresolved-conflict note. Verified: the answer surfaces both values, flags it unresolved, prefers recency. Paper p21.

### Phase D — evaluation alignment (after A-C work)

- [x] **D1. Ablation set** (per decision — keep extras, update paper) — added three paper baselines: `without_community_summaries` (seams `deep._community_candidates`), `flat_memory` (replaces `quick`/`deep` `SOURCE_WEIGHT` with a flat mapping so no source outranks another — ablates the B1 structured-first tiering), and `full_transcript` (seams `agent.retrieve_by_mode` + session-working-set + hot-memory to empty, so the model answers from the raw transcript alone). Baselines carry their own names via `BASELINE_CONFIGS`, not `without_X`; `SELECTABLE_ABLATIONS` gates the CLI. **Kept** the extra `without_deep_mode` / `without_contradiction_supersession` (useful) — the standard set is now 11 configs, a superset of the paper's 8; reconcile by updating the paper. Seam-application unit-tested. Paper p28.
- [x] **D2. Eval cases** — added three to `memory_cases.json`: `contradiction-deadline-conflict` (asserts a CONTRADICTS edge + both dates surface), `reflection-self-knowledge` (5 habit obs → Deep query retrieves a `reflection`), `deep-mode-community-summary` (8 connected obs → Deep query retrieves a `community_summary`). Assert end-to-end (created *and* retrieved), the honest signal. Live-only (need a provider); they run in D3, not offline CI. Paper p28.
- [x] **D3. Re-run DONE** (DeepSeek + local embeddings, clean single run on the fixed system).
  **Local eval 13/13 (1.00)**. `reflection-user-knowledge` now PASSES
  (reflection firing+retrieval fixes verified end-to-end), and contradiction handling now
  preserves explicit graph evidence. **Ablation: full_system 7/7 (1.00)**
  on the lean set; every layer discriminates cleanly and attributes to the right case
  (session_working_set→session-constraint, relational/contradiction→supersession,
  reflection→reflection, deep_mode & community_summaries→reflection+community, foresight→foresight,
  **flat_memory→structured-first** — structured-first weighting is load-bearing on ranking-sensitive
  queries, resolving the earlier "flat_memory looked inert" question). Baselines crater:
  vector_only 0.29, full_transcript 0.14. Ablation sped up via lean case set + default-on LLM
  cache + `PARALLEL=N` (parallel verified == sequential). `[verify]` satisfied.
- [x] **D4. Reflection-invalidation staleness** — **found + fixed a real bug**: `_step_reflection_invalidation` only re-checked reflections derived from the *incoming* observation, so when a new observation superseded an *old* fact, the reflection built on that old observation was never re-evaluated. Fix: `_apply_changes` now records the superseded/contradicted prior fact's `source_observation_id` into `context["reflection_recheck_observations"]`, and the invalidation step re-checks reflections from those too. Verified end-to-end (superseding the 2025 fact invalidates a reflection grounded on the old observation). Retrieval-side filtering already correct: Quick (`_semantic_record_is_active`), Deep (`_fetch_active_reflections` status='active'), and hydration all exclude non-active reflections — stale beliefs stop controlling retrieval. **`confirmed_memory_id` lineage — decision needed:** no structured column exists. Lineage today is (a) durable→session, structured, via `working_memory_items.source_record_id → session_working_set.id`, and (b) session→durable, free-text, via `resolution_reason = "promoted_to_durable_candidate:{id}"`. Plain `confirm_session_item` records no durable id (confirmation ≠ promotion). **Recommendation: do NOT add a `confirmed_memory_id` column now** — nothing reads it, provenance is already queryable via `source_record_id`; keep the current arrangement and update the paper. Paper p12, p21.

## Sequencing logic

A makes the layers actually run and keeps stale/assistant junk out — without it, the
ablation and demos measure a broken system. B makes retrieval match the paper (or
prompts a paper edit). C is the hardest/riskiest, isolated. D re-establishes honest
evidence last.
