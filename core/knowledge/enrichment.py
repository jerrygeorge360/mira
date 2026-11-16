"""Durable document enrichment using the existing grounded fact extractor."""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Mapping
from contextlib import suppress
from datetime import UTC, datetime

from core.db.evidence import (
    claim_document_jobs,
    complete_document_job,
    create_document_fact,
    fail_document_job,
    reconcile_ready_document_jobs,
    register_source,
)
from core.db.repositories import get_document, list_document_chunks, repository_connection
from core.evidence.config import document_enrichment_enabled
from core.memory.atomic_fact import MAX_SOURCE_TEXT_CHARS, extract_atomic_facts_from_source

LOGGER = logging.getLogger(__name__)


def enrichment_enabled_for_workspace(workspace_id: str) -> bool:
    """Evaluate workspace and project allowlists without broadening either scope."""
    if document_enrichment_enabled(workspace_id=workspace_id):
        return True
    with repository_connection() as db:
        projects = db.execute(
            "SELECT DISTINCT project_id FROM project_namespaces WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchall()
        project_documents = db.execute(
            "SELECT project_id FROM project_knowledge_workspaces WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchall()
    project_ids = {str(row[0]) for row in (*projects, *project_documents)}
    return any(
        document_enrichment_enabled(workspace_id=workspace_id, project_id=project_id)
        for project_id in project_ids
    )


def run_document_enrichment_batch(
    *, limit: int = 20, worker_id: str = "slow-path-worker"
) -> dict[str, int]:
    """Drain one batch; job failures are recorded independently of raw documents."""
    counts = {"processed": 0, "failed": 0}
    if os.environ.get("MIRA_DOCUMENT_ENRICHMENT_ENABLED", "false").strip().casefold() not in {
        "1",
        "true",
        "yes",
    }:
        return counts
    with repository_connection() as db:
        rows = db.execute(
            "SELECT DISTINCT workspace_id FROM documents "
            "WHERE status = 'ready' AND deleted_at IS NULL"
        ).fetchall()
    eligible = [str(row[0]) for row in rows if enrichment_enabled_for_workspace(str(row[0]))]
    if not eligible:
        return counts
    reconcile_ready_document_jobs(eligible_workspace_ids=eligible)
    for job in claim_document_jobs(limit, worker_id=worker_id, eligible_workspace_ids=eligible):
        job_id = str(job["id"])
        workspace_id = str(job["workspace_id"])
        try:
            enrich_document(str(job["document_id"]), workspace_id=workspace_id)
            complete_document_job(job_id, workspace_id=workspace_id)
            counts["processed"] += 1
        except Exception as error:  # noqa: BLE001 - isolate each durable job
            LOGGER.exception("Document enrichment failed for job %s", job_id)
            with suppress(ValueError):
                fail_document_job(
                    job_id,
                    workspace_id=workspace_id,
                    error_message=str(error) or error.__class__.__name__,
                )
            counts["failed"] += 1
    return counts


def enrich_document(document_id: str, *, workspace_id: str) -> int:
    """Run the shared fact, graph, change, reflection and foresight passes."""
    document = get_document(document_id, workspace_id=workspace_id)
    if document is None or document["status"] != "ready":
        raise ValueError("ready document not found in workspace")
    chunks = list_document_chunks(document_id, workspace_id=workspace_id)
    created = 0
    evidence_source_ids: list[str] = []
    from core.memory.change import apply_contradiction, apply_supersession, detect_memory_change
    from core.memory.foresight import (
        detect_document_foresight_candidates,
        store_document_foresight_candidate,
    )
    from core.memory.graph import (
        create_graph_edge,
        ensure_entity_graph_node,
        ensure_evidence_graph_node,
        extract_entities_from_source,
    )

    for index, chunk in enumerate(chunks):
        chunk_id = str(chunk["id"])
        source_id = register_source(
            "document_chunk",
            chunk_id,
            workspace_id=workspace_id,
            knowledge_base_id=str(document["knowledge_base_id"]),
            metadata={"document_id": document_id, "filename": str(document["filename"])},
        )
        evidence_source_ids.append(source_id)
        source_node_id = ensure_evidence_graph_node(source_id, workspace_id=workspace_id)
        raw_content = str(chunk["content"])
        excerpt = _chunk_context(chunks, index, str(document["filename"]))
        candidates = extract_atomic_facts_from_source(
            {"source_type": "document_chunk", "source_record_id": chunk_id}, excerpt
        )
        # A neighboring chunk may clarify a sentence, but the linked chunk must
        # actually contain the quote used as evidence for every persisted claim.
        supported = [fact for fact in candidates if _grounded_in_chunk(fact, str(chunk["content"]))]
        for entity in extract_entities_from_source(
            raw_content[:MAX_SOURCE_TEXT_CHARS], workspace_id=workspace_id
        ):
            entity_id = str(entity.get("id", ""))
            if not entity_id:
                continue
            entity_node_id = ensure_entity_graph_node(entity_id, workspace_id=workspace_id)
            if not _edge_exists(
                source_node_id, entity_node_id, "MENTIONS", workspace_id=workspace_id
            ):
                create_graph_edge(
                    source_node_id,
                    entity_node_id,
                    "MENTIONS",
                    1.0,
                    workspace_id=workspace_id,
                    evidence_source_ids=[source_id],
                )
        for fact in supported:
            raw_confidence = fact.get("confidence")
            if not isinstance(raw_confidence, int | float):
                continue
            confidence = float(raw_confidence)
            fact_id = create_document_fact(
                workspace_id,
                source_id,
                str(fact["subject"]),
                str(fact["predicate"]),
                str(fact["object"]),
                confidence,
            )
            fact_node_id = _ensure_fact_node(
                fact_id,
                str(fact["subject"]),
                str(fact["predicate"]),
                str(fact["object"]),
                workspace_id=workspace_id,
            )
            if not _edge_exists(
                fact_node_id, source_node_id, "DERIVED_FROM", workspace_id=workspace_id
            ):
                create_graph_edge(
                    fact_node_id,
                    source_node_id,
                    "DERIVED_FROM",
                    confidence,
                    workspace_id=workspace_id,
                    evidence_source_ids=[source_id],
                )
            else:
                _link_edge_source(source_id, fact_node_id, source_node_id, workspace_id)
            candidate_ids = _candidate_fact_ids(fact_id, workspace_id=workspace_id)
            for change in detect_memory_change(fact_id, candidate_ids):
                relation = str(change["relation"])
                prior_id = str(change["source_id"])
                raw_source_ids = change.get("evidence_source_ids")
                raw_observations = change.get("evidence")
                source_ids = (
                    [str(item) for item in raw_source_ids]
                    if isinstance(raw_source_ids, list)
                    else []
                )
                observations = (
                    [str(item) for item in raw_observations]
                    if isinstance(raw_observations, list)
                    else []
                )
                if relation == "SUPERSEDED_BY":
                    apply_supersession(
                        prior_id,
                        fact_id,
                        observations,
                        evidence_source_ids=source_ids,
                    )
                elif relation == "CONTRADICTS":
                    apply_contradiction(
                        prior_id,
                        fact_id,
                        observations,
                        evidence_source_ids=source_ids,
                    )
            created += 1

        if re.search(
            r"\b(?:20\d{2}-\d{2}-\d{2}|deadline|due|exam|scheduled|upcoming|tomorrow|next week)\b",
            raw_content,
            flags=re.IGNORECASE,
        ):
            try:
                proposals = detect_document_foresight_candidates(
                    source_id,
                    {"current_time": datetime.now(UTC).isoformat()},
                    workspace_id=workspace_id,
                )
                for proposal in proposals[:4]:
                    store_document_foresight_candidate(proposal, workspace_id=workspace_id)
            except Exception as error:  # noqa: BLE001 - proposals do not block factual memory
                LOGGER.warning(
                    "Document foresight detection failed for chunk %s: %s",
                    chunk_id,
                    str(error) or error.__class__.__name__,
                )

    if len(evidence_source_ids) >= 2:
        try:
            from core.memory.reflection import (
                store_domain_reflection_with_evidence,
                synthesize_domain_reflections,
            )

            for reflection in synthesize_domain_reflections(
                evidence_source_ids, workspace_id=workspace_id
            )[:3]:
                raw_evidence_ids = reflection.get("evidence_ids")
                source_ids = (
                    [str(item) for item in raw_evidence_ids]
                    if isinstance(raw_evidence_ids, list)
                    else []
                )
                store_domain_reflection_with_evidence(
                    reflection, source_ids, workspace_id=workspace_id
                )
        except Exception as error:  # noqa: BLE001 - reflections are optional enrichment
            LOGGER.warning(
                "Document reflection synthesis failed for %s: %s",
                document_id,
                str(error) or error.__class__.__name__,
            )
    return created


def cancel_and_retract_document(document_id: str, *, workspace_id: str) -> int:
    """Stop jobs and retract their evidence before the chunks are removed."""
    from core.db.evidence import cancel_document_jobs, retract_document_sources

    cancel_document_jobs(document_id, workspace_id=workspace_id)
    result = retract_document_sources(document_id, workspace_id=workspace_id)
    return int(result["sources"])


def _chunk_context(chunks: list[dict[str, object]], index: int, filename: str) -> str:
    chunk = chunks[index]
    parts = [f"Document: {filename}"]
    if chunk.get("heading"):
        parts.append(f"Heading: {chunk['heading']}")
    if chunk.get("page_start"):
        parts.append(f"Page: {chunk['page_start']}")
    for offset, label in ((-1, "Previous context"), (0, "Source chunk"), (1, "Next context")):
        position = index + offset
        if 0 <= position < len(chunks):
            text = str(chunks[position]["content"])
            if offset:
                text = text[-500:] if offset < 0 else text[:500]
            parts.append(f"{label}: {text}")
    return "\n\n".join(parts)[:MAX_SOURCE_TEXT_CHARS]


def _grounded_in_chunk(fact: Mapping[str, object], content: str) -> bool:
    span = str(fact.get("evidence_span") or "")
    return bool(span and " ".join(span.casefold().split()) in " ".join(content.casefold().split()))


def _ensure_fact_node(
    fact_id: str,
    subject: str,
    predicate: str,
    object_value: str,
    *,
    workspace_id: str,
) -> str:
    with repository_connection() as db:
        row = db.execute(
            "SELECT id FROM graph_nodes WHERE workspace_id = ? AND node_type = 'atomic_fact' "
            "AND source_table = 'atomic_facts' AND source_id = ? ORDER BY created_at LIMIT 1",
            (workspace_id, fact_id),
        ).fetchone()
    if row is not None:
        return str(row[0])
    from core.memory.graph import create_graph_node

    return create_graph_node(
        "atomic_fact",
        f"{subject} {predicate} {object_value}",
        source_table="atomic_facts",
        source_id=fact_id,
        workspace_id=workspace_id,
    )


def _candidate_fact_ids(fact_id: str, *, workspace_id: str) -> list[str]:
    with repository_connection() as db:
        fact = db.execute(
            "SELECT canonical_subject_id, canonical_predicate_id FROM atomic_facts "
            "WHERE id = ? AND workspace_id = ?",
            (fact_id, workspace_id),
        ).fetchone()
        if fact is None:
            return []
        rows = db.execute(
            "SELECT id FROM atomic_facts WHERE workspace_id = ? AND status = 'active' "
            "AND canonical_subject_id = ? AND canonical_predicate_id = ? AND id != ? "
            "ORDER BY created_at DESC LIMIT 100",
            (workspace_id, fact[0], fact[1], fact_id),
        ).fetchall()
    return [str(row[0]) for row in rows]


def _edge_exists(
    source_node_id: str, target_node_id: str, edge_type: str, *, workspace_id: str
) -> bool:
    with repository_connection() as db:
        return (
            db.execute(
                "SELECT 1 FROM graph_edges WHERE workspace_id = ? "
                "AND source_node_id = ? AND target_node_id = ? AND edge_type = ? "
                "AND invalidated_at IS NULL LIMIT 1",
                (workspace_id, source_node_id, target_node_id, edge_type),
            ).fetchone()
            is not None
        )


def _link_edge_source(
    source_id: str, source_node_id: str, target_node_id: str, workspace_id: str
) -> None:
    from core.db.evidence import link_evidence

    with repository_connection() as db:
        edge = db.execute(
            "SELECT id FROM graph_edges WHERE workspace_id = ? AND source_node_id = ? "
            "AND target_node_id = ? AND edge_type = 'DERIVED_FROM' "
            "AND invalidated_at IS NULL ORDER BY created_at LIMIT 1",
            (workspace_id, source_node_id, target_node_id),
        ).fetchone()
    if edge is not None:
        link_evidence(str(source_id), "graph_edge", str(edge[0]), workspace_id=workspace_id)
