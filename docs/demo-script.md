# MIRA Demo Script — Under Five Minutes

## Status
Ready for team rehearsal.

## Setup
Run the deterministic demo seed before the walkthrough:

```bash
python -m scripts.seed_demo --reset
make slow-path-status PYTHON=.venv/bin/python
make graph-inspect PYTHON=.venv/bin/python
make run
```

Use the Streamlit navigation in this order:

1. Chat
2. Session Working Set
3. Graph Viewer
4. Memory Inspector
5. Foresight Timeline
6. Retrieval Trace
7. Evaluation Dashboard

No hidden manual setup is required beyond the seed command, the quick inspection checks, and
launching the UI. The inspection commands catch stale local state before rehearsal starts.

## Five-minute narrative

| Time | UI screen | Action | Expected result |
| --- | --- | --- | --- |
| 0:00-0:25 | Chat | Introduce MIRA as a session-aware memory agent and send: `Use 2026, not 2025, for MIRA dates.` | The chat shows a response and the Session Working Set indicator updates immediately. |
| 0:25-0:55 | Session Working Set | Open the Session Working Set page. | A provisional correction is visible with project scope, high priority, and source evidence. |
| 0:55-1:20 | Chat | Ask a follow-up that depends on the correction: `What year should the MIRA demo use?` | The next response respects 2026 before slow-path confirmation. |
| 1:20-1:50 | Session Working Set | Show lifecycle state changes. | The demo data shows provisional, hydrated, confirmed/rejected-style states so the team can explain slow path confirmation or rejection. |
| 1:50-2:25 | Graph Viewer | Show graph paths for `MongoDB → PostgreSQL` and `Python ↔ Rust`. | Relational Mode has visible typed edges for `SUPERSEDED_BY` and `CONTRADICTS`. |
| 2:25-2:55 | Graph Viewer | Explain the distinction. | Supersession means acknowledged change over time; contradiction means unresolved incompatible claims preserved together. |
| 2:55-3:25 | Memory Inspector | Open durable memory and community summary examples. | Deep Mode can use community summaries rather than raw-only recall. |
| 3:25-3:50 | Foresight Timeline | Show the hackathon deadline record. | Foresight activates from a deadline and is available for prompt injection while active. |
| 3:50-4:25 | Retrieval Trace | Open the seeded retrieval trace. | The trace explains retrieval mode, selected evidence, graph paths/community IDs, sufficiency, and prompt sections without exposing hidden prompts. |
| 4:25-4:45 | Evaluation Dashboard | Close with evaluation status. | Judges see that the demo is repeatable and tied to testable architecture behavior. |

Target runtime: **4 minutes 45 seconds**.

## Talk track

MIRA is not just storing chat history. The first beat shows the fast path and
Session Working Set: a correction becomes prompt-relevant immediately. The second
beat shows why that matters: the next response can respect the correction before
the slow path finishes. Then the slow path gives the correction a lifecycle:
confirmed, rejected, downgraded, expired, or promoted later.

The graph section is the centerpiece. Relational Mode traverses typed evidence
paths instead of guessing from a blob of memories. `Python` versus `Rust` is an
unresolved contradiction because no transition was acknowledged. `MongoDB` to
`PostgreSQL` is supersession because the user explicitly switched. Both remain
graph-visible.

Deep Mode then shows a different read path: community summaries answer broad
architecture questions without pretending a summary is raw evidence. Foresight
shows time-aware memory by activating the hackathon deadline. Retrieval Trace
finishes the story by showing why the answer happened: route, evidence,
sufficiency, and prompt sections.

For a live runtime sanity check outside the UI, run:

```bash
QUERY="MongoDB PostgreSQL" make memory-search PYTHON=.venv/bin/python
make local-eval PYTHON=.venv/bin/python
```

`memory-search` should return Chroma pointers with `record_found=true` after a fresh seed.
If it returns `record_found=false`, clear or rebuild Chroma for the active SQLite database.
`local-eval` should pass the small routing/memory regression suite without paid provider
calls.

## Feature checklist

- [ ] User correction updates Session Working Set immediately.
- [ ] Next response respects correction before slow-path confirmation.
- [ ] Slow path confirmation/rejection lifecycle is explained.
- [ ] Relational Mode traverses typed graph paths.
- [ ] Contradiction versus supersession is visible.
- [ ] Deep Mode uses community summaries.
- [ ] Foresight activates from the hackathon deadline.
- [ ] Retrieval Trace explains the answer.
- [ ] `graph-inspect`, `slow-path-status`, and `memory-search` agree with the seeded state.
- [ ] `local-eval` passes before a live benchmark or judge rehearsal.

## Rehearsal notes

- Keep the first chat correction short; the visual point is the Session Working Set indicator.
- Do not discuss implementation internals unless asked. Stay on the architecture story.
- If a live model call is unavailable, use seeded mock data and say: “This is deterministic demo mode.”
- If time runs short, skip the Evaluation Dashboard and end on Retrieval Trace.
