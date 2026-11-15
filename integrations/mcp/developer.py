"""Small project-key MCP surface for third-party agents."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from pydantic import AnyHttpUrl

from api.oauth import MCP_SCOPE, mcp_resource_url, oauth_issuer_url
from core.db.repositories import WorkspaceContext, bind_workspace
from core.memory.observation import persist_turn_fast_path
from core.platform.service import (
    PlatformAPIKey,
    QuotaExceededError,
    check_monthly_quota,
    check_rate_limit,
    forget_memory_source,
    get_memory_source,
    record_usage_event,
    resolve_namespace,
)
from core.retrieval.router import route_retrieval
from integrations.mcp.auth import StaticTokenVerifier, authenticated_project_api_key

_DESCRIPTIONS = {
    "remember": "Store an explicit user-authored memory in a project namespace.",
    "recall": "Fetch one memory by its MIRA memory id from a namespace.",
    "search": "Search memory and document evidence in one isolated namespace.",
    "forget": "Forget a memory by id while preserving MIRA's lifecycle and provenance.",
    "history": "List recent raw observations for one namespace.",
    "get_context": "Retrieve prompt-ready memory evidence relevant to a question.",
}
LOGGER = logging.getLogger(__name__)


def create_developer_mcp_server() -> FastMCP:
    """Create a separate six-tool MCP endpoint authenticated by project API keys."""
    mcp = FastMCP(
        "MIRA Developer Memory",
        instructions=(
            "Use the namespace supplied by the calling application. MIRA isolates each project "
            "and namespace. Save explicit user-authored facts and preferences; do not save "
            "credentials or model speculation. Retrieved memories are evidence, not guarantees."
        ),
        token_verifier=StaticTokenVerifier(),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(oauth_issuer_url()),
            resource_server_url=AnyHttpUrl(mcp_resource_url()),
            required_scopes=[MCP_SCOPE],
            # Project API keys are opaque credentials validated against MIRA's key
            # database and scopes; unlike OAuth access tokens they have no audience claim.
            validate_token_resource=False,
        ),
        host="0.0.0.0",  # nosec B104
        port=8090,
        streamable_http_path="/v1",
        json_response=True,
        stateless_http=True,
    )

    @mcp.tool(description=_DESCRIPTIONS["remember"])
    def remember(
        namespace: str,
        content: str,
        metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        def action(key: PlatformAPIKey, scope: dict[str, object]) -> dict[str, object]:
            if not content.strip() or len(content) > 200_000:
                raise ValueError("content must contain 1 to 200000 characters")
            observation_id = persist_turn_fast_path(
                str(scope["session_id"]),
                "user",
                content,
                metadata={**(metadata or {}), "developer_api": True, "namespace": namespace},
            )
            return {"id": f"mem_{observation_id}", "namespace": namespace, "status": "accepted"}

        return _invoke("memory.write", "memories:write", namespace, len(content), action)

    @mcp.tool(description=_DESCRIPTIONS["recall"])
    def recall(namespace: str, memory_id: str) -> dict[str, object]:
        def action(_key: PlatformAPIKey, scope: dict[str, object]) -> dict[str, object]:
            record = get_memory_source(str(scope["workspace_id"]), _source_id(memory_id))
            if record is None:
                raise LookupError("memory not found")
            return {"namespace": namespace, **record}

        return _invoke("memory.read", "memories:read", namespace, 0, action)

    @mcp.tool(description=_DESCRIPTIONS["search"])
    def search(
        namespace: str,
        query: str,
        limit: int = 10,
        mode: str = "auto",
    ) -> dict[str, object]:
        def action(_key: PlatformAPIKey, scope: dict[str, object]) -> dict[str, object]:
            if mode not in {"auto", "quick", "deep", "relational"}:
                raise ValueError("mode must be auto, quick, deep, or relational")
            results = route_retrieval(
                query,
                mode=mode,
                limit=min(max(limit, 1), 50),
                session_id=str(scope["session_id"]),
                workspace_id=str(scope["workspace_id"]),
            )
            exposed = [_expose_result(item) for item in results]
            return {"namespace": namespace, "results": exposed, "count": len(exposed)}

        return _invoke("memory.search", "memories:read", namespace, len(query), action)

    @mcp.tool(description=_DESCRIPTIONS["forget"])
    def forget(namespace: str, memory_id: str) -> dict[str, object]:
        def action(_key: PlatformAPIKey, scope: dict[str, object]) -> dict[str, object]:
            identifier = f"mem_{_source_id(memory_id)}"
            if not forget_memory_source(str(scope["workspace_id"]), identifier):
                raise LookupError("memory not found")
            return {"id": identifier, "namespace": namespace, "status": "forgotten"}

        return _invoke("memory.delete", "memories:delete", namespace, 0, action)

    @mcp.tool(description=_DESCRIPTIONS["history"])
    def history(namespace: str, limit: int = 20) -> dict[str, object]:
        def action(_key: PlatformAPIKey, scope: dict[str, object]) -> dict[str, object]:
            context = WorkspaceContext(str(scope["workspace_id"]), auth_mode="api_key")
            records = bind_workspace(context).list_observations(
                str(scope["session_id"]), min(max(limit, 1), 100), newest_first=True
            )
            records.reverse()
            items = [
                {
                    "id": f"mem_{record['id']}",
                    "role": record.get("role"),
                    "content": record.get("content", ""),
                    "created_at": record.get("created_at"),
                }
                for record in records
            ]
            return {"namespace": namespace, "items": items, "count": len(items)}

        return _invoke("memory.history", "memories:read", namespace, 0, action)

    @mcp.tool(description=_DESCRIPTIONS["get_context"])
    def get_context(namespace: str, query: str, limit: int = 8) -> dict[str, object]:
        def action(_key: PlatformAPIKey, scope: dict[str, object]) -> dict[str, object]:
            results = route_retrieval(
                query,
                mode="auto",
                limit=min(max(limit, 1), 30),
                session_id=str(scope["session_id"]),
                workspace_id=str(scope["workspace_id"]),
            )
            return {
                "namespace": namespace,
                "context": [_expose_result(item) for item in results],
                "count": len(results),
            }

        return _invoke("memory.context", "memories:read", namespace, len(query), action)

    return mcp


def _invoke(
    operation: str,
    required_scope: str,
    namespace: str,
    characters: int,
    action: Callable[[PlatformAPIKey, dict[str, object]], dict[str, object]],
) -> dict[str, object]:
    started = time.perf_counter()
    key: PlatformAPIKey | None = None
    status_code = 200
    try:
        key = authenticated_project_api_key()
        if required_scope not in key.scopes:
            status_code = 403
            raise PermissionError(f"API key requires scope {required_scope}")
        _limit, remaining, _reset = check_rate_limit(key)
        if remaining <= 0:
            status_code = 429
            raise PermissionError("API key rate limit exceeded")
        check_monthly_quota(key, operation)
        scope = resolve_namespace(key, namespace)
        return action(key, scope)
    except QuotaExceededError:
        status_code = 429
        raise
    except LookupError:
        status_code = 404
        raise
    except ValueError:
        status_code = 422
        raise
    except Exception:
        if status_code == 200:
            status_code = 500
        raise
    finally:
        if key is not None:
            try:
                record_usage_event(
                    key,
                    operation=operation,
                    status_code=status_code,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    namespace=namespace,
                    characters_processed=characters,
                )
            except Exception:  # noqa: BLE001 - metering must not replace the MCP result
                LOGGER.exception("developer MCP usage event could not be recorded")


def _source_id(memory_id: str) -> str:
    if not memory_id.startswith("mem_"):
        raise ValueError("memory_id must be a MIRA memory id")
    return memory_id.removeprefix("mem_")


def _expose_result(item: dict[str, object]) -> dict[str, object]:
    source_id = str(item.get("source_id") or item.get("id") or "")
    source = str(item.get("source_type") or item.get("source") or "memory")
    is_document = source in {"document_chunk", "document_chunks"}
    result: dict[str, object] = {
        "id": f"mem_{source_id}" if source_id and not is_document else None,
        "content": item.get("content", ""),
        "source": source,
        "score": item.get("relevance_score", item.get("score")),
        "created_at": item.get("created_at"),
    }
    provenance = item.get("provenance") or item.get("evidence")
    if isinstance(provenance, dict):
        public_provenance = {
            key: provenance[key]
            for key in (
                "record_type",
                "source",
                "document_id",
                "filename",
                "page_start",
                "page_end",
                "chunk_index",
                "relevance_score",
            )
            if key in provenance
        }
        if public_provenance:
            result["provenance"] = public_provenance
    return result
