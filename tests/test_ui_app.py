"""Verify ISSUE-043 Streamlit UI shell navigation.

Ownership: MIRA contributors.
Related issue: ISSUE-043.
Architecture area: UI.
"""

from __future__ import annotations

from typing import Any

import pytest

from core.db.repositories import configure_database, create_session
from core.db.schema import LEGACY_WORKSPACE_ID
from ui.app import (
    STREAMLIT_SESSION_KEY,
    _initialize_workspace_binding,
    build_app,
    main,
    page_titles,
    render_page,
)

EXPECTED_PAGES = [
    "Chat",
    "Session Working Set",
    "Memory Inspector",
    "Graph Viewer",
    "Retrieval Trace",
    "Foresight Timeline",
    "Evaluation Dashboard",
]


class _FakeStreamlit:
    """Records Streamlit calls and serves as its own sidebar; no real UI needed."""

    def __init__(self, selection: str | None = None) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.titles: list[str] = []
        self.errors: list[str] = []
        self._selection = selection
        self.sidebar = self
        self.session_state: dict[str, object] = {}

    def title(self, text: str) -> None:
        self.titles.append(text)
        self.calls.append(("title", text))

    def radio(self, label: str, options: list[str]) -> str:
        self.calls.append(("radio", options))
        return self._selection or options[0]

    def error(self, text: str) -> None:
        self.errors.append(text)
        self.calls.append(("error", text))

    def __getattr__(self, name: str) -> Any:
        def _recorder(*args: Any, **kwargs: Any) -> None:
            # Use object.__getattribute__ to avoid recursing through __getattr__.
            object.__getattribute__(self, "calls").append((name, args))

        return _recorder


def test_app_starts() -> None:
    """Building the app yields the seven registered pages."""
    pages = build_app()
    assert len(pages) == 7
    assert [page.title for page in pages] == EXPECTED_PAGES


def test_navigation_works() -> None:
    """The shell offers all page titles and renders the selected page."""
    assert page_titles() == EXPECTED_PAGES

    fake = _FakeStreamlit(selection="Graph Viewer")
    main(fake)

    # The navigation widget was offered every page title...
    radio_calls = [options for name, options in fake.calls if name == "radio"]
    assert radio_calls and radio_calls[0] == EXPECTED_PAGES
    # ...and the selected page (not the default) was rendered.
    assert any("Graph Viewer" in title for title in fake.titles)


def test_placeholder_pages_render(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every page renders a title without error using mock data."""
    path = tmp_path / "placeholder-pages.sqlite3"
    monkeypatch.setenv("MIRA_DB_PATH", str(path))
    monkeypatch.setenv("MIRA_STREAMLIT_WORKSPACE_ID", LEGACY_WORKSPACE_ID)
    configure_database(path)
    session_id = create_session("streamlit-test")
    for title in EXPECTED_PAGES:
        fake = _FakeStreamlit()
        fake.session_state[STREAMLIT_SESSION_KEY] = session_id
        assert render_page(title, fake) is True
        assert fake.titles, f"{title} rendered no title"
        assert not fake.errors


def test_unknown_page_reports_error() -> None:
    """An unknown page id surfaces a UI error instead of raising."""
    fake = _FakeStreamlit()
    assert render_page("Nonexistent", fake) is False
    assert fake.errors


def test_streamlit_binding_requires_explicit_workspace(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "streamlit.sqlite3"
    monkeypatch.setenv("MIRA_DB_PATH", str(path))
    monkeypatch.delenv("MIRA_STREAMLIT_WORKSPACE_ID", raising=False)
    configure_database(path)
    fake = _FakeStreamlit()

    with pytest.raises(ValueError, match="MIRA_STREAMLIT_WORKSPACE_ID"):
        _initialize_workspace_binding(fake)


def test_streamlit_binding_creates_workspace_owned_session(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "streamlit-bound.sqlite3"
    monkeypatch.setenv("MIRA_DB_PATH", str(path))
    monkeypatch.setenv("MIRA_STREAMLIT_WORKSPACE_ID", LEGACY_WORKSPACE_ID)
    configure_database(path)
    fake = _FakeStreamlit()

    session_id = _initialize_workspace_binding(fake)

    assert session_id == f"streamlit:{LEGACY_WORKSPACE_ID}"
    assert fake.session_state[STREAMLIT_SESSION_KEY] == session_id


def test_default_navigation_renders_first_page() -> None:
    """With no explicit selection the first page (Chat) renders."""
    fake = _FakeStreamlit()
    main(fake)
    assert any("Chat" in title for title in fake.titles)
