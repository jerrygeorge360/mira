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

- [x] **B2. Hybrid router** (per decision) — deterministic route first; escalate to the existing LLM classifier (`_llm_route_retrieval`) only when the route is low-confidence (<0.72) or ambiguous, and only when a provider key is configured (so unit tests / offline stay deterministic). Agent defaults to `strategy="hybrid"`. Verified: hybrid unit tests + agent suite green. Paper p24.
- [x] **B1. Quick ranking = RRF + structured-first** (per decision) — reciprocal rank fusion over the semantic + keyword retrievers, a source-tier weight so validated derived memory (facts/foresight/reflections) outranks the raw observation log (observations = fallback), decay-aware rerank, and a relative recall gate. Replaces the flat weighted sum. **Divergence from paper p23** (RRF but no source priority) — reconcile in the paper. Verified live: for "what do I prefer?" the Rust fact/foresight rank top-2, stale Python observations demoted to fallback.
- [x] **B3. Sufficiency wiring** — the check existed but was never executed (agent only flagged it). Ambiguous routes now run `resolve_with_one_retry` (retrieve → sufficiency check → one rewrite+retry) instead of answering on thin context. Verified: resolver runs when flagged, skipped when confident. Paper p24.

Design note (observations): retrieved as **fallback/evidence**, not a primary answer source — needed for the latency gap, extraction misses, provenance, and evidence chains. Structured-first weighting + recall gating implement this.

### Phase C — contradiction (Problem 2)

- [ ] **C1. Entity-graph pairing** so contradictory deadlines pair (same entity node + attribute). `[decide]` (algorithm choice; A2 entity-graph vs A1 subject-similarity vs A3 structured extraction). Design Req 3/4.
- [ ] **C2. CONTRADICTS outcome** — edge + lower confidence, keep both active. `[bug/decide]`. Paper p21.
- [ ] **C3. Query-time contradiction resolver** (recency/scope/confidence). `[decide]`. Paper p21.

### Phase D — evaluation alignment (after A-C work)

- [ ] **D1. Ablation set** → the paper's 8 (add without_community_summaries, flat_memory, full_transcript; reconcile the extra without_deep_mode / without_contradiction_supersession). `[decide]`. Paper p28.
- [ ] **D2. Eval cases** → add CONTRADICTS deadlines, self-knowledge reflection (≥5 obs), Deep-Mode-community. `[bug]` (coverage gap). Paper p28.
- [ ] **D3. Re-run** full ablation + all 6 demo scenarios on the honest system. `[verify]`.
- [ ] **D4. Reflection-invalidation staleness** verify + `confirmed_memory_id` lineage on session items. `[verify/decide]`. Paper p12, p21.

## Sequencing logic

A makes the layers actually run and keeps stale/assistant junk out — without it, the
ablation and demos measure a broken system. B makes retrieval match the paper (or
prompts a paper edit). C is the hardest/riskiest, isolated. D re-establishes honest
evidence last.
