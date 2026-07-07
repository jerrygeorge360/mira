"""Typed temporal graph visualization for the MIRA UI.

Ownership: MIRA contributors.
Related issue: ISSUE-046.
Architecture area: UI.

Graph visibility demonstrates that edges are read, not just written. This page
renders MIRA's single typed graph: every node type and edge type, filterable by
node/edge type, with contradiction and supersession visually distinguished,
confidence/status shown, and per-node evidence inspection so relational
retrieval paths can be displayed. It computes no graph semantics (Non-Goal) --
it reads nodes/edges and draws them. Streamlit is lazy-imported and ``st``/the
loader are injectable so the page is testable without Streamlit or a database.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any

Node = dict[str, object]
Edge = dict[str, object]
Graph = dict[str, list[dict[str, object]]]
GraphLoader = Callable[[], Graph]

NODE_TYPES = ("entity", "observation", "reflection", "foresight", "community", "atomic_fact")
EDGE_TYPES = (
    "MENTIONS",
    "DERIVED_FROM",
    "SUPERSEDED_BY",
    "CONTRADICTS",
    "CAUSED_BY",
    "LEADS_TO",
    "PART_OF_COMMUNITY",
    "PREFERS",
    "DISLIKES",
    "WORKS_ON",
    "IS_EXPERT_IN",
)

NODE_COLORS = {
    "entity": "#1f77b4",
    "observation": "#7f7f7f",
    "reflection": "#2ca02c",
    "foresight": "#ff7f0e",
    "community": "#9467bd",
    "atomic_fact": "#17becf",
}

# Edge styling — contradiction and supersession are deliberately distinct.
EDGE_STYLES: dict[str, dict[str, str]] = {
    "CONTRADICTS": {"color": "#d62728", "glyph": "✗", "note": "contradiction"},
    "SUPERSEDED_BY": {"color": "#ff7f0e", "glyph": "➜", "note": "supersession"},
    "CAUSED_BY": {"color": "#1f77b4", "glyph": "←", "note": "causal"},
    "LEADS_TO": {"color": "#1f77b4", "glyph": "→", "note": "causal"},
    "DERIVED_FROM": {"color": "#2ca02c", "glyph": "·", "note": "evidence"},
    "PART_OF_COMMUNITY": {"color": "#9467bd", "glyph": "◇", "note": "community"},
    "MENTIONS": {"color": "#7f7f7f", "glyph": "·", "note": "mention"},
}
_DEFAULT_EDGE_STYLE = {"color": "#8c564b", "glyph": "·", "note": "preference/work"}

LEGEND = (
    "**Edge legend** — "
    "🟥 **CONTRADICTS** (✗ contradiction) · "
    "🟧 **SUPERSEDED_BY** (➜ supersession) · "
    "🟦 CAUSED_BY / LEADS_TO (causal) · "
    "🟩 DERIVED_FROM (evidence) · "
    "🟪 PART_OF_COMMUNITY · ⬜ MENTIONS · 🟫 preference/work"
)

DEFAULT_SESSION_ID = "demo-session"

_MOCK_GRAPH: Graph = {
    "nodes": [
        {
            "id": "e1",
            "type": "entity",
            "label": "MIRA",
            "source_table": "entities",
            "source_id": "e1",
        },
        {
            "id": "e2",
            "type": "entity",
            "label": "PostgreSQL",
            "source_table": "entities",
            "source_id": "e2",
        },
        {
            "id": "e3",
            "type": "entity",
            "label": "MongoDB",
            "source_table": "entities",
            "source_id": "e3",
        },
        {
            "id": "r1",
            "type": "reflection",
            "label": "Prefers repository helpers",
            "source_table": "reflections",
            "source_id": "r1",
        },
        {
            "id": "f1",
            "type": "fact",
            "label": "uses PostgreSQL",
            "source_table": "atomic_facts",
            "source_id": "f1",
        },
        {
            "id": "c1",
            "type": "community",
            "label": "Persistence",
            "source_table": "community_summaries",
            "source_id": "c1",
        },
    ],
    "edges": [
        {
            "id": "x1",
            "source": "e1",
            "target": "e2",
            "type": "WORKS_ON",
            "confidence": 0.9,
            "status": "active",
            "source_observations": ["obs_2"],
        },
        {
            "id": "x2",
            "source": "e3",
            "target": "e2",
            "type": "SUPERSEDED_BY",
            "confidence": 0.95,
            "status": "active",
            "source_observations": ["obs_3"],
        },
        {
            "id": "x3",
            "source": "f1",
            "target": "e3",
            "type": "CONTRADICTS",
            "confidence": 0.8,
            "status": "active",
            "source_observations": ["obs_3"],
        },
        {
            "id": "x4",
            "source": "r1",
            "target": "f1",
            "type": "DERIVED_FROM",
            "confidence": 1.0,
            "status": "active",
            "source_observations": ["obs_4"],
        },
        {
            "id": "x5",
            "source": "f1",
            "target": "c1",
            "type": "PART_OF_COMMUNITY",
            "confidence": 0.7,
            "status": "active",
            "source_observations": ["obs_5"],
        },
    ],
}


def filter_graph(
    graph: Graph,
    node_types: list[str] | None = None,
    edge_types: list[str] | None = None,
) -> Graph:
    """Filter the graph by node and edge type, keeping only connectable edges."""
    nodes = list(graph.get("nodes", []))
    edges = list(graph.get("edges", []))
    if node_types is not None:
        allowed = set(node_types)
        nodes = [node for node in nodes if str(node.get("type")) in allowed]
    node_ids = {str(node.get("id")) for node in nodes}
    if edge_types is not None:
        allowed_edges = set(edge_types)
        edges = [edge for edge in edges if str(edge.get("type")) in allowed_edges]
    edges = [
        edge
        for edge in edges
        if str(edge.get("source")) in node_ids and str(edge.get("target")) in node_ids
    ]
    return {"nodes": nodes, "edges": edges}


def edge_style(edge_type: str) -> dict[str, str]:
    """Return the visual style for an edge type (with a preference/work default)."""
    return EDGE_STYLES.get(edge_type, _DEFAULT_EDGE_STYLE)


def build_dot(graph: Graph) -> str:
    """Build a Graphviz DOT string with readable node/edge labels and styling."""
    lines = ["digraph MIRA {", "rankdir=LR;", "node [style=filled, fontcolor=white];"]
    for node in graph.get("nodes", []):
        node_id = _safe(str(node.get("id")))
        label = _safe(f"{node.get('label', node_id)}\\n({node.get('type', 'node')})")
        color = NODE_COLORS.get(str(node.get("type")), "#333333")
        lines.append(f'"{node_id}" [label="{label}", fillcolor="{color}"];')
    for edge in graph.get("edges", []):
        style = edge_style(str(edge.get("type")))
        confidence = edge.get("confidence")
        suffix = f" ({confidence})" if isinstance(confidence, int | float) else ""
        label = _safe(f"{edge.get('type', 'EDGE')}{suffix}")
        source = _safe(str(edge.get("source")))
        target = _safe(str(edge.get("target")))
        lines.append(f'"{source}" -> "{target}" [label="{label}", color="{style["color"]}"];')
    lines.append("}")
    return "\n".join(lines)


def node_evidence(node: Node, edges: list[Edge]) -> str:
    """Return an evidence summary for a clicked node (no semantics computed here)."""
    node_id = str(node.get("id"))
    observations = sorted(
        {
            str(observation)
            for edge in edges
            if node_id in (str(edge.get("source")), str(edge.get("target")))
            for observation in _as_list(edge.get("source_observations"))
        }
    )
    lines = [
        f"**Label:** {node.get('label', node_id)}",
        f"**Node type:** {node.get('type', 'unknown')}",
        f"**Source record:** {node.get('source_table', '—')}:{node.get('source_id', '—')}",
        f"**Source observations:** {', '.join(observations) or '—'}",
    ]
    return "\n\n".join(lines)


def render_graph(
    st: Any | None = None,
    loader: GraphLoader | None = None,
    *,
    use_mock: bool = True,
) -> None:
    """Render the typed-graph viewer page."""
    streamlit = st if st is not None else _load_streamlit()
    graph = _resolve_loader(loader, use_mock)()

    streamlit.title("🕸️ Graph Viewer")
    streamlit.caption("MIRA's single typed temporal graph — edges are read, not just written.")
    streamlit.markdown(LEGEND)

    node_filter = streamlit.sidebar.multiselect("Node types", list(NODE_TYPES), list(NODE_TYPES))
    edge_filter = streamlit.sidebar.multiselect("Edge types", list(EDGE_TYPES), list(EDGE_TYPES))

    filtered = filter_graph(graph, _as_filter(node_filter), _as_filter(edge_filter))
    if not filtered["nodes"]:
        streamlit.info("No nodes match the current filters.")
        return

    streamlit.graphviz_chart(build_dot(filtered))
    streamlit.dataframe([_edge_row(edge) for edge in filtered["edges"]])

    labels = {str(node.get("label", node.get("id"))): node for node in filtered["nodes"]}
    selected = streamlit.selectbox("Inspect a node for evidence", list(labels))
    node = labels.get(str(selected)) or next(iter(labels.values()))
    streamlit.markdown(node_evidence(node, filtered["edges"]))


def _edge_row(edge: Edge) -> dict[str, object]:
    style = edge_style(str(edge.get("type")))
    return {
        "source": edge.get("source"),
        "edge": f"{style['glyph']} {edge.get('type')}",
        "target": edge.get("target"),
        "relation": style["note"],
        "confidence": edge.get("confidence"),
        "status": edge.get("status"),
    }


def load_graph() -> Graph:
    """Load the typed graph from durable storage (read-only)."""
    from core.db.repositories import repository_connection

    with repository_connection() as connection:
        node_rows = connection.execute("SELECT * FROM graph_nodes").fetchall()
        edge_rows = connection.execute(
            "SELECT * FROM graph_edges WHERE invalidated_at IS NULL"
        ).fetchall()
    nodes = [
        {
            "id": str(row["id"]),
            "type": str(row["node_type"]),
            "label": str(row["label"]),
            "source_table": row["source_table"],
            "source_id": row["source_id"],
        }
        for row in node_rows
    ]
    edges = [
        {
            "id": str(row["id"]),
            "source": str(row["source_node_id"]),
            "target": str(row["target_node_id"]),
            "type": str(row["edge_type"]),
            "confidence": row["confidence"],
            "status": "invalidated" if row["invalidated_at"] else "active",
            "source_observations": _as_list(_decode_json(row["source_observations_json"])),
        }
        for row in edge_rows
    ]
    return {"nodes": nodes, "edges": edges}


def _resolve_loader(loader: GraphLoader | None, use_mock: bool) -> GraphLoader:
    if loader is not None:
        return loader
    if use_mock:
        return lambda: {"nodes": list(_MOCK_GRAPH["nodes"]), "edges": list(_MOCK_GRAPH["edges"])}
    return load_graph


def _decode_json(value: object) -> object:
    if isinstance(value, str):
        import json

        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return []
    return value


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _as_filter(value: object) -> list[str] | None:
    """Coerce a multiselect result to a filter list, or None when not a list."""
    if isinstance(value, list):
        return [str(item) for item in value]
    return None


def _safe(text: str) -> str:
    return text.replace('"', "'")


def _load_streamlit() -> Any:
    try:
        return importlib.import_module("streamlit")
    except ModuleNotFoundError as error:  # pragma: no cover - only without streamlit
        raise RuntimeError("streamlit is not installed; install it to run the MIRA UI") from error
