"""MIRA Streamlit UI shell: navigation across inspectable memory pages.

Ownership: MIRA contributors.
Related issue: ISSUE-043.
Architecture area: UI.

The command-center surface can run against deterministic demo data or the real
MIRA agent. Smaller legacy pages stay lightweight but call the same UI/read-model
components where durable memory data exists.

Streamlit is imported lazily so importing this module stays dependency-free; the
render functions take an injected ``st`` so they are testable without Streamlit.
The real entry point is ``streamlit run ui/app.py`` (or ``run_app()``).
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# `streamlit run ui/app.py` puts only the ui/ directory on sys.path, so the
# `from ui... import` lines below fail. Add the repo root so the app runs the same
# whether launched via `make run`, `streamlit run`, or `python -m ui.app`.
_REPO_ROOT = str(Path(__file__).resolve().parents[1])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from ui.chat import DEFAULT_SESSION_ID, MockChatAgent, render_chat  # noqa: E402
from ui.command_center import render_command_center  # noqa: E402
from ui.foresight_view import render_foresight_timeline  # noqa: E402
from ui.graph_viz import render_graph  # noqa: E402
from ui.landing import render_landing  # noqa: E402
from ui.memory_inspector import render_memory_inspector  # noqa: E402
from ui.retrieval_trace import render_retrieval_trace  # noqa: E402
from ui.session_view import render_session_working_set  # noqa: E402

APP_TITLE = "MIRA — Memory Command Center"


@dataclass(frozen=True)
class Page:
    """One navigable UI page: a stable key, a sidebar title, and a renderer."""

    key: str
    title: str
    render: Callable[[Any], None]


# --- Deterministic demo data for pages that do not require a populated database. ---
_MOCK_BENCHMARK_RESULTS = [
    {
        "benchmark": "LongMemEval",
        "task": "Long-term cross-session recall",
        "primary_metric": "Recall / evidence F1",
        "mira_result": "Pending",
        "notes": "Official external-style memory benchmark track.",
    },
    {
        "benchmark": "LoCoMo-style",
        "task": "Temporal conversational memory",
        "primary_metric": "Temporal QA accuracy",
        "mira_result": "Pending",
        "notes": "Conversation timeline and temporal dependency track.",
    },
]

_MOCK_ABLATION_RESULTS = [
    {
        "ablation": "Remove Session Working Set",
        "expected_drop": "High",
        "metric_to_report": "Next-turn correction compliance",
        "why_it_matters": "Tests whether immediate corrections work before durable confirmation.",
        "result": "Pending",
    },
    {
        "ablation": "Remove keyword retrieval",
        "expected_drop": "Medium",
        "metric_to_report": "Exact-name / deadline recall",
        "why_it_matters": (
            "Tests whether semantic search alone misses IDs, names, and exact phrases."
        ),
        "result": "Pending",
    },
    {
        "ablation": "Remove typed graph traversal",
        "expected_drop": "High",
        "metric_to_report": "Contradiction and supersession QA",
        "why_it_matters": (
            "Tests whether MIRA can answer change/relationship questions without graph paths."
        ),
        "result": "Pending",
    },
    {
        "ablation": "Remove foresight records",
        "expected_drop": "Medium",
        "metric_to_report": "Future-task activation precision",
        "why_it_matters": (
            "Tests whether deadlines and pending commitments resurface at the right time."
        ),
        "result": "Pending",
    },
    {
        "ablation": "Remove reflections/community summaries",
        "expected_drop": "Medium",
        "metric_to_report": "Long-horizon synthesis score",
        "why_it_matters": "Tests whether broad pattern recall depends on higher-order memory.",
        "result": "Pending",
    },
]

_DEMO_NOTE = "Deterministic demo data keeps this page usable without a populated memory database."


def _render_chat(st: Any) -> None:
    render_chat(DEFAULT_SESSION_ID, st, MockChatAgent())


def _render_session_working_set(st: Any) -> None:
    render_session_working_set(DEFAULT_SESSION_ID, st)


def _render_memory_inspector(st: Any) -> None:
    render_memory_inspector(DEFAULT_SESSION_ID, st)


def _render_graph_viewer(st: Any) -> None:
    render_graph(st)


def _render_retrieval_trace(st: Any) -> None:
    render_retrieval_trace(st=st)


def _render_foresight_timeline(st: Any) -> None:
    render_foresight_timeline(st=st)


def _render_evaluation_dashboard(st: Any) -> None:
    st.title("📊 Evaluation Dashboard")
    st.caption("Official benchmark results are separate from MIRA ablation studies.")
    st.markdown(
        """
        Official benchmarks evaluate the complete MIRA system against standard
        memory tasks. Ablation studies remove one MIRA component at a time and
        measure the performance drop, so the team can prove which architectural
        pieces are actually carrying the result.
        """
    )
    st.subheader("Official benchmark results")
    st.dataframe(_MOCK_BENCHMARK_RESULTS)
    st.subheader("Ablation studies")
    st.dataframe(_MOCK_ABLATION_RESULTS)
    st.info(_DEMO_NOTE)


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
            streamlit.markdown(_landing_transition_css(), unsafe_allow_html=True)
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


def _landing_transition_css() -> str:
    """Return a small pre-render reset used when leaving the command center."""
    return """
    <style>
    .st-key-cc_rail { display: none !important; }
    .block-container {
      max-width: 1080px !important;
      padding: 1.4rem 1.6rem 4rem !important;
    }
    </style>
    """


if __name__ == "__main__":  # pragma: no cover - Streamlit entry point
    main()
