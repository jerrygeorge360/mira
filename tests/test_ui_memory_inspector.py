"""Verify the memory inspector renders real read-model snapshots.

Ownership: MIRA contributors.
Related issue: ISSUE-604.
Architecture area: UI.
"""

from __future__ import annotations

from typing import Any

from ui.memory_inspector import (
    filter_snapshot,
    flatten_snapshot,
    record_detail_markdown,
    render_memory_inspector,
    summary_rows,
)


def _snapshot() -> dict[str, list[dict[str, object]]]:
    return {
        "session_working_set": [
            {
                "id": "sws_1",
                "type": "correction",
                "status": "provisional",
                "content": "Use PostgreSQL, not MongoDB.",
                "priority": 0.96,
                "source_observations": ["obs_1"],
            }
        ],
        "hot_memory": [
            {
                "id": "hot_1",
                "memory_type": "project_constraint",
                "status": "active",
                "content": "Database is PostgreSQL.",
                "priority": 0.9,
            }
        ],
        "reflections": [
            {
                "id": "ref_1",
                "reflection_type": "user_knowledge",
                "status": "active",
                "content": "User separates source of truth from indexes.",
                "confidence": 0.87,
            }
        ],
        "foresight": [
            {
                "id": "fore_1",
                "status": "pending",
                "content": "Benchmark run is upcoming.",
            }
        ],
        "community_summaries": [
            {
                "id": "comm_1",
                "title": "Storage architecture",
                "summary": "SQLite, Chroma, and retrieval responsibilities.",
            }
        ],
    }


class _FakeStreamlit:
    def __init__(self, selections: dict[str, str] | None = None) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.markdowns: list[str] = []
        self.dataframes: list[Any] = []
        self.infos: list[str] = []
        self._selections = selections or {}
        self.sidebar = self

    def title(self, text: str) -> None:
        self.calls.append(("title", text))

    def caption(self, text: str) -> None:
        self.calls.append(("caption", text))

    def subheader(self, text: str) -> None:
        self.calls.append(("subheader", text))

    def markdown(self, text: str) -> None:
        self.markdowns.append(text)

    def dataframe(self, data: Any) -> None:
        self.dataframes.append(data)

    def info(self, text: str) -> None:
        self.infos.append(text)

    def selectbox(self, label: str, options: list[str]) -> str:
        self.calls.append(("selectbox", label, options))
        return self._selections.get(label, options[0])


def test_summary_rows_count_each_memory_source() -> None:
    """The inspector summary reports counts and active records by source."""
    rows = summary_rows(_snapshot())
    by_source = {str(row["source"]): row for row in rows}

    assert by_source["Session Working Set"]["records"] == 1
    assert by_source["Session Working Set"]["active"] == 1
    assert by_source["Foresight"]["active"] == 0


def test_filters_compose_by_source_status_and_type() -> None:
    """Source, status, and type filters select the intended records."""
    filtered = filter_snapshot(
        _snapshot(),
        source_filter="session_working_set",
        status_filter="provisional",
        type_filter="correction",
    )

    assert [item["id"] for item in filtered["session_working_set"]] == ["sws_1"]
    assert all(not items for source, items in filtered.items() if source != "session_working_set")


def test_flatten_snapshot_adds_source_for_detail_selection() -> None:
    """Flattened records carry their source so detail rendering can explain provenance."""
    rows = flatten_snapshot(_snapshot())

    assert {row["source"] for row in rows} >= {"session_working_set", "hot_memory"}
    assert any(row["id"] == "comm_1" for row in rows)


def test_record_detail_shows_evidence_and_content() -> None:
    """Selected-record markdown includes content and evidence ids."""
    detail = record_detail_markdown({"id": "sws_1", **_snapshot()["session_working_set"][0]})

    assert "Use PostgreSQL" in detail
    assert "obs_1" in detail


def test_render_memory_inspector_uses_snapshot_loader() -> None:
    """Rendering uses the supplied loader, draws summary/detail, and returns the snapshot."""
    seen: list[tuple[str, int]] = []

    def _loader(session_id: str, limit: int) -> dict[str, list[dict[str, object]]]:
        seen.append((session_id, limit))
        return _snapshot()

    fake = _FakeStreamlit(selections={"Inspect memory record": "hot_1"})
    rendered = render_memory_inspector("session_1", fake, limit=10, loader=_loader)

    assert seen == [("session_1", 10)]
    assert rendered == _snapshot()
    assert len(fake.dataframes) >= 2
    assert any("Database is PostgreSQL" in markdown for markdown in fake.markdowns)


def test_empty_filter_result_shows_info() -> None:
    """An empty filtered view is explicit rather than looking broken."""
    fake = _FakeStreamlit(selections={"Status": "missing"})

    render_memory_inspector("session_1", fake, loader=lambda _session, _limit: _snapshot())

    assert fake.infos
