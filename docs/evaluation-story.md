# The Evaluation Story: Local Eval, Ablation, and Benchmark

A detailed account of how MIRA is measured — what the local eval and the component
ablation actually do, the journey from misleading numbers to honest ones, the final
results, and what each result means. Written to be read start-to-finish.

---

## 1. Why two harnesses, and what each one answers

MIRA is a memory system: a fast in-session path, a slow path that distills conversation
into durable structured memory (atomic facts, a typed temporal graph, reflections,
community summaries, foresight), and a retrieval-gated prompt builder. The hard question
for any memory system is not "can it answer one demo question" but "do its parts actually
work, and does each part earn its place." Two harnesses answer two different questions.

- **Local eval** answers: *does the system exhibit the memory behaviors it claims?* It
  replays scripted mini-conversations through the real agent and scores the outcome. It is
  a **capability** test.
- **Ablation** answers: *does each layer actually contribute?* It re-runs the same kind of
  cases with one component switched off at a time and watches the score move. It is a
  **contribution** test — a defense against carrying dead weight.

Neither re-implements the system. Both drive the real agent runtime end-to-end, so a pass
means the mechanism genuinely fired, not that a mock returned the right string.

---

## 2. Local eval — mechanics

The suite lives in `evaluation/local/memory_cases.json`: declarative cases, each a short
sequence of user turns plus an `expect` block. The runner (`scripts/run_local_eval.py` →
`evaluation/local/cases.py`) replays each case through `handle_user_message` — the same
entry point the API uses — and scores the final response.

Key properties that make the numbers trustworthy:

- **Real runtime.** Each turn goes through routing, retrieval, prompt construction, and
  generation. With `--run-slow-path`, the durable-memory pipeline is drained after every
  turn, so facts, reflections, communities, and contradiction edges are actually built.
- **Isolation.** By default each case runs against its own SQLite database and a cleared
  vector store, so one case's memory can't leak into the next through retrieval.
- **Mechanism-level scoring.** Checks go beyond answer text: `retrieval_mode` (did it route
  to Deep?), `retrieved_sources_include` (was a *reflection* actually retrieved?),
  `used_session_items_nonempty` (did the Session Working Set reach the prompt?),
  `slow_path_created_edge_types_include` (was a `SUPERSEDED_BY` edge created?),
  `top_retrieved_source` (did the validated fact out-rank the raw log?).
- **Resumable.** Results are checkpointed after every case; a crashed run resumes with
  `--resume` instead of starting over.

The suite spans the memory behaviors: direct fact recall, in-session correction,
cross-session recall, contradiction handling, supersession, foresight, deep-mode
synthesis, reflection, community summaries, retrieval sufficiency, and routing intent.

---

## 3. Ablation — mechanics

The ablation (`scripts/run_ablation.py` → `evaluation/ablation/studies.py`) runs a curated
case set once per **configuration**. `full_system` disables nothing; each other config
disables exactly one layer by patching the real composition seam so the component does not
run — disabling is genuine, not faked. The set of configs:

```
full_system                          (baseline — nothing disabled)
without_session_working_set
without_relational_mode
without_deep_mode
without_foresight
without_reflection
without_community_summaries
without_contradiction_supersession
vector_only_baseline    (all higher layers off; Quick retrieval only)
flat_memory             (structured-first ranking weights flattened)
full_transcript         (no derived/retrieved memory; raw transcript only)
```

The lean case set (`evaluation/ablation/ablation_cases.json`) is deliberately small and
**targeted**: each case is chosen so removing a specific layer changes the outcome. A
config's drop from `full_system`, and the specific case it loses, is that layer's
contribution made visible.

Speed matters because `--run-slow-path` re-runs the full ingestion pipeline for every
config. Three levers keep it tractable: the lean case set, an **on-by-default LLM response
cache** (identical slow-path prompts across configs are served from disk), and
**`--parallel N`** (configs run in isolated subprocesses, N at a time). Parallel is
verified to produce identical rows to sequential.

---

## 4. The journey: from misleading to honest

The first ablation was **actively misleading**, and fixing that is the real story.

- **Reflection read as non-load-bearing (`without_reflection` = 10/10).** Not because
  reflection is useless — because **it never ran**. Reflection and community detection were
  gated on the number of observations *in a single slow-path batch*, but the eval and
  interactive paths drain one observation at a time, so the threshold was never met. The
  ablation was measuring a dormant layer.
- **Reflection couldn't fire even after that.** The importance gate that decides whether
  observations are worth reflecting on was keyword-based and tuned for *urgency* (deadline,
  changed, now). Stable self/user habit statements — exactly the content reflection is for
  — scored the floor and never cleared the gate.
- **Reflection couldn't be retrieved even after it fired.** Reflections were **never
  embedded into the vector store** at all (observations and community summaries were, but
  reflection creation skipped it), so neither Quick nor Deep could find a reflection by
  meaning. Deep fell back to brittle lexical token-overlap, which drops any reflection that
  doesn't literally share words with the question.
- **Contradiction never fired** for same-entity deadlines because extraction fragmented the
  subject, so facts never paired.
- **Two layers were untested.** `session_working_set` and `flat_memory` showed no effect
  simply because no case exercised them — a coverage gap, not proof they were inert.

Each of these was found by driving the real system and inspecting the actual database, not
by trusting the score. Each was fixed: the consolidation passes were relocated so they run
in every drain; the importance gate learned durable-trait markers; reflections are now
embedded on creation and retrieved by meaning; contradiction pairing became a hybrid
deterministic + LLM verifier; and dedicated cases were added for the untested layers.

The lesson threaded through all of it: **a green ablation cell can mean "this layer does
nothing" or "this layer never ran." Only inspecting the mechanism tells you which.**

---

## 5. The results (clean run, DeepSeek + local embeddings)

### Local eval — 12 / 13 (0.92)

Every behavior passes except one. `reflection-user-knowledge` now passes end-to-end (fires
*and* is retrieved via Deep). The single failure, `contradiction-deadline-conflict`, is a
**case-design issue, not a system bug**: two same-subject deadline claims canonicalize
together, so the deterministic path treats the second as an *update* (`SUPERSEDED_BY`)
rather than an unresolved *conflict* (`CONTRADICTS`). The answer still surfaces both dates;
only the edge-type assertion fails. The fix is to rewrite the case with two distinct
sources so it elicits a genuine contradiction.

### Ablation — full_system 7 / 7 (1.00), every layer load-bearing

```
Config                              Pass   Loses (vs full_system)
full_system                        7/7    — (passes all)
without_session_working_set        6/7    session-constraint
without_relational_mode            6/7    supersession
without_deep_mode                  5/7    reflection, community
without_foresight                  6/7    foresight
without_reflection                 6/7    reflection
without_community_summaries        5/7    reflection, community
without_contradiction_supersession 6/7    supersession
flat_memory                        6/7    structured-first
vector_only_baseline               2/7    (only fact-recall + structured-first survive)
full_transcript                    1/7    (only fact-recall survives)
```

Every disabled layer drops the score and loses **exactly the case it should**:

- **relational_mode** and **contradiction_supersession** both own *supersession* — one
  retrieves the transition edge, the other creates it. Remove either and the belief change
  can't be answered.
- **foresight** owns the time-sensitive case.
- **reflection** owns the identity-synthesis case; **deep_mode** and
  **community_summaries** also lose it, because Deep Mode only engages when community
  summaries exist — so reflection retrieval currently rides on Deep being active. (This
  coupling is a real, documented architectural fact, not noise.)
- **session_working_set** owns the in-session constraint — now that a case exercises it.
- **flat_memory** owns *structured-first*: flatten the source weights and the validated
  fact no longer out-ranks the raw observation, so the ranking-sensitive case fails. This
  is the direct answer to "does structured-first weighting matter?" — **yes, on
  ranking-sensitive queries**, which is precisely where a small answer-only test wouldn't
  have caught it.
- The **baselines crater**: `vector_only` keeps only Quick retrieval (2/7), and
  `full_transcript` — no derived or retrieved memory, just the raw conversation — drops to
  the floor (1/7). This is the honest evidence that the memory stack beats naive retrieval.

Read magnitudes as *direction* rather than precision: the lean set is intentionally small
(N=7), so each case is a ~0.14 swing.

### Benchmark — LongMemEval (subset)

The benchmark harness (`scripts/run_benchmark.py`, `evaluation/benchmarks/`) runs the
external **LongMemEval** suite with a hybrid judge (deterministic match + LLM judge). The
dataset is present (`data/benchmarks/longmemeval.json`), and an official-protocol **subset**
has been run: 5 temporal-reasoning examples, LLM-judge pass rate 0.4, estimated cost $0.07
against a $15 budget. It is wired and working; scaling to the full set is a matter of
budget and time, not readiness.

---

## 6. Seeing it in the product

The API exposes `GET /evaluation/summary`, which reads the latest local-eval, ablation, and
benchmark result files and returns a normalized summary (null sections before the first
run, so it degrades gracefully). The **Results** view in the UI fetches it and renders the
live numbers — per-case pass/fail, the ablation contribution table with a bar and the lost
cases per layer, and the benchmark card — falling back to a static snapshot when the API is
offline.

---

## 7. How to reproduce

```bash
# from repo root, with the provider env loaded
set -a && . ./.env && set +a

# fresh: clear prior results and cache
rm -rf .llm-cache
rm -f evaluation/local/memory_cases.results.json
rm -f evaluation/results/ablation_results.json evaluation/results/ablation_summary.md

# local eval (all cases, live)
LLM_PROFILE=deepseek python -m scripts.run_local_eval \
  --cases evaluation/local/memory_cases.json --live --run-slow-path

# ablation (lean set, all layers, 4 configs at a time, cache on by default)
LLM_PROFILE=deepseek make ablation-live RUN_SLOW_PATH=1 PARALLEL=4
```

Read results: `cat evaluation/results/ablation_summary.md`, or open the **Results** view in
the UI with the API running.
