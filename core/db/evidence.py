"""Workspace-bound evidence and durable document enrichment operations."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta

from core.db.repositories import (
    CANONICAL_LOW_CONFIDENCE,
    _normalize_canonical,
    repository_connection,
)
from core.evidence.source import resolve_source

PIPELINE_VERSION = "v1"
LEASE_SECONDS = 300
RETRY_SECONDS = 60
_TARGET_COLUMNS = {
    "atomic_fact": ("atomic_facts", "atomic_fact_id"),
    "graph_edge": ("graph_edges", "graph_edge_id"),
    "reflection": ("reflections", "reflection_id"),
    "foresight": ("foresight_records", "foresight_id"),
}
_ROLE_AUTHORITIES = {"user": 0.95, "assistant": 0.55, "system": 0.4, "tool": 0.35}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _row(row: sqlite3.Row) -> dict[str, object]:
    return dict(row)


def _scope(
    db: sqlite3.Connection, workspace_id: str, project_id: str | None, namespace: str | None
) -> None:
    if project_id is None and namespace is not None:
        raise ValueError("namespace requires project_id")
    if project_id is not None:
        table, scope_clause, values = (
            ("project_namespaces", "AND namespace = ?", (workspace_id, project_id, namespace))
            if namespace is not None
            else ("project_knowledge_workspaces", "", (workspace_id, project_id))
        )
        # Table/fragment come only from the two fixed branches above; values stay bound.
        if (
            db.execute(
                f"SELECT 1 FROM {table} WHERE workspace_id = ? AND project_id = ? "  # nosec B608
                f"{scope_clause}",
                values,
            ).fetchone()
            is None
        ):
            raise ValueError("project scope does not own workspace")


def _scope_for_workspace(
    db: sqlite3.Connection, workspace_id: str
) -> tuple[str | None, str | None]:
    namespace = db.execute(
        "SELECT project_id, namespace FROM project_namespaces WHERE workspace_id = ?",
        (workspace_id,),
    ).fetchone()
    if namespace is not None:
        return str(namespace["project_id"]), str(namespace["namespace"])
    project = db.execute(
        "SELECT project_id FROM project_knowledge_workspaces WHERE workspace_id = ?",
        (workspace_id,),
    ).fetchone()
    return (str(project["project_id"]), None) if project is not None else (None, None)


def register_source(
    source_type: str,
    source_id: str,
    *,
    workspace_id: str,
    project_id: str | None = None,
    namespace: str | None = None,
    knowledge_base_id: str | None = None,
    authority: float | None = None,
    metadata: dict[str, object] | None = None,
) -> str:
    """Register a stable source after checking original ownership and status."""
    if source_type not in {"conversation_observation", "document_chunk"}:
        raise ValueError("unsupported source type")
    if authority is not None and not 0 <= authority <= 1:
        raise ValueError("authority must be between 0 and 1")
    with repository_connection() as db:
        db.row_factory = sqlite3.Row
        if project_id is None and namespace is None:
            project_id, namespace = _scope_for_workspace(db, workspace_id)
        _scope(db, workspace_id, project_id, namespace)
        if source_type == "conversation_observation":
            original = db.execute(
                "SELECT o.content, o.created_at, o.role, s.status FROM observations AS o "
                "JOIN sessions AS s ON s.id = o.session_id AND s.workspace_id = o.workspace_id "
                "WHERE o.id = ? AND o.workspace_id = ?",
                (source_id, workspace_id),
            ).fetchone()
            if original is None or original["status"] == "deleted" or knowledge_base_id is not None:
                raise ValueError("observation is unavailable or has invalid scope")
            observed_at = original["created_at"]
            if authority is None:
                authority = _ROLE_AUTHORITIES.get(str(original["role"]), 0.35)
        else:
            original = db.execute(
                "SELECT c.content, c.created_at, c.knowledge_base_id, d.status, "
                "d.deleted_at, k.status AS kb_status "
                "FROM document_chunks AS c JOIN documents AS d ON d.id = c.document_id "
                "AND d.workspace_id = c.workspace_id AND d.knowledge_base_id = c.knowledge_base_id "
                "JOIN knowledge_bases AS k ON k.id = c.knowledge_base_id "
                "AND k.workspace_id = c.workspace_id "
                "WHERE c.id = ? AND c.workspace_id = ?",
                (source_id, workspace_id),
            ).fetchone()
            if (
                original is None
                or original["status"] != "ready"
                or original["deleted_at"] is not None
                or original["kb_status"] != "active"
            ):
                raise ValueError("document chunk is unavailable")
            if knowledge_base_id is not None and knowledge_base_id != original["knowledge_base_id"]:
                raise ValueError("knowledge base mismatch")
            knowledge_base_id = original["knowledge_base_id"]
            observed_at = original["created_at"]
            if authority is None:
                authority = 0.5
        digest = hashlib.sha256(original["content"].encode()).hexdigest()
        existing = db.execute(
            "SELECT * FROM evidence_sources WHERE workspace_id = ? "
            "AND source_type = ? AND source_id = ?",
            (workspace_id, source_type, source_id),
        ).fetchone()
        if existing:
            if (
                existing["retracted_at"] is not None
                or existing["content_hash"] != digest
                or existing["project_id"] != project_id
                or existing["namespace"] != namespace
                or existing["knowledge_base_id"] != knowledge_base_id
            ):
                raise ValueError("source has changed, been retracted, or has conflicting scope")
            return str(existing["id"])
        evidence_id = uuid.uuid4().hex
        db.execute(
            "INSERT INTO evidence_sources "
            "(id, workspace_id, source_type, source_id, project_id, namespace, "
            "knowledge_base_id, authority, content_hash, metadata_json, observed_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                evidence_id,
                workspace_id,
                source_type,
                source_id,
                project_id,
                namespace,
                knowledge_base_id,
                authority,
                digest,
                json.dumps(metadata) if metadata is not None else None,
                observed_at,
                _now(),
            ),
        )
        return evidence_id


def _link(
    db: sqlite3.Connection,
    source_id: str,
    target_type: str,
    target_id: str,
    workspace_id: str,
    stance: str,
    confidence: float,
) -> str:
    if target_type not in _TARGET_COLUMNS or stance not in {"support", "contradict"}:
        raise ValueError("invalid evidence link type or stance")
    if not 0 <= confidence <= 1:
        raise ValueError("confidence must be between 0 and 1")
    resolve_source(source_id, workspace_id=workspace_id, connection=db)
    table, fk_column = _TARGET_COLUMNS[target_type]
    if (
        db.execute(
            f"SELECT 1 FROM {table} WHERE id = ? AND workspace_id = ?",  # nosec B608
            (target_id, workspace_id),
        ).fetchone()
        is None
    ):
        raise ValueError("target not found in workspace")
    existing = db.execute(
        "SELECT id FROM evidence_links WHERE workspace_id = ? AND source_id = ? "
        "AND target_type = ? "
        "AND target_id = ? AND stance = ? AND retracted_at IS NULL",
        (workspace_id, source_id, target_type, target_id, stance),
    ).fetchone()
    if existing:
        return str(existing[0])
    link_id = uuid.uuid4().hex
    db.execute(
        f"INSERT INTO evidence_links (id, workspace_id, source_id, target_type, "  # nosec B608
        f"target_id, {fk_column}, stance, confidence, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            link_id,
            workspace_id,
            source_id,
            target_type,
            target_id,
            target_id,
            stance,
            confidence,
            _now(),
        ),
    )
    return link_id


def link_evidence(
    source_id: str,
    target_type: str,
    target_id: str,
    *,
    workspace_id: str,
    stance: str = "support",
    confidence: float = 1.0,
) -> str:
    """Idempotently attach supporting or contradicting evidence to a target."""
    with repository_connection() as db:
        return _link(db, source_id, target_type, target_id, workspace_id, stance, confidence)


def list_active_evidence(
    target_type: str, target_id: str, *, workspace_id: str
) -> list[dict[str, object]]:
    if target_type not in _TARGET_COLUMNS:
        raise ValueError("invalid target type")
    with repository_connection() as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT l.* FROM evidence_links AS l JOIN evidence_sources AS s ON s.id = l.source_id "
            "WHERE l.workspace_id = ? AND l.target_type = ? AND l.target_id = ? "
            "AND l.retracted_at IS NULL AND s.retracted_at IS NULL ORDER BY l.created_at, l.id",
            (workspace_id, target_type, target_id),
        ).fetchall()
        active = []
        for row in rows:
            try:
                source = resolve_source(row["source_id"], workspace_id=workspace_id, connection=db)
            except ValueError:
                continue
            active.append({**_row(row), "source": source})
        return active


def retract_source(source_id: str, *, workspace_id: str) -> int:
    """Retract a source and all its links; preserve historical rows."""
    with repository_connection() as db:
        now = _now()
        result = db.execute(
            "UPDATE evidence_sources SET retracted_at = ? WHERE id = ? "
            "AND workspace_id = ? AND retracted_at IS NULL",
            (now, source_id, workspace_id),
        )
        if result.rowcount:
            db.execute(
                "UPDATE evidence_links SET retracted_at = ? WHERE source_id = ? "
                "AND workspace_id = ? AND retracted_at IS NULL",
                (now, source_id, workspace_id),
            )
        return result.rowcount


def create_document_fact(
    workspace_id: str,
    evidence_source_id: str,
    subject: str,
    predicate: str,
    object: str,
    confidence: float,
    valid_from: str | None = None,
    valid_until: str | None = None,
) -> str:
    """Insert a document-derived fact and support link in one transaction."""
    if (
        not subject.strip()
        or not predicate.strip()
        or not object.strip()
        or not 0 <= confidence <= 1
    ):
        raise ValueError("fact fields or confidence are invalid")
    with repository_connection() as db:
        source = resolve_source(evidence_source_id, workspace_id=workspace_id, connection=db)
        if source["source_type"] != "document_chunk":
            raise ValueError("document fact requires document chunk evidence")
        canonical_subject_id = _canonical_id(db, "canonical_subjects", subject, workspace_id)
        canonical_predicate_id = _canonical_id(db, "canonical_predicates", predicate, workspace_id)
        candidates = db.execute(
            "SELECT id, object, valid_from, valid_until FROM atomic_facts "
            "WHERE workspace_id = ? AND status = 'active' AND canonical_subject_id = ? "
            "AND canonical_predicate_id = ? ORDER BY created_at, id",
            (workspace_id, canonical_subject_id, canonical_predicate_id),
        ).fetchall()
        normalized_object = _normalize_canonical(object)
        for candidate in candidates:
            if (
                _normalize_canonical(candidate[1]) == normalized_object
                and candidate[2] == valid_from
                and candidate[3] == valid_until
                and _fact_scope_compatible(
                    db, str(candidate[0]), workspace_id=workspace_id, source=source
                )
            ):
                _link(
                    db,
                    evidence_source_id,
                    "atomic_fact",
                    candidate[0],
                    workspace_id,
                    "support",
                    confidence,
                )
                return str(candidate[0])
        fact_id = uuid.uuid4().hex
        db.execute(
            "INSERT INTO atomic_facts "
            "(id, workspace_id, subject, predicate, object, confidence, status, "
            "source_observation_id, canonical_subject_id, canonical_predicate_id, "
            "created_at, valid_from, valid_until) "
            "VALUES (?, ?, ?, ?, ?, ?, 'active', NULL, ?, ?, ?, ?, ?)",
            (
                fact_id,
                workspace_id,
                subject,
                predicate,
                object,
                confidence,
                canonical_subject_id,
                canonical_predicate_id,
                _now(),
                valid_from,
                valid_until,
            ),
        )
        _link(db, evidence_source_id, "atomic_fact", fact_id, workspace_id, "support", confidence)
        return fact_id


def _canonical_id(db: sqlite3.Connection, table: str, value: str, workspace_id: str) -> str:
    if table not in {"canonical_subjects", "canonical_predicates"}:
        raise ValueError("unsupported canonical registry")
    normalized = _normalize_canonical(value)
    rows = db.execute(
        f"SELECT id, canonical_form, aliases_json FROM {table} WHERE workspace_id = ?",  # nosec B608
        (workspace_id,),
    ).fetchall()
    for row in rows:
        aliases = json.loads(row[2]) if row[2] else []
        if normalized == row[1] or any(
            _normalize_canonical(str(alias)) == normalized for alias in aliases
        ):
            return str(row[0])
    canonical_id = uuid.uuid4().hex
    db.execute(
        f"INSERT OR IGNORE INTO {table} "
        "(id, workspace_id, canonical_form, aliases_json, confidence, created_at) "
        "VALUES (?, ?, ?, '[]', ?, ?)",
        (canonical_id, workspace_id, normalized, CANONICAL_LOW_CONFIDENCE, _now()),
    )
    return str(
        db.execute(
            f"SELECT id FROM {table} WHERE workspace_id = ? AND canonical_form = ?",  # nosec B608
            (workspace_id, normalized),
        ).fetchone()[0]
    )


def _fact_scope_compatible(
    db: sqlite3.Connection,
    fact_id: str,
    *,
    workspace_id: str,
    source: dict[str, object],
) -> bool:
    """Allow shared claims only inside the same project/namespace and KB policy."""
    rows = db.execute(
        "SELECT s.id, s.source_type, s.source_id FROM evidence_links AS l "
        "JOIN evidence_sources AS s ON s.id = l.source_id AND s.workspace_id = l.workspace_id "
        "WHERE l.workspace_id = ? AND l.target_type = 'atomic_fact' AND l.target_id = ? "
        "AND l.stance = 'support' AND l.retracted_at IS NULL AND s.retracted_at IS NULL",
        (workspace_id, fact_id),
    ).fetchall()
    existing_sources = []
    for row in rows:
        try:
            existing_sources.append(
                resolve_source(str(row["id"]), workspace_id=workspace_id, connection=db)
            )
        except ValueError:
            continue
    if not existing_sources:
        legacy = db.execute(
            "SELECT o.id, o.session_id FROM atomic_facts AS f JOIN observations AS o "
            "ON o.id = f.source_observation_id AND o.workspace_id = f.workspace_id "
            "JOIN sessions AS s ON s.id = o.session_id AND s.workspace_id = o.workspace_id "
            "WHERE f.id = ? AND s.status != 'deleted'",
            (fact_id,),
        ).fetchone()
        if legacy is None:
            return False
        return (
            source["project_id"] is None
            and source["namespace"] is None
            and _session_has_kb_attachment(
                db,
                str(legacy["session_id"]),
                str(source["knowledge_base_id"]),
                workspace_id,
            )
        )
    for existing in existing_sources:
        if (existing["project_id"], existing["namespace"]) != (
            source["project_id"],
            source["namespace"],
        ):
            return False
        if (
            existing["source_type"] == "document_chunk"
            and existing["knowledge_base_id"] != source["knowledge_base_id"]
        ):
            return False
        if (
            existing["source_type"] == "conversation_observation"
            and source["source_type"] == "document_chunk"
        ):
            provenance = existing.get("provenance")
            session_id = ""
            if isinstance(provenance, dict):
                session_id = str(provenance.get("session_id", ""))
            if not _session_has_kb_attachment(
                db, session_id, str(source["knowledge_base_id"]), workspace_id
            ):
                return False
        if (
            existing["source_type"] == "document_chunk"
            and source["source_type"] == "conversation_observation"
        ):
            provenance = source.get("provenance")
            session_id = (
                str(provenance.get("session_id", "")) if isinstance(provenance, dict) else ""
            )
            if not _session_has_kb_attachment(
                db, session_id, str(existing["knowledge_base_id"]), workspace_id
            ):
                return False
    return True


def _session_has_kb_attachment(
    db: sqlite3.Connection, session_id: str, knowledge_base_id: str, workspace_id: str
) -> bool:
    return bool(
        session_id
        and db.execute(
            "SELECT 1 FROM session_knowledge_base_attachments AS a "
            "JOIN sessions AS s ON s.id = a.session_id AND s.workspace_id = a.workspace_id "
            "JOIN knowledge_bases AS k ON k.id = a.knowledge_base_id "
            "AND k.workspace_id = a.workspace_id "
            "WHERE a.workspace_id = ? AND a.session_id = ? AND a.knowledge_base_id = ? "
            "AND s.status != 'deleted' AND k.status = 'active'",
            (workspace_id, session_id, knowledge_base_id),
        ).fetchone()
    )


def create_conversation_fact(
    observation_id: str,
    subject: str,
    predicate: str,
    object_value: str,
    confidence: float,
    valid_from: str | None = None,
    valid_until: str | None = None,
) -> str:
    """Persist a conversation fact with its normalized source in one transaction."""
    if (
        not subject.strip()
        or not predicate.strip()
        or not object_value.strip()
        or not 0 < confidence <= 1
    ):
        raise ValueError("fact fields or confidence are invalid")
    with repository_connection() as db:
        db.row_factory = sqlite3.Row
        observation = db.execute(
            "SELECT o.content, o.created_at, o.workspace_id, o.role, "
            "s.status AS session_status "
            "FROM observations AS o JOIN sessions AS s ON s.id = o.session_id "
            "AND s.workspace_id = o.workspace_id WHERE o.id = ?",
            (observation_id,),
        ).fetchone()
        if observation is None or observation["session_status"] == "deleted":
            raise ValueError("active conversation observation not found")
        workspace_id = str(observation["workspace_id"])
        project_id, namespace = _scope_for_workspace(db, workspace_id)
        _scope(db, workspace_id, project_id, namespace)
        digest = hashlib.sha256(str(observation["content"]).encode()).hexdigest()
        source = db.execute(
            "SELECT * FROM evidence_sources WHERE workspace_id = ? "
            "AND source_type = 'conversation_observation' AND source_id = ?",
            (workspace_id, observation_id),
        ).fetchone()
        if source is None:
            source_id = uuid.uuid4().hex
            authority = _ROLE_AUTHORITIES.get(str(observation["role"]), 0.35)
            db.execute(
                "INSERT INTO evidence_sources "
                "(id, workspace_id, source_type, source_id, project_id, namespace, authority, "
                "content_hash, observed_at, created_at) "
                "VALUES (?, ?, 'conversation_observation', ?, ?, ?, ?, ?, ?, ?)",
                (
                    source_id,
                    workspace_id,
                    observation_id,
                    project_id,
                    namespace,
                    authority,
                    digest,
                    observation["created_at"],
                    _now(),
                ),
            )
        else:
            source_id = str(source["id"])
            if (
                source["retracted_at"] is not None
                or source["content_hash"] != digest
                or source["project_id"] != project_id
                or source["namespace"] != namespace
            ):
                raise ValueError("conversation source changed, was retracted, or is out of scope")
        resolved_source = resolve_source(source_id, workspace_id=workspace_id, connection=db)
        canonical_subject_id = _canonical_id(db, "canonical_subjects", subject, workspace_id)
        canonical_predicate_id = _canonical_id(db, "canonical_predicates", predicate, workspace_id)
        candidates = db.execute(
            "SELECT id, object, valid_from, valid_until FROM atomic_facts "
            "WHERE workspace_id = ? AND status = 'active' AND canonical_subject_id = ? "
            "AND canonical_predicate_id = ? ORDER BY created_at, id",
            (workspace_id, canonical_subject_id, canonical_predicate_id),
        ).fetchall()
        normalized_object = _normalize_canonical(object_value)
        for candidate in candidates:
            if (
                _normalize_canonical(str(candidate["object"])) == normalized_object
                and candidate["valid_from"] == valid_from
                and candidate["valid_until"] == valid_until
                and _fact_scope_compatible(
                    db, str(candidate["id"]), workspace_id=workspace_id, source=resolved_source
                )
            ):
                _link(
                    db,
                    source_id,
                    "atomic_fact",
                    str(candidate["id"]),
                    workspace_id,
                    "support",
                    confidence,
                )
                return str(candidate["id"])
        fact_id = uuid.uuid4().hex
        db.execute(
            "INSERT INTO atomic_facts "
            "(id, workspace_id, subject, predicate, object, confidence, status, "
            "source_observation_id, canonical_subject_id, canonical_predicate_id, "
            "created_at, valid_from, valid_until) "
            "VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)",
            (
                fact_id,
                workspace_id,
                subject,
                predicate,
                object_value,
                confidence,
                observation_id,
                canonical_subject_id,
                canonical_predicate_id,
                _now(),
                valid_from,
                valid_until,
            ),
        )
        _link(db, source_id, "atomic_fact", fact_id, workspace_id, "support", confidence)
        return fact_id


def retract_document_sources(document_id: str, *, workspace_id: str) -> dict[str, int]:
    """Retract chunk evidence and invalidate targets left without valid support."""
    counts = {
        "sources": 0,
        "links": 0,
        "atomic_facts": 0,
        "graph_edges": 0,
        "reflections": 0,
        "foresight_records": 0,
    }
    with repository_connection() as db:
        db.row_factory = sqlite3.Row
        document = db.execute(
            "SELECT 1 FROM documents WHERE id = ? AND workspace_id = ?",
            (document_id, workspace_id),
        ).fetchone()
        if document is None:
            raise ValueError("document not found in workspace")
        source_rows = db.execute(
            "SELECT s.id FROM evidence_sources AS s JOIN document_chunks AS c "
            "ON c.id = s.source_id AND c.workspace_id = s.workspace_id "
            "WHERE c.document_id = ? AND s.workspace_id = ? AND s.source_type = 'document_chunk' "
            "AND s.retracted_at IS NULL",
            (document_id, workspace_id),
        ).fetchall()
        if not source_rows:
            return counts
        source_ids = [row["id"] for row in source_rows]
        placeholders = ", ".join("?" for _ in source_ids)
        impacted = db.execute(
            f"SELECT DISTINCT target_type, target_id FROM evidence_links WHERE workspace_id = ? "
            f"AND source_id IN ({placeholders}) AND stance = 'support' AND retracted_at IS NULL",  # nosec B608
            (workspace_id, *source_ids),
        ).fetchall()
        now = _now()
        counts["links"] = db.execute(
            f"UPDATE evidence_links SET retracted_at = ? WHERE workspace_id = ? "
            f"AND source_id IN ({placeholders}) AND retracted_at IS NULL",  # nosec B608
            (now, workspace_id, *source_ids),
        ).rowcount
        counts["sources"] = db.execute(
            f"UPDATE evidence_sources SET retracted_at = ? WHERE workspace_id = ? "
            f"AND id IN ({placeholders}) AND retracted_at IS NULL",  # nosec B608
            (now, workspace_id, *source_ids),
        ).rowcount
        for target in impacted:
            kind, target_id = target["target_type"], target["target_id"]
            supported = db.execute(
                "SELECT 1 FROM evidence_links AS l "
                "JOIN evidence_sources AS s ON s.id = l.source_id "
                "WHERE l.workspace_id = ? AND l.target_type = ? AND l.target_id = ? "
                "AND l.stance = 'support' AND l.retracted_at IS NULL "
                "AND s.retracted_at IS NULL LIMIT 1",
                (workspace_id, kind, target_id),
            ).fetchone()
            if kind == "graph_edge":
                edge = db.execute(
                    "SELECT id, edge_type, source_node_id, target_node_id, "
                    "source_observations_json, metadata_json FROM graph_edges "
                    "WHERE id = ? AND workspace_id = ?",
                    (target_id, workspace_id),
                ).fetchone()
                if edge is None:
                    continue
                if supported and edge["edge_type"] in {"SUPERSEDED_BY", "CONTRADICTS"}:
                    if graph_relation_has_bilateral_support(db, edge, workspace_id):
                        continue
                    invalidated = db.execute(
                        "UPDATE graph_edges SET invalidated_at = ? WHERE id = ? "
                        "AND workspace_id = ? AND invalidated_at IS NULL",
                        (now, target_id, workspace_id),
                    )
                    if invalidated.rowcount:
                        restore_invalidated_graph_relation(db, edge, workspace_id)
                        counts["graph_edges"] += invalidated.rowcount
                    continue
                if supported:
                    continue
                if json.loads(edge["source_observations_json"] or "[]"):
                    continue
                invalidated = db.execute(
                    "UPDATE graph_edges SET invalidated_at = ? WHERE id = ? "
                    "AND workspace_id = ? AND invalidated_at IS NULL",
                    (now, target_id, workspace_id),
                )
                if invalidated.rowcount:
                    restore_invalidated_graph_relation(db, edge, workspace_id)
                    counts["graph_edges"] += invalidated.rowcount
                continue
            if supported:
                continue
            if kind == "atomic_fact":
                counts["atomic_facts"] += db.execute(
                    "UPDATE atomic_facts SET status = 'expired', "
                    "valid_until = COALESCE(valid_until, ?) "
                    "WHERE id = ? AND workspace_id = ? AND status = 'active' "
                    "AND source_observation_id IS NULL",
                    (now, target_id, workspace_id),
                ).rowcount
            elif kind == "reflection":
                legacy_evidence = db.execute(
                    "SELECT 1 FROM reflection_evidence WHERE reflection_id = ? LIMIT 1",
                    (target_id,),
                ).fetchone()
                active_source_count = db.execute(
                    "SELECT COUNT(*) FROM evidence_links AS l "
                    "JOIN evidence_sources AS s ON s.id = l.source_id "
                    "WHERE l.workspace_id = ? AND l.target_type = 'reflection' "
                    "AND l.target_id = ? AND l.stance = 'support' "
                    "AND l.retracted_at IS NULL AND s.retracted_at IS NULL",
                    (workspace_id, target_id),
                ).fetchone()[0]
                if legacy_evidence or active_source_count >= 2:
                    continue
                counts["reflections"] += db.execute(
                    "UPDATE reflections SET status = 'stale', "
                    "stale_reason = 'document evidence fell below minimum support', updated_at = ? "
                    "WHERE id = ? AND workspace_id = ? AND status = 'active'",
                    (now, target_id, workspace_id),
                ).rowcount
            elif kind == "foresight":
                counts["foresight_records"] += db.execute(
                    "UPDATE foresight_records SET status = 'cancelled', "
                    "resolved_by = 'document source retracted', updated_at = ? "
                    "WHERE id = ? AND workspace_id = ? "
                    "AND status IN ('candidate', 'pending', 'active') "
                    "AND source_observation_id IS NULL",
                    (now, target_id, workspace_id),
                ).rowcount
        return counts


def graph_relation_has_bilateral_support(
    db: sqlite3.Connection, edge: sqlite3.Row, workspace_id: str
) -> bool:
    """Keep a fact relation only while live linked sources support both endpoints."""
    endpoints = db.execute(
        "SELECT source_id FROM graph_nodes WHERE workspace_id = ? AND node_type = 'atomic_fact' "
        "AND source_table = 'atomic_facts' AND id IN (?, ?)",
        (workspace_id, edge["source_node_id"], edge["target_node_id"]),
    ).fetchall()
    fact_ids = [str(row[0]) for row in endpoints if row[0]]
    if len(set(fact_ids)) != 2:
        return False
    relation_rows = db.execute(
        "SELECT source_id FROM evidence_links WHERE workspace_id = ? "
        "AND target_type = 'graph_edge' AND target_id = ? AND stance = 'support' "
        "AND retracted_at IS NULL",
        (workspace_id, edge["id"]),
    ).fetchall()
    relation_sources = {str(row[0]) for row in relation_rows}
    if not relation_sources:
        return False
    for fact_id in fact_ids:
        fact_sources = {
            str(row[0])
            for row in db.execute(
                "SELECT l.source_id FROM evidence_links AS l "
                "JOIN evidence_sources AS s ON s.id = l.source_id "
                "WHERE l.workspace_id = ? AND l.target_type = 'atomic_fact' "
                "AND l.target_id = ? AND l.stance = 'support' "
                "AND l.retracted_at IS NULL AND s.retracted_at IS NULL",
                (workspace_id, fact_id),
            ).fetchall()
        }
        legacy = db.execute(
            "SELECT e.id FROM atomic_facts AS f JOIN evidence_sources AS e "
            "ON e.workspace_id = f.workspace_id AND e.source_type = 'conversation_observation' "
            "AND e.source_id = f.source_observation_id AND e.retracted_at IS NULL "
            "WHERE f.id = ? AND f.workspace_id = ?",
            (fact_id, workspace_id),
        ).fetchone()
        if legacy is not None:
            fact_sources.add(str(legacy[0]))
        if not relation_sources & fact_sources:
            return False
    return True


def _restore_superseded_fact(
    db: sqlite3.Connection, edge: sqlite3.Row | dict[str, object], workspace_id: str
) -> None:
    """Restore the old fact's pre-transition state after its proof is retracted."""
    if str(edge["edge_type"]) != "SUPERSEDED_BY":
        return
    metadata = json.loads(str(edge["metadata_json"] or "{}"))
    rollback = metadata.get("supersession_rollback") if isinstance(metadata, dict) else None
    if not isinstance(rollback, dict) or not rollback.get("fact_id"):
        return
    fact_id = str(rollback["fact_id"])
    supported = db.execute(
        "SELECT 1 FROM evidence_links AS l JOIN evidence_sources AS s "
        "ON s.id = l.source_id AND s.workspace_id = l.workspace_id "
        "WHERE l.workspace_id = ? AND l.target_type = 'atomic_fact' AND l.target_id = ? "
        "AND l.stance = 'support' AND l.retracted_at IS NULL AND s.retracted_at IS NULL "
        "UNION ALL "
        "SELECT 1 FROM atomic_facts AS f JOIN observations AS o "
        "ON o.id = f.source_observation_id AND o.workspace_id = f.workspace_id "
        "JOIN sessions AS s ON s.id = o.session_id AND s.workspace_id = o.workspace_id "
        "WHERE f.id = ? AND f.workspace_id = ? AND s.status != 'deleted' LIMIT 1",
        (workspace_id, fact_id, fact_id, workspace_id),
    ).fetchone()
    if supported is None:
        db.execute(
            "UPDATE atomic_facts SET status = 'rejected', valid_until = COALESCE(valid_until, ?) "
            "WHERE id = ? AND workspace_id = ? AND status = 'superseded'",
            (_now(), fact_id, workspace_id),
        )
        return
    competing = db.execute(
        "SELECT 1 FROM graph_edges AS e JOIN graph_nodes AS n "
        "ON n.id = e.source_node_id AND n.workspace_id = e.workspace_id "
        "WHERE e.workspace_id = ? AND e.edge_type = 'SUPERSEDED_BY' "
        "AND e.invalidated_at IS NULL AND n.source_table = 'atomic_facts' "
        "AND n.source_id = ? LIMIT 1",
        (workspace_id, fact_id),
    ).fetchone()
    if competing:
        return
    previous_status = str(rollback.get("status") or "active")
    if previous_status not in {"active", "superseded", "contradicted", "expired", "rejected"}:
        previous_status = "active"
    db.execute(
        "UPDATE atomic_facts SET status = ?, valid_until = ? "
        "WHERE id = ? AND workspace_id = ? AND status = 'superseded'",
        (previous_status, rollback.get("valid_until"), fact_id, workspace_id),
    )


def restore_invalidated_graph_relation(
    db: sqlite3.Connection, edge: sqlite3.Row | dict[str, object], workspace_id: str
) -> None:
    """Restore state changes whose only justification was a retracted relation."""
    _restore_superseded_fact(db, edge, workspace_id)
    if str(edge["edge_type"]) != "CONTRADICTS":
        return
    metadata = json.loads(str(edge["metadata_json"] or "{}"))
    rollback = metadata.get("contradiction_rollback") if isinstance(metadata, dict) else None
    if not isinstance(rollback, dict):
        return
    try:
        factor = float(rollback.get("confidence_factor", 0))
    except (TypeError, ValueError):
        return
    fact_ids = rollback.get("fact_ids")
    if not 0 < factor < 1 or not isinstance(fact_ids, list):
        return
    for fact_id in dict.fromkeys(str(value) for value in fact_ids if value):
        db.execute(
            "UPDATE atomic_facts SET confidence = MIN(1.0, confidence / ?) "
            "WHERE id = ? AND workspace_id = ?",
            (factor, fact_id, workspace_id),
        )


def enqueue_document_job(document_id: str, *, workspace_id: str) -> str:
    """Enqueue one ready document once for the current pipeline version."""
    with repository_connection() as db:
        row = db.execute(
            "SELECT 1 FROM documents AS d JOIN knowledge_bases AS k "
            "ON k.id = d.knowledge_base_id "
            "AND k.workspace_id = d.workspace_id WHERE d.id = ? AND d.workspace_id = ? "
            "AND d.status = 'ready' AND d.deleted_at IS NULL AND k.status = 'active'",
            (document_id, workspace_id),
        ).fetchone()
        if row is None:
            raise ValueError("ready document not found in workspace")
        existing = db.execute(
            "SELECT id FROM document_enrichment_jobs "
            "WHERE document_id = ? AND pipeline_version = ?",
            (document_id, PIPELINE_VERSION),
        ).fetchone()
        if existing:
            return str(existing[0])
        job_id, now = uuid.uuid4().hex, _now()
        db.execute(
            "INSERT INTO document_enrichment_jobs "
            "(id, workspace_id, document_id, pipeline_version, status, "
            "available_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)",
            (job_id, workspace_id, document_id, PIPELINE_VERSION, now, now, now),
        )
        return job_id


def claim_document_jobs(
    limit: int,
    *,
    worker_id: str,
    eligible_workspace_ids: list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, object]]:
    """Atomically claim due jobs, including expired leases, with bounded retries."""
    if not 1 <= limit <= 100 or not worker_id.strip():
        raise ValueError("limit must be 1..100 and worker_id must be nonempty")
    if eligible_workspace_ids is not None and not eligible_workspace_ids:
        return []
    scope = ""
    scope_values: tuple[str, ...] = ()
    if eligible_workspace_ids is not None:
        scope_values = tuple(dict.fromkeys(eligible_workspace_ids))
        scope = " AND j.workspace_id IN (" + ", ".join("?" for _ in scope_values) + ")"
    db = repository_connection()
    db.row_factory = sqlite3.Row
    try:
        db.execute("BEGIN IMMEDIATE")
        now = _now()
        db.execute(
            "UPDATE document_enrichment_jobs SET status = 'failed', "
            "lease_until = NULL, worker_id = NULL, updated_at = ? "
            "WHERE status = 'processing' AND lease_until <= ? AND attempts >= max_attempts",
            (now, now),
        )
        rows = db.execute(
            "SELECT j.id FROM document_enrichment_jobs AS j "
            "JOIN documents AS d ON d.id = j.document_id "
            "AND d.workspace_id = j.workspace_id JOIN knowledge_bases AS k "
            "ON k.id = d.knowledge_base_id "
            "AND k.workspace_id = j.workspace_id WHERE d.status = 'ready' "
            "AND d.deleted_at IS NULL "
            "AND k.status = 'active' AND j.attempts < j.max_attempts " + scope + " AND "  # nosec B608
            "((j.status = 'pending' AND j.available_at <= ?) OR "
            "(j.status = 'processing' AND j.lease_until <= ?)) "
            "ORDER BY j.available_at, j.created_at, j.id LIMIT ?",
            (*scope_values, now, now, limit),
        ).fetchall()
        lease = (datetime.now(UTC) + timedelta(seconds=LEASE_SECONDS)).isoformat()
        claimed = []
        for row in rows:
            db.execute(
                "UPDATE document_enrichment_jobs SET status = 'processing', "
                "attempts = attempts + 1, "
                "lease_until = ?, worker_id = ?, updated_at = ? WHERE id = ?",
                (lease, worker_id, now, row["id"]),
            )
            claimed.append(
                _row(
                    db.execute(
                        "SELECT * FROM document_enrichment_jobs WHERE id = ?", (row["id"],)
                    ).fetchone()
                )
            )
        db.commit()
        return claimed
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def complete_document_job(job_id: str, *, workspace_id: str) -> None:
    with repository_connection() as db:
        result = db.execute(
            "UPDATE document_enrichment_jobs SET status = 'done', "
            "lease_until = NULL, worker_id = NULL, updated_at = ? "
            "WHERE id = ? AND workspace_id = ? AND status = 'processing' "
            "AND EXISTS (SELECT 1 FROM documents WHERE id = document_enrichment_jobs.document_id "
            "AND workspace_id = document_enrichment_jobs.workspace_id "
            "AND status = 'ready' AND deleted_at IS NULL)",
            (_now(), job_id, workspace_id),
        )
        if not result.rowcount:
            raise ValueError("processing job not found in workspace")


def fail_document_job(job_id: str, *, workspace_id: str, error_message: str) -> None:
    with repository_connection() as db:
        row = db.execute(
            "SELECT attempts, max_attempts FROM document_enrichment_jobs "
            "WHERE id = ? AND workspace_id = ? AND status = 'processing'",
            (job_id, workspace_id),
        ).fetchone()
        if row is None:
            raise ValueError("processing job not found in workspace")
        status = "failed" if row[0] >= row[1] else "pending"
        now = _now()
        available = (datetime.now(UTC) + timedelta(seconds=RETRY_SECONDS * row[0])).isoformat()
        db.execute(
            "UPDATE document_enrichment_jobs SET status = ?, last_error = ?, available_at = ?, "
            "lease_until = NULL, worker_id = NULL, updated_at = ? "
            "WHERE id = ? AND workspace_id = ?",
            (status, error_message[:2000], available, now, job_id, workspace_id),
        )


def cancel_document_jobs(document_id: str, *, workspace_id: str) -> int:
    with repository_connection() as db:
        result = db.execute(
            "UPDATE document_enrichment_jobs SET status = 'cancelled', lease_until = NULL, "
            "worker_id = NULL, updated_at = ? WHERE document_id = ? AND workspace_id = ? "
            "AND status IN ('pending', 'processing')",
            (_now(), document_id, workspace_id),
        )
        return result.rowcount


def reconcile_ready_document_jobs(
    pipeline_version: str = PIPELINE_VERSION, *, eligible_workspace_ids: list[str] | tuple[str, ...]
) -> int:
    """Enqueue ready documents in explicitly eligible workspaces after interrupted uploads."""
    if not eligible_workspace_ids or not pipeline_version.strip():
        return 0
    ids = list(dict.fromkeys(eligible_workspace_ids))
    placeholders = ", ".join("?" for _ in ids)
    with repository_connection() as db:
        now = _now()
        result = db.execute(
            "INSERT INTO document_enrichment_jobs "
            "(id, workspace_id, document_id, pipeline_version, status, "
            "available_at, created_at, updated_at) "
            f"SELECT lower(hex(randomblob(16))), d.workspace_id, d.id, ?, 'pending', ?, ?, ? "  # nosec B608
            "FROM documents AS d JOIN knowledge_bases AS k ON k.id = d.knowledge_base_id "
            "AND k.workspace_id = d.workspace_id WHERE d.status = 'ready' AND d.deleted_at IS NULL "
            f"AND k.status = 'active' AND d.workspace_id IN ({placeholders}) "  # nosec B608
            "AND NOT EXISTS (SELECT 1 FROM document_enrichment_jobs AS j "
            "WHERE j.document_id = d.id AND j.pipeline_version = ?)",
            (pipeline_version, now, now, now, *ids, pipeline_version),
        )
        return result.rowcount
