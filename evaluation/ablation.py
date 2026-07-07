"""Component ablations for MIRA architecture evaluation.

Ownership: MIRA contributors.
Related issue: ISSUE-053.
Architecture area: evaluation.

Ablations show which layers contribute by genuinely turning components off and
re-running the evaluation cases. Disabling is real, not faked: each ablation
patches the actual composition seam (so the component does not run) for the
duration of a run, then restores it. Components that only affect the asynchronous
slow path are marked as such rather than pretended to change agent behavior, so a
demo/paper can show an honest prototype ablation.
"""

from __future__ import annotations

import contextlib
import importlib
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from core.db.repositories import create_session
from evaluation.cases import load_evaluation_cases, score_case

LOGGER = logging.getLogger(__name__)

ABLATION_COMPONENTS = (
    "session_working_set",
    "relational_mode",
    "deep_mode",
    "foresight",
    "reflection",
    "contradiction_supersession",
    "vector_only",
)

# Components whose effect is observable in the synchronous agent turn.
AGENT_EFFECTIVE = frozenset(
    {"session_working_set", "relational_mode", "deep_mode", "foresight", "reflection"}
)
# Components that only affect the asynchronous slow path (not the agent turn).
SLOW_PATH_ONLY = frozenset({"contradiction_supersession"})

# The vector-only baseline strips every higher layer, leaving Quick retrieval.
VECTOR_ONLY_DISABLED = frozenset(AGENT_EFFECTIVE)

DEFAULT_CASES_PATH = str(Path(__file__).resolve().parent / "memory_cases.json")


@dataclass(frozen=True)
class AblationConfig:
    """A named ablation: the set of components disabled for a run."""

    name: str
    disabled: frozenset[str]


@dataclass
class AblationRow:
    """The outcome of running the cases under one ablation config."""

    name: str
    disabled: list[str]
    applied: list[str]
    total: int
    passed: int
    pass_rate: float
    note: str = ""
    results: list[dict[str, object]] = field(default_factory=list)


def standard_ablations() -> list[AblationConfig]:
    """Return the full-system baseline plus one config per architecture ablation."""
    configs = [AblationConfig("full_system", frozenset())]
    for component in ABLATION_COMPONENTS:
        if component == "vector_only":
            continue
        configs.append(AblationConfig(f"without_{component}", frozenset({component})))
    configs.append(AblationConfig("vector_only_baseline", VECTOR_ONLY_DISABLED))
    return configs


def _empty(*_args: object, **_kwargs: object) -> list[object]:
    return []


_SIMPLE_DISABLERS: dict[str, list[tuple[str, str, Callable[..., object]]]] = {
    "session_working_set": [("core.agent", "export_prompt_ready_session_items", _empty)],
    "foresight": [("core.session.hydration", "list_relevant_foresight", _empty)],
    "reflection": [
        ("core.retrieval.deep", "_reflection_candidates", _empty),
        ("core.session.hydration", "_reflection_candidates", _empty),
    ],
}


@contextlib.contextmanager
def apply_ablation(config: AblationConfig) -> Iterator[set[str]]:
    """Genuinely disable the config's components for the duration of the block.

    Yields the set of components that were actually disabled (agent-effective
    ones), so callers can report honest coverage.
    """
    disabled = config.disabled
    applied: set[str] = set()
    with contextlib.ExitStack() as stack:
        for component in disabled:
            for module_path, attr, replacement in _SIMPLE_DISABLERS.get(component, []):
                if stack.enter_context(_patched(module_path, attr, replacement)):
                    applied.add(component)

        disabled_modes = {mode for mode in ("relational", "deep") if f"{mode}_mode" in disabled}
        if disabled_modes:
            route_patch = _patched(
                "core.agent", "route_retrieval", _route_downgrade(disabled_modes)
            )
            if stack.enter_context(route_patch):
                applied.update(f"{mode}_mode" for mode in disabled_modes)

        yield applied


@contextlib.contextmanager
def _patched(module_path: str, attr: str, value: object) -> Iterator[bool]:
    module = importlib.import_module(module_path)
    if not hasattr(module, attr):
        LOGGER.warning("Ablation seam missing: %s.%s", module_path, attr)
        yield False
        return
    original = getattr(module, attr)
    setattr(module, attr, value)
    try:
        yield True
    finally:
        setattr(module, attr, original)


def _route_downgrade(disabled_modes: set[str]) -> Callable[..., dict[str, object]]:
    original = importlib.import_module("core.retrieval.auto").route_retrieval

    def wrapper(query: str, session_id: str | None, **kwargs: object) -> dict[str, object]:
        decision: dict[str, object] = original(query, session_id, **kwargs)
        if decision.get("mode") in disabled_modes:
            return {
                "mode": "quick",
                "reason": f"ablation: {decision.get('mode')} mode disabled -> quick",
                "confidence": decision.get("confidence", 0.0),
                "needs_sufficiency_check": decision.get("needs_sufficiency_check", False),
            }
        return decision

    return wrapper


def run_ablation(component_names: list[str], cases_path: str | None = None) -> dict[str, object]:
    """Run the evaluation cases with the named components disabled."""
    config = AblationConfig("custom", frozenset(component_names))
    row = _run_config(config, cases_path or DEFAULT_CASES_PATH)
    return _row_to_dict(row)


def run_ablation_study(
    cases_path: str | None = None,
    configs: list[AblationConfig] | None = None,
) -> dict[str, object]:
    """Run baseline plus each ablation and produce a comparison table."""
    resolved_path = cases_path or DEFAULT_CASES_PATH
    rows = [_run_config(config, resolved_path) for config in (configs or standard_ablations())]
    return {
        "cases_path": resolved_path,
        "rows": [_row_to_dict(row) for row in rows],
        "table": render_ablation_table(rows),
    }


def render_ablation_table(rows: list[AblationRow]) -> str:
    """Render ablation rows as a Markdown comparison table."""
    lines = [
        "| Config | Disabled | Cases | Passed | Pass rate | Note |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        disabled = ", ".join(row.disabled) or "none"
        lines.append(
            f"| {row.name} | {disabled} | {row.total} | {row.passed} "
            f"| {row.pass_rate:.2f} | {row.note} |"
        )
    return "\n".join(lines)


def _run_config(config: AblationConfig, cases_path: str) -> AblationRow:
    cases = load_evaluation_cases(cases_path)
    results: list[dict[str, object]] = []
    with apply_ablation(config) as applied:
        for case in cases:
            results.append(_run_case(case))

    passed = sum(1 for result in results if result["passed"])
    total = len(results)
    return AblationRow(
        name=config.name,
        disabled=sorted(config.disabled),
        applied=sorted(applied),
        total=total,
        passed=passed,
        pass_rate=round(passed / total, 4) if total else 0.0,
        note=_coverage_note(config.disabled, applied),
        results=results,
    )


def _run_case(case: dict[str, object]) -> dict[str, object]:
    from core.agent import handle_user_message

    raw_interactions = case.get("interactions")
    interactions = raw_interactions if isinstance(raw_interactions, list) else []
    expected = case.get("expect")
    expected_dict = expected if isinstance(expected, dict) else {}

    session_id = create_session("ablation")
    actual: dict[str, object] = {}
    try:
        for interaction in interactions:
            if not isinstance(interaction, dict):
                continue
            if interaction.get("reset_session"):
                session_id = create_session("ablation")
            message = str(interaction.get("message", "")).strip()
            if message:
                actual = handle_user_message(session_id, message)
        error = None if actual else "no response"
    except (ValueError, KeyError) as failure:
        actual = {"answer": ""}
        error = str(failure)

    score = score_case(expected_dict, actual)
    return {
        "id": str(case.get("id", "unnamed")),
        "category": str(case.get("category", "uncategorized")),
        "passed": bool(score["passed"]) and error is None,
        "score": score["score"],
        "error": error,
    }


def _coverage_note(disabled: frozenset[str], applied: set[str]) -> str:
    slow_path = sorted(component for component in disabled if component in SLOW_PATH_ONLY)
    not_applied = sorted(
        component
        for component in disabled
        if component not in applied and component not in SLOW_PATH_ONLY
    )
    notes = []
    if slow_path:
        notes.append(f"slow-path-only (not exercised by agent harness): {', '.join(slow_path)}")
    if not_applied:
        notes.append(f"no seam applied: {', '.join(not_applied)}")
    return "; ".join(notes)


def _row_to_dict(row: AblationRow) -> dict[str, object]:
    return {
        "name": row.name,
        "disabled": row.disabled,
        "applied": row.applied,
        "total": row.total,
        "passed": row.passed,
        "pass_rate": row.pass_rate,
        "note": row.note,
        "results": row.results,
    }
