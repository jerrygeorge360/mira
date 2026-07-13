# Session Checkpoint — Spec-Alignment Phase D + Resume

Handoff for the next agent (Codex) picking up this work. Snapshot as of the end of
the Claude session that implemented Phase D and the eval/ablation resume feature.

Branch: **`feat/runtime-inspection-eval`**. Nothing pushed; all work is local commits
plus an uncommitted working tree (the resume feature).

---

## 1. TL;DR — where things stand

- **Phases A–D of the spec-alignment plan are implemented and committed.** The plan
  lives at [`docs/spec-alignment-plan.md`](spec-alignment-plan.md) (the paper is *design
  intent*, not a verbatim contract — each gap is a decision tagged `[bug]`/`[decide]`/`[verify]`).
- **Phase D code is committed** (`176371e`) and offline-verified (60 targeted tests +
  full-suite pass; ruff/format/mypy clean).
- **A resume feature for the eval and ablation harnesses is committed** (`233134d`),
  added alongside this handoff doc. It is offline-proven.
- **Architecture decisions from A–D are recorded as ADRs** in [`docs/adr/`](adr/):
  0011 (structured-first retrieval weighting), 0012 (hybrid contradiction/supersession
  detection); 0009 (reflection staleness) was annotated with the cross-observation trigger.
- **A paper-update checklist** consolidates every code-vs-paper decision at
  [`docs/paper-reconciliation.md`](paper-reconciliation.md) — the single place to look when
  revising the paper (which p-sections to EDIT/ADD/CLARIFY/CONFIRM).
- **The Phase D *live* re-run (D3) has NOT been completed yet.** Two attempts were made:
  one on SiliconFlow crashed on a transient provider connection error; a DeepSeek attempt
  was started then intentionally killed. **No live results files exist yet.** This is the
  main remaining task — see §4.

---

## 2. Commit stack on this branch

```
176371e  Spec-alignment Phase D: eval alignment, paper baselines, reflection-staleness fix
db7b64b  Spec-alignment Phase C: contradiction detection (hybrid pairing, confidence, resolver)
bd87171  Spec-alignment Phase B: hybrid routing, structured-first RRF retrieval, sufficiency wiring
2b722e7  Activate dormant memory layers, fix attribution/canonicalization, add slow-path-aware ablation
```

A follow-up commit on top of these adds the resumable checkpointing (§5) and this handoff
doc (run `git log --oneline -3` for the hash).

Repo conventions observed: commit only on this branch, **no `Co-Authored-By` trailer**,
and never stage `frontend/` (separate Vite app with its own `.env`) or
`evaluation/ablation/results/` (generated artifacts).

---

## 3. What Phase D changed (committed in `176371e`)

- **D1 — ablation baselines.** Added the paper's comparison baselines to the standard
  ablation set in [`evaluation/ablation/studies.py`](../evaluation/ablation/studies.py):
  - `without_community_summaries` — seams `deep._community_candidates` to empty.
  - `flat_memory` — replaces `quick`/`deep` `SOURCE_WEIGHT` with a flat mapping
    (`_FlatWeights`) so no source outranks another; ablates the structured-first tiering.
  - `full_transcript` — seams `agent.retrieve_by_mode` + session working set + hot memory
    to empty, so the model answers from the raw transcript alone.
  - Baselines carry their own names via `BASELINE_CONFIGS` (not `without_X`);
    `SELECTABLE_ABLATIONS` gates the CLI. Standard set is now **11 configs**, a superset of
    the paper's 8 — the extra `without_deep_mode` / `without_contradiction_supersession`
    were kept on purpose (reconcile by updating the paper, `[decide]`).
- **D2 — eval cases.** Three added to
  [`evaluation/local/memory_cases.json`](../evaluation/local/memory_cases.json):
  `contradiction-deadline-conflict` (asserts a `CONTRADICTS` edge + both dates surface),
  `reflection-self-knowledge` (5 habit obs → a Deep query retrieves a `reflection`),
  `deep-mode-community-summary` (8 connected obs → a Deep query retrieves a
  `community_summary`). They assert **end-to-end (created AND retrieved)** and are
  **live-only** (need a provider) — they run in D3, not offline CI.
- **D4 — reflection-invalidation staleness bug (found + fixed).**
  In [`core/memory/slow_path.py`](../core/memory/slow_path.py), `_step_reflection_invalidation`
  only re-checked reflections derived from the *incoming* observation, so when a new
  observation superseded an *old* fact, a reflection built on that old observation never
  went stale — stale beliefs kept controlling retrieval. Fix: `_apply_changes` records the
  superseded/contradicted prior fact's `source_observation_id` into
  `context["reflection_recheck_observations"]`, and the invalidation step re-checks those
  too. Verified end-to-end (see `tests/test_slow_path_orchestrator.py::test_supersession_invalidates_reflection_built_on_the_old_fact`).
  Retrieval-side filtering was already correct (Quick/Deep/hydration all filter
  `status='active'`).
  - **`confirmed_memory_id` lineage decision:** no column was added. Provenance is already
    queryable via `working_memory_items.source_record_id → session_working_set.id`;
    nothing reads a `confirmed_memory_id`. Recommendation stands: don't add it, update the
    paper. `[decide]`

The six paper demo scenarios now map 1:1 to eval cases — see
[`docs/demo-scenario-audit.md`](demo-scenario-audit.md) (refreshed to show each original
root cause and the A/C/D fix that resolved it).

---

## 4. D3 live re-run — DONE (clean run on the fixed system)

**Final numbers (DeepSeek + local embeddings, fresh run):** Local eval **12/13 (0.92)** — only
`contradiction-deadline-conflict` fails (known eval-case issue: same-subject conflict becomes
`SUPERSEDED_BY` not `CONTRADICTS`; fix = rewrite the case). Reflection now works end-to-end
(`reflection-user-knowledge` PASSES). Ablation **full_system 7/7 (1.00)** on the lean set;
**every layer discriminates and attributes to the right case**, including the two that were
previously inert: `session_working_set` (loses session-constraint) and `flat_memory` (loses
structured-first — structured-first weighting is load-bearing on ranking queries). Baselines
crater: vector_only 0.29, full_transcript 0.14. Older partial-run notes below are superseded.

---

## 4b. Earlier partial-run notes (superseded by the clean run above)

Goal: run the honest system live and record real numbers for (a) the 13 local eval cases /
6 demo scenarios and (b) the 11-config ablation. Use **DeepSeek** with local embeddings.

### Results so far (DeepSeek, local embeddings, run by the user)

**Local eval: 11/13 passed (0.85)** — `evaluation/local/memory_cases.results.json`.
All 10 original cases pass. Of the 3 new D2 cases: `deep-mode-community-summary` PASS;
two FAILs that are **real behavior, not harness bugs**:
- `contradiction-deadline-conflict`: the answer correctly surfaced both dates and flagged
  the conflict, but the system created **`SUPERSEDED_BY`, not `CONTRADICTS`**. The Phase A
  canonicalization fix makes the two deadline claims share a canonical subject+predicate, so
  the deterministic fast-path claims them as a supersession (later value wins) and they never
  reach the LLM verifier. **Open decision:** treat same-subject conflicting values (no
  change-cue) as CONTRADICTS, or accept SUPERSEDED_BY and change the eval expectation.
- `reflection-user-knowledge` (renamed from `reflection-self-knowledge` — it tests
  user-knowledge reflection; assertion is type-agnostic). Diagnosed on the real
  `eval.case-6` DB: reflection **never fired** (0 reflections; 12 obs). Root cause:
  `_importance_score` is keyword-based and biased to urgency words, so self/user habit
  statements scored the 0.35 floor, below the `reflection_min_importance` 0.6 gate.
  **FIXED (uncommitted), end-to-end live-verified.** Two bugs, both fixed:
  1. **Firing:** `_importance_score` gained a durable-trait marker group and the gate dropped
     0.6 → 0.5, so stable self/user habit statements qualify. (Reflection fires: 2–4 created.)
  2. **Retrieval — the deeper root cause:** reflections were **never embedded into the vector
     store** (observations and community summaries are; `reflection.py` skipped it), so the
     `reflections` collection was always empty and *neither Quick nor Deep* could find them by
     meaning. Fix: `store_reflection_with_evidence` now indexes the reflection
     (`chroma.add_embedding`), and Deep's `_reflection_candidates` matches by embedding
     similarity (`vector_search`) instead of brittle token overlap. Live-verified: Deep now
     returns `reflection` sources; `test_deep_retrieval` updated to index its fixture reflection.
  **Open item (non-blocking) `[decide]`:** reflection `reflection_type` is non-deterministic
  for first-person user input — the same habits were typed `self_knowledge` one run and
  `user_knowledge` the next. Decide whether user-about-self should be forced to `user_knowledge`
  (reserving `self_knowledge` for the agent's own behavior; only `self_knowledge` is hot-promoted).

**Ablation: CLEAN RUN DONE (lean set)** — `evaluation/results/ablation_results.json`, 11
configs over the lean 5-case set (`evaluation/ablation/ablation_cases.json`). **Every memory
layer is now load-bearing.** full_system 0.80; each single ablation drops to 0.60;
vector_only_baseline and full_transcript crater to 0.20. **Headline: reflection is finally
load-bearing** — `abl-reflection` passes at full_system and fails under `without_reflection`
(was 1.00/no-effect before today's firing+retrieval fixes). **Case fixes applied (need a live re-run to confirm):** (1) `abl-community` beefed up 4 → 7
statements so community detection reliably fires; (2) added `abl-session-constraint` (asserts
`used_session_items_nonempty`) so the `session_working_set` ablation shows an effect — the
prior 5 cases never exercised it; (3) added `abl-structured-first` (asserts a new
`top_retrieved_source: atomic_facts` ranking check) so the `flat_memory` ablation shows an
effect — flat weighting lets the raw observation outrank the fact. The `top_retrieved_source`
scorer is unit-verified; the two new cases' *discrimination* is best-effort and needs the live
re-run to confirm (esp. flat_memory, a ranking effect the answer LLM can smooth over). NOTE: a
stale `evaluation/ablation/results/ablation_results.json` (8 configs, 10 cases, pre-fix,
`without_reflection`=1.00) is an old artifact — ignore/delete it.

### Rerun commands (still valid)

### Setup
```bash
cd /home/jerry/mira/mira
set -a && . ./.env && set +a       # loads provider keys; .env has DEEPSEEK_API_KEY
```
`.env` defaults `LLM_PROFILE=siliconflow`; override to `deepseek` per run (below).
`EMBEDDING_MODE=local` (FastEmbed bge-small) — no embedding API needed.

### Run the local eval (resumable)
```bash
LLM_PROFILE=deepseek python -m scripts.run_local_eval \
  --cases evaluation/local/memory_cases.json \
  --live --run-slow-path --resume 2>&1 | tee -a eval-run.log
```
If it dies (provider blip, etc.), **re-run the identical line** — `--resume` skips finished
cases. Results checkpoint to `evaluation/local/memory_cases.results.json` after every case.

Read results any time:
```bash
python -c "import json; s=json.load(open('evaluation/local/memory_cases.results.json')); \
print('pass', s['passed'],'/',s['total']); \
[print(('PASS' if r['passed'] else 'FAIL'), r['id'], r.get('retrieval_mode')) for r in s['results']]"
```

### Run the ablation (resumable)
```bash
LLM_PROFILE=deepseek make ablation-live RUN_SLOW_PATH=1 RESUME=1 2>&1 | tee -a ablation-run.log
```
Re-run the same line to resume. Output: `evaluation/results/ablation.json` + `ablation.md`.
Scope a smoke test with `COMPONENTS="reflection community_summaries flat_memory full_transcript" LIMIT=3`.

### After the run
- Update the `[ ] D3` checkbox in [`docs/spec-alignment-plan.md`](spec-alignment-plan.md)
  with the real numbers, and add a results summary to `docs/demo-scenario-audit.md`.
- Sanity check the *shape* of the ablation table: each disabled layer should degrade pass
  rate vs `full_system`; `full_transcript` is the naive floor. Before Phase A, reflection
  never ran so `without_reflection` read 10/10 — that class of artifact should be gone now.

---

## 5. The resume feature (committed)

Added this session and offline-proven; **committed** as `233134d` (together with this
doc). Files:

- [`evaluation/local/cases.py`](../evaluation/local/cases.py) — `run_evaluation_cases`
  gains `resume: bool`; checkpoints the results file after every case; `_load_prior_results`
  skips already-recorded case ids. Cases are isolated/independent → resume is exact.
- [`scripts/run_local_eval.py`](../scripts/run_local_eval.py) — `--resume` flag.
- [`evaluation/ablation/studies.py`](../evaluation/ablation/studies.py) —
  `run_ablation_study` gains `checkpoint_path` + `resume`; writes the partial table after
  every config; `_load_prior_rows` reconstructs finished `AblationRow`s and skips them.
  **Granularity is per-config**: an interrupted config re-runs in full (you keep every
  other finished config).
- [`scripts/run_ablation.py`](../scripts/run_ablation.py) — `--resume` flag; checkpoints to
  the same `--out`/`--json-name` file it already writes.
- [`Makefile`](../Makefile) — `ablation-live` passes `$${RESUME:+--resume}` (so `RESUME=1`).

Design: the file each harness already outputs *is* the checkpoint. Fresh runs (no
`--resume`) overwrite as before — zero behavior change without the flag. Proven by: killing
a live eval mid-run and confirming the checkpoint retained completed cases + the resume log
skipped them; and a round-trip + skip unit check for the ablation.

These five files plus this doc are the follow-up commit on top of Phase D (`176371e`),
following repo conventions (this branch, no co-author trailer). The stray `eval-run.log`
was intentionally left uncommitted.

---

## 6. Known caveats / open decisions

- **Harness abort on sustained provider outage.** Both harnesses only catch
  `ValueError`/`KeyError` per case, not `LLMRequestError`. A sustained outage still aborts
  the process (the LLM client retries 3× internally first). That is *why* resume exists —
  it is the recovery path, not a per-call retry. If per-case retry-on-network-error is
  wanted, that's a further change (deliberately not done).
- **Ablation resume is per-config, not per-case** (see §5). Finer granularity is possible
  but more involved.
- **Paper reconciliation still pending** — the full decision log and per-section edit
  checklist is [`docs/paper-reconciliation.md`](paper-reconciliation.md) (structured-first
  Quick ranking p23, cross-mode CONTRADICTS surfacing p21, hybrid detection, hybrid router
  p24, 11-vs-8 ablations p28, `confirmed_memory_id` lineage, agent-self facts p12). These
  are paper edits, not code bugs.

---

## 7. Memory / context pointers

The Claude session kept working memory at
`/home/jerry/.claude/projects/-home-jerry-mira-mira/memory/` (not part of the repo):
`mira-spec-alignment-plan.md` (the tracker), `mira-demo-scenario-audit.md`,
`mira-retrieval-priority-decision.md`. The repo-tracked equivalents are
[`docs/spec-alignment-plan.md`](spec-alignment-plan.md) and
[`docs/demo-scenario-audit.md`](demo-scenario-audit.md) — prefer those.
