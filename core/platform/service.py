"""Organization, project, API key, namespace, and usage services."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from core.db.repositories import (
    create_session,
    create_workspace,
    repository_connection,
)
from core.knowledge.service import create_knowledge_base
from core.memory.lifecycle import forget_memory
from core.memory.observation import persist_turn_fast_path
from core.platform.plans import plan_for
from core.platform.plans import plans as configured_plans

ALLOWED_SCOPES = frozenset(
    {
        "memories:read",
        "memories:write",
        "memories:delete",
        "documents:read",
        "documents:write",
        "documents:delete",
        "usage:read",
    }
)
_NAMESPACE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class PlatformAPIKey:
    id: str
    organization_id: str
    project_id: str
    project_name: str
    organization_owner_user_id: str
    plan: str
    subscription_status: str
    environment: str
    scopes: frozenset[str]
    prefix: str
    name: str


class QuotaExceededError(RuntimeError):
    """Raised when an organization has exhausted a monthly operation quota."""

    def __init__(self, operation: str, used: int, limit: int) -> None:
        super().__init__(f"Monthly {operation} limit reached.")
        self.operation = operation
        self.used = used
        self.limit = limit


class RateLimitExceededError(RuntimeError):
    """Raised when an API key exceeds its plan's per-minute request ceiling."""

    def __init__(self, limit: int, reset_at: int) -> None:
        super().__init__("API key rate limit exceeded; try again after the current minute.")
        self.limit = limit
        self.reset_at = reset_at


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def ensure_user_platform(user_id: str, login: str | None = None) -> tuple[str, str]:
    """Return the owner's default organization and production project, creating if missing."""
    with repository_connection() as connection:
        row = connection.execute(
            """
            SELECT organizations.id AS organization_id, projects.id AS project_id
            FROM organizations
            LEFT JOIN projects ON projects.organization_id = organizations.id
            WHERE organizations.owner_user_id = ?
            ORDER BY organizations.created_at, projects.created_at
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()
        if row is not None and row["project_id"] is not None:
            return str(row["organization_id"]), str(row["project_id"])
        suffix = secrets.token_hex(10)
        org_id, project_id = f"org_{suffix}", f"prj_{suffix}"
        now = now_iso()
        connection.execute(
            """
            INSERT INTO organizations (
                id, name, slug, owner_user_id, plan, subscription_status,
                billing_currency, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'free', 'active', 'NGN', ?, ?)
            """,
            (org_id, f"{login or 'My'} organization", f"org-{suffix}", user_id, now, now),
        )
        connection.execute(
            """
            INSERT INTO projects (
                id, organization_id, name, slug, environment, created_at, updated_at
            ) VALUES (?, ?, 'Default project', 'default-production', 'production', ?, ?)
            """,
            (project_id, org_id, now, now),
        )
        return org_id, project_id


def list_organizations_for_user(user_id: str) -> list[dict[str, object]]:
    ensure_user_platform(user_id)
    with repository_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, name, slug, plan, subscription_status, billing_currency,
                   current_period_end, created_at, updated_at
            FROM organizations WHERE owner_user_id = ? ORDER BY created_at, id
            """,
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_owned_organization(user_id: str, organization_id: str) -> dict[str, object] | None:
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT * FROM organizations WHERE id = ? AND owner_user_id = ?",
            (organization_id, user_id),
        ).fetchone()
    return None if row is None else dict(row)


def create_organization(user_id: str, name: str) -> dict[str, object]:
    clean_name = name.strip()
    if not clean_name or len(clean_name) > 80:
        raise ValueError("organization name must contain 1 to 80 characters")
    suffix = secrets.token_hex(5)
    slug_base = _slug(clean_name)[:40] or "organization"
    identifier, now = f"org_{secrets.token_hex(12)}", now_iso()
    with repository_connection() as connection:
        connection.execute(
            """
            INSERT INTO organizations (
                id, name, slug, owner_user_id, plan, subscription_status,
                billing_currency, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'free', 'active', 'NGN', ?, ?)
            """,
            (identifier, clean_name, f"{slug_base}-{suffix}", user_id, now, now),
        )
    project = create_project(user_id, identifier, "Default project", "production")
    return {"id": identifier, "name": clean_name, "plan": "free", "project": project}


def list_projects_for_user(
    user_id: str, organization_id: str | None = None
) -> list[dict[str, object]]:
    with repository_connection() as connection:
        rows = connection.execute(
            """
            SELECT projects.*, organizations.plan, organizations.subscription_status
            FROM projects JOIN organizations ON organizations.id = projects.organization_id
            WHERE organizations.owner_user_id = ?
              AND (? IS NULL OR organizations.id = ?)
            ORDER BY projects.created_at, projects.id
            """,
            (user_id, organization_id, organization_id),
        ).fetchall()
    return [dict(row) for row in rows]


def create_project(
    user_id: str, organization_id: str, name: str, environment: str
) -> dict[str, object]:
    clean_name = name.strip()
    if not clean_name or len(clean_name) > 80:
        raise ValueError("project name must contain 1 to 80 characters")
    if environment not in {"development", "production"}:
        raise ValueError("environment must be development or production")
    org = get_owned_organization(user_id, organization_id)
    if org is None:
        raise LookupError("organization not found")
    plan = plan_for(str(org["plan"]))
    with repository_connection() as connection:
        count = connection.execute(
            "SELECT COUNT(*) AS count FROM projects WHERE organization_id = ?",
            (organization_id,),
        ).fetchone()
        if int(count["count"]) >= plan["projects"]:
            raise QuotaExceededError("project", int(count["count"]), plan["projects"])
        suffix = secrets.token_hex(5)
        identifier, now = f"prj_{secrets.token_hex(12)}", now_iso()
        connection.execute(
            """
            INSERT INTO projects (
                id, organization_id, name, slug, environment, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                identifier,
                organization_id,
                clean_name,
                f"{_slug(clean_name)[:40] or 'project'}-{suffix}",
                environment,
                now,
                now,
            ),
        )
    return {
        "id": identifier,
        "organization_id": organization_id,
        "name": clean_name,
        "environment": environment,
        "created_at": now,
    }


def create_api_key(
    user_id: str,
    project_id: str,
    name: str,
    scopes: list[str],
    expires_at: str | None = None,
) -> tuple[dict[str, object], str]:
    clean_name = name.strip()
    if not clean_name or len(clean_name) > 80:
        raise ValueError("API key name must contain 1 to 80 characters")
    selected_scopes = sorted(set(scopes))
    if not selected_scopes or set(selected_scopes) - ALLOWED_SCOPES:
        raise ValueError("API key must include one or more supported scopes")
    expiry = _validate_expiry(expires_at)
    with repository_connection() as connection:
        row = connection.execute(
            """
            SELECT projects.id, projects.organization_id, projects.environment,
                   organizations.plan
            FROM projects JOIN organizations ON organizations.id = projects.organization_id
            WHERE projects.id = ? AND organizations.owner_user_id = ?
            """,
            (project_id, user_id),
        ).fetchone()
        if row is None:
            raise LookupError("project not found")
        key_limit = plan_for(str(row["plan"]))["api_keys"]
        key_count = connection.execute(
            """SELECT COUNT(*) AS count FROM api_keys
               WHERE organization_id = ? AND revoked_at IS NULL""",
            (str(row["organization_id"]),),
        ).fetchone()
        if int(key_count["count"]) >= key_limit:
            raise QuotaExceededError("API key", int(key_count["count"]), key_limit)
        environment = str(row["environment"])
        secret = secrets.token_urlsafe(32)
        raw_key = f"mira_{'live' if environment == 'production' else 'test'}_{secret}"
        prefix = raw_key[:22]
        identifier, now = f"key_{secrets.token_hex(12)}", now_iso()
        connection.execute(
            """
            INSERT INTO api_keys (
                id, organization_id, project_id, name, prefix, key_hash, environment,
                scopes_json, created_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                identifier,
                str(row["organization_id"]),
                project_id,
                clean_name,
                prefix,
                _key_hash(raw_key),
                environment,
                json.dumps(selected_scopes),
                now,
                expiry,
            ),
        )
    return (
        {
            "id": identifier,
            "project_id": project_id,
            "name": clean_name,
            "prefix": prefix,
            "environment": environment,
            "scopes": selected_scopes,
            "created_at": now,
            "expires_at": expiry,
            "last_used_at": None,
        },
        raw_key,
    )


def list_api_keys_for_user(
    user_id: str, organization_id: str | None = None
) -> list[dict[str, object]]:
    with repository_connection() as connection:
        rows = connection.execute(
            """
            SELECT api_keys.id, api_keys.organization_id, api_keys.project_id,
                   projects.name AS project_name, api_keys.name, api_keys.prefix,
                   api_keys.environment, api_keys.scopes_json, api_keys.created_at,
                   api_keys.last_used_at, api_keys.expires_at, api_keys.revoked_at
            FROM api_keys
            JOIN projects ON projects.id = api_keys.project_id
            JOIN organizations ON organizations.id = api_keys.organization_id
            WHERE organizations.owner_user_id = ?
              AND (? IS NULL OR api_keys.organization_id = ?)
            ORDER BY api_keys.created_at DESC
            """,
            (user_id, organization_id, organization_id),
        ).fetchall()
    return [
        {
            **{key: value for key, value in dict(row).items() if key != "scopes_json"},
            "scopes": _string_list(row["scopes_json"]),
        }
        for row in rows
    ]


def revoke_api_key(user_id: str, key_id: str) -> bool:
    with repository_connection() as connection:
        result = connection.execute(
            """
            UPDATE api_keys SET revoked_at = ?
            WHERE id = ? AND revoked_at IS NULL AND organization_id IN (
                SELECT id FROM organizations WHERE owner_user_id = ?
            )
            """,
            (now_iso(), key_id, user_id),
        )
    return result.rowcount > 0


def authenticate_api_key(raw_key: str) -> PlatformAPIKey | None:
    """Validate a bearer key by its short prefix and constant-time digest comparison."""
    if not raw_key.startswith(("mira_live_", "mira_test_")):
        return None
    prefix, now = raw_key[:22], now_iso()
    with repository_connection() as connection:
        row = connection.execute(
            """
            SELECT api_keys.*, projects.name AS project_name,
                   organizations.owner_user_id, organizations.plan,
                   organizations.subscription_status
            FROM api_keys
            JOIN projects ON projects.id = api_keys.project_id
            JOIN organizations ON organizations.id = api_keys.organization_id
            WHERE api_keys.prefix = ?
            """,
            (prefix,),
        ).fetchone()
        if row is None or not secrets.compare_digest(str(row["key_hash"]), _key_hash(raw_key)):
            return None
        if row["revoked_at"] is not None or (
            row["expires_at"] is not None and str(row["expires_at"]) <= now
        ):
            return None
        if str(row["subscription_status"]) == "inactive":
            return None
        connection.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (now, row["id"]))
        scopes = frozenset(_string_list(row["scopes_json"]))
    return PlatformAPIKey(
        id=str(row["id"]),
        organization_id=str(row["organization_id"]),
        project_id=str(row["project_id"]),
        project_name=str(row["project_name"]),
        organization_owner_user_id=str(row["owner_user_id"]),
        plan=str(row["plan"]),
        subscription_status=str(row["subscription_status"]),
        environment=str(row["environment"]),
        scopes=scopes,
        prefix=str(row["prefix"]),
        name=str(row["name"]),
    )


def resolve_namespace(api_key: PlatformAPIKey, namespace: str) -> dict[str, object]:
    clean_namespace = namespace.strip()
    if not _NAMESPACE_PATTERN.fullmatch(clean_namespace):
        raise ValueError(
            "namespace must be 1 to 128 letters, numbers, dots, underscores, colons, or hyphens"
        )
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT * FROM project_namespaces WHERE project_id = ? AND namespace = ?",
            (api_key.project_id, clean_namespace),
        ).fetchone()
    if row is not None:
        if row["knowledge_base_id"] is None:
            return _add_namespace_knowledge_base(dict(row))
        return dict(row)

    now = now_iso()
    suffix = hashlib.sha256(f"{api_key.project_id}:{clean_namespace}".encode()).hexdigest()[:20]
    workspace_id = f"ext_{suffix}"
    try:
        create_workspace(
            f"{api_key.project_name} / {clean_namespace}",
            f"ext-{suffix}",
            "development",
            owner_user_id=api_key.organization_owner_user_id,
            workspace_id=workspace_id,
        )
        session_id = create_session(
            f"api:{api_key.project_id}", "Developer API", workspace_id=workspace_id
        )
        knowledge_base = create_knowledge_base(
            workspace_id=workspace_id,
            name="API documents",
            description="Documents uploaded through the MIRA developer API.",
        )
        namespace_id = f"ns_{secrets.token_hex(12)}"
        with repository_connection() as connection:
            connection.execute(
                """
                INSERT INTO project_namespaces (
                    id, organization_id, project_id, namespace, workspace_id,
                    session_id, knowledge_base_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    namespace_id,
                    api_key.organization_id,
                    api_key.project_id,
                    clean_namespace,
                    workspace_id,
                    session_id,
                    str(knowledge_base["id"]),
                    now,
                    now,
                ),
            )
    except sqlite3.IntegrityError:
        # Concurrent first requests can race; use the winner's isolated record.
        with repository_connection() as connection:
            row = connection.execute(
                "SELECT * FROM project_namespaces WHERE project_id = ? AND namespace = ?",
                (api_key.project_id, clean_namespace),
            ).fetchone()
        if row is None:
            raise
        return dict(row)
    return {
        "id": namespace_id,
        "organization_id": api_key.organization_id,
        "project_id": api_key.project_id,
        "namespace": clean_namespace,
        "workspace_id": workspace_id,
        "session_id": session_id,
        "knowledge_base_id": str(knowledge_base["id"]),
        "created_at": now,
        "updated_at": now,
    }


def persist_memory(
    api_key: PlatformAPIKey,
    namespace: str,
    content: str,
    metadata: dict[str, object],
) -> str:
    if not content.strip() or len(content) > 200_000:
        raise ValueError("content must contain 1 to 200000 characters")
    scope = resolve_namespace(api_key, namespace)
    observation_id = persist_turn_fast_path(
        str(scope["session_id"]),
        "user",
        content,
        metadata={**metadata, "developer_api": True, "namespace": namespace},
    )
    return observation_id


def get_memory_source(workspace_id: str, source_id: str) -> dict[str, object] | None:
    with repository_connection() as connection:
        state = connection.execute(
            """SELECT source_type, source_id, lifecycle_status, created_at
               FROM memory_state WHERE workspace_id = ? AND source_id = ?""",
            (workspace_id, source_id),
        ).fetchone()
        if state is None:
            return None
        source_table = {
            "observations": "observations",
            "atomic_facts": "atomic_facts",
            "reflections": "reflections",
            "foresight_records": "foresight_records",
            "community_summaries": "community_summaries",
            "working_memory": "working_memory",
        }.get(str(state["source_type"]))
        if source_table is None:
            return None
        record = connection.execute(
            f"SELECT * FROM {source_table} WHERE id = ? AND workspace_id = ?",  # nosec B608
            (source_id, workspace_id),
        ).fetchone()
    if record is None:
        return None
    item = dict(record)
    return {
        "id": f"mem_{source_id}",
        "content": str(item.get("content") or item.get("object") or item.get("label") or ""),
        "source": str(state["source_type"]),
        "status": str(state["lifecycle_status"]),
        "created_at": item.get("created_at"),
    }


def forget_memory_source(workspace_id: str, memory_id: str) -> bool:
    source_id = memory_id.removeprefix("mem_")
    with repository_connection() as connection:
        state = connection.execute(
            "SELECT source_type FROM memory_state WHERE workspace_id = ? AND source_id = ?",
            (workspace_id, source_id),
        ).fetchone()
    if state is None:
        return False
    forget_memory(
        str(state["source_type"]), source_id, workspace_id, reason="developer_api_request"
    )
    return True


def check_monthly_quota(api_key: PlatformAPIKey, operation: str) -> None:
    if operation not in {"memory.write", "memory.search", "memory.context"}:
        return
    plan = plan_for(api_key.plan)
    is_write = operation == "memory.write"
    limit = plan["memory_writes_monthly"] if is_write else plan["retrievals_monthly"]
    now = datetime.now(UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    with repository_connection() as connection:
        if is_write:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count FROM usage_events
                WHERE organization_id = ? AND operation = 'memory.write'
                  AND status_code >= 200 AND status_code < 300 AND created_at >= ?
                """,
                (api_key.organization_id, month_start),
            ).fetchone()
        else:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count FROM usage_events
                WHERE organization_id = ? AND operation IN ('memory.search', 'memory.context')
                  AND status_code >= 200 AND status_code < 300 AND created_at >= ?
                """,
                (api_key.organization_id, month_start),
            ).fetchone()
    used = int(row["count"])
    if used >= limit:
        raise QuotaExceededError(operation, used, limit)


def check_rate_limit(api_key: PlatformAPIKey) -> tuple[int, int, int]:
    plan_limit = plan_for(api_key.plan)["rate_limit_per_minute"]
    now = datetime.now(UTC)
    window_start = (now - timedelta(seconds=60)).isoformat()
    with repository_connection() as connection:
        row = connection.execute(
            """SELECT COUNT(*) AS count
               FROM usage_events WHERE api_key_id = ? AND created_at >= ?""",
            (api_key.id, window_start),
        ).fetchone()
        used = int(row["count"])
        # Include this in-flight request in the sliding-window reset calculation;
        # authenticated 429 responses are metered too.
        reset_offset = max(0, used + 1 - plan_limit)
        expiry = connection.execute(
            """SELECT created_at FROM usage_events
               WHERE api_key_id = ? AND created_at >= ?
               ORDER BY created_at LIMIT 1 OFFSET ?""",
            (api_key.id, window_start, reset_offset),
        ).fetchone()
    reset_time = (
        datetime.fromisoformat(str(expiry["created_at"])).astimezone(UTC) + timedelta(seconds=60)
        if expiry is not None
        else now + timedelta(seconds=60)
    )
    reset_at = int(reset_time.timestamp())
    return plan_limit, max(0, plan_limit - used), reset_at


def record_usage_event(
    api_key: PlatformAPIKey,
    *,
    operation: str,
    status_code: int,
    latency_ms: int,
    namespace: str | None = None,
    bytes_ingested: int = 0,
    characters_processed: int = 0,
) -> None:
    with repository_connection() as connection:
        connection.execute(
            """
            INSERT INTO usage_events (
                id, organization_id, project_id, api_key_id, namespace, operation,
                status_code, latency_ms, bytes_ingested, characters_processed, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex,
                api_key.organization_id,
                api_key.project_id,
                api_key.id,
                namespace,
                operation,
                status_code,
                max(0, latency_ms),
                max(0, bytes_ingested),
                max(0, characters_processed),
                now_iso(),
            ),
        )


def usage_summary(user_id: str, organization_id: str) -> dict[str, object]:
    if get_owned_organization(user_id, organization_id) is None:
        raise LookupError("organization not found")
    start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    with repository_connection() as connection:
        organization = connection.execute(
            "SELECT plan, subscription_status, billing_currency FROM organizations WHERE id = ?",
            (organization_id,),
        ).fetchone()
        rows = connection.execute(
            """
            SELECT operation, COUNT(*) AS requests,
                   SUM(CASE WHEN status_code >= 200 AND status_code < 300
                            THEN 1 ELSE 0 END) AS succeeded,
                   SUM(bytes_ingested) AS bytes_ingested,
                   SUM(characters_processed) AS characters_processed
            FROM usage_events WHERE organization_id = ? AND created_at >= ?
            GROUP BY operation
            """,
            (organization_id, start),
        ).fetchall()
    by_operation = {str(row["operation"]): dict(row) for row in rows}
    writes = int(by_operation.get("memory.write", {}).get("succeeded") or 0)
    retrievals = sum(
        int(by_operation.get(operation, {}).get("succeeded") or 0)
        for operation in ("memory.search", "memory.context")
    )
    documents = sum(
        int(row.get("succeeded") or 0)
        for operation, row in by_operation.items()
        if operation.startswith("document.") and operation.endswith("upload")
    )
    requests = sum(int(row.get("requests") or 0) for row in by_operation.values())
    plan = str(organization["plan"])
    limits = plan_for(plan)
    return {
        "period_start": start,
        "plan": plan,
        "subscription_status": str(organization["subscription_status"]),
        "billing_currency": str(organization["billing_currency"]),
        "memory_writes": {"used": writes, "limit": limits["memory_writes_monthly"]},
        "retrievals": {"used": retrievals, "limit": limits["retrievals_monthly"]},
        "documents_uploaded": documents,
        "api_requests": requests,
        "by_operation": by_operation,
    }


def api_key_usage_summary(api_key: PlatformAPIKey) -> dict[str, object]:
    start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    with repository_connection() as connection:
        rows = connection.execute(
            """
            SELECT operation, status_code, COUNT(*) AS count,
                   SUM(bytes_ingested) AS bytes_ingested,
                   SUM(characters_processed) AS characters_processed
            FROM usage_events
            WHERE api_key_id = ? AND created_at >= ?
            GROUP BY operation, status_code
            """,
            (api_key.id, start),
        ).fetchall()
    operations: dict[str, dict[str, int]] = {}
    for row in rows:
        bucket = operations.setdefault(
            str(row["operation"]), {"requests": 0, "successful": 0, "failed": 0}
        )
        count = int(row["count"])
        bucket["requests"] += count
        bucket["successful" if 200 <= int(row["status_code"]) < 300 else "failed"] += count
    return {
        "period_start": start,
        "organization_id": api_key.organization_id,
        "project_id": api_key.project_id,
        "by_operation": operations,
        "api_requests": sum(bucket["requests"] for bucket in operations.values()),
        "bytes_ingested": sum(int(row["bytes_ingested"] or 0) for row in rows),
        "characters_processed": sum(int(row["characters_processed"] or 0) for row in rows),
    }


def list_namespace_summaries(user_id: str, organization_id: str) -> list[dict[str, object]]:
    if get_owned_organization(user_id, organization_id) is None:
        raise LookupError("organization not found")
    with repository_connection() as connection:
        rows = connection.execute(
            """
            SELECT project_namespaces.namespace, project_namespaces.project_id,
                   projects.name AS project_name, project_namespaces.created_at,
                   (SELECT COUNT(*) FROM observations
                    WHERE observations.workspace_id = project_namespaces.workspace_id) AS memories,
                   (SELECT COUNT(*) FROM documents
                    WHERE documents.workspace_id = project_namespaces.workspace_id
                      AND documents.status != 'deleted') AS documents
            FROM project_namespaces
            JOIN projects ON projects.id = project_namespaces.project_id
            WHERE project_namespaces.organization_id = ?
            ORDER BY project_namespaces.updated_at DESC
            """,
            (organization_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def platform_overview(user_id: str, organization_id: str) -> dict[str, object]:
    org = get_owned_organization(user_id, organization_id)
    if org is None:
        raise LookupError("organization not found")
    projects = list_projects_for_user(user_id, organization_id)
    keys = list_api_keys_for_user(user_id, organization_id)
    with repository_connection() as connection:
        namespace_count = connection.execute(
            "SELECT COUNT(*) AS count FROM project_namespaces WHERE organization_id = ?",
            (organization_id,),
        ).fetchone()
        docs = connection.execute(
            """SELECT COUNT(*) AS count FROM documents
               JOIN project_namespaces ON project_namespaces.workspace_id = documents.workspace_id
               WHERE project_namespaces.organization_id = ? AND documents.status != 'deleted'""",
            (organization_id,),
        ).fetchone()
    return {
        "organization": {
            key: org[key]
            for key in (
                "id",
                "name",
                "slug",
                "plan",
                "subscription_status",
                "billing_currency",
                "current_period_end",
            )
        },
        "projects": projects,
        "api_keys": keys,
        "namespaces": int(namespace_count["count"]),
        "documents": int(docs["count"]),
        "usage": usage_summary(user_id, organization_id),
        "plans": {name: dict(plan) for name, plan in configured_plans().items()},
    }


def get_user_email(user_id: str) -> str | None:
    with repository_connection() as connection:
        row = connection.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()
    return None if row is None or row["email"] is None else str(row["email"])


def api_key_from_token(token: str) -> PlatformAPIKey | None:
    """Alias used by public MCP authentication for revocation-aware key checks."""
    return authenticate_api_key(token)


def _add_namespace_knowledge_base(namespace: dict[str, object]) -> dict[str, object]:
    knowledge_base = create_knowledge_base(
        workspace_id=str(namespace["workspace_id"]),
        name="API documents",
        description="Documents uploaded through the MIRA developer API.",
    )
    with repository_connection() as connection:
        connection.execute(
            "UPDATE project_namespaces SET knowledge_base_id = ?, updated_at = ? WHERE id = ?",
            (str(knowledge_base["id"]), now_iso(), namespace["id"]),
        )
    return {**namespace, "knowledge_base_id": str(knowledge_base["id"])}


def _validate_expiry(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("expires_at must be an ISO 8601 timestamp") from error
    if parsed.tzinfo is None or parsed <= datetime.now(UTC):
        raise ValueError("expires_at must include a timezone and be in the future")
    return parsed.astimezone(UTC).isoformat()


def _slug(value: str) -> str:
    return _SLUG_PATTERN.sub("-", value.casefold()).strip("-")


def _key_hash(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _string_list(value: object) -> list[str]:
    try:
        parsed = json.loads(str(value))
    except (json.JSONDecodeError, TypeError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []
