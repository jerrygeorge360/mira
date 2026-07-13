"""Shared slow-path worker contract for cross-session memory processing.

Ownership: Jerry.
Related issue: ISSUE-022.
Architecture area: slow path.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol
from uuid import uuid4

from core.db import chroma
from core.db.repositories import (
    canonical_form_for_id,
    claim_pending_batch,
    create_atomic_fact,
    list_session_items_by_status,
    mark_done,
    mark_failed,
    mark_slow_path_step_completed,
    mark_slow_path_step_failed,
    mark_slow_path_step_started,
    quarantine_queue_job,
    repository_connection,
    require_active_workspace,
    resolve_canonical_form,
    slow_path_step_completed,
    workspace_id_for_observation,
)
from core.db.schema import LEGACY_WORKSPACE_ID
from core.llm.embeddings import embed_text
from core.llm.prompts import render_prompt
from core.llm.qwen import LLMClientError, call_qwen_json
from core.memory.atomic_fact import detect_transitions, extract_atomic_facts, store_atomic_facts
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

QUEUE_STATUSES = ("pending", "processing", "done", "failed", "dead_letter", "quarantined")

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

# Embedding-similarity fallback pairing (see _similar_prior_fact_ids). Threshold tuned so
# predicate variants like "prefers" vs "prefers_programming_language" match while unrelated
# relations under the same subject do not.
_SIMILARITY_THRESHOLD = 0.72
_SIMILARITY_CANDIDATE_LIMIT = 25

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
    # A single durable-trait marker scores 0.53; the gate sits just below so one clearly
    # self/user-descriptive observation is enough to qualify a reflection pass.
    reflection_min_importance: float = 0.5
    reflection_min_observations: int = 5
    reflection_cooldown_observations: int = 10
    # Cumulative observations (across batches) before the graph community job reruns.
    # Low default so interactive sessions and the eval actually exercise Deep Mode;
    # raise it for large-scale deployments to trade freshness for cost.
    community_refresh_every_observations: int = 8
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
    workspace_id = workspace_id_for_observation(observation_id)

    content = str(observation["content"])
    session_id = observation.get("session_id")
    session_id = str(session_id) if isinstance(session_id, str) else None
    context: dict[str, list[str]] = {"fact_ids": []}
    semantic_config = config or SlowPathSemanticConfig()

    steps: tuple[tuple[str, Callable[[], dict[str, list[str]]]], ...] = (
        ("session_confirmation", lambda: _step_session_confirmation(observation_id, session_id)),
        ("durable_promotion", lambda: _step_durable_promotion(observation_id, session_id)),
        (
            "embedding_index",
            lambda: _step_embedding_index(observation_id, content, observation, workspace_id),
        ),
        ("atomic_fact_extraction", lambda: _step_atomic_facts(observation_id, content, context)),
        ("graph_update", lambda: _step_entities(observation_id, content, workspace_id)),
        ("contradiction_supersession", lambda: _step_changes(context, observation_id, content)),
        (
            "reflection_invalidation",
            lambda: _step_reflection_invalidation(observation_id, context, semantic_config),
        ),
        ("tier_update", lambda: _step_tiers(context)),
        ("foresight_detection", lambda: _step_foresight(observation_id, content, semantic_config)),
    )
    for step_name, step in steps:
        if slow_path_step_completed(workspace_id, observation_id, step_name):
            _add_step(result, step_name, succeeded=True, created=[])
            continue
        mark_slow_path_step_started(workspace_id, observation_id, step_name)
        try:
            created = step()
        except Exception as error:  # noqa: BLE001 - any step failure must be isolated and reported
            message = str(error) or error.__class__.__name__
            LOGGER.exception("Slow-path step %s failed for %s", step_name, observation_id)
            mark_slow_path_step_failed(workspace_id, observation_id, step_name, message)
            _add_step(result, step_name, succeeded=False, created=[], error_message=message)
            result["succeeded"] = False
            result["error_message"] = message
            return result
        mark_slow_path_step_completed(workspace_id, observation_id, step_name)
        _record_created(result, step_name, created)
        _add_step(result, step_name, succeeded=True, created=_flatten(created))

    _mark_observation_processed(observation_id)
    result["succeeded"] = True
    return result


def run_slow_path_batch(
    batch_size: int,
    config: SlowPathSemanticConfig | None = None,
    *,
    workspace_id: str | None = None,
) -> list[OrchestratorResult]:
    """Claim pending queue items and orchestrate each through the chain."""
    if batch_size < 1:
        raise ValueError("batch_size must be a positive integer")
    queue_records = (
        claim_pending_batch(batch_size)
        if workspace_id is None
        else claim_pending_batch(batch_size, workspace_id=workspace_id)
    )
    results: list[OrchestratorResult] = []
    workspace_ids: set[str] = set()
    for record in queue_records:
        observation_id = str(record["observation_id"])
        queue_id = str(record["id"])
        try:
            workspace_ids.add(_validate_queue_workspace(record))
        except ValueError as error:
            message = str(error) or "queue ownership validation failed"
            quarantine_queue_job(queue_id, message)
            results.append(_fail_result(_new_result(observation_id), message))
            continue
        result = run_slow_path_for_observation(observation_id, config=config)
        if result["succeeded"]:
            mark_done(queue_id)
        else:
            mark_failed(queue_id, str(result.get("error_message") or "slow-path step failed"))
        results.append(result)
    for workspace_id in sorted(workspace_ids):
        run_semantic_passes(config, workspace_id=workspace_id)
    return results


def run_semantic_passes(
    config: SlowPathSemanticConfig | None = None,
    *,
    workspace_id: str = LEGACY_WORKSPACE_ID,
) -> list[SlowPathStepResult]:
    """Run the batch-level consolidation passes: reflection and community refresh.

    These accumulate evidence across batches and look across observations, so they
    belong to any batch drain (worker, eval harness, or scripts), not only the
    long-running worker loop. Both are internally gated on cumulative store state and
    no-op until enough evidence exists.
    """
    semantic_results = [
        *maybe_run_reflection_pass(config, workspace_id=workspace_id),
        *maybe_run_community_refresh(config, workspace_id=workspace_id),
    ]
    for semantic_result in semantic_results:
        if semantic_result.created_record_ids or semantic_result.updated_record_ids:
            log_event(
                "semantic_step_completed",
                "semantic slow-path step completed",
                step_name=semantic_result.step_name,
                created_record_ids=semantic_result.created_record_ids,
                updated_record_ids=semantic_result.updated_record_ids,
                succeeded=semantic_result.succeeded,
            )
    return semantic_results


def _validate_queue_workspace(record: dict[str, object]) -> str:
    """Cross-check queue, observation, and session ownership before processing."""
    queue_workspace = str(record.get("workspace_id") or "")
    observation_id = str(record.get("observation_id") or "")
    with repository_connection() as connection:
        row = connection.execute(
            """
            SELECT observations.workspace_id AS observation_workspace,
                   sessions.workspace_id AS session_workspace
            FROM observations
            JOIN sessions ON sessions.id = observations.session_id
            WHERE observations.id = ?
            """,
            (observation_id,),
        ).fetchone()
    if row is None:
        raise ValueError("queued observation not found")
    if not queue_workspace or not (
        queue_workspace == str(row["observation_workspace"]) == str(row["session_workspace"])
    ):
        raise ValueError("queue, observation, and session workspace mismatch")
    require_active_workspace(queue_workspace)
    return queue_workspace


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
            results = (
                run_slow_path_batch(batch_size, config=config)
                if semantic_config is not None
                else run_slow_path_batch(batch_size)
            )
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
            # Reflection and community refresh run inside run_slow_path_batch so every
            # batch drain (worker, eval, scripts) exercises them, not only this worker.
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


def get_slow_path_queue_status(workspace_id: str | None = None) -> dict[str, int]:
    """Return queue health: a count per slow-path queue status."""
    counts = dict.fromkeys(QUEUE_STATUSES, 0)
    with repository_connection() as connection:
        if workspace_id is None:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM slow_path_queue GROUP BY status"
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM slow_path_queue "
                "WHERE workspace_id = ? GROUP BY status",
                (workspace_id,),
            ).fetchall()
    for row in rows:
        counts[str(row["status"])] = int(row["count"])
    return counts


def get_slow_path_health(
    limit: int = 10, *, workspace_id: str = LEGACY_WORKSPACE_ID
) -> dict[str, object]:
    """Return queue, processing, and durable artifact health for inspection."""
    if limit < 1:
        raise ValueError("limit must be a positive integer")
    with repository_connection() as connection:
        unprocessed = connection.execute(
            "SELECT COUNT(*) AS count FROM observations "
            "WHERE workspace_id = ? AND processed_at IS NULL",
            (workspace_id,),
        ).fetchone()
        artifacts = {
            table: int(
                connection.execute(
                    f"SELECT COUNT(*) AS count FROM {table} WHERE workspace_id = ?",  # nosec B608
                    (workspace_id,),
                ).fetchone()["count"]
            )
            for table in (
                "atomic_facts",
                "entities",
                "graph_nodes",
                "graph_edges",
                "working_memory",
                "foresight_records",
                "reflections",
                "community_summaries",
            )
        }
        failed_rows = connection.execute(
            """
            SELECT id, observation_id, status, attempt_count, last_error, updated_at
            FROM slow_path_queue
            WHERE workspace_id = ? AND status IN ('failed', 'dead_letter', 'quarantined')
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (workspace_id, limit),
        ).fetchall()
    return {
        "queue": get_slow_path_queue_status(workspace_id),
        "unprocessed_observations": 0 if unprocessed is None else int(unprocessed["count"]),
        "artifacts": artifacts,
        "recent_failures": [dict(row) for row in failed_rows],
    }


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


def _step_embedding_index(
    observation_id: str,
    content: str,
    observation: dict[str, object],
    workspace_id: str,
) -> dict[str, list[str]]:
    chroma.add_embedding(
        "observations",
        "observations",
        observation_id,
        embed_text(content),
        metadata={
            "index_text_version": chroma.INDEX_TEXT_VERSION,
            "role": str(observation.get("role", "")),
            "source": str(observation.get("source", "")),
        },
        workspace_id=workspace_id,
    )
    return {"observations": [observation_id]}


_AGENT_SELF_SUBJECTS = frozenset({"i", "me", "my", "myself", "assistant", "agent", "mira", "ai"})


def _agent_self_facts(facts: list[dict[str, object]]) -> list[dict[str, object]]:
    """Keep only facts a non-user turn asserts about itself, attributed to the assistant.

    Pronoun attribution is speaker-relative: in an assistant turn "I/me/my" is the
    assistant and "you" is the user, but the shared canonical registry assumes the user
    is speaking. So we resolve self-reference here and keep only the agent's own
    commitments/self-knowledge, re-attributing the subject to "assistant". Everything
    else from an assistant turn -- echoes of the user's claims ("You prefer Rust") and
    third-party/world assertions -- is dropped so the agent cannot mint user facts or
    confirm its own output.
    """
    kept: list[dict[str, object]] = []
    for fact in facts:
        tokens = str(fact.get("subject", "")).casefold().replace("_", " ").split()
        if len(tokens) > 1 and tokens[0] in {"the", "a", "an"}:
            tokens = tokens[1:]
        if " ".join(tokens) in _AGENT_SELF_SUBJECTS:
            attributed = dict(fact)
            attributed["subject"] = "assistant"
            kept.append(attributed)
    return kept


def _step_atomic_facts(
    observation_id: str,
    content: str,
    context: dict[str, list[str]],
) -> dict[str, list[str]]:
    existing = _fact_ids_for_observation(observation_id)
    if existing:
        context["fact_ids"] = existing
        return {}
    facts = extract_atomic_facts(observation_id, content)
    if _observation_role(observation_id) != "user":
        # Assistant/system turns contribute only what the agent says about itself.
        facts = _agent_self_facts(facts)
    fact_ids = store_atomic_facts(facts)
    context["fact_ids"] = fact_ids
    return {"atomic_facts": fact_ids}


def _step_entities(observation_id: str, content: str, workspace_id: str) -> dict[str, list[str]]:
    try:
        entities = extract_entities(content, workspace_id=workspace_id)
    except TypeError as error:
        if "workspace_id" not in str(error):
            raise
        entities = extract_entities(content)
    if not entities:
        return {}
    observation_node = _ensure_observation_node(observation_id, content, workspace_id)
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


_ENTITY_GRAPH_CANDIDATE_LIMIT = 25


def _apply_changes(
    changes: list[dict[str, object]],
    transition_edge_ids: list[str],
    general_edge_ids: list[str],
    recheck_observations: set[str],
) -> int:
    """Apply detected memory changes as edges; return supersessions suppressed by a transition.

    A general SUPERSEDED_BY is skipped when an explicit "from X to Y" transition in the
    same observation already recorded the authoritative edge, so one transition yields
    one edge. Contradictions are always applied (they never duplicate a transition). The
    prior fact's source observation is recorded in ``recheck_observations`` so any
    reflection derived from it is re-evaluated for staleness (its evidence just changed).
    """
    suppressed = 0
    for change in changes:
        relation = str(change["relation"])
        old_id = str(change["source_id"])
        new_id = str(change["target_id"])
        # Evidence must be real observation ids; skip rather than fabricate one.
        evidence = _json_string_list(change.get("evidence"))
        if not evidence:
            continue
        if _relation_edge_exists_by_fact(old_id, new_id, relation):
            continue
        if relation == "SUPERSEDED_BY":
            if transition_edge_ids:
                suppressed += 1
                continue
            general_edge_ids.append(apply_supersession(old_id, new_id, evidence))
        else:
            general_edge_ids.append(apply_contradiction(old_id, new_id, evidence))
        old_fact = _fetch_fact(old_id)
        old_source = _optional_str(old_fact.get("source_observation_id")) if old_fact else None
        if old_source:
            recheck_observations.add(old_source)
    return suppressed


_LLM_CHANGE_CANDIDATE_SCAN = 25
_LLM_CHANGE_SHORTLIST_LIMIT = 5
_LLM_CHANGE_SHORTLIST_THRESHOLD = 0.5
_LLM_CHANGE_CONFIDENCE_GATE = 0.5


def _shortlist_candidate_facts(fact: dict[str, object]) -> list[dict[str, object]]:
    """Embedding-shortlist recent active facts for LLM change verification (high recall).

    Recent active facts ranked by embedding similarity to the new fact, excluding this
    fact and the *exact* canonical matches (same canonical subject AND predicate) that the
    deterministic fast path already classifies. Everything else -- fragmented subjects or
    predicates the fast path misses -- is a candidate for the LLM to judge, capped to a
    small top-k so at most one LLM call runs per fact.
    """
    fact_id = str(fact["id"])
    subject_canonical = _optional_str(fact.get("canonical_subject_id"))
    predicate_canonical = _optional_str(fact.get("canonical_predicate_id"))
    new_text = _fact_text(fact)
    if not new_text:
        return []
    with repository_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, subject, predicate, object, canonical_subject_id,
                   canonical_predicate_id, source_observation_id
            FROM atomic_facts
            WHERE status = 'active' AND id != ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (fact_id, _LLM_CHANGE_CANDIDATE_SCAN),
        ).fetchall()
    target = embed_text(new_text)
    scored: list[tuple[float, dict[str, object]]] = []
    for row in rows:
        exact_match = (
            subject_canonical
            and predicate_canonical
            and _optional_str(row["canonical_subject_id"]) == subject_canonical
            and _optional_str(row["canonical_predicate_id"]) == predicate_canonical
        )
        if exact_match:
            continue
        similarity = _cosine_similarity(target, embed_text(_fact_text(dict(row))))
        if similarity >= _LLM_CHANGE_SHORTLIST_THRESHOLD:
            scored.append((similarity, dict(row)))
    scored.sort(key=lambda pair: -pair[0])
    return [row for _score, row in scored[:_LLM_CHANGE_SHORTLIST_LIMIT]]


def _llm_verify_changes(
    fact: dict[str, object], candidates: list[dict[str, object]]
) -> list[dict[str, object]]:
    """Have the LLM classify each shortlisted pair, returning applied-ready change records.

    One structured-JSON call judges the plausible pairs with full context, handling the
    entity-distinction, value-equivalence, and acknowledged-change-vs-conflict edge cases
    that string rules miss. Verdicts are validated against the ids we supplied and gated on
    confidence before they can create an edge; the call degrades to no changes on error.
    """
    new_id = str(fact["id"])
    valid_ids = {new_id} | {str(candidate["id"]) for candidate in candidates}
    observation_by_fact = {new_id: _optional_str(fact.get("source_observation_id"))}
    for candidate in candidates:
        observation_by_fact[str(candidate["id"])] = _optional_str(
            candidate.get("source_observation_id")
        )
    prompt = render_prompt(
        "contradiction_supersession_detection",
        {
            "existing_records": _format_fact_records(candidates),
            "new_evidence": _format_fact_records([fact]),
        },
    )
    try:
        response = call_qwen_json(
            [{"role": "user", "content": prompt}],
            schema_name="contradiction_supersession_detection",
        )
    except LLMClientError:
        return []
    payload = response.get("json", {})
    raw_relations = payload.get("relations", []) if isinstance(payload, dict) else []
    changes: list[dict[str, object]] = []
    for relation in raw_relations if isinstance(raw_relations, list) else []:
        if not isinstance(relation, dict):
            continue
        relation_type = str(relation.get("relation", "")).upper()
        source_id = _optional_str(relation.get("source_id"))
        target_id = _optional_str(relation.get("target_id"))
        if relation_type not in ("SUPERSEDED_BY", "CONTRADICTS"):
            continue
        if source_id not in valid_ids or target_id not in valid_ids or source_id == target_id:
            continue
        if _confidence_value(relation.get("confidence")) < _LLM_CHANGE_CONFIDENCE_GATE:
            continue
        evidence = [
            observation
            for observation in (
                observation_by_fact.get(source_id),
                observation_by_fact.get(target_id),
            )
            if observation
        ]
        if not evidence:
            continue
        changes.append(
            {
                "relation": relation_type,
                "source_id": source_id,
                "target_id": target_id,
                "evidence": evidence,
            }
        )
    log_event(
        "llm_change_verification",
        "LLM contradiction/supersession verification",
        step="contradiction_supersession",
        fact_id=new_id,
        candidates=len(candidates),
        applied=len(changes),
    )
    return changes


def _fact_text(fact: dict[str, object]) -> str:
    return " ".join(
        part
        for part in (
            _optional_str(fact.get("subject")),
            _optional_str(fact.get("predicate")),
            _optional_str(fact.get("object")),
        )
        if part
    )


def _format_fact_records(facts: list[dict[str, object]]) -> str:
    return "\n".join(f"- id={fact['id']}: {_fact_text(fact)}" for fact in facts)


def _confidence_value(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _step_changes(
    context: dict[str, list[str]],
    observation_id: str,
    content: str,
) -> dict[str, list[str]]:
    if _observation_role(observation_id) != "user":
        # Contradiction/supersession are driven by the user's own claims. Assistant echoes
        # merely paraphrase them, so running change detection on assistant observations only
        # duplicates edges the user turn already produced.
        return {"graph_edges": []}
    transition_edge_ids: list[str] = _apply_transition_supersessions(observation_id, content)
    general_edge_ids: list[str] = []
    general_superseded = 0
    recheck_observations: set[str] = set()
    for fact_id in context.get("fact_ids", []):
        fact = _fetch_fact(fact_id)
        if fact is None or str(fact.get("status")) != "active":
            continue
        priors = _active_prior_fact_ids(fact)
        log_event(
            "change_detection",
            "contradiction/supersession candidate scan",
            step="contradiction_supersession",
            fact_id=fact_id,
            subject_canonical=canonical_form_for_id(
                "canonical_subjects", _optional_str(fact.get("canonical_subject_id"))
            ),
            predicate_canonical=canonical_form_for_id(
                "canonical_predicates", _optional_str(fact.get("canonical_predicate_id"))
            ),
            candidates_found=len(priors),
            reason="no_candidates" if not priors else "candidates_found",
        )
        general_superseded += _apply_changes(
            detect_memory_change(fact_id, priors),
            transition_edge_ids,
            general_edge_ids,
            recheck_observations,
        )
        # Hybrid hard-case path: the deterministic scan above handles clean
        # same-canonical-subject pairs cheaply; embedding-shortlisted cross-subject
        # candidates are verified by the LLM, which judges entity identity, value
        # equivalence, and change-vs-conflict that string rules miss.
        candidates = _shortlist_candidate_facts(fact)
        if candidates:
            general_superseded += _apply_changes(
                _llm_verify_changes(fact, candidates),
                transition_edge_ids,
                general_edge_ids,
                recheck_observations,
            )
    if transition_edge_ids and general_superseded:
        # Measures how often the general path WOULD have duplicated the explicit
        # transition edge (now suppressed above). See docs/canonicalization-followups.md.
        log_event(
            "general_supersession_suppressed",
            "redundant general supersession suppressed (explicit transition handled)",
            step="contradiction_supersession",
            observation_id=observation_id,
            transition_edges=len(transition_edge_ids),
            suppressed=general_superseded,
        )
    # Reflections built on facts that were just superseded/contradicted must be
    # re-evaluated for staleness; the invalidation step reads this from context.
    context["reflection_recheck_observations"] = sorted(recheck_observations)
    return {"graph_edges": transition_edge_ids + general_edge_ids}


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
    config: SlowPathSemanticConfig | None = None,
    *,
    workspace_id: str = LEGACY_WORKSPACE_ID,
) -> list[SlowPathStepResult]:
    """Run gated reflection synthesis when enough important evidence has accumulated.

    Evidence is drawn from recent observations in the store (accumulated across
    batches), not from a single batch, so reflection fires once enough important
    observations exist regardless of drain cadence.
    """
    semantic_config = config or SlowPathSemanticConfig()
    if not semantic_config.enable_reflection:
        return [_semantic_result("reflection_check")]
    evidence_ids = _recent_unreflected_observation_ids(semantic_config, workspace_id)
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
            if not content or _active_reflection_exists(content, workspace_id):
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


def _observations_since_last_community_refresh(workspace_id: str) -> int:
    """Count observations processed since the last community summary was written.

    Community detection is a background job over the accumulated graph (paper,
    Community Detection), so the trigger is a cumulative observation count derived
    from the store -- observations processed after the most recent summary -- rather
    than the size of a single slow-path batch. This survives one-at-a-time draining.
    """
    with repository_connection() as connection:
        last_refresh = connection.execute(
            "SELECT MAX(created_at) AS ts FROM community_summaries WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()["ts"]
        if last_refresh is None:
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM observations "
                "WHERE workspace_id = ? AND processed_at IS NOT NULL",
                (workspace_id,),
            ).fetchone()
        else:
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM observations "
                "WHERE workspace_id = ? AND processed_at IS NOT NULL AND processed_at > ?",
                (workspace_id, last_refresh),
            ).fetchone()
    return int(row["n"])


def maybe_run_community_refresh(
    config: SlowPathSemanticConfig | None = None,
    *,
    workspace_id: str = LEGACY_WORKSPACE_ID,
) -> list[SlowPathStepResult]:
    """Run graph community detection and summary refresh when enough has accumulated."""
    semantic_config = config or SlowPathSemanticConfig()
    if not semantic_config.enable_community_summaries:
        return [_semantic_result("community_update")]
    if (
        _observations_since_last_community_refresh(workspace_id)
        < semantic_config.community_refresh_every_observations
    ):
        return [_semantic_result("community_update")]

    created: list[str] = []
    try:
        communities = detect_graph_communities(workspace_id=workspace_id)
        for community in communities[: semantic_config.max_community_summaries_per_run]:
            community_id = str(community.get("community_id", ""))
            if not community_id or _community_summary_exists(community_id, workspace_id):
                continue
            member_node_ids = _json_string_list(community.get("member_node_ids"))
            if not member_node_ids:
                continue
            summary = summarize_community(community_id, member_node_ids, workspace_id=workspace_id)
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
    try:
        records = detect_foresight(observation_id, content, ambient_context)
    except Exception as error:  # noqa: BLE001 - semantic memory must not break factual slow path
        LOGGER.warning(
            "Skipping foresight for %s because detection failed: %s",
            observation_id,
            str(error) or error.__class__.__name__,
        )
        return {}
    for record in records[: config.max_foresight_records_per_observation]:
        foresight_content = str(record.get("content", "")).strip()
        if not foresight_content or _foresight_exists(observation_id, foresight_content):
            continue
        created.append(create_foresight(record))
    return {"foresight_records": created}


def _step_reflection_invalidation(
    observation_id: str,
    context: dict[str, list[str]],
    config: SlowPathSemanticConfig,
) -> dict[str, list[str]]:
    if not config.enable_reflection_invalidation:
        return {}
    # Re-check reflections derived from this observation and from any observation whose
    # facts were just superseded/contradicted this turn (their evidence collapsed even
    # though the observation itself is not the one being processed).
    recheck_observations = {observation_id, *context.get("reflection_recheck_observations", [])}
    reflection_ids: set[str] = set()
    for source_observation_id in recheck_observations:
        reflection_ids.update(find_reflections_derived_from(source_observation_id))
    updated: list[str] = []
    for reflection_id in sorted(reflection_ids):
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


def _apply_transition_supersessions(observation_id: str, content: str) -> list[str]:
    """Directly record SUPERSEDED_BY edges for explicit "from X to Y" transitions.

    Extraction already knows the direction (prior=X, current=Y) from the sentence, so
    the two facts are flagged as a supersession pair directly rather than routed through
    the general created_at-ordered pairing, which cannot disambiguate direction for two
    facts created in the same pass. The edge still carries the source observation as
    evidence, so provenance matches the general path.
    """
    if _observation_role(observation_id) != "user":
        # Transitions are first-person user statements; assistant echoes merely restate
        # them (often verbosely and with varied phrasing). Processing only the user turn
        # yields one edge per real transition instead of one per restatement.
        return []
    edge_ids: list[str] = []
    for transition in detect_transitions(content):
        subject_id = resolve_canonical_form("canonical_subjects", transition["subject"])
        predicate_id = resolve_canonical_form("canonical_predicates", transition["predicate"])
        if _transition_supersession_exists(
            subject_id, predicate_id, transition["prior_object"], transition["current_object"]
        ):
            # The same canonical prior->current transition was already recorded (e.g. the
            # user turn, now restated by the assistant echo). Skip so a single logical
            # transition yields exactly one edge regardless of how many turns restate it.
            log_event(
                "transition_supersession_skipped",
                "duplicate transition suppressed",
                step="contradiction_supersession",
                observation_id=observation_id,
                predicate=transition["predicate"],
                prior=transition["prior_object"],
                current=transition["current_object"],
            )
            continue
        prior_id = create_atomic_fact(_transition_fact(transition, "prior_object", observation_id))
        current_id = create_atomic_fact(
            _transition_fact(transition, "current_object", observation_id)
        )
        edge_ids.append(apply_supersession(prior_id, current_id, [observation_id]))
        log_event(
            "transition_supersession",
            "explicit transition superseded",
            step="contradiction_supersession",
            observation_id=observation_id,
            predicate=transition["predicate"],
            prior=transition["prior_object"],
            current=transition["current_object"],
        )
    return edge_ids


def _transition_fact(
    transition: dict[str, str], object_key: str, observation_id: str
) -> dict[str, object]:
    return {
        "subject": transition["subject"],
        "predicate": transition["predicate"],
        "object": transition[object_key],
        "confidence": 0.9,
        "source_observation_id": observation_id,
    }


def _observation_role(observation_id: str) -> str | None:
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT role FROM observations WHERE id = ?", (observation_id,)
        ).fetchone()
    return None if row is None else str(row["role"])


def _transition_supersession_exists(
    subject_id: str | None,
    predicate_id: str | None,
    prior_object: str,
    current_object: str,
) -> bool:
    """Return whether this canonical prior->current transition is already recorded.

    Keys on the canonical subject/predicate plus the prior and current object values,
    not on the source observation, so a transition restated across the user turn and the
    assistant echo collapses to a single SUPERSEDED_BY edge.
    """
    if not subject_id or not predicate_id:
        return False
    with repository_connection() as connection:
        row = connection.execute(
            """
            SELECT 1
            FROM graph_edges edge
            JOIN graph_nodes prior_node ON prior_node.id = edge.source_node_id
            JOIN graph_nodes current_node ON current_node.id = edge.target_node_id
            JOIN atomic_facts prior_fact ON prior_fact.id = prior_node.source_id
            JOIN atomic_facts current_fact ON current_fact.id = current_node.source_id
            WHERE edge.edge_type = 'SUPERSEDED_BY'
              AND prior_node.source_table = 'atomic_facts'
              AND current_node.source_table = 'atomic_facts'
              AND prior_fact.canonical_subject_id = ?
              AND prior_fact.canonical_predicate_id = ?
              AND current_fact.canonical_subject_id = ?
              AND current_fact.canonical_predicate_id = ?
              AND prior_fact.object = ? COLLATE NOCASE
              AND current_fact.object = ? COLLATE NOCASE
            LIMIT 1
            """,
            (subject_id, predicate_id, subject_id, predicate_id, prior_object, current_object),
        ).fetchone()
    return row is not None


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def _active_prior_fact_ids(fact: dict[str, object]) -> list[str]:
    canonical_subject_id = fact.get("canonical_subject_id")
    canonical_predicate_id = fact.get("canonical_predicate_id")
    if not canonical_subject_id or not canonical_predicate_id:
        return []
    with repository_connection() as connection:
        rows = connection.execute(
            """
            SELECT id FROM atomic_facts
            WHERE canonical_subject_id = ?
              AND canonical_predicate_id = ?
              AND status = 'active'
              AND id != ?
            ORDER BY created_at ASC
            """,
            (str(canonical_subject_id), str(canonical_predicate_id), str(fact["id"])),
        ).fetchall()
    exact = [str(row["id"]) for row in rows]
    if exact:
        return exact
    return _similar_prior_fact_ids(fact, str(canonical_subject_id))


def _similar_prior_fact_ids(fact: dict[str, object], canonical_subject_id: str) -> list[str]:
    """Fallback pairing: recent same-subject facts with an embedding-similar predicate.

    Exact canonical matching misses facts whose predicate wording landed in a different
    canonical bucket ("prefers" vs "prefers_programming_language"). Rather than solve
    open-ended vocabulary merging, this makes one embedding pass over recent facts under
    the same canonical subject and admits those whose predicate is similar enough. It is
    a best-effort rescue, not a guarantee.
    """
    with repository_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, predicate FROM atomic_facts
            WHERE canonical_subject_id = ?
              AND status = 'active'
              AND id != ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (canonical_subject_id, str(fact["id"]), _SIMILARITY_CANDIDATE_LIMIT),
        ).fetchall()
    if not rows:
        return []
    target = embed_text(str(fact["predicate"]))
    matched = [
        str(row["id"])
        for row in rows
        if _cosine_similarity(target, embed_text(str(row["predicate"]))) >= _SIMILARITY_THRESHOLD
    ]
    log_event(
        "similarity_fallback",
        "predicate embedding fallback pairing",
        step="contradiction_supersession",
        fact_id=str(fact["id"]),
        predicate=str(fact["predicate"]),
        candidates_scanned=len(rows),
        matched=len(matched),
    )
    return matched


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    return dot / (left_norm * right_norm)


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


def _ensure_observation_node(observation_id: str, content: str, workspace_id: str) -> str:
    existing = _existing_node_id("observation", "observations", observation_id, workspace_id)
    if existing is not None:
        return existing
    return create_graph_node(
        node_type="observation",
        label=_label(content) or observation_id,
        source_table="observations",
        source_id=observation_id,
        workspace_id=workspace_id,
    )


def _ensure_entity_node(entity_id: str, observation_id: str) -> str:
    existing = _existing_node_id("entity", "entities", entity_id)
    if existing is not None:
        return existing
    return link_entity_mention(entity_id, observation_id)


def _existing_node_id(
    node_type: str,
    source_table: str,
    source_id: str,
    workspace_id: str | None = None,
) -> str | None:
    with repository_connection() as connection:
        row = connection.execute(
            """
            SELECT id FROM graph_nodes
            WHERE node_type = ? AND source_table = ? AND source_id = ?
              AND (? IS NULL OR workspace_id = ?)
            ORDER BY created_at ASC LIMIT 1
            """,
            (node_type, source_table, source_id, workspace_id, workspace_id),
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


def _active_reflection_exists(content: str, workspace_id: str) -> bool:
    with repository_connection() as connection:
        row = connection.execute(
            """
            SELECT 1 FROM reflections
            WHERE workspace_id = ? AND status = 'active' AND lower(content) = lower(?)
            LIMIT 1
            """,
            (workspace_id, content),
        ).fetchone()
    return row is not None


def _community_summary_exists(community_id: str, workspace_id: str) -> bool:
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT 1 FROM community_summaries WHERE workspace_id = ? AND community_id = ? LIMIT 1",
            (workspace_id, community_id),
        ).fetchone()
    return row is not None


def _recent_unreflected_observation_ids(
    config: SlowPathSemanticConfig, workspace_id: str
) -> list[str]:
    """Return recent observations not yet reflected on, accumulated across batches.

    Reflection is cross-session consolidation over a flat set of recent observations
    (paper, Reflection), so the evidence window is drawn from the observation store,
    not from the current slow-path batch. Draining one observation at a time otherwise
    means each batch holds a single observation and the min-observations gate is never
    reached, so reflection never fires.
    """
    limit = max(config.reflection_min_observations, config.reflection_cooldown_observations)
    window = limit * 3
    with repository_connection() as connection:
        rows = connection.execute(
            "SELECT id FROM observations WHERE workspace_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (workspace_id, window),
        ).fetchall()
    newest_first = [str(row["id"]) for row in rows]
    unreflected_newest_first = [
        observation_id
        for observation_id in newest_first
        if not find_reflections_derived_from(observation_id)
    ]
    # Return the most recent unreflected observations in chronological order.
    return list(reversed(unreflected_newest_first))[-limit:]


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
    # Urgency / change markers: things that must be acted on or that revise prior state.
    urgency_markers = (
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
    # Durable-trait markers: stable self/user identity, preferences, and habits. Reflection
    # (user_knowledge and self_knowledge) is built from exactly this content, but it carries
    # none of the urgency words above, so without these it scored at the floor and the gate
    # never fired. See docs/paper-reconciliation.md (A1).
    trait_markers = (
        "always",
        "usually",
        "prefer",
        "tend to",
        "every ",
        "habit",
        "routinely",
        "typically",
        "generally",
        "frequent",
        "value ",
        "believe",
    )
    hits = sum(1 for marker in urgency_markers + trait_markers if marker in normalized)
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
