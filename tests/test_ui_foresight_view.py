"""Verify ISSUE-048 foresight timeline page.

Ownership: MIRA contributors.
Related issue: ISSUE-048.
Architecture area: UI.
"""

from __future__ import annotations

from typing import Any

from ui.foresight_view import filter_foresight, render_foresight_timeline, timeline_rows


def _records() -> list[dict[str, object]]:
    return [
        {
            "id": "fs_1",
            "content": "Hackathon due 2026-07-01.",
            "status": "active",
            "valid_from": "2026-06-24T00:00:00+00:00",
            "valid_until": "2026-07-01T23:59:59+00:00",
            "always_inject": 0,
            "source_observation_id": "obs_deadline",
            "resolved_by": None,
        },
        {
            "id": "fs_2",
            "content": "Audit freeze.",
            "status": "pending",
            "valid_from": "2026-08-01T00:00:00+00:00",
            "valid_until": "2026-08-15T00:00:00+00:00",
            "always_inject": 0,
            "source_observation_id": "obs_audit",
            "resolved_by": None,
        },
        {
            "id": "fs_3",
            "content": "Old deadline.",
            "status": "expired",
            "valid_from": "2026-04-01T00:00:00+00:00",
            "valid_until": "2026-04-15T00:00:00+00:00",
            "always_inject": 0,
            "source_observation_id": "obs_old",
            "resolved_by": None,
        },
    ]


class _FakeStreamlit:
    def __init__(self, selections: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.markdowns: list[str] = []
        self.dataframes: list[Any] = []
        self.infos: list[str] = []
        self._selections = selections or {}
        self.sidebar = self

    def markdown(self, text: str) -> None:
        self.markdowns.append(text)

    def dataframe(self, data: Any) -> None:
        self.dataframes.append(data)

    def info(self, text: str) -> None:
        self.infos.append(text)

    def selectbox(self, label: str, options: list[str]) -> str:
        return self._selections.get(label, options[0])

    def __getattr__(self, name: str) -> Any:
        def _recorder(*args: Any, **kwargs: Any) -> None:
            object.__getattribute__(self, "calls").append((name, args))

        return _recorder


def test_active_foresight_listed() -> None:
    """The active filter selects only active records."""
    active = filter_foresight(_records(), "active")
    assert [record["id"] for record in active] == ["fs_1"]


def test_status_filters_select_correct_records() -> None:
    """Each lifecycle filter selects the matching records."""
    assert [r["id"] for r in filter_foresight(_records(), "expired")] == ["fs_3"]
    assert [r["id"] for r in filter_foresight(_records(), "upcoming")] == ["fs_2"]
    assert len(filter_foresight(_records(), "all")) == 3


def test_timeline_displays_valid_windows() -> None:
    """Timeline rows carry each record's validity window, sorted by start."""
    rows = timeline_rows(_records())
    assert [row["valid_from"] for row in rows] == [
        "2026-04-01T00:00:00+00:00",
        "2026-06-24T00:00:00+00:00",
        "2026-08-01T00:00:00+00:00",
    ]
    assert any("→" in str(row["window"]) for row in rows)


def test_timeline_rendered_in_page() -> None:
    """Rendering shows the timeline table for the filtered records."""
    fake = _FakeStreamlit(selections={"Status": "active"})
    render_foresight_timeline("s1", fake, loader=_records)

    assert fake.dataframes, "expected a timeline table"
    windows = [row["window"] for row in fake.dataframes[0]]
    assert any("2026-07-01" in str(window) for window in windows)


def test_source_observation_visible() -> None:
    """Each rendered record shows its source observation."""
    fake = _FakeStreamlit()
    render_foresight_timeline("s1", fake, loader=_records)
    joined = "\n".join(fake.markdowns)
    assert "Source observation:" in joined
    assert "obs_deadline" in joined


def test_empty_filter_shows_info() -> None:
    """A filter that matches nothing surfaces an informational message."""
    fake = _FakeStreamlit(selections={"Status": "resolved"})
    render_foresight_timeline("s1", fake, loader=_records)
    assert fake.infos


def test_default_mock_renders() -> None:
    """With the default mock loader the page renders a timeline."""
    fake = _FakeStreamlit()
    render_foresight_timeline("s1", fake)
    assert fake.dataframes
    assert not fake.infos
