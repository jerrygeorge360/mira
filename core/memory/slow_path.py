"""Shared slow-path worker contract for cross-session memory processing.

Ownership: Jerry.
Related issue: ISSUE-022.
Architecture area: slow path.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol
from uuid import uuid4

from core.db.repositories import (
    claim_pending_batch,
    list_session_items_by_status,
    mark_done,
    mark_failed,
    repository_connection,
)
from core.memory.atomic_fact import extract_atomic_facts, store_atomic_facts
from core.memory.change import apply_contradiction, apply_supersession, detect_memory_change
from core.memory.community import (
    detect_graph_communities,
    store_community_summary,
    summarize_community,
)
from core.memory.foresight import create_foresight, detect_foresight
from core.memory.graph import (
    create_graph_edge,
    create_graph_node,
    extract_entities,
    link_entity_mention,
)
from core.memory.reflection import (
    find_reflections_derived_from,
    invalidate_reflection_if_unsupported,
    should_reflect,
    store_reflection_with_evidence,
    synthesize_reflections,
)
from core.memory.tiers import evaluate_promotion_candidate, promote_to_hot_memory
from core.observability import log_event
from core.session.confirmation import (
    confirm_session_item,
    promote_session_item_to_durable_candidate,
)

QUEUE_STATUSES = ("pending", "processing", "done", "failed", "dead_letter")

WorkerRunRecord = dict[str, object]
OrchestratorResult = dict[str, object]

LOGGER = logging.getLogger(__name__)

CREATED_RECORD_BUCKETS = (
    "session_items",
    "atomic_facts",
    "entities",
    "graph_nodes",
    "graph_edges",
    "working_memory",
    "foresight_records",
    "reflections",
    "community_summaries",
)
DURABLE_SCOPES = frozenset({"project", "cross_session"})

SLOW_PATH_STEP_NAMES = frozenset(
    {
        "embedding_index",
        "atomic_fact_extraction",
        "entity_extraction",
        "graph_update",
        "foresight_detection",
        "contradiction_supersession_detection",
        "reflection_check",
        "tier_update",
        "community_update",
    }
)


@dataclass(frozen=True)
class SlowPathBatch:
    """Payload claimed by the worker and passed to each slow-path step."""

    batch_id: str
    observation_ids: list[str]
    session_id: str | None


@dataclass(frozen=True)
class SlowPathStepResult:
    """Result returned by one slow-path memory-processing step."""

    step_name: str
    succeeded: bool
    created_record_ids: list[str]
    failed_observation_ids: list[str]
    error_message: str | None
    updated_record_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SlowPathSemanticConfig:
    """Cost/safety knobs for semantic slow-path memory steps."""

    enable_foresight: bool = True
    enable_reflection: bool = True
    enable_reflection_invalidation: bool = True
    enable_community_summaries: bool = True
    reflection_min_importance: float = 0.6
    reflection_min_observations: int = 5
    reflection_cooldown_observations: int = 10
    community_refresh_every_observations: int = 50
    community_refresh_every_minutes: int = 30
    max_foresight_records_per_observation: int = 3
    max_reflections_per_run: int = 3
    max_community_summaries_per_run: int = 5


class SlowPathStep(Protocol):
    """Stable protocol implemented by each slow-path memory-processing step."""

    def run(self, batch: SlowPathBatch) -> SlowPathStepResult:
        """Run the step for a claimed slow-path batch."""


REGISTERED_SLOW_PATH_STEPS: list[SlowPathStep] = []


def run_slow_path_steps(
    batch: SlowPathBatch,
    steps: list[SlowPathStep],
) -> list[SlowPathStepResult]:
    """Run slow-path steps sequentially and return their reported results."""
    results: list[SlowPathStepResult] = []
    for step in steps:
        result = step.run(batch)
        validate_step_result(result, batch)
        results.append(result)
    return results


def register_slow_path_step(step: SlowPathStep) -> None:
    """Register a slow-path step for subsequent worker runs."""
    if step not in REGISTERED_SLOW_PATH_STEPS:
        REGISTERED_SLOW_PATH_STEPS.append(step)


def run_slow_path_once(batch_size: int) -> list[WorkerRunRecord]:
    """Claim one queue batch, run registered steps, and update queue statuses."""
    if batch_size < 1:
        raise ValueError("batch_size must be a positive integer")
    queue_records = claim_pending_batch(batch_size)
    if not queue_records:
        return []

    batch = _build_batch(queue_records)
    queue_ids_by_observation_id = {
        str(record["observation_id"]): str(record["id"]) for record in queue_records
    }
    run_records: list[WorkerRunRecord] = []
    failed_observation_ids: set[str] = set()

    try:
        for result in run_slow_path_steps(batch, REGISTERED_SLOW_PATH_STEPS):
            failed_observation_ids.update(result.failed_observation_ids)
            run_record = _result_record(batch, result)
            run_records.append(run_record)
            LOGGER.info("Slow-path step completed: %s", run_record)
    except Exception as error:
        LOGGER.exception("Slow-path batch failed: %s", batch.batch_id)
        error_message = str(error) or error.__class__.__name__
        failed_observation_ids.update(batch.observation_ids)
        run_records.append(
            {
                "batch_id": batch.batch_id,
                "step_name": "worker",
                "succeeded": False,
                "created_record_ids": [],
                "failed_observation_ids": list(batch.observation_ids),
                "error_message": error_message,
            }
        )

    _complete_queue_records(
        queue_ids_by_observation_id,
        failed_observation_ids,
        _failure_message(run_records),
    )
    return run_records


def run_slow_path_loop(
    batch_size: int,
    poll_interval_s: float,
    *,
    max_iterations: int | None = None,
) -> None:
    """Continuously drain the queue through the orchestrator-backed batch path.

    Uses ``run_slow_path_batch`` (the ISSUE-121 orchestrator) -- not the empty
    step registry -- so the production loop performs real memory work.
    """
    if poll_interval_s < 0:
        raise ValueError("poll_interval_s must not be negative")
    iterations = 0
    while True:
        iterations += 1
        results = run_slow_path_batch(batch_size)
        if max_iterations is not None and iterations >= max_iterations:
            return
        if not results:
            time.sleep(poll_interval_s)


def validate_step_result(result: SlowPathStepResult, batch: SlowPathBatch) -> None:
    """Validate that a step result follows the shared worker contract."""
    if result.step_name not in SLOW_PATH_STEP_NAMES:
        raise ValueError(f"Unknown slow-path step: {result.step_name}")
    unknown_failures = sorted(set(result.failed_observation_ids) - set(batch.observation_ids))
    if unknown_failures:
        joined_ids = ", ".join(unknown_failures)
        raise ValueError(f"Step {result.step_name} failed unknown observation(s): {joined_ids}")
    if result.succeeded and result.error_message is not None:
        raise ValueError(f"Successful step {result.step_name} must not include an error")
    if not result.succeeded and not result.failed_observation_ids:
        raise ValueError(f"Failed step {result.step_name} must report failed observations")


async def enrich_observation(observation_id: str) -> None:
    """Synthesize durable memory artifacts from one queued observation."""
    run_slow_path_for_observation(observation_id)


async def run_slow_path(batch_size: int = 20) -> None:
    """Process queued observations through the orchestrator chain."""
    run_slow_path_batch(batch_size)


# --- Automatic slow-path orchestrator chain (ISSUE-121) ---------------------


def run_slow_path_for_observation(
    observation_id: str,
    config: SlowPathSemanticConfig | None = None,
) -> OrchestratorResult:
    """Chain the implemented slow-path memory steps for one observation.

    Confirms session items, promotes durable candidates, extracts atomic facts,
    links entities into the typed graph, applies SUPERSEDED_BY/CONTRADICTS edges,
    and evaluates tier promotion. Each step is idempotent where practical and is
    isolated: a failing step stops the chain, is reported, and leaves the
    observation unprocessed (so the queue item stays retryable) without deleting
    history.
    """
    result = _new_result(observation_id)
    observation = _load_observation(observation_id)
    if observation is None:
        return _fail_result(result, "observation not found")
    if observation.get("processed_at"):
        _add_step(result, "already_processed", succeeded=True, created=[])
        return result

    content = str(observation["content"])
    session_id = observation.get("session_id")
    session_id = str(session_id) if isinstance(session_id, str) else None
    context: dict[str, list[str]] = {"fact_ids": []}
    semantic_config = config or SlowPathSemanticConfig()

    steps: tuple[tuple[str, Callable[[], dict[str, list[str]]]], ...] = (
        ("session_confirmation", lambda: _step_session_confirmation(observation_id, session_id)),
        ("durable_promotion", lambda: _step_durable_promotion(observation_id, session_id)),
        ("atomic_fact_extraction", lambda: _step_atomic_facts(observation_id, content, context)),
        ("graph_update", lambda: _step_entities(observation_id, content)),
        ("contradiction_supersession", lambda: _step_changes(context)),
        (
            "reflection_invalidation",
            lambda: _step_reflection_invalidation(observation_id, semantic_config),
        ),
        ("tier_update", lambda: _step_tiers(context)),
        ("foresight_detection", lambda: _step_foresight(observation_id, content, semantic_config)),
    )
    for step_name, step in steps:
        try:
            created = step()
        except Exception as error:  # noqa: BLE001 - any step failure must be isolated and reported
            message = str(error) or error.__class__.__name__
            LOGGER.exception("Slow-path step %s failed for %s", step_name, observation_id)
            _add_step(result, step_name, succeeded=False, created=[], error_message=message)
            result["succeeded"] = False
            result["error_message"] = message
            return result
        _record_created(result, step_name, created)
        _add_step(result, step_name, succeeded=True, created=_flatten(created))

    _mark_observation_processed(observation_id)
    result["succeeded"] = True
    return result


def run_slow_path_batch(
    batch_size: int,
    config: SlowPathSemanticConfig | None = None,
) -> list[OrchestratorResult]:
    """Claim pending queue items and orchestrate each through the chain."""
    if batch_size < 1:
        raise ValueError("batch_size must be a positive integer")
    queue_records = claim_pending_batch(batch_size)
    results: list[OrchestratorResult] = []
    for record in queue_records:
        observation_id = str(record["observation_id"])
        queue_id = str(record["id"])
        result = run_slow_path_for_observation(observation_id, config=config)
        if result["succeeded"]:
            mark_done(queue_id)
        else:
            mark_failed(queue_id, str(result.get("error_message") or "slow-path step failed"))
        results.append(result)
    return results


# --- background worker runtime (ISSUE-124) ----------------------------------


def run_worker_once(batch_size: int = 20, *, worker_id: str = "slow-path-worker") -> dict[str, int]:
    """Process exactly one batch through the orchestrator and return counts."""
    return run_worker(batch_size=batch_size, once=True, worker_id=worker_id)


def run_worker(
    *,
    batch_size: int = 20,
    poll_interval_s: float = 2.0,
    once: bool = False,
    max_iterations: int | None = None,
    worker_id: str = "slow-path-worker",
    semantic_config: SlowPathSemanticConfig | None = None,
) -> dict[str, int]:
    """Drain the slow-path queue continuously via the orchestrator-backed batch.

    Emits structured worker events, sleeps when the queue is empty, and stops on
    ``--once``, ``max_iterations``, or interruption -- shutting down without
    corrupting queue state. One failed observation never stops the batch: each is
    marked done/failed independently by ``run_slow_path_batch``.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be a positive integer")
    if poll_interval_s < 0:
        raise ValueError("poll_interval_s must not be negative")

    config = semantic_config or SlowPathSemanticConfig()
    log_event(
        "worker_started",
        "slow-path worker started",
        worker_id=worker_id,
        batch_size=batch_size,
        poll_interval_s=poll_interval_s,
    )
    processed = 0
    failed = 0
    iterations = 0
    try:
        while True:
            iterations += 1
            batch_id = uuid4().hex
            started = time.monotonic()
            results = run_slow_path_batch(batch_size, config=config)
            duration_ms = int((time.monotonic() - started) * 1000)

            if not results:
                log_event(
                    "batch_empty", "no pending observations", worker_id=worker_id, batch_id=batch_id
                )
                if once or _reached(max_iterations, iterations):
                    break
                log_event(
                    "worker_sleeping",
                    "sleeping until work is available",
                    worker_id=worker_id,
                    seconds=poll_interval_s,
                )
                time.sleep(poll_interval_s)
                continue

            log_event(
                "batch_claimed",
                "claimed batch",
                worker_id=worker_id,
                batch_id=batch_id,
                count=len(results),
            )
            batch_failed = 0
            for result in results:
                observation_id = str(result["observation_id"])
                if result["succeeded"]:
                    processed += 1
                    log_event(
                        "observation_processing_completed",
                        "observation processed",
                        worker_id=worker_id,
                        batch_id=batch_id,
                        observation_id=observation_id,
                        status="done",
                    )
                else:
                    failed += 1
                    batch_failed += 1
                    log_event(
                        "observation_processing_failed",
                        "observation processing failed",
                        level=logging.WARNING,
                        worker_id=worker_id,
                        batch_id=batch_id,
                        observation_id=observation_id,
                        status="failed",
                        error_message=result.get("error_message"),
                    )
            log_event(
                "batch_completed",
                "batch completed",
                worker_id=worker_id,
                batch_id=batch_id,
                processed=len(results) - batch_failed,
                failed=batch_failed,
                duration_ms=duration_ms,
            )
            processed_observation_ids = [
                str(result["observation_id"]) for result in results if result["succeeded"]
            ]
            semantic_results = [
                *maybe_run_reflection_pass(processed_observation_ids, config),
                *maybe_run_community_refresh(processed, config),
            ]
            for semantic_result in semantic_results:
                if semantic_result.created_record_ids or semantic_result.updated_record_ids:
                    log_event(
                        "semantic_step_completed",
                        "semantic slow-path step completed",
                        worker_id=worker_id,
                        step_name=semantic_result.step_name,
                        created_record_ids=semantic_result.created_record_ids,
                        updated_record_ids=semantic_result.updated_record_ids,
                        succeeded=semantic_result.succeeded,
                    )
            if once or _reached(max_iterations, iterations):
                break
    except KeyboardInterrupt:
        log_event("worker_stopped", "worker interrupted", worker_id=worker_id, status="interrupted")
        return {"processed": processed, "failed": failed, "iterations": iterations}

    log_event(
        "worker_stopped",
        "worker stopped",
        worker_id=worker_id,
        processed=processed,
        failed=failed,
        iterations=iterations,
    )
    return {"processed": processed, "failed": failed, "iterations": iterations}


def get_slow_path_queue_status() -> dict[str, int]:
    """Return queue health: a count per slow-path queue status."""
    counts = dict.fromkeys(QUEUE_STATUSES, 0)
    with repository_connection() as connection:
        rows = connection.execute(
            "SELECT status, COUNT(*) AS count FROM slow_path_queue GROUP BY status"
        ).fetchall()
    for row in rows:
        counts[str(row["status"])] = int(row["count"])
    return counts


def _reached(max_iterations: int | None, iterations: int) -> bool:
    return max_iterations is not None and iterations >= max_iterations


def _step_session_confirmation(observation_id: str, session_id: str | None) -> dict[str, list[str]]:
    if session_id is None:
        return {}
    confirmed: list[str] = []
    for item in list_session_items_by_status(session_id, "provisional"):
        if observation_id in _json_string_list(item.get("source_observations_json")):
            confirm_session_item(str(item["id"]), "slow_path")
            confirmed.append(str(item["id"]))
    return {"session_items": confirmed}


def _step_durable_promotion(observation_id: str, session_id: str | None) -> dict[str, list[str]]:
    if session_id is None:
        return {}
    promoted: list[str] = []
    for item in list_session_items_by_status(session_id, "confirmed"):
        item_id = str(item["id"])
        if observation_id not in _json_string_list(item.get("source_observations_json")):
            continue
        if str(item.get("scope")) not in DURABLE_SCOPES:
            continue
        if _durable_candidate_exists(item_id):
            continue
        promoted.append(promote_session_item_to_durable_candidate(item_id))
    return {"working_memory": promoted}


def _step_atomic_facts(
    observation_id: str,
    content: str,
    context: dict[str, list[str]],
) -> dict[str, list[str]]:
    existing = _fact_ids_for_observation(observation_id)
    if existing:
        context["fact_ids"] = existing
        return {}
    fact_ids = store_atomic_facts(extract_atomic_facts(observation_id, content))
    context["fact_ids"] = fact_ids
    return {"atomic_facts": fact_ids}


def _step_entities(observation_id: str, content: str) -> dict[str, list[str]]:
    entities = extract_entities(content)
    if not entities:
        return {}
    observation_node = _ensure_observation_node(observation_id, content)
    entity_ids: list[str] = []
    node_ids: list[str] = [observation_node]
    edge_ids: list[str] = []
    for entity in entities:
        entity_id = str(entity.get("id", ""))
        if not entity_id:
            continue
        entity_ids.append(entity_id)
        entity_node = _ensure_entity_node(entity_id, observation_id)
        node_ids.append(entity_node)
        if not _relation_edge_exists_by_node(observation_node, entity_node, "MENTIONS"):
            edge_ids.append(
                create_graph_edge(observation_node, entity_node, "MENTIONS", 1.0, [observation_id])
            )
    return {"entities": entity_ids, "graph_nodes": node_ids, "graph_edges": edge_ids}


def _step_changes(context: dict[str, list[str]]) -> dict[str, list[str]]:
    edge_ids: list[str] = []
    for fact_id in context.get("fact_ids", []):
        fact = _fetch_fact(fact_id)
        if fact is None or str(fact.get("status")) != "active":
            continue
        priors = _active_prior_fact_ids(fact)
        for change in detect_memory_change(fact_id, priors):
            relation = str(change["relation"])
            old_id = str(change["source_id"])
            new_id = str(change["target_id"])
            evidence = _json_string_list(change.get("evidence")) or [fact_id]
            if _relation_edge_exists_by_fact(old_id, new_id, relation):
                continue
            if relation == "SUPERSEDED_BY":
                edge_ids.append(apply_supersession(old_id, new_id, evidence))
            else:
                edge_ids.append(apply_contradiction(old_id, new_id, evidence))
    return {"graph_edges": edge_ids}


def _step_tiers(context: dict[str, list[str]]) -> dict[str, list[str]]:
    promoted: list[str] = []
    for fact_id in context.get("fact_ids", []):
        fact = _fetch_fact(fact_id)
        if fact is None or str(fact.get("status")) != "active":
            continue
        candidate = evaluate_promotion_candidate("atomic_facts", fact_id)
        if candidate.get("eligible"):
            promoted.append(promote_to_hot_memory(candidate))
    return {"working_memory": promoted}


def run_foresight_step_for_observation(
    observation_id: str,
    config: SlowPathSemanticConfig | None = None,
) -> SlowPathStepResult:
    """Run the per-observation foresight step with structured reporting."""
    semantic_config = config or SlowPathSemanticConfig()
    observation = _load_observation(observation_id)
    if observation is None:
        return _semantic_result(
            "foresight_detection",
            succeeded=False,
            failed_observation_ids=[observation_id],
            error_message="observation not found",
        )
    try:
        created = _step_foresight(
            observation_id,
            str(observation["content"]),
            semantic_config,
        ).get("foresight_records", [])
    except Exception as error:  # noqa: BLE001 - semantic failures should be reported, not hidden
        return _semantic_result(
            "foresight_detection",
            succeeded=False,
            failed_observation_ids=[observation_id],
            error_message=str(error) or error.__class__.__name__,
        )
    return _semantic_result("foresight_detection", created_record_ids=created)


def maybe_run_reflection_pass(
    observation_ids: list[str],
    config: SlowPathSemanticConfig | None = None,
) -> list[SlowPathStepResult]:
    """Run gated reflection synthesis when enough important evidence has accumulated."""
    semantic_config = config or SlowPathSemanticConfig()
    if not semantic_config.enable_reflection:
        return [_semantic_result("reflection_check")]
    evidence_ids = _recent_unreflected_observation_ids(observation_ids, semantic_config)
    importance = {
        observation_id: _importance_score(str(row["content"]))
        for observation_id, row in _observations_by_id(evidence_ids).items()
    }
    if len(evidence_ids) < semantic_config.reflection_min_observations:
        return [_semantic_result("reflection_check")]
    if not _passes_reflection_gate(evidence_ids, importance, semantic_config):
        return [_semantic_result("reflection_check")]

    created: list[str] = []
    try:
        for reflection in synthesize_reflections(evidence_ids)[
            : semantic_config.max_reflections_per_run
        ]:
            content = str(reflection.get("content", "")).strip()
            evidence = _json_string_list(reflection.get("evidence_ids")) or evidence_ids
            if not content or _active_reflection_exists(content):
                continue
            created.append(store_reflection_with_evidence(reflection, evidence))
    except Exception as error:  # noqa: BLE001 - reflection failures should not break factual memory
        return [
            _semantic_result(
                "reflection_check",
                succeeded=False,
                failed_observation_ids=list(evidence_ids),
                error_message=str(error) or error.__class__.__name__,
            )
        ]
    return [_semantic_result("reflection_check", created_record_ids=created)]


def maybe_run_community_refresh(
    processed_observations: int,
    config: SlowPathSemanticConfig | None = None,
) -> list[SlowPathStepResult]:
    """Run periodic graph community detection and summary refresh when due."""
    semantic_config = config or SlowPathSemanticConfig()
    if not semantic_config.enable_community_summaries:
        return [_semantic_result("community_update")]
    if processed_observations < semantic_config.community_refresh_every_observations:
        return [_semantic_result("community_update")]

    created: list[str] = []
    try:
        communities = detect_graph_communities()
        for community in communities[: semantic_config.max_community_summaries_per_run]:
            community_id = str(community.get("community_id", ""))
            if not community_id or _community_summary_exists(community_id):
                continue
            member_node_ids = _json_string_list(community.get("member_node_ids"))
            if not member_node_ids:
                continue
            summary = summarize_community(community_id, member_node_ids)
            created.append(store_community_summary(summary))
    except Exception as error:  # noqa: BLE001 - community work is periodic and recoverable
        return [
            _semantic_result(
                "community_update",
                succeeded=False,
                error_message=str(error) or error.__class__.__name__,
            )
        ]
    return [_semantic_result("community_update", created_record_ids=created)]


def _step_foresight(
    observation_id: str,
    content: str,
    config: SlowPathSemanticConfig,
) -> dict[str, list[str]]:
    if not config.enable_foresight:
        return {}
    ambient_context: dict[str, object] = {"current_time": _now()}
    created: list[str] = []
    records = detect_foresight(observation_id, content, ambient_context)
    for record in records[: config.max_foresight_records_per_observation]:
        foresight_content = str(record.get("content", "")).strip()
        if not foresight_content or _foresight_exists(observation_id, foresight_content):
            continue
        created.append(create_foresight(record))
    return {"foresight_records": created}


def _step_reflection_invalidation(
    observation_id: str,
    config: SlowPathSemanticConfig,
) -> dict[str, list[str]]:
    if not config.enable_reflection_invalidation:
        return {}
    updated: list[str] = []
    for reflection_id in find_reflections_derived_from(observation_id):
        before = _reflection_status(reflection_id)
        invalidate_reflection_if_unsupported(reflection_id)
        after = _reflection_status(reflection_id)
        if after != before:
            updated.append(reflection_id)
    return {"reflections": updated}


def _new_result(observation_id: str) -> OrchestratorResult:
    return {
        "observation_id": observation_id,
        "succeeded": False,
        "steps": [],
        "created_record_ids": {bucket: [] for bucket in CREATED_RECORD_BUCKETS},
        "error_message": None,
    }


def _fail_result(result: OrchestratorResult, message: str) -> OrchestratorResult:
    _add_step(result, "load_observation", succeeded=False, created=[], error_message=message)
    result["error_message"] = message
    return result


def _add_step(
    result: OrchestratorResult,
    step_name: str,
    *,
    succeeded: bool,
    created: list[str],
    error_message: str | None = None,
) -> None:
    steps = result["steps"]
    if isinstance(steps, list):
        steps.append(
            {
                "step_name": step_name,
                "succeeded": succeeded,
                "created_record_ids": list(created),
                "updated_record_ids": [],
                "failed_record_ids": [],
                "error_message": error_message,
            }
        )


def _record_created(
    result: OrchestratorResult,
    step_name: str,
    created: dict[str, list[str]],
) -> None:
    del step_name
    buckets = result["created_record_ids"]
    if isinstance(buckets, dict):
        for bucket, ids in created.items():
            buckets.setdefault(bucket, [])
            buckets[bucket].extend(ids)


def _flatten(created: dict[str, list[str]]) -> list[str]:
    return [record_id for ids in created.values() for record_id in ids]


def _load_observation(observation_id: str) -> dict[str, object] | None:
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT * FROM observations WHERE id = ?",
            (observation_id,),
        ).fetchone()
    return None if row is None else dict(row)


def _mark_observation_processed(observation_id: str) -> None:
    with repository_connection() as connection:
        connection.execute(
            "UPDATE observations SET processed_at = ? WHERE id = ?",
            (_now(), observation_id),
        )


def _fact_ids_for_observation(observation_id: str) -> list[str]:
    with repository_connection() as connection:
        rows = connection.execute(
            "SELECT id FROM atomic_facts WHERE source_observation_id = ? ORDER BY created_at ASC",
            (observation_id,),
        ).fetchall()
    return [str(row["id"]) for row in rows]


def _fetch_fact(fact_id: str) -> dict[str, object] | None:
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT * FROM atomic_facts WHERE id = ?",
            (fact_id,),
        ).fetchone()
    return None if row is None else dict(row)


def _active_prior_fact_ids(fact: dict[str, object]) -> list[str]:
    with repository_connection() as connection:
        rows = connection.execute(
            """
            SELECT id FROM atomic_facts
            WHERE subject = ? AND predicate = ? AND status = 'active' AND id != ?
            ORDER BY created_at ASC
            """,
            (str(fact["subject"]), str(fact["predicate"]), str(fact["id"])),
        ).fetchall()
    return [str(row["id"]) for row in rows]


def _durable_candidate_exists(session_item_id: str) -> bool:
    with repository_connection() as connection:
        row = connection.execute(
            """
            SELECT 1 FROM working_memory
            WHERE source_record_type = 'session_working_set' AND source_record_id = ?
            LIMIT 1
            """,
            (session_item_id,),
        ).fetchone()
    return row is not None


def _ensure_observation_node(observation_id: str, content: str) -> str:
    existing = _existing_node_id("observation", "observations", observation_id)
    if existing is not None:
        return existing
    return create_graph_node(
        node_type="observation",
        label=_label(content) or observation_id,
        source_table="observations",
        source_id=observation_id,
    )


def _ensure_entity_node(entity_id: str, observation_id: str) -> str:
    existing = _existing_node_id("entity", "entities", entity_id)
    if existing is not None:
        return existing
    return link_entity_mention(entity_id, observation_id)


def _existing_node_id(node_type: str, source_table: str, source_id: str) -> str | None:
    with repository_connection() as connection:
        row = connection.execute(
            """
            SELECT id FROM graph_nodes
            WHERE node_type = ? AND source_table = ? AND source_id = ?
            ORDER BY created_at ASC LIMIT 1
            """,
            (node_type, source_table, source_id),
        ).fetchone()
    return None if row is None else str(row["id"])


def _relation_edge_exists_by_node(source_node: str, target_node: str, edge_type: str) -> bool:
    with repository_connection() as connection:
        row = connection.execute(
            """
            SELECT 1 FROM graph_edges
            WHERE source_node_id = ? AND target_node_id = ? AND edge_type = ?
              AND invalidated_at IS NULL
            LIMIT 1
            """,
            (source_node, target_node, edge_type),
        ).fetchone()
    return row is not None


def _relation_edge_exists_by_fact(fact_a: str, fact_b: str, edge_type: str) -> bool:
    with repository_connection() as connection:
        row = connection.execute(
            """
            SELECT 1 FROM graph_edges AS e
            JOIN graph_nodes AS s ON s.id = e.source_node_id
            JOIN graph_nodes AS t ON t.id = e.target_node_id
            WHERE e.edge_type = ? AND e.invalidated_at IS NULL
              AND s.source_table = 'atomic_facts' AND t.source_table = 'atomic_facts'
              AND ((s.source_id = ? AND t.source_id = ?) OR (s.source_id = ? AND t.source_id = ?))
            LIMIT 1
            """,
            (edge_type, fact_a, fact_b, fact_b, fact_a),
        ).fetchone()
    return row is not None


def _json_string_list(value: object) -> list[str]:
    if isinstance(value, str):
        import json

        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _label(content: str) -> str:
    return " ".join(content.split())[:120].strip()


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()  # noqa: UP017


def _build_batch(queue_records: list[WorkerRunRecord]) -> SlowPathBatch:
    observation_ids = [str(record["observation_id"]) for record in queue_records]
    session_ids = _session_ids_for_observations(observation_ids)
    session_id = session_ids[0] if len(session_ids) == 1 else None
    return SlowPathBatch(
        batch_id=f"batch_{uuid4().hex}",
        observation_ids=observation_ids,
        session_id=session_id,
    )


def _session_ids_for_observations(observation_ids: list[str]) -> list[str]:
    if not observation_ids:
        return []
    placeholders = ", ".join("?" for _ in observation_ids)
    with repository_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT DISTINCT session_id
            FROM observations
            WHERE id IN ({placeholders})
            ORDER BY session_id ASC
            """,  # nosec B608
            tuple(observation_ids),
        ).fetchall()
    return [str(row["session_id"]) for row in rows]


def _result_record(batch: SlowPathBatch, result: SlowPathStepResult) -> WorkerRunRecord:
    return {
        "batch_id": batch.batch_id,
        "step_name": result.step_name,
        "succeeded": result.succeeded,
        "created_record_ids": list(result.created_record_ids),
        "updated_record_ids": list(result.updated_record_ids),
        "failed_observation_ids": list(result.failed_observation_ids),
        "error_message": result.error_message,
    }


def _complete_queue_records(
    queue_ids_by_observation_id: dict[str, str],
    failed_observation_ids: set[str],
    error_message: str | None,
) -> None:
    for observation_id, queue_id in queue_ids_by_observation_id.items():
        if observation_id in failed_observation_ids:
            mark_failed(queue_id, error_message or "slow-path step failed")
        else:
            mark_done(queue_id)


def _failure_message(run_records: list[WorkerRunRecord]) -> str | None:
    for record in run_records:
        if not bool(record["succeeded"]):
            error = record.get("error_message")
            if isinstance(error, str) and error:
                return error
    return None


def _semantic_result(
    step_name: str,
    *,
    succeeded: bool = True,
    created_record_ids: list[str] | None = None,
    updated_record_ids: list[str] | None = None,
    failed_observation_ids: list[str] | None = None,
    error_message: str | None = None,
) -> SlowPathStepResult:
    return SlowPathStepResult(
        step_name=step_name,
        succeeded=succeeded,
        created_record_ids=created_record_ids or [],
        updated_record_ids=updated_record_ids or [],
        failed_observation_ids=failed_observation_ids or [],
        error_message=error_message,
    )


def _foresight_exists(observation_id: str, content: str) -> bool:
    with repository_connection() as connection:
        row = connection.execute(
            """
            SELECT 1 FROM foresight_records
            WHERE source_observation_id = ? AND lower(content) = lower(?)
            LIMIT 1
            """,
            (observation_id, content),
        ).fetchone()
    return row is not None


def _active_reflection_exists(content: str) -> bool:
    with repository_connection() as connection:
        row = connection.execute(
            """
            SELECT 1 FROM reflections
            WHERE status = 'active' AND lower(content) = lower(?)
            LIMIT 1
            """,
            (content,),
        ).fetchone()
    return row is not None


def _community_summary_exists(community_id: str) -> bool:
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT 1 FROM community_summaries WHERE community_id = ? LIMIT 1",
            (community_id,),
        ).fetchone()
    return row is not None


def _recent_unreflected_observation_ids(
    observation_ids: list[str],
    config: SlowPathSemanticConfig,
) -> list[str]:
    unique_ids = list(dict.fromkeys(observation_ids))
    if not unique_ids:
        return []
    unreflected: list[str] = []
    for observation_id in unique_ids:
        if find_reflections_derived_from(observation_id):
            continue
        unreflected.append(observation_id)
    if not unreflected:
        return []
    limit = max(config.reflection_min_observations, config.reflection_cooldown_observations)
    return unreflected[-limit:]


def _observations_by_id(observation_ids: list[str]) -> dict[str, dict[str, object]]:
    observations: dict[str, dict[str, object]] = {}
    for observation_id in observation_ids:
        observation = _load_observation(observation_id)
        if observation is not None:
            observations[observation_id] = observation
    return observations


def _passes_reflection_gate(
    observation_ids: list[str],
    importance_scores: dict[str, float],
    config: SlowPathSemanticConfig,
) -> bool:
    if not observation_ids:
        return False
    important = [
        observation_id
        for observation_id in observation_ids
        if importance_scores.get(observation_id, 0.0) >= config.reflection_min_importance
    ]
    if not important:
        return False
    # should_reflect (ISSUE-028) provides the count/importance threshold logic;
    # the gate above only requires at least one sufficiently important observation.
    return should_reflect(observation_ids, importance_scores)


def _importance_score(content: str) -> float:
    normalized = content.casefold()
    markers = (
        "must",
        "need",
        "important",
        "deadline",
        "official",
        "benchmark",
        "correction",
        "changed",
        "now",
        "not ",
        "remember",
        "decided",
    )
    hits = sum(1 for marker in markers if marker in normalized)
    return min(1.0, 0.35 + hits * 0.18)


def _reflection_status(reflection_id: str) -> str:
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT status FROM reflections WHERE id = ?",
            (reflection_id,),
        ).fetchone()
    if row is None:
        return ""
    return str(row["status"])
