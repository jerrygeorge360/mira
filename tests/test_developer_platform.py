"""Isolation, API key, usage, webhook, and MCP tests for the public platform layer."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.db.evidence import register_source
from core.db.repositories import configure_database, create_user, repository_connection
from core.db.schema import initialize_database
from core.evidence.source import resolve_source
from core.platform import billing
from core.platform.service import (
    PlatformAPIKey,
    authenticate_api_key,
    create_api_key,
    create_project,
    ensure_user_platform,
    get_memory_source,
    persist_memory,
    resolve_namespace,
    resolve_project_knowledge,
    revoke_api_key,
)


@pytest.fixture
def platform_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, str]]:
    database_path = tmp_path / "platform.sqlite3"
    monkeypatch.setenv("MIRA_DB_PATH", str(database_path))
    monkeypatch.delenv("MIRA_PLAN_LIMITS_JSON", raising=False)
    monkeypatch.delenv("PAYSTACK_SECRET_KEY", raising=False)
    monkeypatch.delenv("PAYSTACK_WEBHOOK_SECRET", raising=False)
    configure_database(database_path)
    user_id = create_user(github_id="platform-test-user", github_login="platform-test")
    organization_id, project_id = ensure_user_platform(user_id, "platform-test")
    yield {
        "database": str(database_path),
        "user_id": user_id,
        "organization_id": organization_id,
        "project_id": project_id,
    }


def _key(
    state: dict[str, str], scopes: list[str] | None = None, *, project_id: str | None = None
) -> tuple[dict[str, object], str]:
    key, secret = create_api_key(
        state["user_id"],
        project_id or state["project_id"],
        "test key",
        scopes or ["memories:read", "memories:write", "memories:delete", "usage:read"],
    )
    return key, secret


def test_existing_users_receive_a_default_platform_on_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "legacy.sqlite3"
    monkeypatch.setenv("MIRA_DB_PATH", str(database_path))
    configure_database(database_path)
    user_id = create_user(github_id="legacy-platform-user", github_login="legacy")

    initialize_database(database_path)

    with repository_connection() as connection:
        organization = connection.execute(
            "SELECT id FROM organizations WHERE owner_user_id = ?", (user_id,)
        ).fetchone()
        assert organization is not None
        project = connection.execute(
            "SELECT environment FROM projects WHERE organization_id = ?",
            (organization["id"],),
        ).fetchone()
    assert project["environment"] == "production"


def test_api_key_hash_authentication_and_immediate_revocation(
    platform_state: dict[str, str],
) -> None:
    key, secret = _key(platform_state)
    assert secret.startswith("mira_live_")
    assert key["prefix"] != secret

    with repository_connection() as connection:
        stored = connection.execute(
            "SELECT key_hash FROM api_keys WHERE id = ?", (key["id"],)
        ).fetchone()
    assert stored is not None
    assert stored["key_hash"] == hashlib.sha256(secret.encode()).hexdigest()
    assert secret not in str(stored["key_hash"])
    assert authenticate_api_key(secret) is not None

    assert revoke_api_key(platform_state["user_id"], str(key["id"]))
    assert authenticate_api_key(secret) is None
    assert not revoke_api_key(platform_state["user_id"], str(key["id"]))


def test_expired_api_key_is_rejected(platform_state: dict[str, str]) -> None:
    key, secret = _key(platform_state)
    with repository_connection() as connection:
        connection.execute(
            "UPDATE api_keys SET expires_at = '2000-01-01T00:00:00+00:00' WHERE id = ?",
            (key["id"],),
        )
    assert authenticate_api_key(secret) is None


def test_project_and_namespace_isolation_reuses_internal_workspaces(
    platform_state: dict[str, str],
) -> None:
    with repository_connection() as connection:
        connection.execute(
            "UPDATE organizations SET plan = 'developer' WHERE id = ?",
            (platform_state["organization_id"],),
        )
    second_project = create_project(
        platform_state["user_id"],
        platform_state["organization_id"],
        "Second app",
        "production",
    )
    key_a, _secret_a = _key(platform_state)
    key_a2, _secret_a2 = _key(platform_state)
    key_c, _secret_c = _key(platform_state, project_id=str(second_project["id"]))
    other_user_id = create_user(github_id="other-platform-customer", github_login="other")
    other_org_id, other_project_id = ensure_user_platform(other_user_id, "other")
    other_customer = {
        "user_id": other_user_id,
        "organization_id": other_org_id,
        "project_id": other_project_id,
    }
    key_b, _secret_b = _key(other_customer)

    same_a = resolve_namespace(api_key_from_token_for_test(key_a), "student_123")
    same_a2 = resolve_namespace(api_key_from_token_for_test(key_a2), "student_123")
    same_c = resolve_namespace(api_key_from_token_for_test(key_c), "student_123")
    same_b = resolve_namespace(api_key_from_token_for_test(key_b), "student_123")
    assert same_a["workspace_id"] == same_a2["workspace_id"]
    assert same_a["workspace_id"] != same_b["workspace_id"]
    assert same_a["workspace_id"] != same_c["workspace_id"]

    memory_id = persist_memory(
        api_key_from_token_for_test(key_a), "student_123", "Private note", {}
    )
    assert get_memory_source(str(same_a["workspace_id"]), memory_id) is not None
    assert get_memory_source(str(same_b["workspace_id"]), memory_id) is None


def test_project_knowledge_workspace_is_registered_for_project_allowlists(
    platform_state: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _key_record, secret = _key(platform_state)
    api_key = authenticate_api_key(secret)
    assert api_key is not None

    scope = resolve_project_knowledge(api_key)

    with repository_connection() as connection:
        mapping = connection.execute(
            "SELECT project_id, workspace_id, knowledge_base_id "
            "FROM project_knowledge_workspaces WHERE project_id = ?",
            (platform_state["project_id"],),
        ).fetchone()
    assert tuple(mapping) == (
        platform_state["project_id"],
        scope["workspace_id"],
        scope["knowledge_base_id"],
    )
    now = "2026-11-16T00:00:00+00:00"
    with repository_connection() as connection:
        connection.execute(
            "INSERT INTO documents (id, workspace_id, knowledge_base_id, filename, mime_type, "
            "size_bytes, s3_bucket, s3_key, checksum_sha256, status, created_at, updated_at) "
            "VALUES ('project-document', ?, ?, 'shared.txt', 'text/plain', 4, 'bucket', "
            "'project-key', 'hash', 'ready', ?, ?)",
            (scope["workspace_id"], scope["knowledge_base_id"], now, now),
        )
        connection.execute(
            "INSERT INTO document_chunks (id, workspace_id, knowledge_base_id, document_id, "
            "chunk_index, content, created_at) VALUES ('project-chunk', ?, ?, "
            "'project-document', 0, 'Shared project text.', ?)",
            (scope["workspace_id"], scope["knowledge_base_id"], now),
        )
    source_id = register_source(
        "document_chunk", "project-chunk", workspace_id=scope["workspace_id"]
    )
    source = resolve_source(source_id, workspace_id=scope["workspace_id"])
    assert source["project_id"] == platform_state["project_id"]
    assert source["namespace"] is None

    monkeypatch.setenv("MIRA_DOCUMENT_ENRICHMENT_ENABLED", "true")
    monkeypatch.setenv("MIRA_DOCUMENT_ENRICHMENT_WORKSPACE_IDS", "")
    monkeypatch.setenv("MIRA_DOCUMENT_ENRICHMENT_PROJECT_IDS", platform_state["project_id"])
    from core.knowledge.enrichment import enrichment_enabled_for_workspace

    assert enrichment_enabled_for_workspace(scope["workspace_id"])


def test_public_rest_enforces_scope_revocation_and_usage_metering(
    platform_state: dict[str, str],
) -> None:
    _key_record, secret = _key(platform_state, ["memories:write"])
    from api.main import create_app

    with TestClient(create_app()) as client:
        unauthorized = client.post(
            "/v1/memories",
            json={"namespace": "student_123", "content": "A private memory."},
        )
        assert unauthorized.status_code == 401

        written = client.post(
            "/v1/memories",
            headers={"Authorization": f"Bearer {secret}"},
            json={"namespace": "student_123", "content": "A private memory."},
        )
        assert written.status_code == 201, written.text
        assert written.json()["status"] == "accepted"
        assert written.headers["X-RateLimit-Limit"] == "60"

        no_read_scope = client.post(
            "/v1/memories/search",
            headers={"Authorization": f"Bearer {secret}"},
            json={"namespace": "student_123", "query": "private"},
        )
        assert no_read_scope.status_code == 403

    with repository_connection() as connection:
        events = connection.execute(
            "SELECT operation, status_code, namespace FROM usage_events ORDER BY created_at"
        ).fetchall()
    assert [(row["operation"], row["status_code"]) for row in events] == [
        ("memory.write", 201),
        ("memory.search", 403),
    ]
    assert all(row["namespace"] == "student_123" for row in events)


def test_public_rest_search_returns_namespace_bound_evidence(
    platform_state: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _key_record, secret = _key(platform_state, ["memories:read", "documents:read"])
    import api.routes.platform as platform_routes
    from api.main import create_app

    captured: dict[str, object] = {}

    def fake_retrieval(
        query: str,
        *,
        mode: str,
        limit: int,
        session_id: str,
        workspace_id: str,
        include_documents: bool,
        allowed_knowledge_base_ids: tuple[str, ...],
    ) -> list[dict[str, object]]:
        captured.update(
            query=query,
            mode=mode,
            limit=limit,
            session_id=session_id,
            workspace_id=workspace_id,
            include_documents=include_documents,
            allowed_knowledge_base_ids=allowed_knowledge_base_ids,
        )
        return [
            {
                "source_id": "obs_private123",
                "content": "Quadratic equations need more practice.",
                "source_type": "observation",
                "relevance_score": 0.93,
                "provenance": {
                    "record_type": "observation",
                    "record_id": "obs_private123",
                    "session_id": session_id,
                },
            },
            {
                "source_id": "chunk_internal",
                "source": "document_chunks",
                "content": "Citation from the private study guide.",
                "document_id": "doc_public123",
                "filename": "study-guide.pdf",
                "page_start": 4,
                "provenance": {
                    "source": "document",
                    "document_id": "doc_public123",
                    "filename": "study-guide.pdf",
                    "page_start": 4,
                    "knowledge_base_id": "kb_internal",
                    "chunk_id": "chunk_internal",
                },
            },
        ]

    monkeypatch.setattr(platform_routes, "route_retrieval", fake_retrieval)
    with TestClient(create_app()) as client:
        response = client.post(
            "/v1/memories/search",
            headers={"Authorization": f"Bearer {secret}"},
            json={"namespace": "student_123", "query": "What should be revised?"},
        )
    assert response.status_code == 200, response.text
    assert response.json()["results"][0]["id"] == "mem_obs_private123"
    assert response.json()["results"][0]["provenance"] == {"record_type": "observation"}
    document_result = response.json()["results"][1]
    assert document_result["id"] is None
    assert document_result["provenance"] == {
        "source": "document",
        "document_id": "doc_public123",
        "filename": "study-guide.pdf",
        "page_start": 4,
    }
    assert (
        captured["workspace_id"]
        == resolve_namespace(
            authenticate_api_key(secret),
            "student_123",  # type: ignore[arg-type]
        )["workspace_id"]
    )
    assert captured["include_documents"] is True
    scope = resolve_namespace(authenticate_api_key(secret), "student_123")  # type: ignore[arg-type]
    assert captured["allowed_knowledge_base_ids"] == (scope["knowledge_base_id"],)


def test_public_search_document_scope_preserves_memory_only_access(
    platform_state: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import core.retrieval.quick as quick
    from api.main import create_app

    _memory_record, memory_secret = _key(platform_state, ["memories:read"])
    _document_record, document_secret = _key(platform_state, ["memories:read", "documents:read"])
    memory_key = authenticate_api_key(memory_secret)
    assert memory_key is not None
    scope = resolve_namespace(memory_key, "student_123")
    persist_memory(memory_key, "student_123", "Private study note.", {})

    calls: list[str | None] = []

    def fake_documents(
        _query: str,
        *,
        workspace_id: str,
        limit: int,
        knowledge_base_id: str | None = None,
    ) -> list[dict[str, object]]:
        assert workspace_id == scope["workspace_id"]
        calls.append(knowledge_base_id)
        return [
            {
                "chunk_id": "chunk_private",
                "knowledge_base_id": knowledge_base_id,
                "document_id": "doc_private",
                "content": "Private document text.",
                "record": {"id": "chunk_private", "workspace_id": workspace_id},
            }
        ]

    monkeypatch.setattr(quick, "retrieve_document_chunks", fake_documents)
    monkeypatch.setattr(quick, "_semantic_candidates", lambda *args, **kwargs: [])
    with TestClient(create_app()) as client:

        def search(secret: str) -> dict[str, object]:
            response = client.post(
                "/v1/memories/search",
                headers={"Authorization": f"Bearer {secret}"},
                json={"namespace": "student_123", "query": "private study note", "mode": "quick"},
            )
            assert response.status_code == 200, response.text
            return response.json()

        memory_results = search(memory_secret)["results"]
        assert any("Private study note" in item["content"] for item in memory_results)
        assert all("Private document text" not in item["content"] for item in memory_results)
        assert calls == []

        document_results = search(document_secret)["results"]
        assert any("Private document text" in item["content"] for item in document_results)
        assert calls == [scope["knowledge_base_id"]]


def test_developer_mcp_search_and_context_guard_documents(
    platform_state: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import core.retrieval.quick as quick
    import core.retrieval.router as retrieval_router
    import integrations.mcp.developer as developer_mcp

    _memory_record, memory_secret = _key(platform_state, ["memories:read"])
    _document_record, document_secret = _key(platform_state, ["memories:read", "documents:read"])
    memory_key = authenticate_api_key(memory_secret)
    document_key = authenticate_api_key(document_secret)
    assert memory_key is not None and document_key is not None
    scope = resolve_namespace(memory_key, "student_123")
    calls: list[str | None] = []

    def fake_documents(
        _query: str,
        *,
        workspace_id: str,
        limit: int,
        knowledge_base_id: str | None = None,
    ) -> list[dict[str, object]]:
        assert workspace_id == scope["workspace_id"]
        calls.append(knowledge_base_id)
        return [
            {
                "chunk_id": "chunk_private",
                "knowledge_base_id": knowledge_base_id,
                "document_id": "doc_private",
                "content": "Private document text.",
                "record": {"id": "chunk_private", "workspace_id": workspace_id},
            }
        ]

    monkeypatch.setattr(quick, "retrieve_document_chunks", fake_documents)
    monkeypatch.setattr(quick, "_semantic_candidates", lambda *args, **kwargs: [])
    monkeypatch.setattr(retrieval_router, "choose_retrieval_mode", lambda *args: {"mode": "quick"})
    server = developer_mcp.create_developer_mcp_server()
    search = server._tool_manager._tools["search"].fn
    get_context = server._tool_manager._tools["get_context"].fn

    monkeypatch.setattr(developer_mcp, "authenticated_project_api_key", lambda: memory_key)
    for result in (
        search(namespace="student_123", query="private document", mode="quick"),
        get_context(namespace="student_123", query="private document"),
    ):
        assert result["count"] == 0
    assert calls == []

    monkeypatch.setattr(developer_mcp, "authenticated_project_api_key", lambda: document_key)
    search_result = search(namespace="student_123", query="private document", mode="quick")
    context_result = get_context(namespace="student_123", query="private document")
    assert search_result["results"][0]["content"] == "Private document text."
    assert context_result["context"][0]["content"] == "Private document text."
    assert calls == [scope["knowledge_base_id"], scope["knowledge_base_id"]]


def test_public_document_upload_uses_shared_knowledge_service_and_meters_file_bytes(
    platform_state: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _key_record, secret = _key(platform_state, ["documents:write"])
    import api.routes.platform as platform_routes
    from api.main import create_app

    file_contents = b"MIRA developer platform test document."
    monkeypatch.setattr(
        platform_routes,
        "process_document_upload",
        lambda **kwargs: {
            "id": "doc_test_upload",
            "filename": kwargs["filename"],
            "status": "processed",
            "character_count": len(kwargs["content"]),
            "workspace_id": "internal_workspace",
            "s3_key": "private/object/key.txt",
        },
    )
    with TestClient(create_app()) as client:
        response = client.post(
            "/v1/documents",
            headers={"Authorization": f"Bearer {secret}"},
            data={"namespace": "student_123"},
            files={"file": ("notes.txt", file_contents, "text/plain")},
        )
    assert response.status_code == 201, response.text
    assert response.json()["document"]["id"] == "doc_test_upload"
    assert "workspace_id" not in response.json()["document"]
    assert "s3_key" not in response.json()["document"]
    with repository_connection() as connection:
        usage = connection.execute(
            "SELECT operation, bytes_ingested, namespace FROM usage_events"
        ).fetchone()
    assert usage["operation"] == "document.upload"
    assert usage["bytes_ingested"] == len(file_contents)
    assert usage["namespace"] == "student_123"


def test_usage_quota_is_centralized_and_counts_successful_operations(
    platform_state: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.platform.service import QuotaExceededError, check_monthly_quota, record_usage_event

    key_record, _secret = _key(platform_state)
    key = authenticate_api_key(_secret)
    assert key is not None
    monkeypatch.setenv("MIRA_PLAN_LIMITS_JSON", '{"free":{"memory_writes_monthly":1}}')
    record_usage_event(key, operation="memory.write", status_code=201, latency_ms=1)
    with pytest.raises(QuotaExceededError, match="Monthly memory.write limit reached"):
        check_monthly_quota(key, "memory.write")
    monkeypatch.setenv("MIRA_PLAN_LIMITS_JSON", '{"free":{"retrievals_monthly":1}}')
    record_usage_event(key, operation="memory.search", status_code=403, latency_ms=1)
    check_monthly_quota(key, "memory.search")
    record_usage_event(key, operation="memory.context", status_code=200, latency_ms=1)
    with pytest.raises(QuotaExceededError, match="Monthly memory.search limit reached"):
        check_monthly_quota(key, "memory.search")
    assert key_record["id"] == key.id


def test_per_key_rate_limit_returns_reset_headers(platform_state: dict[str, str]) -> None:
    from core.platform.service import record_usage_event

    _key_record, secret = _key(platform_state)
    api_key = authenticate_api_key(secret)
    assert api_key is not None
    for _ in range(60):
        record_usage_event(api_key, operation="memory.read", status_code=200, latency_ms=1)

    from api.main import create_app

    with TestClient(create_app()) as client:
        response = client.get("/v1/usage", headers={"Authorization": f"Bearer {secret}"})
    assert response.status_code == 429
    assert response.headers["X-RateLimit-Limit"] == "60"
    assert response.headers["X-RateLimit-Remaining"] == "0"
    assert 1 <= int(response.headers["Retry-After"]) <= 60


def test_paystack_checkout_uses_configured_plan_and_only_webhook_upgrades(
    platform_state: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx

    monkeypatch.setenv("PAYSTACK_SECRET_KEY", "sk_test_example")
    monkeypatch.setenv("PAYSTACK_DEVELOPER_PLAN_CODE", "PLN_developer_example")
    captured: dict[str, object] = {}

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        captured["url"] = url
        captured["kwargs"] = kwargs
        return httpx.Response(
            200,
            json={
                "status": True,
                "data": {
                    "authorization_url": "https://checkout.paystack.com/example",
                    "reference": "ignored-provider-reference",
                },
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(billing.httpx, "post", fake_post)
    checkout = billing.initialize_checkout(
        platform_state["user_id"],
        platform_state["organization_id"],
        "developer",
        "user@example.com",
    )
    assert checkout["authorization_url"].startswith("https://checkout.paystack.com/")
    assert re.fullmatch(r"mira-[0-9a-f]{48}", checkout["reference"])
    assert captured["url"] == "https://api.paystack.co/transaction/initialize"
    assert captured["kwargs"]["json"]["plan"] == "PLN_developer_example"  # type: ignore[index]

    with repository_connection() as connection:
        org_before = connection.execute(
            "SELECT plan FROM organizations WHERE id = ?", (platform_state["organization_id"],)
        ).fetchone()
    assert org_before["plan"] == "free"

    event = {
        "event": "charge.success",
        "data": {
            "reference": checkout["reference"],
            "status": "success",
            "customer": {"customer_code": "CUS_platform"},
            "subscription": {"subscription_code": "SUB_platform"},
        },
    }
    raw = json.dumps(event, separators=(",", ":")).encode()
    assert billing.process_webhook(event, raw)
    assert not billing.process_webhook(event, raw)
    with repository_connection() as connection:
        organization = connection.execute(
            """SELECT plan, subscription_status, paystack_customer_code
               FROM organizations WHERE id = ?""",
            (platform_state["organization_id"],),
        ).fetchone()
    assert organization["plan"] == "developer"
    assert organization["subscription_status"] == "active"
    assert organization["paystack_customer_code"] == "CUS_platform"


def test_paystack_webhook_signature_uses_raw_body_timestamp_and_constant_time_hex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime

    secret = "whsec_platform_test"
    monkeypatch.setenv("PAYSTACK_WEBHOOK_SECRET", secret)
    timestamp = str(int(datetime.now(UTC).timestamp()))
    raw_body = b'{"event":"charge.success","data":{"amount":1500000}}'
    digest = hmac.new(
        secret.encode(), timestamp.encode() + b"." + raw_body, hashlib.sha512
    ).hexdigest()
    header = {"Paystack-Signature": f"t={timestamp},v1=whk_test:{digest}"}
    assert billing.verify_webhook_signature(raw_body, header)
    assert not billing.verify_webhook_signature(raw_body + b" ", header)
    assert not billing.verify_webhook_signature(raw_body, {"Paystack-Signature": "bad"})


def test_paystack_cancellation_and_failed_payment_update_subscription_state(
    platform_state: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx

    monkeypatch.setenv("PAYSTACK_SECRET_KEY", "sk_test_example")
    with repository_connection() as connection:
        connection.execute(
            """UPDATE organizations SET plan = 'developer',
               paystack_subscription_code = 'SUB_platform' WHERE id = ?""",
            (platform_state["organization_id"],),
        )

    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        assert url.endswith("/subscription/SUB_platform/manage/link")
        assert kwargs["headers"] == {"Authorization": "Bearer sk_test_example"}
        return httpx.Response(
            200,
            json={"status": True, "data": {"link": "https://paystack.com/manage/example"}},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(billing.httpx, "get", fake_get)
    result = billing.cancel_subscription(
        platform_state["user_id"], platform_state["organization_id"]
    )
    assert result["manage_url"] == "https://paystack.com/manage/example"

    failed_event = {
        "event": "invoice.payment_failed",
        "data": {"subscription_code": "SUB_platform"},
    }
    raw = json.dumps(failed_event, separators=(",", ":")).encode()
    assert billing.process_webhook(failed_event, raw)
    with repository_connection() as connection:
        organization = connection.execute(
            "SELECT plan, subscription_status FROM organizations WHERE id = ?",
            (platform_state["organization_id"],),
        ).fetchone()
    assert organization["plan"] == "developer"
    assert organization["subscription_status"] == "past_due"

    not_renew_event = {
        "event": "subscription.not_renew",
        "data": {"subscription_code": "SUB_platform", "next_payment_date": "2027-01-01"},
    }
    not_renew_raw = json.dumps(not_renew_event, separators=(",", ":")).encode()
    assert billing.process_webhook(not_renew_event, not_renew_raw)
    with repository_connection() as connection:
        organization = connection.execute(
            "SELECT plan, subscription_status, current_period_end FROM organizations WHERE id = ?",
            (platform_state["organization_id"],),
        ).fetchone()
    assert organization["plan"] == "developer"
    assert organization["subscription_status"] == "cancelled"
    assert organization["current_period_end"] == "2027-01-01"

    disable_event = {
        "event": "subscription.disable",
        "data": {"subscription_code": "SUB_platform"},
    }
    disable_raw = json.dumps(disable_event, separators=(",", ":")).encode()
    assert billing.process_webhook(disable_event, disable_raw)
    with repository_connection() as connection:
        organization = connection.execute(
            """SELECT plan, subscription_status, paystack_subscription_code
               FROM organizations WHERE id = ?""",
            (platform_state["organization_id"],),
        ).fetchone()
    assert organization["plan"] == "free"
    assert organization["subscription_status"] == "cancelled"
    assert organization["paystack_subscription_code"] is None


@pytest.mark.asyncio
async def test_project_api_key_verifies_for_separate_mcp_tool_surface(
    platform_state: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import integrations.mcp.developer as developer_mcp
    from integrations.mcp.auth import StaticTokenVerifier
    from integrations.mcp.developer import create_developer_mcp_server

    _key_record, secret = _key(platform_state, ["memories:read", "memories:write"])
    access_token = await StaticTokenVerifier().verify_token(secret)
    assert access_token is not None
    assert access_token.claims["project_id"] == platform_state["project_id"]
    assert {"mira:memory", "memories:read", "memories:write"} <= set(access_token.scopes)

    server = create_developer_mcp_server()
    tools = {tool.name for tool in await server.list_tools()}
    assert tools == {"remember", "recall", "search", "forget", "history", "get_context"}

    first_key = authenticate_api_key(secret)
    assert first_key is not None
    remember = server._tool_manager._tools["remember"].fn
    monkeypatch.setattr(developer_mcp, "authenticated_project_api_key", lambda: first_key)
    saved = remember(
        namespace="shared_agent_user",
        content="The user prefers concise explanations.",
        metadata={"namespace": "forged", "developer_api": False},
    )
    source_id = str(saved["id"]).removeprefix("mem_")
    namespace = resolve_namespace(first_key, "shared_agent_user")
    memory = get_memory_source(str(namespace["workspace_id"]), source_id)
    assert memory is not None
    assert memory["content"] == "The user prefers concise explanations."
    with repository_connection() as connection:
        metadata = connection.execute(
            "SELECT metadata_json FROM observations WHERE id = ?", (source_id,)
        ).fetchone()
    assert json.loads(metadata["metadata_json"]) == {
        "developer_api": True,
        "namespace": "shared_agent_user",
    }
    remember(
        namespace="shared_agent_user",
        content="The learner prefers worked examples.",
    )
    history = server._tool_manager._tools["history"].fn(namespace="shared_agent_user", limit=1)
    assert history["items"][0]["content"] == "The learner prefers worked examples."

    second_key_record, second_secret = _key(platform_state, ["memories:read"])
    second_key = authenticate_api_key(second_secret)
    assert second_key is not None
    assert second_key_record["project_id"] == first_key.project_id
    monkeypatch.setattr(developer_mcp, "authenticated_project_api_key", lambda: second_key)
    recalled = server._tool_manager._tools["recall"].fn(
        namespace="shared_agent_user", memory_id=str(saved["id"])
    )
    assert recalled["content"] == memory["content"]

    with repository_connection() as connection:
        connection.execute(
            "UPDATE organizations SET plan = 'developer' WHERE id = ?",
            (platform_state["organization_id"],),
        )
    other_project = create_project(
        platform_state["user_id"],
        platform_state["organization_id"],
        "Isolated MCP project",
        "production",
    )
    _other_key_record, other_secret = _key(
        platform_state, ["memories:read"], project_id=str(other_project["id"])
    )
    other_key = authenticate_api_key(other_secret)
    assert other_key is not None
    monkeypatch.setattr(developer_mcp, "authenticated_project_api_key", lambda: other_key)
    with pytest.raises(LookupError, match="memory not found"):
        server._tool_manager._tools["recall"].fn(
            namespace="shared_agent_user", memory_id=str(saved["id"])
        )


def api_key_from_token_for_test(key_record: dict[str, object]) -> PlatformAPIKey:
    with repository_connection() as connection:
        row = connection.execute(
            """SELECT api_keys.*, projects.name AS project_name,
                      organizations.owner_user_id, organizations.plan,
                      organizations.subscription_status
               FROM api_keys JOIN projects ON projects.id = api_keys.project_id
               JOIN organizations ON organizations.id = api_keys.organization_id
               WHERE api_keys.id = ?""",
            (key_record["id"],),
        ).fetchone()
    assert row is not None
    return PlatformAPIKey(
        id=str(row["id"]),
        organization_id=str(row["organization_id"]),
        project_id=str(row["project_id"]),
        project_name=str(row["project_name"]),
        organization_owner_user_id=str(row["owner_user_id"]),
        plan=str(row["plan"]),
        subscription_status=str(row["subscription_status"]),
        environment=str(row["environment"]),
        scopes=frozenset(json.loads(str(row["scopes_json"]))),
        prefix=str(row["prefix"]),
        name=str(row["name"]),
    )
