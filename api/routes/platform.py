"""Developer dashboard, public REST API, and billing routes."""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile

from api.auth import WorkspaceAuth, require_csrf
from api.platform_auth import APIKeyAuth, require_scope
from api.schemas.platform import (
    APIKeyCreate,
    BillingCancel,
    BillingSubscribe,
    OrganizationCreate,
    OrganizationUpdate,
    ProjectCreate,
    PublicMemorySearch,
    PublicMemoryWrite,
)
from core.knowledge.documents import (
    MAX_DOCUMENT_BYTES,
    DocumentProcessingError,
    DocumentStorageError,
    DocumentValidationError,
)
from core.knowledge.service import (
    delete_document,
    list_documents,
    process_document_upload,
)
from core.platform import billing
from core.platform.billing import BillingError
from core.platform.plans import plans
from core.platform.service import (
    ALLOWED_SCOPES,
    PlatformAPIKey,
    QuotaExceededError,
    api_key_usage_summary,
    check_monthly_quota,
    create_api_key,
    create_organization,
    create_project,
    forget_memory_source,
    get_memory_source,
    get_owned_organization,
    list_api_keys_for_user,
    list_namespace_summaries,
    list_organizations_for_user,
    list_projects_for_user,
    persist_memory,
    platform_overview,
    resolve_namespace,
    revoke_api_key,
    usage_summary,
)
from core.retrieval.router import route_retrieval

router = APIRouter(prefix="/platform", tags=["developer-platform"])
billing_router = APIRouter(prefix="/billing", tags=["billing"])
public_router = APIRouter(prefix="/v1", tags=["developer-api"])


@router.get("")
def get_platform_overview(
    auth: WorkspaceAuth,
    organization_id: str | None = None,
) -> dict[str, object]:
    user_id = _user_id(auth)
    organizations = list_organizations_for_user(user_id)
    if not organizations:
        raise HTTPException(status_code=500, detail="organization provisioning failed")
    selected_id = organization_id or str(organizations[0]["id"])
    try:
        overview = platform_overview(user_id, selected_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail="organization not found") from error
    return {"organizations": organizations, **overview}


@router.post("/organizations", status_code=201)
def post_organization(
    request: Request,
    payload: OrganizationCreate,
    auth: WorkspaceAuth,
) -> dict[str, object]:
    require_csrf(request, auth)
    try:
        return create_organization(_user_id(auth), payload.name)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.patch("/organizations/{organization_id}")
def patch_organization(
    organization_id: str,
    request: Request,
    payload: OrganizationUpdate,
    auth: WorkspaceAuth,
) -> dict[str, object]:
    require_csrf(request, auth)
    user_id = _user_id(auth)
    organization = get_owned_organization(user_id, organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="organization not found")
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="organization name must not be empty")
    from core.db.repositories import repository_connection
    from core.platform.service import now_iso

    with repository_connection() as connection:
        connection.execute(
            "UPDATE organizations SET name = ?, updated_at = ? WHERE id = ?",
            (name, now_iso(), organization_id),
        )
    return {"id": organization_id, "name": name}


@router.get("/projects")
def get_projects(auth: WorkspaceAuth, organization_id: str | None = None) -> dict[str, object]:
    return {"projects": list_projects_for_user(_user_id(auth), organization_id)}


@router.post("/projects", status_code=201)
def post_project(
    request: Request,
    payload: ProjectCreate,
    auth: WorkspaceAuth,
) -> dict[str, object]:
    require_csrf(request, auth)
    try:
        return create_project(
            _user_id(auth), payload.organization_id, payload.name, payload.environment
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail="organization not found") from error
    except QuotaExceededError as error:
        raise HTTPException(
            status_code=429,
            detail={"error": "quota_exceeded", "message": str(error), "limit": error.limit},
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/keys")
def get_api_keys(
    auth: WorkspaceAuth,
    organization_id: str | None = None,
) -> dict[str, object]:
    return {"api_keys": list_api_keys_for_user(_user_id(auth), organization_id)}


@router.post("/keys", status_code=201)
def post_api_key(
    request: Request,
    payload: APIKeyCreate,
    auth: WorkspaceAuth,
) -> dict[str, object]:
    require_csrf(request, auth)
    if set(payload.scopes) - ALLOWED_SCOPES:
        raise HTTPException(status_code=422, detail="unsupported API key scope")
    try:
        key, secret = create_api_key(
            _user_id(auth), payload.project_id, payload.name, payload.scopes, payload.expires_at
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail="project not found") from error
    except QuotaExceededError as error:
        raise HTTPException(
            status_code=429,
            detail={"error": "quota_exceeded", "message": str(error), "limit": error.limit},
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        "api_key": key,
        "secret": secret,
        "warning": "Copy this key now. You won't be able to see it again.",
    }


@router.delete("/keys/{key_id}", status_code=204)
def delete_api_key(key_id: str, request: Request, auth: WorkspaceAuth) -> None:
    require_csrf(request, auth)
    if not revoke_api_key(_user_id(auth), key_id):
        raise HTTPException(status_code=404, detail="API key not found")


@router.get("/usage")
def get_dashboard_usage(
    auth: WorkspaceAuth,
    organization_id: str = Query(min_length=1),
) -> dict[str, object]:
    try:
        return usage_summary(_user_id(auth), organization_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail="organization not found") from error


@router.get("/namespaces")
def get_namespaces(
    auth: WorkspaceAuth,
    organization_id: str = Query(min_length=1),
) -> dict[str, object]:
    try:
        return {"namespaces": list_namespace_summaries(_user_id(auth), organization_id)}
    except LookupError as error:
        raise HTTPException(status_code=404, detail="organization not found") from error


@router.get("/mcp")
def get_mcp_setup(auth: WorkspaceAuth) -> dict[str, object]:
    _user_id(auth)
    return {
        "endpoint": "/mcp/v1",
        "transport": "Streamable HTTP",
        "tools": ["remember", "recall", "search", "forget", "history", "get_context"],
        "authorization": "Bearer MIRA project API key",
        "namespace_argument": "namespace",
    }


@billing_router.get("/subscription")
def get_subscription(
    auth: WorkspaceAuth,
    organization_id: str = Query(min_length=1),
) -> dict[str, object]:
    organization = get_owned_organization(_user_id(auth), organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="organization not found")
    return {
        "organization_id": organization_id,
        "plan": organization["plan"],
        "subscription_status": organization["subscription_status"],
        "billing_currency": organization["billing_currency"],
        "current_period_end": organization["current_period_end"],
        "monthly_price_minor": plans().get(str(organization["plan"]), plans()["free"])[
            "monthly_price_minor"
        ],
        "public_key_configured": bool(_paystack_public_key()),
    }


@billing_router.post("/subscribe")
def subscribe(
    request: Request,
    payload: BillingSubscribe,
    auth: WorkspaceAuth,
) -> dict[str, str]:
    require_csrf(request, auth)
    try:
        return billing.initialize_checkout(
            _user_id(auth), payload.organization_id, payload.plan, payload.email
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail="organization not found") from error
    except BillingError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@billing_router.post("/cancel")
def cancel_subscription(
    request: Request,
    payload: BillingCancel,
    auth: WorkspaceAuth,
) -> dict[str, str]:
    require_csrf(request, auth)
    try:
        return billing.cancel_subscription(_user_id(auth), payload.organization_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail="organization not found") from error
    except BillingError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@billing_router.post("/webhook/paystack")
async def paystack_webhook(request: Request) -> dict[str, object]:
    raw_body = await request.body()
    if not billing.verify_webhook_signature(raw_body, request.headers):
        raise HTTPException(status_code=401, detail="invalid webhook signature")
    try:
        event = json.loads(raw_body)
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=400, detail="invalid webhook payload") from error
    if not isinstance(event, dict):
        raise HTTPException(status_code=400, detail="invalid webhook payload")
    processed = billing.process_webhook(event, raw_body)
    return {"received": True, "duplicate": not processed}


@public_router.get("/health")
def public_api_health() -> dict[str, str]:
    return {"status": "ok", "service": "mira-public-api", "version": "v1"}


@public_router.post("/memories", status_code=201)
def write_memory(
    request: Request, payload: PublicMemoryWrite, api_key: APIKeyAuth
) -> dict[str, str]:
    request.state.platform_operation = "memory.write"
    request.state.platform_namespace = payload.namespace
    request.state.platform_characters = len(payload.content)
    require_scope(api_key, "memories:write")
    try:
        check_monthly_quota(api_key, "memory.write")
        observation_id = persist_memory(
            api_key, payload.namespace, payload.content, payload.metadata
        )
    except QuotaExceededError as error:
        raise _quota_http_error(error) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"id": f"mem_{observation_id}", "namespace": payload.namespace, "status": "accepted"}


@public_router.post("/memories/search")
def search_memories(
    request: Request,
    payload: PublicMemorySearch,
    api_key: APIKeyAuth,
) -> dict[str, object]:
    request.state.platform_operation = "memory.search"
    request.state.platform_namespace = payload.namespace
    request.state.platform_characters = len(payload.query)
    require_scope(api_key, "memories:read")
    try:
        check_monthly_quota(api_key, "memory.search")
        scope = resolve_namespace(api_key, payload.namespace)
        results = route_retrieval(
            payload.query,
            mode=payload.mode,
            limit=payload.limit,
            session_id=str(scope["session_id"]),
            workspace_id=str(scope["workspace_id"]),
        )
    except QuotaExceededError as error:
        raise _quota_http_error(error) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    exposed = [_public_evidence(item) for item in results]
    return {
        "namespace": payload.namespace,
        "mode": payload.mode,
        "results": exposed,
        "count": len(exposed),
    }


@public_router.get("/memories/{memory_id}")
def read_memory(
    memory_id: str,
    request: Request,
    *,
    namespace: str = Query(min_length=1, max_length=128),
    api_key: APIKeyAuth,
) -> dict[str, object]:
    request.state.platform_operation = "memory.read"
    request.state.platform_namespace = namespace
    require_scope(api_key, "memories:read")
    scope = _resolve_namespace_or_404(api_key, namespace)
    source_id = _memory_source_id(memory_id)
    record = get_memory_source(str(scope["workspace_id"]), source_id)
    if record is None:
        raise HTTPException(status_code=404, detail="memory not found")
    return {"namespace": namespace, **record}


@public_router.delete("/memories/{memory_id}")
def remove_memory(
    memory_id: str,
    request: Request,
    *,
    namespace: str = Query(min_length=1, max_length=128),
    api_key: APIKeyAuth,
) -> dict[str, object]:
    request.state.platform_operation = "memory.delete"
    request.state.platform_namespace = namespace
    require_scope(api_key, "memories:delete")
    scope = _resolve_namespace_or_404(api_key, namespace)
    removed = forget_memory_source(
        str(scope["workspace_id"]), f"mem_{_memory_source_id(memory_id)}"
    )
    if not removed:
        raise HTTPException(status_code=404, detail="memory not found")
    return {"id": memory_id, "namespace": namespace, "status": "forgotten"}


@public_router.post("/documents", status_code=201)
async def upload_document(
    request: Request,
    *,
    namespace: str = Form(min_length=1, max_length=128),
    file: UploadFile = File(),  # noqa: B008
    api_key: APIKeyAuth,
) -> dict[str, object]:
    request.state.platform_operation = "document.upload"
    request.state.platform_namespace = namespace
    require_scope(api_key, "documents:write")
    try:
        scope = resolve_namespace(api_key, namespace)
        content = await file.read(MAX_DOCUMENT_BYTES + 1)
        if len(content) > MAX_DOCUMENT_BYTES:
            raise HTTPException(status_code=413, detail="document exceeds the 10 MB upload limit")
        result = process_document_upload(
            workspace_id=str(scope["workspace_id"]),
            knowledge_base_id=str(scope["knowledge_base_id"]),
            filename=file.filename or "upload.txt",
            content=content,
            mime_type=file.content_type,
        )
        request.state.platform_bytes_ingested = len(content)
        character_count = result.get("character_count")
        request.state.platform_characters = (
            character_count if isinstance(character_count, int) else 0
        )
        return {"namespace": namespace, "document": _public_document(result)}
    except DocumentValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except DocumentStorageError as error:
        raise HTTPException(status_code=502, detail="document storage failed") from error
    except DocumentProcessingError as error:
        raise HTTPException(status_code=422, detail="document could not be processed") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@public_router.get("/documents")
def get_documents(
    request: Request,
    *,
    namespace: str = Query(min_length=1, max_length=128),
    api_key: APIKeyAuth,
) -> dict[str, object]:
    request.state.platform_operation = "document.list"
    request.state.platform_namespace = namespace
    require_scope(api_key, "documents:read")
    scope = resolve_namespace(api_key, namespace)
    return {
        "namespace": namespace,
        "documents": [
            _public_document(document)
            for document in list_documents(
                workspace_id=str(scope["workspace_id"]),
                knowledge_base_id=str(scope["knowledge_base_id"]),
            )
        ],
    }


@public_router.delete("/documents/{document_id}")
def remove_document(
    document_id: str,
    request: Request,
    *,
    namespace: str = Query(min_length=1, max_length=128),
    api_key: APIKeyAuth,
) -> dict[str, object]:
    request.state.platform_operation = "document.delete"
    request.state.platform_namespace = namespace
    require_scope(api_key, "documents:delete")
    scope = _resolve_namespace_or_404(api_key, namespace)
    try:
        result = delete_document(workspace_id=str(scope["workspace_id"]), document_id=document_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail="document not found") from error
    except (DocumentStorageError, DocumentProcessingError) as error:
        raise HTTPException(status_code=502, detail="document could not be deleted") from error
    return {"namespace": namespace, "document": _public_document(result)}


@public_router.get("/usage")
def get_public_usage(request: Request, api_key: APIKeyAuth) -> dict[str, object]:
    request.state.platform_operation = "usage.read"
    require_scope(api_key, "usage:read")
    return api_key_usage_summary(api_key)


def _resolve_namespace_or_404(api_key: PlatformAPIKey, namespace: str) -> dict[str, object]:
    try:
        return resolve_namespace(api_key, namespace)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _public_evidence(item: dict[str, object]) -> dict[str, object]:
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


def _public_document(item: dict[str, object]) -> dict[str, object]:
    """Expose document status and display metadata without storage/internal identifiers."""
    allowed = (
        "id",
        "filename",
        "mime_type",
        "size_bytes",
        "status",
        "page_count",
        "character_count",
        "chunk_count",
        "created_at",
        "processed_at",
    )
    return {key: item[key] for key in allowed if key in item}


def _memory_source_id(memory_id: str) -> str:
    if not memory_id.startswith("mem_") or not re.fullmatch(r"mem_[A-Za-z0-9_-]{8,100}", memory_id):
        raise HTTPException(status_code=404, detail="memory not found")
    return memory_id.removeprefix("mem_")


def _quota_http_error(error: QuotaExceededError) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail={
            "error": "quota_exceeded",
            "message": str(error),
            "used": error.used,
            "limit": error.limit,
        },
    )


def _user_id(auth: object) -> str:
    context = getattr(auth, "context", None)
    user_id = getattr(context, "user_id", None)
    if not isinstance(user_id, str) or not user_id:
        raise HTTPException(status_code=403, detail="a signed-in MIRA user is required")
    return user_id


def _paystack_public_key() -> str:
    import os

    return os.environ.get("PAYSTACK_PUBLIC_KEY", "").strip()
