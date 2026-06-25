"""Verify ISSUE-046 typed-graph visualization page.

Ownership: MIRA contributors.
Related issue: ISSUE-046.
Architecture area: UI.
"""

from __future__ import annotations

from typing import Any

from ui.graph_viz import (
    EDGE_STYLES,
    build_dot,
    edge_style,
    filter_graph,
    node_evidence,
    render_graph,
)


def _graph() -> dict[str, list[dict[str, object]]]:
    return {
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
                "id": "f1",
                "type": "atomic_fact",
                "label": "uses PostgreSQL",
                "source_table": "atomic_facts",
                "source_id": "f1",
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
                "source": "f1",
                "target": "e2",
                "type": "CONTRADICTS",
                "confidence": 0.8,
                "status": "active",
                "source_observations": ["obs_3"],
            },
        ],
    }


class _FakeStreamlit:
    def __init__(self, selections: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.markdowns: list[str] = []
        self.dataframes: list[Any] = []
        self.graphviz: list[str] = []
        self.infos: list[str] = []
        self._selections = selections or {}
        self.sidebar = self

    def markdown(self, text: str) -> None:
        self.markdowns.append(text)

    def dataframe(self, data: Any) -> None:
        self.dataframes.append(data)

    def graphviz_chart(self, dot: str) -> None:
        self.graphviz.append(dot)

    def info(self, text: str) -> None:
        self.infos.append(text)

    def multiselect(self, label: str, options: list[str], default: list[str]) -> list[str]:
        return self._selections.get(label, default)

    def selectbox(self, label: str, options: list[str]) -> str:
        return self._selections.get(label, options[0])

    def __getattr__(self, name: str) -> Any:
        def _recorder(*args: Any, **kwargs: Any) -> None:
            object.__getattribute__(self, "calls").append((name, args))

        return _recorder


def test_demo_graph_renders() -> None:
    """The page renders a graphviz chart and an edge table from mock data."""
    fake = _FakeStreamlit()
    render_graph(fake, loader=_graph)

    assert fake.graphviz, "expected a graphviz chart"
    assert fake.dataframes and fake.dataframes[0], "expected an edge table"


def test_edge_labels_are_readable() -> None:
    """The DOT output carries readable node labels and edge-type labels."""
    dot = build_dot(_graph())
    assert "MIRA" in dot
    assert "WORKS_ON" in dot
    assert "CONTRADICTS" in dot


def test_contradiction_and_supersession_are_distinct() -> None:
    """Contradiction and supersession have distinct visual styles."""
    assert edge_style("CONTRADICTS")["color"] != edge_style("SUPERSEDED_BY")["color"]
    assert "contradiction" in EDGE_STYLES["CONTRADICTS"]["note"]
    assert "supersession" in EDGE_STYLES["SUPERSEDED_BY"]["note"]


def test_evidence_inspection_works() -> None:
    """Inspecting a node surfaces its source observations and provenance."""
    fact_node = _graph()["nodes"][2]
    evidence = node_evidence(fact_node, _graph()["edges"])
    assert "obs_3" in evidence
    assert "atomic_fact" in evidence

    fake = _FakeStreamlit(selections={"Inspect a node for evidence": "uses PostgreSQL"})
    render_graph(fake, loader=_graph)
    assert any("obs_3" in text for text in fake.markdowns)


def test_filter_by_edge_type() -> None:
    """Filtering by edge type keeps only matching, connectable edges."""
    filtered = filter_graph(_graph(), None, ["CONTRADICTS"])
    assert [edge["type"] for edge in filtered["edges"]] == ["CONTRADICTS"]


def test_filter_by_node_type_drops_orphan_edges() -> None:
    """Filtering out a node type drops edges that referenced it."""
    filtered = filter_graph(_graph(), ["atomic_fact"], None)
    assert {node["type"] for node in filtered["nodes"]} == {"atomic_fact"}
    assert filtered["edges"] == []  # endpoints were filtered away


def test_empty_filter_shows_info() -> None:
    """A filter that removes every node surfaces an informational message."""
    fake = _FakeStreamlit(selections={"Node types": []})
    render_graph(fake, loader=_graph)
    assert fake.infos
