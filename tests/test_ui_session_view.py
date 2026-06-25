"""Verify ISSUE-045 Session Working Set inspector page.

Ownership: MIRA contributors.
Related issue: ISSUE-045.
Architecture area: UI.
"""

from __future__ import annotations

from typing import Any

from ui.session_view import filter_session_items, render_session_working_set


def _items() -> list[dict[str, object]]:
    return [
        {
            "id": "a",
            "content": "Use 2026, not 2025.",
            "type": "correction",
            "scope": "project",
            "status": "provisional",
            "priority": 0.96,
            "explicitness_label": "direct_correction",
            "evidence_span": "Use 2026, not 2025.",
            "origin": "micro_path",
            "source_observations": ["obs_a"],
            "resolution_reason": None,
        },
        {
            "id": "b",
            "content": "Hydrated durable constraint.",
            "type": "active_constraint",
            "scope": "project",
            "status": "hydrated",
            "priority": 0.8,
            "explicitness_label": "direct_instruction",
            "evidence_span": "durable constraint",
            "origin": "cross_session_hydration",
            "source_observations": ["obs_b"],
            "resolution_reason": None,
        },
        {
            "id": "c",
            "content": "Rejected idea.",
            "type": "decision",
            "scope": "current_session",
            "status": "rejected",
            "priority": 0.3,
            "explicitness_label": "direct_decision",
            "evidence_span": "rejected idea",
            "origin": "micro_path",
            "source_observations": ["obs_c"],
            "resolution_reason": "Contradicted later.",
        },
    ]


class _FakeStreamlit:
    """Records Streamlit calls; serves as its own sidebar with scripted selectboxes."""

    def __init__(self, selections: dict[str, str] | None = None) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.markdowns: list[str] = []
        self.dataframes: list[Any] = []
        self.infos: list[str] = []
        self._selections = selections or {}
        self.sidebar = self

    def title(self, text: str) -> None:
        self.calls.append(("title", text))

    def markdown(self, text: str) -> None:
        self.markdowns.append(text)

    def dataframe(self, data: Any) -> None:
        self.dataframes.append(data)

    def info(self, text: str) -> None:
        self.infos.append(text)

    def selectbox(self, label: str, options: list[str]) -> str:
        self.calls.append(("selectbox", label, options))
        return self._selections.get(label, options[0])

    def __getattr__(self, name: str) -> Any:
        def _recorder(*args: Any, **kwargs: Any) -> None:
            object.__getattribute__(self, "calls").append((name, args))

        return _recorder


def test_filter_active_only() -> None:
    """The active-only filter keeps prompt-relevant statuses and drops terminal ones."""
    active = filter_session_items(_items(), "active_only")
    statuses = {str(item["status"]) for item in active}
    assert statuses == {"provisional", "hydrated"}


def test_status_filters_work() -> None:
    """Provisional and rejected/expired filters select the right items."""
    provisional = filter_session_items(_items(), "provisional")
    assert [item["id"] for item in provisional] == ["a"]

    terminal = filter_session_items(_items(), "rejected_expired")
    assert [item["id"] for item in terminal] == ["c"]


def test_filter_by_type_and_scope() -> None:
    """Type and scope filters compose with the status filter."""
    by_type = filter_session_items(_items(), "all", item_type="correction")
    assert [item["id"] for item in by_type] == ["a"]

    by_scope = filter_session_items(_items(), "all", scope="current_session")
    assert [item["id"] for item in by_scope] == ["c"]


def test_active_items_are_listed() -> None:
    """Rendering with the active filter lists the active items in a table."""
    fake = _FakeStreamlit(selections={"Status": "active_only"})
    render_session_working_set("s1", fake, loader=lambda _s: _items())

    assert fake.dataframes, "expected a table of items"
    listed_ids = {row["content"] for row in fake.dataframes[0]}
    assert "Use 2026, not 2025." in listed_ids
    assert "Rejected idea." not in listed_ids  # terminal item filtered out


def test_evidence_span_is_visible() -> None:
    """Each rendered item shows its evidence span."""
    fake = _FakeStreamlit()
    render_session_working_set("s1", fake, loader=lambda _s: _items())

    joined = "\n".join(fake.markdowns)
    assert "Evidence span:" in joined
    assert "Use 2026, not 2025." in joined


def test_explains_provisional_vs_confirmed() -> None:
    """The page explains provisional vs confirmed memory."""
    fake = _FakeStreamlit()
    render_session_working_set("s1", fake, loader=lambda _s: _items())

    joined = "\n".join(fake.markdowns).lower()
    assert "provisional" in joined
    assert "confirmed" in joined


def test_no_matching_items_shows_info() -> None:
    """An empty result set surfaces an informational message."""
    fake = _FakeStreamlit(selections={"Status": "rejected_expired"})
    render_session_working_set("s1", fake, loader=lambda _s: [])

    assert fake.infos
