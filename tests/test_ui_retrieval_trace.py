"""Verify ISSUE-047 retrieval/answer trace viewer.

Ownership: MIRA contributors.
Related issue: ISSUE-047.
Architecture area: UI.
"""

from __future__ import annotations

from typing import Any

from ui.retrieval_trace import _section_row, render_retrieval_trace


def _trace(trace_id: str = "resp_1") -> dict[str, object]:
    return {
        "id": trace_id,
        "retrieval_mode": "relational",
        "router_reason": "entity-centered change question",
        "retrieved_observation_ids": ["obs_1", "obs_2"],
        "retrieved_fact_ids": ["fact_1"],
        "session_item_ids": ["sws_1"],
        "graph_path_ids": ["node_a", "node_b"],
        "community_summary_ids": ["comm_1"],
        "sufficiency": {"is_sufficient": True, "missing": [], "rewrite_query": None},
        "prompt_sections": [
            {"section": "session_working_set", "source_ids": ["sws_1"]},
            {"section": "system_prompt", "source_ids": ["secret"]},
        ],
    }


class _FakeStreamlit:
    def __init__(self, selections: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.markdowns: list[str] = []
        self.dataframes: list[Any] = []
        self.warnings: list[str] = []
        self.infos: list[str] = []
        self._selections = selections or {}
        self.sidebar = self

    def title(self, text: str) -> None:
        self.calls.append(("title", text))

    def markdown(self, text: str) -> None:
        self.markdowns.append(text)

    def dataframe(self, data: Any) -> None:
        self.dataframes.append(data)

    def warning(self, text: str) -> None:
        self.warnings.append(text)

    def info(self, text: str) -> None:
        self.infos.append(text)

    def selectbox(self, label: str, options: list[str]) -> str:
        self.calls.append(("selectbox", options))
        return self._selections.get(label, options[0])

    def __getattr__(self, name: str) -> Any:
        def _recorder(*args: Any, **kwargs: Any) -> None:
            object.__getattribute__(self, "calls").append((name, args))

        return _recorder


def test_trace_loads_by_response_id() -> None:
    """A trace is loaded and rendered for a given response id."""
    seen: list[str] = []

    def loader(trace_id: str) -> dict[str, object] | None:
        seen.append(trace_id)
        return _trace(trace_id) if trace_id == "resp_1" else None

    fake = _FakeStreamlit()
    render_retrieval_trace("resp_1", fake, loader=loader)

    assert seen == ["resp_1"]
    assert any("resp_1" in text for text in fake.markdowns)
    assert any("relational" in text for text in fake.markdowns)


def test_missing_trace_warns() -> None:
    """An unknown response id surfaces a warning instead of rendering a trace."""
    fake = _FakeStreamlit()
    render_retrieval_trace("nope", fake, loader=lambda _id: None)
    assert fake.warnings


def test_retrieved_items_are_clickable() -> None:
    """Retrieved records are offered for inspection and the selection is detailed."""
    fake = _FakeStreamlit(selections={"Inspect a retrieved record": "fact_1"})
    render_retrieval_trace("resp_1", fake, loader=lambda _id: _trace())

    selectbox_options = [options for name, options in fake.calls if name == "selectbox"]
    assert selectbox_options and "obs_1" in selectbox_options[0]
    assert any("fact_1" in text for text in fake.markdowns)


def test_sufficiency_result_visible() -> None:
    """The sufficiency verdict is shown in the trace."""
    fake = _FakeStreamlit()
    render_retrieval_trace("resp_1", fake, loader=lambda _id: _trace())
    assert any("sufficient" in text.lower() for text in fake.markdowns)


def test_sensitive_prompt_section_content_hidden() -> None:
    """System/developer prompt sections are flagged as content-hidden."""
    safe = _section_row({"section": "session_working_set", "source_ids": ["sws_1"]})
    sensitive = _section_row({"section": "system_prompt", "source_ids": ["secret"]})
    assert safe["note"] == ""
    assert "hidden" in str(sensitive["note"])


def test_mock_trace_renders_by_default() -> None:
    """With the default mock loader the page renders a demo trace."""
    fake = _FakeStreamlit()
    render_retrieval_trace("demo-trace", fake)
    assert any("Retrieval mode" in text for text in fake.markdowns)
    assert not fake.warnings
