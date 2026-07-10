"""Component ablations for MIRA architecture evaluation.

Ownership: MIRA contributors.
Related issue: ISSUE-053.
Architecture area: evaluation.

Ablations show which layers contribute by genuinely turning components off and
re-running the evaluation cases. Disabling is real, not faked: each ablation
patches the actual composition seam (so the component does not run) for the
duration of a run, then restores it. When slow-path draining is enabled, each
configuration gets the same durable-memory ingestion opportunity before scoring.
"""

from __future__ import annotations

import contextlib
import importlib
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from core.db.chroma import reset_vector_store
from core.db.repositories import configure_database, current_database_path
from evaluation.local.cases import load_evaluation_cases, score_case
from evaluation.runtime.case_runner import (
    ProgressReporter,
    isolate_case_state,
    isolation_base_path,
    run_case_interactions,
)

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
# The vector-only baseline strips every higher layer, leaving Quick retrieval.
VECTOR_ONLY_DISABLED = frozenset(AGENT_EFFECTIVE)

DEFAULT_CASES_PATH = str(Path(__file__).resolve().parent.parent / "local" / "memory_cases.json")


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
    "foresight": [
        # Foresight reaches an answer through two independent paths: proactive session
        # hydration and reactive quick retrieval. Disabling only one leaves the other to
        # satisfy foresight cases, so a fair ablation must seam both.
        ("core.session.hydration", "list_relevant_foresight", _empty),
        ("core.retrieval.quick", "_foresight_candidates", _empty),
    ],
    "reflection": [
        ("core.retrieval.deep", "_reflection_candidates", _empty),
        ("core.session.hydration", "_reflection_candidates", _empty),
    ],
    "contradiction_supersession": [
        ("core.memory.slow_path", "_step_changes", lambda *_args, **_kwargs: {"graph_edges": []})
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


def select_ablations(components: list[str] | None = None) -> list[AblationConfig]:
    """Return the full standard ablation set, or a faster subset.

    With ``components`` the study runs only the ``full_system`` baseline plus the named
    ablations, so a run can target a few layers instead of all of them.
    """
    everything = standard_ablations()
    if not components:
        return everything
    keep = {"full_system"}
    for name in components:
        keep.add("vector_only_baseline" if name == "vector_only" else f"without_{name}")
    return [config for config in everything if config.name in keep]


def run_ablation_study(
    cases_path: str | None = None,
    configs: list[AblationConfig] | None = None,
    progress: ProgressReporter | None = None,
    limit: int | None = None,
    run_slow_path: bool = False,
    slow_path_batch_size: int = 20,
    delay_s: float = 0.0,
    isolate_cases: bool = True,
) -> dict[str, object]:
    """Run baseline plus each ablation and produce a comparison table.

    ``progress`` receives human-readable status messages (per config and per case) so a
    long live run shows what it is doing instead of appearing to hang. ``limit`` caps the
    number of cases each config runs, trading coverage for speed. When
    ``run_slow_path`` is enabled, the queue is drained after each interaction so
    slow-path components receive the same ingestion opportunity in every config.
    """
    if slow_path_batch_size < 1:
        raise ValueError("slow_path_batch_size must be a positive integer")
    if delay_s < 0:
        raise ValueError("delay_s must not be negative")
    resolved_path = cases_path or DEFAULT_CASES_PATH
    all_configs = configs or standard_ablations()
    total = len(all_configs)
    _progress(
        progress,
        f"study start: {total} configs, cases={resolved_path}, limit={limit or 'all'}, "
        f"slow_path={run_slow_path}",
    )
    original_database = current_database_path()
    isolation_base = isolation_base_path(original_database) if isolate_cases else None
    rows: list[AblationRow] = []
    try:
        for index, config in enumerate(all_configs, start=1):
            rows.append(
                _run_config(
                    config,
                    resolved_path,
                    index=index,
                    total=total,
                    progress=progress,
                    limit=limit,
                    run_slow_path=run_slow_path,
                    slow_path_batch_size=slow_path_batch_size,
                    delay_s=delay_s,
                    isolation_base=isolation_base,
                )
            )
    finally:
        if isolate_cases and original_database is not None:
            configure_database(original_database)
            reset_vector_store()
    _progress(progress, f"study complete: {total} configs")
    return {
        "cases_path": resolved_path,
        "run_slow_path": run_slow_path,
        "rows": [_row_to_dict(row) for row in rows],
        "table": render_ablation_table(rows),
    }


def _progress(progress: ProgressReporter | None, message: str) -> None:
    if progress is not None:
        progress(message)


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


def _run_config(
    config: AblationConfig,
    cases_path: str,
    *,
    index: int = 0,
    total: int = 0,
    progress: ProgressReporter | None = None,
    limit: int | None = None,
    run_slow_path: bool = False,
    slow_path_batch_size: int = 20,
    delay_s: float = 0.0,
    isolation_base: Path | None = None,
) -> AblationRow:
    cases = load_evaluation_cases(cases_path)
    if limit is not None:
        cases = cases[:limit]
    disabled_label = ", ".join(sorted(config.disabled)) or "none"
    _progress(progress, f"config {index}/{total} {config.name}: start (disabled: {disabled_label})")
    results: list[dict[str, object]] = []
    with apply_ablation(config) as applied:
        interaction_counter = {"count": 0}
        for case_index, case in enumerate(cases, start=1):
            if isolation_base is not None:
                isolate_case_state(
                    isolation_base,
                    f"{index}-{case_index}",
                    progress,
                    progress_prefix="ablation-case",
                )
            result = _run_case(
                case,
                progress=progress,
                run_slow_path=run_slow_path,
                slow_path_batch_size=slow_path_batch_size,
                delay_s=delay_s,
                interaction_counter=interaction_counter,
            )
            results.append(result)
            outcome = "passed" if result["passed"] else "failed"
            case_id = str(case.get("id", "unnamed"))
            _progress(
                progress,
                f"config {config.name}: case {case_index}/{len(cases)} {case_id}: {outcome}",
            )

    passed = sum(1 for result in results if result["passed"])
    total_cases = len(results)
    rate = round(passed / total_cases, 4) if total_cases else 0.0
    _progress(
        progress, f"config {config.name}: done passed={passed}/{total_cases} pass_rate={rate}"
    )
    return AblationRow(
        name=config.name,
        disabled=sorted(config.disabled),
        applied=sorted(applied),
        total=total_cases,
        passed=passed,
        pass_rate=rate,
        note=_coverage_note(config.disabled, applied),
        results=results,
    )


def _run_case(
    case: dict[str, object],
    *,
    progress: ProgressReporter | None,
    run_slow_path: bool,
    slow_path_batch_size: int,
    delay_s: float,
    interaction_counter: dict[str, int],
) -> dict[str, object]:
    expected = case.get("expect")
    expected_dict = expected if isinstance(expected, dict) else {}
    case_id = str(case.get("id", "unnamed"))
    actual: dict[str, object]
    try:
        actual = run_case_interactions(
            case,
            case_id=case_id,
            session_user="ablation",
            progress=progress,
            delay_s=delay_s,
            interaction_counter=interaction_counter,
            run_slow_path=run_slow_path,
            slow_path_batch_size=slow_path_batch_size,
        )
        error = None
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
    not_applied = sorted(component for component in disabled if component not in applied)
    notes = []
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
