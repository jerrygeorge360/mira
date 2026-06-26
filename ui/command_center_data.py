"""Mock data for the premium MIRA Memory Command Center UI.

Ownership: Sarah.
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
