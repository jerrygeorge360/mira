"""Mock data for the premium MIRA Memory Command Center UI.

Ownership: MIRA contributors.
Related issue: ISSUE-130.
Architecture area: UI.
"""

from __future__ import annotations

NavItem = dict[str, str]
Metric = dict[str, str]
ChatMessage = dict[str, str]
MemoryItem = dict[str, str]
EvidenceItem = dict[str, str]
ReflectionItem = dict[str, object]
CommunityItem = dict[str, str]
TimelineItem = dict[str, str]

NAV_ITEMS: list[NavItem] = [
    {"label": "Command Center", "icon": "⌘"},
    {"label": "Memory Graph", "icon": "◎"},
    {"label": "Conversations", "icon": "◐"},
    {"label": "Timeline", "icon": "↯"},
    {"label": "Reflections", "icon": "✦"},
    {"label": "Sources", "icon": "◧"},
    {"label": "Community", "icon": "◌"},
    {"label": "Settings", "icon": "⚙"},
]

GRAPH_METRICS: list[Metric] = [
    {"label": "Nodes", "value": "1,284"},
    {"label": "Edges", "value": "4,918"},
    {"label": "Integrity", "value": "98%"},
]

CHAT_MESSAGES: list[ChatMessage] = [
    {
        "role": "user",
        "content": "Prepare me for the NovaDynamics meeting. What matters most?",
    },
    {
        "role": "assistant",
        "content": (
            "I pulled the freshest meeting context, the durable account pattern, and the "
            "active session constraints. The main thread is still enterprise AI adoption "
            "with security review risk."
        ),
    },
]

BRIEF_DETAILS: list[Metric] = [
    {"label": "Last meeting", "value": "Apr 28 · Strategy sync"},
    {"label": "Key focus", "value": "Enterprise AI rollout"},
    {"label": "Decision maker", "value": "Maya Chen, CTO"},
    {"label": "Current project", "value": "Pilot expansion"},
    {"label": "Concerns", "value": "Security, auditability, ROI"},
    {"label": "Sources", "value": "27 memories"},
    {"label": "Confidence", "value": "94%"},
]

ACTION_CHIPS = [
    "Key discussion points",
    "Potential risks",
    "Success metrics",
    "Similar past meetings",
]

SESSION_ITEMS: list[MemoryItem] = [
    {
        "title": "Use 2026 timeline for MIRA demo",
        "type": "Correction",
        "priority": "High",
        "scope": "Project",
    },
    {
        "title": "Benchmark cost cap should stay around $15",
        "type": "Decision",
        "priority": "High",
        "scope": "Cross-session",
    },
    {
        "title": "SQLite is source of truth; Chroma is index",
        "type": "Architecture",
        "priority": "High",
        "scope": "Project",
    },
    {
        "title": "Community summaries are not recursive summaries",
        "type": "Constraint",
        "priority": "Medium",
        "scope": "Project",
    },
    {
        "title": "Prepare polished judge narrative",
        "type": "Task",
        "priority": "Medium",
        "scope": "Current task",
    },
]

EVIDENCE_ITEMS: list[EvidenceItem] = [
    {
        "rank": "01",
        "title": "NovaDynamics Q2 meeting notes",
        "source": "Observation",
        "score": "0.96",
    },
    {
        "rank": "02",
        "title": "Enterprise AI rollout risks",
        "source": "Reflection",
        "score": "0.91",
    },
    {
        "rank": "03",
        "title": "Security review decision chain",
        "source": "Graph path",
        "score": "0.88",
    },
    {
        "rank": "04",
        "title": "Pilot expansion community summary",
        "source": "Community",
        "score": "0.84",
    },
]

REFLECTIONS: list[ReflectionItem] = [
    {
        "time": "09:42",
        "insight": "Jerry favors research credibility when demo decisions affect the paper.",
        "tags": ["Pattern", "Strength"],
    },
    {
        "time": "Yesterday",
        "insight": "Cost controls matter most when live judge calls or benchmarks are involved.",
        "tags": ["Balance", "Growth"],
    },
    {
        "time": "Mon",
        "insight": "Architecture decisions should stay visible so contributors avoid wrong layers.",
        "tags": ["Pattern"],
    },
]

COMMUNITIES: list[CommunityItem] = [
    {"title": "Product Strategy Trends", "people": "14", "insights": "38", "delta": "+12%"},
    {"title": "AI in Enterprise", "people": "22", "insights": "61", "delta": "+24%"},
    {"title": "Leadership & Management", "people": "9", "insights": "17", "delta": "+7%"},
]

TIMELINE: list[TimelineItem] = [
    {"when": "Past", "title": "NovaDynamics Q2 Meeting", "kind": "Memory"},
    {"when": "Past", "title": "Product Strategy Workshop", "kind": "Event"},
    {"when": "Today", "title": "Security Review Completed", "kind": "Milestone"},
    {"when": "Today", "title": "Client Meeting NovaDynamics", "kind": "Task"},
    {"when": "Future", "title": "Phase 2 Launch", "kind": "Milestone"},
    {"when": "Future", "title": "Strategy Review Q2 Check-in", "kind": "Event"},
]

# --- Memory-verification result (live DeepSeek run of evaluation/local/memory_cases.json). ---
ResultStat = dict[str, str]
ResultEvidence = dict[str, object]
ResultFix = dict[str, str]
ResultCase = dict[str, str]

RESULT_ABSTRACT = (
    "The local memory suite is ten cases spanning nine memory behaviors, each replaying real "
    "interactions through the live agent and scoring the mechanism, not just the answer text. "
    "It passes 10/10 on a live model (DeepSeek, real neural embeddings), and the harder cases "
    "are confirmed as physical artifacts in the graph — edges that exist and beliefs that close."
)

RESULT_STATS: list[ResultStat] = [
    {"label": "Live suite · DeepSeek", "value": "10 / 10"},
    {"label": "Memory behaviors", "value": "9 / 9"},
    {"label": "Contradiction reliability", "value": "1/3 → 5/5"},
    {"label": "Embeddings", "value": "bge-small"},
]

# The nine behaviors the local memory suite scores (evaluation/local/memory_cases.json).
RESULT_CATEGORIES: list[dict[str, str]] = [
    {
        "name": "Direct fact recall",
        "result": "1/1",
        "checks": "Recalls a stated fact via Quick retrieval.",
    },
    {
        "name": "Session correction",
        "result": "1/1",
        "checks": "Applies an in-session correction before durable confirmation.",
    },
    {
        "name": "Cross-session recall",
        "result": "1/1",
        "checks": "Continues a topic across a session boundary.",
    },
    {
        "name": "Contradiction handling",
        "result": "1/1",
        "checks": "Separates unresolved conflicts from acknowledged changes.",
    },
    {
        "name": "Supersession",
        "result": "1/1",
        "checks": "Closes the old fact and links the transition edge.",
    },
    {
        "name": "Foresight activation",
        "result": "1/1",
        "checks": "Surfaces a future commitment when it matters.",
    },
    {
        "name": "Deep-mode synthesis",
        "result": "1/1",
        "checks": "Routes identity / pattern questions to Deep retrieval.",
    },
    {
        "name": "Retrieval sufficiency",
        "result": "1/1",
        "checks": "Abstains when memory is insufficient to answer.",
    },
    {
        "name": "Routing intent",
        "result": "2/2",
        "checks": "Selects the right mode: direct, quick, deep, relational.",
    },
]

RESULT_EVIDENCE: list[ResultEvidence] = [
    {
        "title": "Contradiction · belief revised",
        "case": "case 4",
        "edge": "SUPERSEDED_BY  I prefers_language Python  →  speaker prefers_language Rust",
        "states": ["Python · superseded", "Rust · active"],
    },
    {
        "title": "Supersession · transition split",
        "case": "case 5",
        "edge": "SUPERSEDED_BY  user uses MongoDB  →  user uses PostgreSQL",
        "states": ["MongoDB · superseded", "PostgreSQL · active", "returned as graph_edge"],
    },
    {
        "title": "Foresight · task persisted",
        "case": "case 6",
        "edge": 'foresight_records  "Hackathon submission due on 2026-07-17."',
        "states": ["active", "future task"],
    },
]

RESULT_FIXES: list[ResultFix] = [
    {
        "title": "Canonical registry + similarity fallback",
        "detail": "Resolve I / you / speaker → user; an embedding pass rescues pairing when exact "
        "match is empty. Took contradiction from 1/3 to 5/5.",
    },
    {
        "title": "Transition clause-splitting",
        "detail": '"from X to Y" is split into a prior/current pair and flagged directly as one '
        "correctly-directed SUPERSEDED_BY edge with source evidence.",
    },
    {
        "title": "User-only change detection",
        "detail": "Supersession and contradiction read the user's own turn, not the assistant "
        "echo — one edge per migration and correct classification.",
    },
    {
        "title": "Per-case isolation + real logging",
        "detail": "Each case runs on its own database and vector store; structured INFO events now "
        "emit, so candidate counts are observable instead of silent.",
    },
]

RESULT_CASES: list[ResultCase] = [
    {"case": "fact-recall-deadline", "mode": "quick"},
    {"case": "session-correction-year", "mode": "quick"},
    {"case": "cross-session-continue", "mode": "quick"},
    {"case": "contradiction-preferences", "mode": "quick"},
    {"case": "supersession-migration", "mode": "relational"},
    {"case": "foresight-hackathon", "mode": "quick"},
    {"case": "deep-developer-identity", "mode": "deep"},
    {"case": "sufficiency-unknown-entity", "mode": "quick"},
    {"case": "general-knowledge-no-memory", "mode": "general"},
    {"case": "personal-memory-uses-memory", "mode": "quick"},
]

RESULT_CAVEATS: list[str] = [
    "Extraction noise rides alongside — the winning edge used the messy predicate "
    "prefers_language (the similarity fallback rescued it). Core artifacts are correct; "
    "surrounding facts are not yet fully canonical.",
    "Contradiction is robust, not guaranteed — 5/5 in this sample; it still depends on the "
    "model emitting a usable fact and the 0.72 similarity threshold catching it.",
    "The fallback costs CPU — one embedding pass per unmatched fact; caching predicate "
    "embeddings is a tracked follow-up.",
    "Gemini is provider-capped — answer quality matches DeepSeek, but the free-tier "
    "5 requests/minute limit cannot complete a full slow-path run.",
]
