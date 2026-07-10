# Demo Scenario Audit (paper §Demo Evaluation)

Live audit of the six demo scenarios the paper claims, run end-to-end against the
real agent with DeepSeek + local embeddings. Purpose: confirm the claimed
behaviors actually reproduce before investing in the full ablation. Verdict:
**2 work, 1 just fixed, 3 broken/dormant.** Root causes below.

| # | Scenario | Status | Root cause |
| --- | --- | --- | --- |
| 1 | Year 2025→2026 correction; Session Working Set updates immediately | ✅ passes (not stress-tested) | — |
| 2 | Preference Python→Rust; `SUPERSEDED_BY` surfaced | ✅ **fixed** (4/4 clean) | canonicalization fragmentation (fixed) |
| 3 | Contradictory deadlines; `CONTRADICTS` surfaced | ❌ **broken** (0/3) | extraction fragments the subject: `(Project, has deadline, Fri)` vs `(project deadline, is, Mon)` — different subject+predicate, never pairs |
| 4 | Foresight, time-valid + topic-relevant | ✅ works; ablation seam fixed | — |
| 5 | Deep Mode uses community summaries | ⚠️ **mechanism works, trigger dormant** | community detection gated at ≥50 obs/batch; batches cap at 20 → never fires in normal/eval use |
| 6 | Self-knowledge reflection produced + promoted | ❌ **dormant** (0 reflections) | reflection gate needs ≥5 obs in one batch; one-at-a-time draining → batch of 1 → never fires |

## #2 — FIXED (canonicalization → supersession)

`_normalize_canonical` was case-fold + whitespace only, with exact matching, so
`the speaker` ≠ seeded `speaker` and `prefers_language` ≠ `prefers language`.
Because supersession pairing requires a shared `canonical_subject_id`, a
fragmented subject yielded zero candidates → no `SUPERSEDED_BY` → stale facts
stayed `active`. Fix: normalize snake_case to spaces and strip a leading
determiner (`core/db/repositories.py`). Verified: 4/4 runs create the edge and
deactivate the Python facts; "What do I prefer?" → "You prefer Rust."

## #3 — BROKEN (CONTRADICTS never fires)

Mechanism exists (`apply_contradiction`, `change.py`), but the two deadline
claims are extracted with inconsistent structure and never pair. Beyond the
canonicalization fix, this needs **subject-similarity pairing** (pair facts whose
subjects are embedding-similar, not just canonical-id equal). That change carries
false-positive risk in contradiction detection — **needs review before
implementing.** No eval case exists for CONTRADICTS either.

## #5 / #6 — DORMANT (batch-count gating)

Both consolidation layers are gated on the number of observations **in a single
slow-path batch**:
- reflection: `reflection_min_observations = 5` (`maybe_run_reflection_pass`)
- community: `community_refresh_every_observations = 50` (`maybe_run_community_refresh`)

But every prompt/eval drain processes observations **one at a time**
(`run_slow_path_batch` after each turn), so each batch holds 1 observation and
neither threshold is ever met. Confirmed live: forcing the community refresh past
its gate produced 5 summaries and Deep Mode retrieved them (mechanism is sound);
reflection produced 0 across 8 observations.

**This also explains the ablation table**: `without_reflection` read 10/10 (no
effect) because reflection never produced anything to disable. The layer isn't
non-load-bearing — it never runs.

Proposed fix (needs review — changes when/how often expensive synthesis runs):
make the reflection/community triggers accumulate over **recent unreflected
observations from the store** (cross-session, per the paper) rather than the
current batch, or lower the thresholds for interactive cadence. The
`unreflected[-limit:]` slice in `_recent_unreflected_observation_ids` shows
accumulation was the original intent; only the caller (which passes the current
batch) diverges.

## Recommended sequence

1. Decide reflection/community trigger fix (unblocks #5, #6, and makes their
   ablation rows meaningful).
2. Decide subject-similarity pairing for #3 (CONTRADICTS).
3. Add dedicated eval cases: CONTRADICTS deadlines, self-knowledge reflection
   (≥5 obs), Deep-Mode-uses-community-summary.
4. Then re-run the full ablation and add the paper's missing baselines
   (community-summaries ablation, full-transcript baseline).
