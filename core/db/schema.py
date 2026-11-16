"""SQLite schema definition for MIRA's canonical durable records.

Ownership: Kelechi.
Related issue: ISSUE-005.
Architecture area: slow path.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

LEGACY_WORKSPACE_ID = "workspace_legacy_default"
LEGACY_WORKSPACE_SLUG = "legacy-default"
WORKSPACE_MIGRATION_ID = "0002_workspace_ownership"
MEMORY_LIFECYCLE_MIGRATION_ID = "0003_memory_lifecycle"
MEMORY_SLEEP_SCHEDULER_MIGRATION_ID = "0004_memory_sleep_scheduler"
KNOWLEDGE_BASE_DOCUMENTS_MIGRATION_ID = "0005_knowledge_base_documents"
DEVELOPER_PLATFORM_MIGRATION_ID = "0006_developer_platform"
EVIDENCE_MIGRATION_ID = "0007_unified_evidence"
SOURCE_SCOPE_MIGRATION_ID = "0008_source_scope_attachments"
RELATION_ROLLBACK_MIGRATION_ID = "0009_relation_rollback_metadata"
INVALIDATED_RELATION_REPAIR_MIGRATION_ID = "0010_restore_invalidated_relations"

# SQLite is the source of truth for ISSUE-005. Enum-like fields intentionally remain
# TEXT columns here; repository helpers validate allowed values before writes.
_TABLE_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        id TEXT PRIMARY KEY,
        applied_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS runtime_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        github_id TEXT UNIQUE,
        github_login TEXT,
        display_name TEXT,
        avatar_url TEXT,
        email TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        last_login_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS workspaces (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        slug TEXT NOT NULL UNIQUE,
        owner_user_id TEXT,
        workspace_type TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        expires_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (owner_user_id) REFERENCES users (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS workspace_members (
        workspace_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        role TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (workspace_id, user_id),
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id),
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS organizations (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        slug TEXT NOT NULL UNIQUE,
        owner_user_id TEXT NOT NULL,
        plan TEXT NOT NULL DEFAULT 'free',
        subscription_status TEXT NOT NULL DEFAULT 'active',
        paystack_customer_code TEXT,
        paystack_subscription_code TEXT,
        paystack_plan_code TEXT,
        billing_currency TEXT NOT NULL DEFAULT 'NGN',
        current_period_end TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (owner_user_id) REFERENCES users (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY,
        organization_id TEXT NOT NULL,
        name TEXT NOT NULL,
        slug TEXT NOT NULL,
        environment TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (id, organization_id),
        UNIQUE (organization_id, slug),
        FOREIGN KEY (organization_id) REFERENCES organizations (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS api_keys (
        id TEXT PRIMARY KEY,
        organization_id TEXT NOT NULL,
        project_id TEXT NOT NULL,
        name TEXT NOT NULL,
        prefix TEXT NOT NULL UNIQUE,
        key_hash TEXT NOT NULL UNIQUE,
        environment TEXT NOT NULL,
        scopes_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        last_used_at TEXT,
        expires_at TEXT,
        revoked_at TEXT,
        FOREIGN KEY (project_id, organization_id)
          REFERENCES projects (id, organization_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS project_namespaces (
        id TEXT PRIMARY KEY,
        organization_id TEXT NOT NULL,
        project_id TEXT NOT NULL,
        namespace TEXT NOT NULL,
        workspace_id TEXT NOT NULL UNIQUE,
        session_id TEXT NOT NULL UNIQUE,
        knowledge_base_id TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (project_id, namespace),
        FOREIGN KEY (project_id, organization_id)
          REFERENCES projects (id, organization_id),
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id),
        FOREIGN KEY (session_id) REFERENCES sessions (id),
        FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_bases (id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS usage_events (
        id TEXT PRIMARY KEY,
        organization_id TEXT NOT NULL,
        project_id TEXT NOT NULL,
        api_key_id TEXT NOT NULL,
        namespace TEXT,
        operation TEXT NOT NULL,
        status_code INTEGER NOT NULL,
        latency_ms INTEGER NOT NULL,
        bytes_ingested INTEGER NOT NULL DEFAULT 0,
        characters_processed INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        FOREIGN KEY (project_id, organization_id)
          REFERENCES projects (id, organization_id),
        FOREIGN KEY (api_key_id) REFERENCES api_keys (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS billing_checkouts (
        reference TEXT PRIMARY KEY,
        organization_id TEXT NOT NULL,
        target_plan TEXT NOT NULL,
        paystack_plan_code TEXT NOT NULL,
        authorization_url TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (organization_id) REFERENCES organizations (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS billing_webhook_events (
        event_id TEXT PRIMARY KEY,
        event_type TEXT NOT NULL,
        payload_sha256 TEXT NOT NULL,
        received_at TEXT NOT NULL,
        processed_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS auth_sessions (
        id TEXT PRIMARY KEY,
        token_hash TEXT NOT NULL UNIQUE,
        csrf_token_hash TEXT NOT NULL,
        user_id TEXT NOT NULL,
        workspace_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        last_used_at TEXT,
        revoked_at TEXT,
        FOREIGN KEY (user_id) REFERENCES users (id),
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS oauth_states (
        id TEXT PRIMARY KEY,
        state_hash TEXT NOT NULL UNIQUE,
        redirect_uri TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        consumed_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS oauth_clients (
        client_id TEXT PRIMARY KEY,
        client_name TEXT NOT NULL,
        redirect_uris_json TEXT NOT NULL,
        scope TEXT NOT NULL,
        token_endpoint_auth_method TEXT NOT NULL DEFAULT 'none',
        client_type TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT,
        disabled_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS oauth_authorization_requests (
        id TEXT PRIMARY KEY,
        request_token_hash TEXT NOT NULL UNIQUE,
        code_hash TEXT UNIQUE,
        client_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        workspace_id TEXT NOT NULL,
        redirect_uri TEXT NOT NULL,
        scope TEXT NOT NULL,
        resource TEXT NOT NULL,
        state TEXT,
        code_challenge TEXT NOT NULL,
        code_challenge_method TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        code_expires_at TEXT,
        consumed_at TEXT,
        FOREIGN KEY (client_id) REFERENCES oauth_clients (client_id),
        FOREIGN KEY (user_id) REFERENCES users (id),
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS oauth_access_tokens (
        id TEXT PRIMARY KEY,
        token_hash TEXT NOT NULL UNIQUE,
        client_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        workspace_id TEXT NOT NULL,
        scope TEXT NOT NULL,
        resource TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        revoked_at TEXT,
        FOREIGN KEY (client_id) REFERENCES oauth_clients (client_id),
        FOREIGN KEY (user_id) REFERENCES users (id),
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS oauth_refresh_tokens (
        id TEXT PRIMARY KEY,
        token_hash TEXT NOT NULL UNIQUE,
        client_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        workspace_id TEXT NOT NULL,
        scope TEXT NOT NULL,
        resource TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        rotated_at TEXT,
        revoked_at TEXT,
        FOREIGN KEY (client_id) REFERENCES oauth_clients (client_id),
        FOREIGN KEY (user_id) REFERENCES users (id),
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS demo_issuances (
        id TEXT PRIMARY KEY,
        requester_hash TEXT NOT NULL,
        user_id TEXT,
        workspace_id TEXT,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        cleaned_at TEXT,
        FOREIGN KEY (user_id) REFERENCES users (id),
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        title TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        ended_at TEXT,
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS observations (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        session_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT 'chat',
        metadata_json TEXT,
        created_at TEXT NOT NULL,
        processed_at TEXT,
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id),
        FOREIGN KEY (session_id) REFERENCES sessions (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS slow_path_queue (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        observation_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        attempt_count INTEGER NOT NULL DEFAULT 0,
        last_error TEXT,
        quarantine_reason TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id),
        FOREIGN KEY (observation_id) REFERENCES observations (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS slow_path_step_journal (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        observation_id TEXT NOT NULL,
        step_name TEXT NOT NULL,
        status TEXT NOT NULL,
        last_error TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (workspace_id, observation_id, step_name),
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id),
        FOREIGN KEY (observation_id) REFERENCES observations (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS session_working_set (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        type TEXT NOT NULL,
        content TEXT NOT NULL,
        scope TEXT NOT NULL,
        status TEXT NOT NULL,
        priority REAL NOT NULL,
        explicitness_label TEXT NOT NULL,
        evidence_span TEXT,
        source_observations_json TEXT NOT NULL,
        supersedes_json TEXT,
        origin TEXT NOT NULL DEFAULT 'micro_path',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        expires_at TEXT,
        resolution_reason TEXT,
        FOREIGN KEY (session_id) REFERENCES sessions (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS canonical_subjects (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        canonical_form TEXT NOT NULL,
        aliases_json TEXT,
        confidence REAL NOT NULL DEFAULT 1.0,
        created_at TEXT NOT NULL,
        UNIQUE (workspace_id, canonical_form),
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS canonical_predicates (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        canonical_form TEXT NOT NULL,
        aliases_json TEXT,
        confidence REAL NOT NULL DEFAULT 1.0,
        created_at TEXT NOT NULL,
        UNIQUE (workspace_id, canonical_form),
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS atomic_facts (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        subject TEXT NOT NULL,
        predicate TEXT NOT NULL,
        object TEXT NOT NULL,
        confidence REAL NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        source_observation_id TEXT,
        canonical_subject_id TEXT,
        canonical_predicate_id TEXT,
        created_at TEXT NOT NULL,
        valid_from TEXT,
        valid_until TEXT,
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id),
        FOREIGN KEY (source_observation_id) REFERENCES observations (id),
        FOREIGN KEY (canonical_subject_id) REFERENCES canonical_subjects (id),
        FOREIGN KEY (canonical_predicate_id) REFERENCES canonical_predicates (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS entities (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        name TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        aliases_json TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_nodes (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        node_type TEXT NOT NULL,
        source_table TEXT,
        source_id TEXT,
        label TEXT NOT NULL,
        metadata_json TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_edges (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        source_node_id TEXT NOT NULL,
        target_node_id TEXT NOT NULL,
        edge_type TEXT NOT NULL,
        confidence REAL NOT NULL,
        source_observations_json TEXT NOT NULL,
        metadata_json TEXT,
        valid_from TEXT,
        valid_until TEXT,
        created_at TEXT NOT NULL,
        invalidated_at TEXT,
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id),
        FOREIGN KEY (source_node_id) REFERENCES graph_nodes (id),
        FOREIGN KEY (target_node_id) REFERENCES graph_nodes (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reflections (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        reflection_type TEXT NOT NULL,
        content TEXT NOT NULL,
        confidence REAL NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        stale_reason TEXT,
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reflection_evidence (
        id TEXT PRIMARY KEY,
        reflection_id TEXT NOT NULL,
        observation_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (reflection_id) REFERENCES reflections (id),
        FOREIGN KEY (observation_id) REFERENCES observations (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS foresight_records (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        content TEXT NOT NULL,
        reason TEXT,
        status TEXT NOT NULL,
        source_observation_id TEXT,
        valid_from TEXT,
        valid_until TEXT,
        always_inject INTEGER NOT NULL DEFAULT 0,
        resolved_by TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id),
        FOREIGN KEY (source_observation_id) REFERENCES observations (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS community_summaries (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        community_id TEXT NOT NULL,
        title TEXT NOT NULL,
        summary TEXT NOT NULL,
        member_nodes_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id),
        UNIQUE (workspace_id, community_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS working_memory (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        content TEXT NOT NULL,
        memory_type TEXT NOT NULL,
        scope TEXT NOT NULL,
        priority REAL NOT NULL,
        status TEXT NOT NULL,
        source_record_type TEXT,
        source_record_id TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS retrieval_logs (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        session_id TEXT NOT NULL,
        query TEXT NOT NULL,
        retrieval_mode TEXT NOT NULL,
        retrieved_records_json TEXT NOT NULL,
        sufficiency_json TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id),
        FOREIGN KEY (session_id) REFERENCES sessions (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS prompt_logs (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        session_id TEXT NOT NULL,
        user_observation_id TEXT NOT NULL,
        included_session_items_json TEXT,
        included_memory_items_json TEXT,
        included_recent_turns_json TEXT,
        token_budget_json TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id),
        FOREIGN KEY (session_id) REFERENCES sessions (id),
        FOREIGN KEY (user_observation_id) REFERENCES observations (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS answer_traces (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        session_id TEXT NOT NULL,
        user_observation_id TEXT NOT NULL,
        assistant_observation_id TEXT NOT NULL,
        retrieval_mode TEXT NOT NULL,
        retrieved_observation_ids_json TEXT,
        retrieved_fact_ids_json TEXT,
        session_item_ids_json TEXT,
        hot_memory_ids_json TEXT,
        graph_path_ids_json TEXT,
        community_summary_ids_json TEXT,
        sufficiency_json TEXT,
        prompt_sections_json TEXT,
        hydration_ids_json TEXT,
        retrieval_log_id TEXT,
        prompt_log_id TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id),
        FOREIGN KEY (session_id) REFERENCES sessions (id),
        FOREIGN KEY (user_observation_id) REFERENCES observations (id),
        FOREIGN KEY (assistant_observation_id) REFERENCES observations (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memory_state (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        source_type TEXT NOT NULL,
        source_id TEXT NOT NULL,
        source_authority TEXT NOT NULL DEFAULT 'unknown',
        last_accessed_at TEXT,
        last_verified_at TEXT,
        successful_uses INTEGER NOT NULL DEFAULT 0,
        failed_uses INTEGER NOT NULL DEFAULT 0,
        verification_count INTEGER NOT NULL DEFAULT 0,
        refuted_count INTEGER NOT NULL DEFAULT 0,
        retention_score REAL NOT NULL DEFAULT 0.5,
        stability REAL NOT NULL DEFAULT 30.0,
        pinned INTEGER NOT NULL DEFAULT 0,
        lifecycle_status TEXT NOT NULL DEFAULT 'active',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (workspace_id, source_type, source_id),
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memory_reviews (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        memory_state_id TEXT NOT NULL,
        trace_id TEXT,
        event_type TEXT NOT NULL,
        retrieved INTEGER NOT NULL DEFAULT 0,
        answer_correct INTEGER,
        answer_wrong INTEGER NOT NULL DEFAULT 0,
        verified INTEGER NOT NULL DEFAULT 0,
        refuted INTEGER NOT NULL DEFAULT 0,
        reinforced INTEGER NOT NULL DEFAULT 0,
        evidence TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id),
        FOREIGN KEY (memory_state_id) REFERENCES memory_state (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memory_sleep_runs (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        status TEXT NOT NULL,
        trigger TEXT NOT NULL DEFAULT 'manual',
        started_at TEXT NOT NULL,
        completed_at TEXT,
        finished_at TEXT,
        reviewed_count INTEGER NOT NULL DEFAULT 0,
        reinforced_count INTEGER NOT NULL DEFAULT 0,
        weakened_count INTEGER NOT NULL DEFAULT 0,
        consolidated_count INTEGER NOT NULL DEFAULT 0,
        archived_count INTEGER NOT NULL DEFAULT 0,
        forgotten_count INTEGER NOT NULL DEFAULT 0,
        configuration_json TEXT,
        before_snapshot_json TEXT,
        after_snapshot_json TEXT,
        changes_json TEXT,
        error TEXT,
        details TEXT,
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memory_sleep_schedule (
        workspace_id TEXT PRIMARY KEY,
        automatic_sleep_enabled INTEGER NOT NULL DEFAULT 1,
        sleep_interval_hours REAL NOT NULL DEFAULT 6.0,
        last_sleep_at TEXT,
        next_sleep_at TEXT,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS knowledge_bases (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        name TEXT NOT NULL,
        description TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS documents (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        knowledge_base_id TEXT NOT NULL,
        filename TEXT NOT NULL,
        mime_type TEXT NOT NULL,
        size_bytes INTEGER NOT NULL,
        s3_bucket TEXT NOT NULL,
        s3_key TEXT NOT NULL,
        checksum_sha256 TEXT NOT NULL,
        status TEXT NOT NULL,
        error_message TEXT,
        page_count INTEGER,
        extracted_char_count INTEGER,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        processed_at TEXT,
        deleted_at TEXT,
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id),
        FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_bases (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS document_chunks (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        knowledge_base_id TEXT NOT NULL,
        document_id TEXT NOT NULL,
        chunk_index INTEGER NOT NULL,
        content TEXT NOT NULL,
        heading TEXT,
        page_start INTEGER,
        page_end INTEGER,
        char_start INTEGER,
        char_end INTEGER,
        created_at TEXT NOT NULL,
        UNIQUE (document_id, chunk_index),
        FOREIGN KEY (workspace_id) REFERENCES workspaces (id),
        FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_bases (id),
        FOREIGN KEY (document_id) REFERENCES documents (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS evidence_sources (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL REFERENCES workspaces(id),
        source_type TEXT NOT NULL CHECK (
            source_type IN ('conversation_observation', 'document_chunk')
        ),
        source_id TEXT NOT NULL,
        project_id TEXT,
        namespace TEXT,
        knowledge_base_id TEXT REFERENCES knowledge_bases(id),
        authority REAL NOT NULL DEFAULT 0.5 CHECK (authority >= 0 AND authority <= 1),
        content_hash TEXT NOT NULL,
        metadata_json TEXT,
        observed_at TEXT,
        created_at TEXT NOT NULL,
        retracted_at TEXT,
        UNIQUE (workspace_id, source_type, source_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS evidence_links (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL REFERENCES workspaces(id),
        source_id TEXT NOT NULL REFERENCES evidence_sources(id),
        target_type TEXT NOT NULL CHECK (
            target_type IN ('atomic_fact', 'graph_edge', 'reflection', 'foresight')
        ),
        target_id TEXT NOT NULL,
        atomic_fact_id TEXT REFERENCES atomic_facts(id),
        graph_edge_id TEXT REFERENCES graph_edges(id),
        reflection_id TEXT REFERENCES reflections(id),
        foresight_id TEXT REFERENCES foresight_records(id),
        stance TEXT NOT NULL CHECK (stance IN ('support', 'contradict')),
        confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
        created_at TEXT NOT NULL,
        retracted_at TEXT,
        CHECK (
            (target_type = 'atomic_fact' AND atomic_fact_id = target_id
                AND graph_edge_id IS NULL AND reflection_id IS NULL AND foresight_id IS NULL) OR
            (target_type = 'graph_edge' AND graph_edge_id = target_id
                AND atomic_fact_id IS NULL AND reflection_id IS NULL AND foresight_id IS NULL) OR
            (target_type = 'reflection' AND reflection_id = target_id
                AND atomic_fact_id IS NULL AND graph_edge_id IS NULL AND foresight_id IS NULL) OR
            (target_type = 'foresight' AND foresight_id = target_id
                AND atomic_fact_id IS NULL AND graph_edge_id IS NULL AND reflection_id IS NULL)
        )
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS document_enrichment_jobs (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL REFERENCES workspaces(id),
        document_id TEXT NOT NULL REFERENCES documents(id),
        pipeline_version TEXT NOT NULL,
        status TEXT NOT NULL CHECK (
            status IN ('pending', 'processing', 'done', 'failed', 'cancelled')
        ),
        attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
        max_attempts INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts > 0),
        available_at TEXT NOT NULL,
        lease_until TEXT,
        worker_id TEXT,
        last_error TEXT,
        progress_json TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (document_id, pipeline_version)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS session_knowledge_base_attachments (
        workspace_id TEXT NOT NULL REFERENCES workspaces(id),
        session_id TEXT NOT NULL REFERENCES sessions(id),
        knowledge_base_id TEXT NOT NULL REFERENCES knowledge_bases(id),
        created_at TEXT NOT NULL,
        PRIMARY KEY (workspace_id, session_id, knowledge_base_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS project_knowledge_workspaces (
        project_id TEXT PRIMARY KEY REFERENCES projects(id),
        workspace_id TEXT NOT NULL UNIQUE REFERENCES workspaces(id),
        knowledge_base_id TEXT NOT NULL UNIQUE REFERENCES knowledge_bases(id),
        created_at TEXT NOT NULL
    )
    """,
)

_INDEX_STATEMENTS: tuple[str, ...] = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_personal_workspace_owner "
    "ON workspaces (owner_user_id) "
    "WHERE workspace_type = 'personal' AND owner_user_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_workspace_members_user ON workspace_members (user_id)",
    "CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions (user_id, expires_at)",
    "CREATE INDEX IF NOT EXISTS idx_oauth_authorization_client "
    "ON oauth_authorization_requests (client_id, status, expires_at)",
    "CREATE INDEX IF NOT EXISTS idx_oauth_access_workspace "
    "ON oauth_access_tokens (workspace_id, expires_at, revoked_at)",
    "CREATE INDEX IF NOT EXISTS idx_oauth_refresh_client "
    "ON oauth_refresh_tokens (client_id, expires_at, revoked_at)",
    "CREATE INDEX IF NOT EXISTS idx_demo_issuances_requester "
    "ON demo_issuances (requester_hash, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_workspace_updated "
    "ON sessions (workspace_id, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_observations_workspace_created "
    "ON observations (workspace_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_queue_workspace_status "
    "ON slow_path_queue (workspace_id, status, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_step_journal_workspace_observation "
    "ON slow_path_step_journal (workspace_id, observation_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_observations_session_id ON observations (session_id)",
    "CREATE INDEX IF NOT EXISTS idx_observations_created_at ON observations (created_at)",
    "CREATE INDEX IF NOT EXISTS idx_observations_processed_at ON observations (processed_at)",
    """
    CREATE INDEX IF NOT EXISTS idx_session_working_set_session_id
    ON session_working_set (session_id)
    """,
    "CREATE INDEX IF NOT EXISTS idx_session_working_set_status ON session_working_set (status)",
    "CREATE INDEX IF NOT EXISTS idx_session_working_set_scope ON session_working_set (scope)",
    "CREATE INDEX IF NOT EXISTS idx_session_working_set_priority ON session_working_set (priority)",
    "CREATE INDEX IF NOT EXISTS idx_answer_traces_sid ON answer_traces (session_id)",
    "CREATE INDEX IF NOT EXISTS idx_answer_traces_uid ON answer_traces (user_observation_id)",
    "CREATE INDEX IF NOT EXISTS idx_facts_workspace_status "
    "ON atomic_facts (workspace_id, status, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_graph_nodes_workspace_source "
    "ON graph_nodes (workspace_id, source_table, source_id)",
    "CREATE INDEX IF NOT EXISTS idx_graph_edges_workspace_source "
    "ON graph_edges (workspace_id, source_node_id)",
    "CREATE INDEX IF NOT EXISTS idx_graph_edges_workspace_target "
    "ON graph_edges (workspace_id, target_node_id)",
    "CREATE INDEX IF NOT EXISTS idx_reflections_workspace_status "
    "ON reflections (workspace_id, status, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_foresight_workspace_status "
    "ON foresight_records (workspace_id, status, valid_from, valid_until)",
    "CREATE INDEX IF NOT EXISTS idx_working_memory_workspace_status "
    "ON working_memory (workspace_id, status, priority)",
    "CREATE INDEX IF NOT EXISTS idx_traces_workspace_session "
    "ON answer_traces (workspace_id, session_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_memory_state_workspace_status "
    "ON memory_state (workspace_id, lifecycle_status, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_memory_state_source "
    "ON memory_state (workspace_id, source_type, source_id)",
    "CREATE INDEX IF NOT EXISTS idx_memory_reviews_workspace_created "
    "ON memory_reviews (workspace_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_memory_reviews_state_created "
    "ON memory_reviews (memory_state_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_memory_sleep_workspace_started "
    "ON memory_sleep_runs (workspace_id, started_at)",
    "CREATE INDEX IF NOT EXISTS idx_memory_sleep_workspace_status "
    "ON memory_sleep_runs (workspace_id, status, started_at)",
    "CREATE INDEX IF NOT EXISTS idx_memory_sleep_schedule_due "
    "ON memory_sleep_schedule (automatic_sleep_enabled, next_sleep_at)",
    "CREATE INDEX IF NOT EXISTS idx_knowledge_bases_workspace_status "
    "ON knowledge_bases (workspace_id, status, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_documents_workspace_status "
    "ON documents (workspace_id, status, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_documents_knowledge_base "
    "ON documents (knowledge_base_id, status, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_projects_organization "
    "ON projects (organization_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_organizations_owner_created "
    "ON organizations (owner_user_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_organizations_paystack_subscription "
    "ON organizations (paystack_subscription_code)",
    "CREATE INDEX IF NOT EXISTS idx_organizations_paystack_customer "
    "ON organizations (paystack_customer_code)",
    "CREATE INDEX IF NOT EXISTS idx_api_keys_project "
    "ON api_keys (project_id, revoked_at, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_billing_checkouts_org_status_created "
    "ON billing_checkouts (organization_id, status, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_usage_org_created "
    "ON usage_events (organization_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_usage_key_created ON usage_events (api_key_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_usage_project_operation "
    "ON usage_events (project_id, operation, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_document_chunks_workspace "
    "ON document_chunks (workspace_id, knowledge_base_id, document_id, chunk_index)",
    """
    CREATE INDEX IF NOT EXISTS idx_atomic_facts_canonical
    ON atomic_facts (canonical_subject_id, canonical_predicate_id)
    """,
    "CREATE INDEX IF NOT EXISTS idx_evidence_sources_scope "
    "ON evidence_sources (workspace_id, source_type, source_id, retracted_at)",
    "CREATE INDEX IF NOT EXISTS idx_evidence_links_target "
    "ON evidence_links (workspace_id, target_type, target_id, retracted_at)",
    "CREATE INDEX IF NOT EXISTS idx_evidence_links_source "
    "ON evidence_links (source_id, retracted_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_evidence_links_active_unique "
    "ON evidence_links (workspace_id, source_id, target_type, target_id, stance) "
    "WHERE retracted_at IS NULL",
    "CREATE INDEX IF NOT EXISTS idx_document_jobs_due "
    "ON document_enrichment_jobs (workspace_id, status, available_at, lease_until)",
    "CREATE INDEX IF NOT EXISTS idx_session_kb_attachments_session "
    "ON session_knowledge_base_attachments (workspace_id, session_id)",
    "CREATE INDEX IF NOT EXISTS idx_project_knowledge_workspace "
    "ON project_knowledge_workspaces (workspace_id, project_id)",
)

_WORKSPACE_TABLES = (
    "sessions",
    "observations",
    "slow_path_queue",
    "slow_path_step_journal",
    "canonical_subjects",
    "canonical_predicates",
    "atomic_facts",
    "entities",
    "graph_nodes",
    "graph_edges",
    "reflections",
    "foresight_records",
    "community_summaries",
    "working_memory",
    "retrieval_logs",
    "prompt_logs",
    "answer_traces",
    "memory_state",
    "memory_reviews",
    "memory_sleep_runs",
    "memory_sleep_schedule",
    "knowledge_bases",
    "documents",
    "document_chunks",
    "evidence_sources",
    "evidence_links",
    "document_enrichment_jobs",
    "session_knowledge_base_attachments",
    "project_knowledge_workspaces",
)

_OWNERSHIP_TRIGGER_STATEMENTS: tuple[str, ...] = tuple(
    statement
    for table in _WORKSPACE_TABLES
    for statement in (
        f"""
        CREATE TRIGGER IF NOT EXISTS trg_{table}_workspace_insert
        BEFORE INSERT ON {table}
        WHEN NEW.workspace_id IS NULL
        BEGIN
            SELECT RAISE(ABORT, 'workspace_id is required for {table}');
        END
        """,
        f"""
        CREATE TRIGGER IF NOT EXISTS trg_{table}_workspace_update
        BEFORE UPDATE OF workspace_id ON {table}
        WHEN NEW.workspace_id IS NULL OR NEW.workspace_id != OLD.workspace_id
        BEGIN
            SELECT RAISE(ABORT, 'workspace_id is immutable for {table}');
        END
        """,
    )
) + (
    """
    CREATE TRIGGER IF NOT EXISTS trg_observation_session_workspace
    BEFORE INSERT ON observations
    WHEN NOT EXISTS (
        SELECT 1 FROM sessions
        WHERE id = NEW.session_id AND workspace_id = NEW.workspace_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'observation workspace does not match session');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_queue_observation_workspace
    BEFORE INSERT ON slow_path_queue
    WHEN NOT EXISTS (
        SELECT 1 FROM observations
        WHERE id = NEW.observation_id AND workspace_id = NEW.workspace_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'queue workspace does not match observation');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_step_journal_observation_workspace
    BEFORE INSERT ON slow_path_step_journal
    WHEN NOT EXISTS (
        SELECT 1 FROM observations
        WHERE id = NEW.observation_id AND workspace_id = NEW.workspace_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'step journal workspace does not match observation');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_graph_edge_workspace
    BEFORE INSERT ON graph_edges
    WHEN NOT EXISTS (
        SELECT 1
        FROM graph_nodes AS source, graph_nodes AS target
        WHERE source.id = NEW.source_node_id
          AND target.id = NEW.target_node_id
          AND source.workspace_id = NEW.workspace_id
          AND target.workspace_id = NEW.workspace_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'graph edge endpoints must share its workspace');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_reflection_evidence_workspace
    BEFORE INSERT ON reflection_evidence
    WHEN NOT EXISTS (
        SELECT 1
        FROM reflections
        JOIN observations ON observations.id = NEW.observation_id
        WHERE reflections.id = NEW.reflection_id
          AND reflections.workspace_id = observations.workspace_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'reflection evidence must share one workspace');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_memory_review_state_workspace
    BEFORE INSERT ON memory_reviews
    WHEN NOT EXISTS (
        SELECT 1 FROM memory_state
        WHERE memory_state.id = NEW.memory_state_id
          AND memory_state.workspace_id = NEW.workspace_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'memory review must share its state workspace');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_document_knowledge_base_workspace
    BEFORE INSERT ON documents
    WHEN NOT EXISTS (
        SELECT 1 FROM knowledge_bases
        WHERE id = NEW.knowledge_base_id AND workspace_id = NEW.workspace_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'document knowledge base must share its workspace');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_document_chunk_workspace
    BEFORE INSERT ON document_chunks
    WHEN NOT EXISTS (
        SELECT 1
        FROM documents
        JOIN knowledge_bases ON knowledge_bases.id = documents.knowledge_base_id
        WHERE documents.id = NEW.document_id
          AND documents.workspace_id = NEW.workspace_id
          AND knowledge_bases.id = NEW.knowledge_base_id
          AND knowledge_bases.workspace_id = NEW.workspace_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'document chunk parents must share its workspace');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_evidence_link_workspace
    BEFORE INSERT ON evidence_links
    WHEN NOT EXISTS (SELECT 1 FROM evidence_sources
                     WHERE id = NEW.source_id AND workspace_id = NEW.workspace_id
                       AND retracted_at IS NULL)
      OR (NEW.target_type = 'atomic_fact' AND NOT EXISTS
          (SELECT 1 FROM atomic_facts WHERE id = NEW.target_id
             AND workspace_id = NEW.workspace_id))
      OR (NEW.target_type = 'graph_edge' AND NOT EXISTS
          (SELECT 1 FROM graph_edges WHERE id = NEW.target_id
             AND workspace_id = NEW.workspace_id))
      OR (NEW.target_type = 'reflection' AND NOT EXISTS
          (SELECT 1 FROM reflections WHERE id = NEW.target_id
             AND workspace_id = NEW.workspace_id))
      OR (NEW.target_type = 'foresight' AND NOT EXISTS
          (SELECT 1 FROM foresight_records WHERE id = NEW.target_id
             AND workspace_id = NEW.workspace_id))
    BEGIN
        SELECT RAISE(ABORT, 'evidence link workspace or source mismatch');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_document_job_workspace
    BEFORE INSERT ON document_enrichment_jobs
    WHEN NOT EXISTS (SELECT 1 FROM documents WHERE id = NEW.document_id
                     AND workspace_id = NEW.workspace_id AND status = 'ready'
                     AND deleted_at IS NULL)
    BEGIN
        SELECT RAISE(ABORT, 'document job requires ready document in workspace');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_session_kb_attachment_workspace
    BEFORE INSERT ON session_knowledge_base_attachments
    WHEN NOT EXISTS (
        SELECT 1 FROM sessions AS s JOIN knowledge_bases AS k
          ON k.workspace_id = s.workspace_id
        WHERE s.id = NEW.session_id AND s.workspace_id = NEW.workspace_id
          AND s.status != 'deleted' AND k.id = NEW.knowledge_base_id
          AND k.status = 'active'
    )
    BEGIN
        SELECT RAISE(ABORT, 'session knowledge base attachment crosses scope');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_session_kb_attachment_update
    BEFORE UPDATE ON session_knowledge_base_attachments
    WHEN NOT EXISTS (
        SELECT 1 FROM sessions AS s JOIN knowledge_bases AS k
          ON k.workspace_id = s.workspace_id
        WHERE s.id = NEW.session_id AND s.workspace_id = NEW.workspace_id
          AND s.status != 'deleted' AND k.id = NEW.knowledge_base_id
          AND k.status = 'active'
    )
    BEGIN
        SELECT RAISE(ABORT, 'session knowledge base attachment crosses scope');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_project_knowledge_workspace_scope
    BEFORE INSERT ON project_knowledge_workspaces
    WHEN NOT EXISTS (
        SELECT 1 FROM knowledge_bases AS k
        WHERE k.id = NEW.knowledge_base_id AND k.workspace_id = NEW.workspace_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'project knowledge base does not match workspace');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_project_knowledge_workspace_scope_update
    BEFORE UPDATE ON project_knowledge_workspaces
    WHEN NOT EXISTS (
        SELECT 1 FROM knowledge_bases AS k
        WHERE k.id = NEW.knowledge_base_id AND k.workspace_id = NEW.workspace_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'project knowledge base does not match workspace');
    END
    """,
)

# Canonical registries seed the alias vocabulary that lets contradiction/supersession
# detection pair facts whose raw subject/predicate wording varies across extractions.
# Auto-created buckets (raw form, low confidence) cover anything not seeded here.
_SEED_CANONICAL_SUBJECTS: dict[str, tuple[str, ...]] = {
    "user": ("i", "me", "my", "myself", "speaker", "user", "you"),
    "assistant": ("assistant", "agent", "mira", "ai"),
}
_SEED_CANONICAL_PREDICATES: dict[str, tuple[str, ...]] = {
    "prefers": ("prefer", "prefers", "likes", "favorite"),
    "uses": ("use", "uses", "using", "is using", "is currently using"),
    "decided": ("decide", "decided", "chose", "choose"),
    "switched_from": ("switched from", "switched_from", "migrated from", "moved from"),
    "works_on": ("work on", "works on", "working on", "works_on"),
}


def schema_statements() -> list[str]:
    """Return idempotent SQLite DDL for MIRA's source-of-truth schema."""
    return [*_TABLE_STATEMENTS, *_INDEX_STATEMENTS, *_OWNERSHIP_TRIGGER_STATEMENTS]


def initialize_database(database_path: str | Path) -> None:
    """Create or update a SQLite database file with the canonical MIRA schema."""
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        # Canonical registry migration rebuilds two tables to replace their old global
        # uniqueness constraint. Foreign keys are validated before this function returns.
        connection.execute("PRAGMA foreign_keys = OFF")
        for statement in _TABLE_STATEMENTS:
            connection.execute(statement)
        # Commit the DDL batch before the upgrade helpers perform inserts and
        # index/trigger work. This keeps schema initialization recoverable on
        # SQLite filesystems that serialize long DDL transactions.
        connection.commit()
        _ensure_legacy_workspace(connection)
        _migrate_workspace_ownership(connection)
        _migrate_slow_path_runtime(connection)
        _migrate_memory_sleep_scheduler(connection)
        _migrate_knowledge_base_documents(connection)
        _migrate_developer_platform(connection)
        _migrate_atomic_facts_canonical(connection)
        _migrate_canonical_registry_uniqueness(connection)
        _migrate_evidence(connection)
        _migrate_source_scopes(connection)
        _migrate_relation_rollback_metadata(connection)
        for statement in _INDEX_STATEMENTS:
            connection.execute(statement)
        _install_ownership_triggers(connection)
        _seed_canonical_registries(connection, LEGACY_WORKSPACE_ID)
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations (id, applied_at) VALUES (?, ?)",
            (WORKSPACE_MIGRATION_ID, _now()),
        )
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations (id, applied_at) VALUES (?, ?)",
            (MEMORY_LIFECYCLE_MIGRATION_ID, _now()),
        )
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations (id, applied_at) VALUES (?, ?)",
            (MEMORY_SLEEP_SCHEDULER_MIGRATION_ID, _now()),
        )
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations (id, applied_at) VALUES (?, ?)",
            (KNOWLEDGE_BASE_DOCUMENTS_MIGRATION_ID, _now()),
        )
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations (id, applied_at) VALUES (?, ?)",
            (DEVELOPER_PLATFORM_MIGRATION_ID, _now()),
        )
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations (id, applied_at) VALUES (?, ?)",
            (EVIDENCE_MIGRATION_ID, _now()),
        )
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations (id, applied_at) VALUES (?, ?)",
            (SOURCE_SCOPE_MIGRATION_ID, _now()),
        )
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations (id, applied_at) VALUES (?, ?)",
            (RELATION_ROLLBACK_MIGRATION_ID, _now()),
        )
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations (id, applied_at) VALUES (?, ?)",
            (INVALIDATED_RELATION_REPAIR_MIGRATION_ID, _now()),
        )
        connection.commit()
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(f"workspace migration left foreign-key violations: {violations!r}")
    finally:
        connection.close()


def _ensure_legacy_workspace(connection: sqlite3.Connection) -> None:
    now = _now()
    connection.execute(
        """
        INSERT OR IGNORE INTO workspaces (
            id, name, slug, owner_user_id, workspace_type, status,
            expires_at, created_at, updated_at
        ) VALUES (?, ?, ?, NULL, 'legacy', 'active', NULL, ?, ?)
        """,
        (LEGACY_WORKSPACE_ID, "Legacy local workspace", LEGACY_WORKSPACE_SLUG, now, now),
    )


def _install_ownership_triggers(connection: sqlite3.Connection) -> None:
    """Replace ownership triggers so upgraded databases receive hardened definitions."""
    trigger_names = [
        *(f"trg_{table}_workspace_insert" for table in _WORKSPACE_TABLES),
        *(f"trg_{table}_workspace_update" for table in _WORKSPACE_TABLES),
        "trg_observation_session_workspace",
        "trg_queue_observation_workspace",
        "trg_step_journal_observation_workspace",
        "trg_graph_edge_workspace",
        "trg_reflection_evidence_workspace",
        "trg_document_knowledge_base_workspace",
        "trg_document_chunk_workspace",
        "trg_evidence_link_workspace",
        "trg_document_job_workspace",
        "trg_session_kb_attachment_workspace",
        "trg_session_kb_attachment_update",
        "trg_project_knowledge_workspace_scope",
        "trg_project_knowledge_workspace_scope_update",
    ]
    for trigger_name in trigger_names:
        connection.execute(f"DROP TRIGGER IF EXISTS {trigger_name}")  # noqa: S608  # nosec B608
    for statement in _OWNERSHIP_TRIGGER_STATEMENTS:
        connection.execute(statement)


def _migrate_workspace_ownership(connection: sqlite3.Connection) -> None:
    """Add and backfill workspace ownership on databases created before workspaces."""
    for table in _WORKSPACE_TABLES:
        columns = _table_columns(connection, table)
        if "workspace_id" not in columns:
            connection.execute(
                f"ALTER TABLE {table} ADD COLUMN workspace_id TEXT "  # noqa: S608  # nosec B608
                "REFERENCES workspaces (id)"
            )
        connection.execute(
            f"UPDATE {table} SET workspace_id = ? WHERE workspace_id IS NULL",  # noqa: S608  # nosec B608
            (LEGACY_WORKSPACE_ID,),
        )


def _migrate_slow_path_runtime(connection: sqlite3.Connection) -> None:
    """Add retry-safety fields introduced after the workspace migration."""
    queue_columns = _table_columns(connection, "slow_path_queue")
    if "quarantine_reason" not in queue_columns:
        connection.execute("ALTER TABLE slow_path_queue ADD COLUMN quarantine_reason TEXT")


def _migrate_memory_sleep_scheduler(connection: sqlite3.Connection) -> None:
    """Upgrade lifecycle databases with scheduler/run observability fields."""
    columns = _table_columns(connection, "memory_sleep_runs")
    additions = {
        "trigger": "TEXT NOT NULL DEFAULT 'manual'",
        "finished_at": "TEXT",
        "configuration_json": "TEXT",
        "before_snapshot_json": "TEXT",
        "after_snapshot_json": "TEXT",
        "changes_json": "TEXT",
        "error": "TEXT",
    }
    for column, definition in additions.items():
        if column not in columns:
            connection.execute(
                f"ALTER TABLE memory_sleep_runs ADD COLUMN {column} {definition}"  # noqa: S608
            )


def _migrate_knowledge_base_documents(connection: sqlite3.Connection) -> None:
    """Keep the knowledge-base schema migration boundary explicit.

    The three tables are created by the idempotent canonical DDL above, so no
    column backfill is required for this first document-storage migration.
    """
    del connection


def _migrate_developer_platform(connection: sqlite3.Connection) -> None:
    """Create a free organization and production project for every existing user."""
    now = _now()
    users = connection.execute(
        "SELECT id, github_login FROM users ORDER BY created_at, id"
    ).fetchall()
    for user in users:
        # The migration connection uses sqlite3's default tuple row factory.
        # Keep this migration independent of the repository connection setup.
        user_id = str(user[0])
        login = str(user[1] or "MIRA user")
        suffix = uuid.uuid5(uuid.NAMESPACE_URL, f"mira-user:{user_id}").hex[:20]
        organization_id = f"org_{suffix}"
        project_id = f"prj_{suffix}"
        connection.execute(
            """
            INSERT OR IGNORE INTO organizations (
                id, name, slug, owner_user_id, plan, subscription_status,
                billing_currency, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'free', 'active', 'NGN', ?, ?)
            """,
            (organization_id, f"{login}'s organization", f"org-{suffix}", user_id, now, now),
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO projects (
                id, organization_id, name, slug, environment, created_at, updated_at
            ) VALUES (?, ?, 'Default project', 'default-production', 'production', ?, ?)
            """,
            (project_id, organization_id, now, now),
        )


def _migrate_canonical_registry_uniqueness(connection: sqlite3.Connection) -> None:
    """Replace legacy global canonical uniqueness with per-workspace uniqueness."""
    for table in ("canonical_subjects", "canonical_predicates"):
        if not _has_global_canonical_unique_index(connection, table):
            continue
        replacement = f"{table}__workspace_v2"
        connection.execute(f"DROP TABLE IF EXISTS {replacement}")  # noqa: S608  # nosec B608
        connection.execute(
            f"""
            CREATE TABLE {replacement} (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                canonical_form TEXT NOT NULL,
                aliases_json TEXT,
                confidence REAL NOT NULL DEFAULT 1.0,
                created_at TEXT NOT NULL,
                UNIQUE (workspace_id, canonical_form),
                FOREIGN KEY (workspace_id) REFERENCES workspaces (id)
            )
            """  # noqa: S608  # nosec B608
        )
        connection.execute(
            f"""
            INSERT INTO {replacement} (
                id, workspace_id, canonical_form, aliases_json, confidence, created_at
            )
            SELECT id, workspace_id, canonical_form, aliases_json, confidence, created_at
            FROM {table}
            """  # noqa: S608  # nosec B608
        )
        connection.execute(f"DROP TABLE {table}")  # noqa: S608  # nosec B608
        connection.execute(
            f"ALTER TABLE {replacement} RENAME TO {table}"  # noqa: S608  # nosec B608
        )


def _has_global_canonical_unique_index(connection: sqlite3.Connection, table: str) -> bool:
    for index in connection.execute(f"PRAGMA index_list({table})"):  # noqa: S608  # nosec B608
        if not bool(index[2]):
            continue
        columns = [
            str(row[2])
            for row in connection.execute(f"PRAGMA index_info({index[1]})")  # noqa: S608  # nosec B608
        ]
        if columns == ["canonical_form"]:
            return True
    return False


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info({table})")  # noqa: S608  # nosec B608
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()  # noqa: UP017


def _migrate_atomic_facts_canonical(connection: sqlite3.Connection) -> None:
    """Add canonical FK columns to an atomic_facts table created before they existed.

    ``CREATE TABLE IF NOT EXISTS`` leaves a pre-existing table untouched, so databases
    created before this change keep the old shape. SQLite allows adding a nullable
    ``REFERENCES`` column to a populated table (existing rows get NULL, satisfying the
    foreign key), which lets legacy rows coexist without a backfill.
    """
    existing = {row[1] for row in connection.execute("PRAGMA table_info(atomic_facts)")}
    if "canonical_subject_id" not in existing:
        connection.execute(
            "ALTER TABLE atomic_facts "
            "ADD COLUMN canonical_subject_id TEXT REFERENCES canonical_subjects (id)"
        )
    if "canonical_predicate_id" not in existing:
        connection.execute(
            "ALTER TABLE atomic_facts "
            "ADD COLUMN canonical_predicate_id TEXT REFERENCES canonical_predicates (id)"
        )


def _migrate_evidence(connection: sqlite3.Connection) -> None:
    """Make legacy provenance optional and backfill normalized observation links."""
    if connection.execute(
        "SELECT 1 FROM schema_migrations WHERE id = ?", (EVIDENCE_MIGRATION_ID,)
    ).fetchone():
        return
    for table in ("atomic_facts", "foresight_records"):
        column = next(
            row
            for row in connection.execute(f"PRAGMA table_info({table})")
            if row[1] == "source_observation_id"
        )
        if column[3] == 0:
            continue
        original = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()[0]
        temporary = f"{table}_evidence_new"
        ddl = re.sub(
            rf"\bCREATE TABLE(?: IF NOT EXISTS)?\s+['\"`]?{table}['\"`]?",
            f"CREATE TABLE {temporary}",
            original,
            count=1,
            flags=re.IGNORECASE,
        )
        ddl = re.sub(
            r"\bsource_observation_id\s+TEXT\s+NOT NULL\b",
            "source_observation_id TEXT",
            ddl,
            count=1,
            flags=re.IGNORECASE,
        )
        if ddl == original or "source_observation_id TEXT NOT NULL" in ddl:
            raise RuntimeError(f"cannot rebuild {table} provenance column")
        connection.execute(ddl)
        columns = [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]
        quoted = ", ".join(f'"{name}"' for name in columns)
        # These identifiers derive exclusively from the fixed table list and its PRAGMA.
        connection.execute(
            f"INSERT INTO {temporary} ({quoted}) SELECT {quoted} FROM {table}"  # nosec B608
        )
        before = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # nosec B608
        after = connection.execute(f"SELECT COUNT(*) FROM {temporary}").fetchone()[0]  # nosec B608
        if before != after:
            raise RuntimeError(f"{table} rebuild lost rows")
        connection.execute(f"DROP TABLE {table}")
        connection.execute(f"ALTER TABLE {temporary} RENAME TO {table}")

    # Backfill only matching, extant observations; never invent provenance.
    targets = (
        ("atomic_fact", "atomic_facts", "source_observation_id", "atomic_fact_id"),
        ("foresight", "foresight_records", "source_observation_id", "foresight_id"),
    )
    for kind, table, column, fk_column in targets:
        confidence = "t.confidence" if table == "atomic_facts" else "1.0"
        rows = connection.execute(
            f"SELECT t.id, t.workspace_id, o.id, o.content, o.created_at, {confidence} "  # nosec B608
            f"FROM {table} AS t JOIN observations AS o ON o.id = t.{column} "
            "AND o.workspace_id = t.workspace_id "
            "JOIN sessions AS session ON session.id = o.session_id "
            "AND session.workspace_id = o.workspace_id AND session.status != 'deleted'"
        ).fetchall()
        for target_id, workspace_id, observation_id, content, observed_at, weight in rows:
            source_id = _backfill_observation_source(
                connection, workspace_id, observation_id, content, observed_at
            )
            _backfill_link(connection, workspace_id, source_id, kind, target_id, fk_column, weight)
    rows = connection.execute(
        "SELECT id, workspace_id, source_observations_json FROM graph_edges "
        "WHERE invalidated_at IS NULL"
    ).fetchall()
    for target_id, workspace_id, raw in rows:
        try:
            observation_ids = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(observation_ids, list):
            continue
        for observation_id in dict.fromkeys(str(value) for value in observation_ids):
            row = connection.execute(
                "SELECT o.content, o.created_at FROM observations AS o "
                "JOIN sessions AS session ON session.id = o.session_id "
                "AND session.workspace_id = o.workspace_id AND session.status != 'deleted' "
                "WHERE o.id = ? AND o.workspace_id = ?",
                (observation_id, workspace_id),
            ).fetchone()
            if row:
                source_id = _backfill_observation_source(
                    connection, workspace_id, observation_id, *row
                )
                _backfill_link(
                    connection,
                    workspace_id,
                    source_id,
                    "graph_edge",
                    target_id,
                    "graph_edge_id",
                    1.0,
                )
    rows = connection.execute(
        "SELECT r.id, r.workspace_id, o.id, o.content, o.created_at "
        "FROM reflection_evidence AS e JOIN reflections AS r ON r.id = e.reflection_id "
        "JOIN observations AS o ON o.id = e.observation_id AND o.workspace_id = r.workspace_id "
        "JOIN sessions AS session ON session.id = o.session_id "
        "AND session.workspace_id = o.workspace_id AND session.status != 'deleted' "
        "WHERE r.status = 'active'"
    ).fetchall()
    for target_id, workspace_id, observation_id, content, observed_at in rows:
        source_id = _backfill_observation_source(
            connection, workspace_id, observation_id, content, observed_at
        )
        _backfill_link(
            connection, workspace_id, source_id, "reflection", target_id, "reflection_id", 1.0
        )


def _migrate_source_scopes(connection: sqlite3.Connection) -> None:
    """Backfill source scope from project workspace mappings already in SQLite."""
    connection.execute(
        "UPDATE evidence_sources SET "
        "project_id = (SELECT p.project_id FROM project_namespaces AS p "
        "WHERE p.workspace_id = evidence_sources.workspace_id), "
        "namespace = (SELECT p.namespace FROM project_namespaces AS p "
        "WHERE p.workspace_id = evidence_sources.workspace_id) "
        "WHERE project_id IS NULL AND namespace IS NULL AND workspace_id IN "
        "(SELECT workspace_id FROM project_namespaces)"
    )
    connection.execute(
        "UPDATE evidence_sources SET "
        "project_id = (SELECT p.project_id FROM project_knowledge_workspaces AS p "
        "WHERE p.workspace_id = evidence_sources.workspace_id) "
        "WHERE project_id IS NULL AND namespace IS NULL AND workspace_id IN "
        "(SELECT workspace_id FROM project_knowledge_workspaces)"
    )


def _migrate_relation_rollback_metadata(connection: sqlite3.Connection) -> None:
    """Backfill relation rollback data and repair retractions from older versions."""
    has_rollback_metadata_migration = (
        connection.execute(
            "SELECT 1 FROM schema_migrations WHERE id = ?",
            (RELATION_ROLLBACK_MIGRATION_ID,),
        ).fetchone()
        is not None
    )
    has_invalidated_repair_migration = (
        connection.execute(
            "SELECT 1 FROM schema_migrations WHERE id = ?",
            (INVALIDATED_RELATION_REPAIR_MIGRATION_ID,),
        ).fetchone()
        is not None
    )
    if has_rollback_metadata_migration and has_invalidated_repair_migration:
        return

    # Earlier evidence registration assigned every conversation observation the same
    # authority. Correct only rows matching that legacy default, leaving caller-set
    # authority values intact.
    authority_by_role = {"user": 0.95, "assistant": 0.55, "system": 0.4, "tool": 0.35}
    sources = connection.execute(
        "SELECT source.id, observation.role FROM evidence_sources AS source "
        "JOIN observations AS observation ON observation.id = source.source_id "
        "AND observation.workspace_id = source.workspace_id "
        "WHERE source.source_type = 'conversation_observation' AND source.authority = 0.95 "
        "AND observation.role != 'user'"
    ).fetchall()
    for source_id, role in sources:
        connection.execute(
            "UPDATE evidence_sources SET authority = ? WHERE id = ?",
            (authority_by_role.get(str(role), 0.35), source_id),
        )

    relations = connection.execute(
        "SELECT edge.id, edge.workspace_id, edge.edge_type, edge.invalidated_at, "
        "edge.source_node_id, edge.target_node_id, edge.metadata_json, old_fact.id, "
        "old_fact.status, new_fact.id FROM graph_edges AS edge "
        "JOIN graph_nodes AS old_node ON old_node.id = edge.source_node_id "
        "AND old_node.workspace_id = edge.workspace_id AND old_node.source_table = 'atomic_facts' "
        "JOIN atomic_facts AS old_fact ON old_fact.id = old_node.source_id "
        "AND old_fact.workspace_id = edge.workspace_id "
        "JOIN graph_nodes AS new_node ON new_node.id = edge.target_node_id "
        "AND new_node.workspace_id = edge.workspace_id AND new_node.source_table = 'atomic_facts' "
        "JOIN atomic_facts AS new_fact ON new_fact.id = new_node.source_id "
        "AND new_fact.workspace_id = edge.workspace_id "
        "WHERE edge.edge_type IN ('SUPERSEDED_BY', 'CONTRADICTS')"
    ).fetchall()
    for (
        edge_id,
        workspace_id,
        edge_type,
        invalidated_at,
        source_node_id,
        target_node_id,
        raw_metadata,
        old_fact_id,
        old_status,
        new_fact_id,
    ) in relations:
        is_invalidated = invalidated_at is not None
        if is_invalidated and has_invalidated_repair_migration:
            continue
        if not is_invalidated and has_rollback_metadata_migration:
            continue
        try:
            metadata = json.loads(str(raw_metadata or "{}"))
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(metadata, dict):
            continue
        key = "supersession_rollback" if edge_type == "SUPERSEDED_BY" else "contradiction_rollback"
        if key in metadata:
            # The relation lifecycle already restored state when these metadata were
            # present. Reapplying a contradiction rollback would inflate confidence.
            continue
        if edge_type == "SUPERSEDED_BY":
            # The previous implementation normally superseded an active source fact.
            # If another active supersession already starts at this fact, preserve the
            # current superseded state when this relation is later retracted.
            prior_state = str(old_status)
            prior_edges = connection.execute(
                """
                SELECT 1 FROM graph_edges AS prior_edge
                JOIN graph_nodes AS prior_node
                  ON prior_node.id = prior_edge.source_node_id
                 AND prior_node.workspace_id = prior_edge.workspace_id
                WHERE prior_edge.workspace_id = (
                    SELECT workspace_id FROM graph_edges WHERE id = ?
                )
                  AND prior_edge.id != ?
                  AND prior_edge.edge_type = 'SUPERSEDED_BY'
                  AND prior_edge.invalidated_at IS NULL
                  AND prior_node.source_table = 'atomic_facts'
                  AND prior_node.source_id = ?
                LIMIT 1
                """,
                (edge_id, edge_id, old_fact_id),
            ).fetchone()
            if prior_edges:
                prior_state = "superseded"
            elif prior_state == "superseded":
                prior_state = "active"
            if prior_state not in {"active", "superseded", "contradicted", "expired", "rejected"}:
                prior_state = "active"
            metadata[key] = {
                "fact_id": str(old_fact_id),
                "status": prior_state,
                "valid_until": None,
            }
        else:
            # Existing apply_contradiction writes used a 0.7 confidence multiplier.
            metadata[key] = {
                "fact_ids": [str(old_fact_id), str(new_fact_id)],
                "confidence_factor": 0.7,
            }
        metadata_json = json.dumps(metadata, sort_keys=True)
        connection.execute(
            "UPDATE graph_edges SET metadata_json = ? WHERE id = ?",
            (metadata_json, edge_id),
        )
        if invalidated_at is not None:
            # Older retraction code invalidated relation edges without restoring the
            # fact state they had changed. Reconcile those rows once during migration.
            from core.db.evidence import restore_invalidated_graph_relation

            restore_invalidated_graph_relation(
                connection,
                {
                    "edge_type": edge_type,
                    "metadata_json": metadata_json,
                    "source_node_id": source_node_id,
                    "target_node_id": target_node_id,
                },
                str(workspace_id),
            )


def _backfill_observation_source(
    connection: sqlite3.Connection,
    workspace_id: str,
    observation_id: str,
    content: str,
    observed_at: str,
) -> str:
    connection.execute(
        "INSERT OR IGNORE INTO evidence_sources "
        "(id, workspace_id, source_type, source_id, authority, content_hash, "
        "observed_at, created_at) "
        "VALUES (?, ?, 'conversation_observation', ?, 0.95, ?, ?, ?)",
        (
            uuid.uuid4().hex,
            workspace_id,
            observation_id,
            hashlib.sha256(content.encode()).hexdigest(),
            observed_at,
            _now(),
        ),
    )
    row = connection.execute(
        "SELECT id FROM evidence_sources WHERE workspace_id = ? "
        "AND source_type = 'conversation_observation' AND source_id = ?",
        (workspace_id, observation_id),
    ).fetchone()
    if row is None:
        raise RuntimeError("backfilled observation source could not be loaded")
    return str(row[0])


def _backfill_link(
    connection: sqlite3.Connection,
    workspace_id: str,
    source_id: str,
    kind: str,
    target_id: str,
    fk_column: str,
    confidence: float,
) -> None:
    if (
        connection.execute(
            "SELECT 1 FROM evidence_sources WHERE id = ? AND retracted_at IS NULL", (source_id,)
        ).fetchone()
        is None
    ):
        return
    existing = connection.execute(
        "SELECT 1 FROM evidence_links WHERE workspace_id = ? AND source_id = ? "
        "AND target_type = ? AND target_id = ? AND stance = 'support' "
        "AND retracted_at IS NULL",
        (workspace_id, source_id, kind, target_id),
    ).fetchone()
    if not existing:
        connection.execute(
            f"INSERT INTO evidence_links (id, workspace_id, source_id, target_type, "  # nosec B608
            f"target_id, {fk_column}, stance, confidence, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'support', ?, ?)",
            (
                uuid.uuid4().hex,
                workspace_id,
                source_id,
                kind,
                target_id,
                target_id,
                max(0, min(1, float(confidence))),
                _now(),
            ),
        )


def seed_workspace_canonical_registries(connection: sqlite3.Connection, workspace_id: str) -> None:
    """Idempotently seed canonical vocabulary for one workspace."""
    _seed_canonical_registries(connection, workspace_id)


def _seed_canonical_registries(connection: sqlite3.Connection, workspace_id: str) -> None:
    """Idempotently seed canonical vocabulary without sharing user-derived buckets."""
    now = _now()
    for table, seeds in (
        ("canonical_subjects", _SEED_CANONICAL_SUBJECTS),
        ("canonical_predicates", _SEED_CANONICAL_PREDICATES),
    ):
        for canonical_form, aliases in seeds.items():
            connection.execute(
                f"INSERT OR IGNORE INTO {table} "  # noqa: S608  # nosec B608
                "(id, workspace_id, canonical_form, aliases_json, confidence, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    uuid.uuid4().hex,
                    workspace_id,
                    canonical_form,
                    json.dumps(list(aliases)),
                    1.0,
                    now,
                ),
            )
