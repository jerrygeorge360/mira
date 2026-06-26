"""MIRA Streamlit UI shell: navigation across inspectable memory pages.

Ownership: Sarah.
Related issue: ISSUE-043.
Architecture area: UI.

This is the navigation shell only. It registers the seven demo pages and renders
the selected one; each page is a placeholder backed by mock data so the UI runs
before the backend is wired and so Sarah can build pages independently. No
backend memory logic lives here (Non-Goal) -- pages call no core modules yet.

Streamlit is imported lazily so importing this module stays dependency-free; the
render functions take an injected ``st`` so they are testable without Streamlit.
The real entry point is ``streamlit run ui/app.py`` (or ``run_app()``).
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ui.chat import DEFAULT_SESSION_ID, MockChatAgent, render_chat
from ui.command_center import render_command_center
from ui.foresight_view import render_foresight_timeline
from ui.graph_viz import render_graph
from ui.landing import render_landing
from ui.retrieval_trace import render_retrieval_trace
from ui.session_view import render_session_working_set

APP_TITLE = "MIRA — Memory Command Center"


@dataclass(frozen=True)
class Page:
    """One navigable UI page: a stable key, a sidebar title, and a renderer."""

    key: str
    title: str
    render: Callable[[Any], None]


# --- Mock data (placeholder only; replaced by real backend wiring per page) ---

_MOCK_MEMORY = [
    {"tier": "hot", "type": "project_constraint", "content": "SQLite is the source of truth."},
    {"tier": "warm", "type": "reflection", "content": "Project prefers repository helpers."},
]
_MOCK_EVAL = [
    {"category": "direct_fact_recall", "passed": 1, "total": 1},
    {"category": "session_correction_handling", "passed": 1, "total": 1},
]

_PLACEHOLDER = "Placeholder page with mock data — backend wiring is a follow-up issue."


def _render_chat(st: Any) -> None:
    render_chat(DEFAULT_SESSION_ID, st, MockChatAgent())


def _render_session_working_set(st: Any) -> None:
    render_session_working_set(DEFAULT_SESSION_ID, st)


def _render_memory_inspector(st: Any) -> None:
    st.title("🗄️ Memory Inspector")
    st.caption("Durable cold/warm/hot memory items.")
    st.dataframe(_MOCK_MEMORY)
    st.info(_PLACEHOLDER)


def _render_graph_viewer(st: Any) -> None:
    render_graph(st)


def _render_retrieval_trace(st: Any) -> None:
    render_retrieval_trace(st=st)


def _render_foresight_timeline(st: Any) -> None:
    render_foresight_timeline(st=st)


def _render_evaluation_dashboard(st: Any) -> None:
    st.title("📊 Evaluation Dashboard")
    st.caption("Per-category pass rates from the evaluation harness.")
    st.dataframe(_MOCK_EVAL)
    st.info(_PLACEHOLDER)


PAGES: tuple[Page, ...] = (
    Page("chat", "Chat", _render_chat),
    Page("session_working_set", "Session Working Set", _render_session_working_set),
    Page("memory_inspector", "Memory Inspector", _render_memory_inspector),
    Page("graph_viewer", "Graph Viewer", _render_graph_viewer),
    Page("retrieval_trace", "Retrieval Trace", _render_retrieval_trace),
    Page("foresight_timeline", "Foresight Timeline", _render_foresight_timeline),
    Page("evaluation_dashboard", "Evaluation Dashboard", _render_evaluation_dashboard),
)


def page_titles() -> list[str]:
    """Return the navigation titles in display order."""
    return [page.title for page in PAGES]


def get_page(identifier: str) -> Page | None:
    """Resolve a page by its title or key."""
    for page in PAGES:
        if identifier in (page.title, page.key):
            return page
    return None


def render_page(identifier: str, st: Any) -> bool:
    """Render the page identified by title or key; return whether it was found."""
    page = get_page(identifier)
    if page is None:
        st.error(f"Unknown page: {identifier}")
        return False
    page.render(st)
    return True


def build_app() -> tuple[Page, ...]:
    """Return the registered pages (the app 'starting' without a UI server)."""
    return PAGES


def main(st: Any | None = None) -> None:
    """Render MIRA.

    With real Streamlit this renders the premium Memory Command Center. When an
    injected fake ``st`` is supplied, it preserves the original testable page
    shell contract used by existing UI tests.
    """
    streamlit = st if st is not None else _load_streamlit()
    streamlit.set_page_config(
        page_title=APP_TITLE,
        layout="wide",
        initial_sidebar_state="expanded",
    )
    if st is None:
        if streamlit.session_state.get("mira_entered"):
            render_command_center(streamlit)
        else:
            render_landing(streamlit)
        return
    streamlit.sidebar.title(APP_TITLE)
    selection = streamlit.sidebar.radio("Navigation", page_titles())
    render_page(str(selection), streamlit)


def run_app() -> None:
    """Entry point used by ``streamlit run ui/app.py``."""
    main()


def _load_streamlit() -> Any:
    try:
        return importlib.import_module("streamlit")
    except ModuleNotFoundError as error:  # pragma: no cover - exercised only without streamlit
        raise RuntimeError(
            "streamlit is not installed; install it to run the MIRA UI shell"
        ) from error


if __name__ == "__main__":  # pragma: no cover - Streamlit entry point
    main()
