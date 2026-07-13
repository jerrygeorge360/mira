# Paper Reconciliation — Decisions Log & Update Checklist

Every deliberate decision taken while aligning the code with the paper, framed as **what
to change in the paper**. The paper is design intent, not a contract; where the code made a
better practical choice, the paper should be updated to match (not the reverse).

Use this as a checklist when revising the paper. Each row: the decision, what the **code**
does, what the **paper** currently says (with section), and the **paper action**.

Legend for paper action: **EDIT** = paper text should change; **CLARIFY** = paper is
ambiguous/underspecified; **CONFIRM** = code matches intent, just verify; **ADD** = paper is
missing something the code has.

Related: [`docs/spec-alignment-plan.md`](spec-alignment-plan.md) (phased tracker),
[`docs/adr/`](adr/) (why each decision was made), [`docs/demo-scenario-audit.md`](demo-scenario-audit.md).

---

## A — activating dormant layers & attribution

### A1. Reflection trigger — CONFIRM
- **Decision:** reflection fires from recent unreflected observations accumulated in the
  store (across batches), and the pass runs inside `run_slow_path_batch` (the eval/demo
  drain never called it before).
- **Code:** `maybe_run_reflection_pass` gates on `reflection_min_observations` (default 5)
  and cumulative importance over recent store observations.
- **Paper:** recent observations + cumulative importance, not a queue batch (p7, p27).
- **Paper action:** CONFIRM — aligned. Optionally note the default threshold/cadence.

### A2. Community-detection trigger — CONFIRM (+ note cadence)
- **Decision:** community refresh runs from a DB-derived cumulative observation counter;
  default lowered 50 → 8 for interactive cadence.
- **Code:** `maybe_run_community_refresh` / `_observations_since_last_community_refresh`.
- **Paper:** background job over the entity graph (p27).
- **Paper action:** CONFIRM the background-job framing; optionally note that cadence is a
  tunable threshold (default 8), not a fixed 50.

### A3. Agent responses contribute self-knowledge facts — CLARIFY (divergence nuance)
- **Decision (yours: "full attribution now"):** assistant turns mint memory, but **only
  facts about the agent itself** (subject re-attributed to `assistant`); user-echoes and
  third-party/world assertions from assistant turns are dropped.
- **Code:** `_agent_self_facts` in `core/memory/slow_path.py`.
- **Paper:** `agent_response` is a **field** of the observation, not a separately-searched
  observation (p12).
- **Paper action:** CLARIFY — both can be true, but the paper should state that agent turns
  additionally produce **self-knowledge atomic facts attributed to the assistant** (so the
  system knows what it committed to), distinct from the raw response text which remains a
  field, not a searchable observation.

### A4. Stale reflections excluded from retrieval — CONFIRM
- **Decision:** non-active reflections are filtered from Quick vector search (facts/foresight
  were already status-filtered).
- **Code:** `_semantic_record_is_active` (Quick); Deep and hydration filter `status='active'`.
- **Paper:** stale beliefs stop controlling current reasoning (p9, p21).
- **Paper action:** CONFIRM — aligned.

---

## B — spec-conformant retrieval

### B1. Structured-first Quick ranking — **EDIT** (divergence). See ADR-0011.
- **Decision (yours: "RRF + structured-first"):** validated derived memory (atomic facts,
  foresight, reflections) is weighted **above** the raw observation log; observations are
  fallback/evidence, not the primary answer surface.
- **Code:** `SOURCE_WEIGHT` inside RRF fusion + decay + recall gate in
  `core/retrieval/quick.py`.
- **Paper:** Quick = RRF + decay-aware reranking + recall gating, with **no source
  priority** (p23).
- **Paper action:** **EDIT p23** — add the source-tier weighting and the
  observations-as-fallback stance to the Quick Mode spec.

### B2. Hybrid retrieval router — **ADD** (paper likely describes deterministic Auto only)
- **Decision (yours: recommended hybrid):** deterministic route first; escalate to an LLM
  classifier only when the route is low-confidence (<0.72) or ambiguous, and only when a
  provider key is configured (so offline/tests stay deterministic). Agent default
  `strategy="hybrid"`.
- **Code:** `route_retrieval` + `_llm_route_retrieval` in `core/retrieval/auto.py`.
- **Paper:** Auto routing rules (p24) — deterministic ordering; verify whether an LLM
  classifier fallback is described.
- **Paper action:** **ADD/CLARIFY** — document the deterministic-first + gated-LLM-escalation
  router if the paper only describes deterministic routing.

### B3. Sufficiency check wired in — CONFIRM
- **Decision:** ambiguous routes run retrieve → sufficiency check → one rewrite+retry
  (previously defined but never executed).
- **Code:** `resolve_with_one_retry` called from the agent on `needs_sufficiency_check`.
- **Paper:** Auto rule 4 / sufficiency escalation (p24).
- **Paper action:** CONFIRM — aligned (it now actually runs).

---

## C — contradiction handling

### C1. Hybrid contradiction/supersession detection — **EDIT** (divergence). See ADR-0012.
- **Decision (yours):** embedding shortlist → single structured-JSON LLM verification per
  new fact, on top of the deterministic canonical fast path. Two earlier heuristics
  (entity-graph pairing, token containment) were tried and dropped as unreliable.
- **Code:** `_shortlist_candidate_facts` + `_llm_verify_changes` in `slow_path.py`.
- **Paper:** verify how the paper describes contradiction pairing (the entity-graph idea
  came from an earlier reading).
- **Paper action:** **EDIT** — describe the two-stage detection (deterministic canonical
  scan + embedding-shortlisted, id-validated, confidence-gated LLM verification), replacing
  any pure entity-graph/heuristic description.

### C2. CONTRADICTS keeps both facts, lowers confidence — CONFIRM (+ note factor)
- **Decision:** on contradiction, both facts stay active with confidence × 0.7.
- **Code:** `apply_contradiction` in `core/memory/change.py`.
- **Paper:** pair → edge → lower confidence, keep both (p21, DR5).
- **Paper action:** CONFIRM — aligned; optionally note the reduction factor is 0.7.

### C3. Contradictions surface in ALL modes — **EDIT** (divergence)
- **Decision (yours: "mode-dependent, recommended"):** retrieved contradicted facts inject
  an unresolved-conflict note into the answer regardless of retrieval mode (not only when
  Relational Mode traverses `CONTRADICTS`).
- **Code:** `resolve_retrieved_contradictions` wired into the agent turn.
- **Paper:** CONTRADICTS surfaced **via Relational** (p21).
- **Paper action:** **EDIT p21** — contradictions are surfaced across modes (Relational
  traverses them directly; other modes get a resolver note), not Relational-only.

---

## D — evaluation & lineage

### D1. Ablation set = 11 configs (superset of the paper's 8) — **EDIT**
- **Decision (yours: keep extras, update paper):** added the paper's `without_community_summaries`,
  `flat_memory`, `full_transcript`; **kept** the extra `without_deep_mode` and
  `without_contradiction_supersession`.
- **Code:** `standard_ablations` / `BASELINE_CONFIGS` in `evaluation/ablation/studies.py`.
- **Paper:** 8 ablations (p28).
- **Paper action:** **EDIT p28** — either add the two extra ablations to the paper's table or
  explicitly note them as additional configurations beyond the reported 8.

### D2. Eval cases for CONTRADICTS / reflection / community — CONFIRM
- **Decision:** added dedicated cases so the three behaviors are measured, not assumed.
- **Paper action:** CONFIRM — no paper change; ensures the demo/eval claims are backed.

### D4. No `confirmed_memory_id` column on session items — **EDIT if paper claims it**
- **Decision (yours):** do **not** add a structured `confirmed_memory_id` field. Provenance
  is already queryable via `working_memory_items.source_record_id → session_working_set.id`;
  nothing consumes a `confirmed_memory_id`.
- **Code:** `promote_session_item_to_durable_candidate` / working-memory `source_record_id`.
- **Paper:** confirmed/lineage modeling (p12, p21).
- **Paper action:** **EDIT** — if the paper names a `confirmed_memory_id` on session items,
  remove it or restate lineage as the durable→session `source_record_id` pointer (plus the
  free-text `resolution_reason` back-pointer on promotion).

---

## Quick paper-edit checklist (the EDIT/ADD items)

- [ ] **p23 Quick Mode** — add source-tier (structured-first) weighting + observations-as-fallback (B1).
- [ ] **p24 Auto routing** — document the deterministic-first + gated-LLM-escalation hybrid router (B2).
- [ ] **Contradiction detection** — replace pairing description with the two-stage deterministic+LLM method (C1).
- [ ] **p21 CONTRADICTS** — surface across modes, not Relational-only (C3).
- [ ] **p28 Ablations** — reconcile 11 configs vs 8 (D1).
- [ ] **p12/p21 Lineage** — drop/adjust `confirmed_memory_id`; state `source_record_id` lineage (D4).
- [ ] **p12 Agent responses** — clarify that agent turns mint assistant-attributed self-knowledge facts (A3).
- [ ] Minor: note reflection/community cadence thresholds (A1/A2) and the 0.7 contradiction-confidence factor (C2).
