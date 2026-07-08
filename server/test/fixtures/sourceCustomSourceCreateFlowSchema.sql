-- Schema fixture for server Custom Source create-flow integration tests
-- (testcontainers). SOURCE OF TRUTH: server/migrations/0001_baseline.sql.
-- Superset of sourceCustomSourceHandlersSchema.sql /
-- sourceCustomSourceMaterializerSchema.sql plus source_connectors and
-- extraction_jobs, since CustomSourceCreateFlowService exercises
-- PgSourcesRepository.createConnection (connector lookup) and the scan-job
-- orchestration (extraction_jobs pairing). CHECK / NOT NULL / UNIQUE
-- constraints are kept verbatim; unrelated FKs (spaces, users, runs,
-- proposals) are stripped except the proposals table needed for Phase 6's
-- Custom Source approval flow. Regenerate when these tables'
-- columns/constraints change.

CREATE TABLE public.source_connectors (
    id character varying(36) NOT NULL,
    connector_key character varying(128) NOT NULL,
    display_name character varying(256) NOT NULL,
    connector_type character varying(64) NOT NULL,
    ingestion_mode character varying(32) NOT NULL,
    status character varying(32) NOT NULL,
    capabilities_json jsonb NOT NULL,
    config_schema_json jsonb,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT source_connectors_pkey PRIMARY KEY (id),
    CONSTRAINT source_connectors_connector_key_key UNIQUE (connector_key)
);

CREATE TABLE public.credentials (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    owner_user_id character varying(36),
    name character varying(256) NOT NULL,
    credential_type character varying(64) NOT NULL,
    secret_ref text NOT NULL,
    scopes_json jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT credentials_pkey PRIMARY KEY (id)
);

CREATE TABLE public.source_connections (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    connector_id character varying(36) NOT NULL,
    owner_user_id character varying(36) NOT NULL,
    credential_id character varying(36),
    name character varying(512) NOT NULL,
    endpoint_url text,
    status character varying(32) NOT NULL,
    fetch_frequency character varying(32) NOT NULL,
    capture_policy character varying(64) NOT NULL,
    trust_level character varying(32) NOT NULL,
    topic_hints_json jsonb,
    consent_json jsonb NOT NULL,
    policy_json jsonb NOT NULL,
    config_json jsonb NOT NULL,
    schedule_rule_json jsonb,
    handler_kind character varying(32) NOT NULL DEFAULT 'built_in',
    active_handler_version_id character varying(36),
    active_recipe_version_id character varying(36),
    repair_status character varying(32) NOT NULL DEFAULT 'ok',
    last_handler_run_id character varying(36),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    deleted_at timestamp with time zone,
    CONSTRAINT source_connections_pkey PRIMARY KEY (id),
    CONSTRAINT ck_source_connections_capture_policy CHECK (((capture_policy)::text = ANY ((ARRAY['reference_only'::character varying, 'extract_text'::character varying, 'archive_original'::character varying])::text[]))),
    CONSTRAINT ck_source_connections_fetch_frequency CHECK (((fetch_frequency)::text = ANY ((ARRAY['manual'::character varying, 'hourly'::character varying, 'daily'::character varying, 'weekly'::character varying])::text[]))),
    CONSTRAINT ck_source_connections_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'paused'::character varying, 'archived'::character varying])::text[]))),
    CONSTRAINT ck_source_connections_trust_level CHECK (((trust_level)::text = ANY ((ARRAY['trusted'::character varying, 'normal'::character varying, 'untrusted'::character varying])::text[]))),
    CONSTRAINT ck_source_connections_handler_kind CHECK (((handler_kind)::text = ANY ((ARRAY['built_in'::character varying, 'generated_custom'::character varying, 'recipe'::character varying])::text[]))),
    CONSTRAINT ck_source_connections_repair_status CHECK (((repair_status)::text = ANY ((ARRAY['ok'::character varying, 'repair_required'::character varying, 'repair_pending'::character varying, 'disabled'::character varying])::text[]))),
    CONSTRAINT source_connections_connector_id_fkey FOREIGN KEY (connector_id) REFERENCES public.source_connectors(id)
);

-- Mirrors the Level 2 recipe portion of server/migrations/0001_baseline.sql.
CREATE TABLE public.source_recipe_versions (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    source_connection_id character varying(36) NOT NULL,
    version_number integer NOT NULL,
    recipe_json jsonb NOT NULL,
    policy_envelope_json jsonb NOT NULL,
    primitive_versions_json jsonb,
    status character varying(32) NOT NULL,
    created_by_user_id character varying(36),
    proposal_id character varying(36),
    test_result_json jsonb,
    created_at timestamp with time zone NOT NULL,
    activated_at timestamp with time zone,
    superseded_at timestamp with time zone,
    CONSTRAINT source_recipe_versions_pkey PRIMARY KEY (id),
    CONSTRAINT uq_source_recipe_versions_connection_version UNIQUE (source_connection_id, version_number),
    CONSTRAINT ck_source_recipe_versions_status CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'test_failed'::character varying, 'pending_approval'::character varying, 'active'::character varying, 'superseded'::character varying, 'disabled'::character varying])::text[]))),
    CONSTRAINT ck_source_recipe_versions_version_number CHECK ((version_number > 0)),
    CONSTRAINT source_recipe_versions_source_connection_id_fkey FOREIGN KEY (source_connection_id) REFERENCES public.source_connections(id) ON DELETE CASCADE
);

CREATE TABLE public.scheduler_tasks (
    id character varying(36) NOT NULL,
    task_type character varying(128) NOT NULL,
    task_key character varying(256) NOT NULL,
    scope_type character varying(32) NOT NULL,
    scope_id character varying(128) NOT NULL,
    space_id character varying(36),
    user_id character varying(36),
    status character varying(32) NOT NULL,
    next_run_at timestamp with time zone,
    last_run_at timestamp with time zone,
    state_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT scheduler_tasks_pkey PRIMARY KEY (id),
    CONSTRAINT uq_scheduler_tasks_type_key UNIQUE (task_type, task_key),
    CONSTRAINT ck_scheduler_tasks_scope_type CHECK (((scope_type)::text = ANY ((ARRAY['instance'::character varying, 'space'::character varying, 'user'::character varying, 'space_user'::character varying])::text[]))),
    CONSTRAINT ck_scheduler_tasks_state_json_object CHECK ((jsonb_typeof(state_json) = 'object'::text)),
    CONSTRAINT ck_scheduler_tasks_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'paused'::character varying, 'archived'::character varying])::text[])))
);

CREATE TABLE public.source_handler_versions (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    source_connection_id character varying(36) NOT NULL,
    version_number integer NOT NULL,
    language character varying(32) NOT NULL,
    entrypoint character varying(512) NOT NULL,
    handler_artifact_id character varying(36),
    manifest_json jsonb NOT NULL,
    input_schema_json jsonb,
    output_schema_json jsonb,
    policy_envelope_json jsonb NOT NULL,
    requested_capabilities_json jsonb,
    checksum character varying(128) NOT NULL,
    status character varying(32) NOT NULL,
    created_by_user_id character varying(36),
    created_by_run_id character varying(36),
    proposal_id character varying(36),
    test_result_json jsonb,
    created_at timestamp with time zone NOT NULL,
    activated_at timestamp with time zone,
    superseded_at timestamp with time zone,
    CONSTRAINT source_handler_versions_pkey PRIMARY KEY (id),
    CONSTRAINT uq_source_handler_versions_connection_version UNIQUE (source_connection_id, version_number),
    CONSTRAINT ck_source_handler_versions_language CHECK (((language)::text = ANY ((ARRAY['typescript_node'::character varying, 'declarative_pipeline_v1'::character varying])::text[]))),
    CONSTRAINT ck_source_handler_versions_status CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'test_failed'::character varying, 'pending_approval'::character varying, 'active'::character varying, 'superseded'::character varying, 'disabled'::character varying])::text[]))),
    CONSTRAINT ck_source_handler_versions_version_number CHECK ((version_number > 0)),
    CONSTRAINT source_handler_versions_source_connection_id_fkey FOREIGN KEY (source_connection_id) REFERENCES public.source_connections(id) ON DELETE CASCADE
);

CREATE TABLE public.source_handler_runs (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    source_connection_id character varying(36) NOT NULL,
    handler_version_id character varying(36) NOT NULL,
    extraction_job_id character varying(36),
    status character varying(32) NOT NULL,
    input_artifact_id character varying(36),
    output_artifact_id character varying(36),
    logs_artifact_id character varying(36),
    failure_class character varying(64),
    failure_detail_json jsonb,
    validation_result_json jsonb,
    resource_usage_json jsonb,
    created_at timestamp with time zone NOT NULL,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    CONSTRAINT source_handler_runs_pkey PRIMARY KEY (id),
    CONSTRAINT ck_source_handler_runs_status CHECK (((status)::text = ANY ((ARRAY['queued'::character varying, 'running'::character varying, 'succeeded'::character varying, 'failed'::character varying, 'validation_failed'::character varying, 'blocked'::character varying])::text[]))),
    CONSTRAINT source_handler_runs_source_connection_id_fkey FOREIGN KEY (source_connection_id) REFERENCES public.source_connections(id) ON DELETE CASCADE,
    CONSTRAINT source_handler_runs_handler_version_id_fkey FOREIGN KEY (handler_version_id) REFERENCES public.source_handler_versions(id) ON DELETE CASCADE
);

ALTER TABLE public.source_connections
    ADD CONSTRAINT source_connections_active_handler_version_id_fkey FOREIGN KEY (active_handler_version_id) REFERENCES public.source_handler_versions(id) ON DELETE SET NULL;

CREATE TABLE public.settings (
    id character varying(36) NOT NULL,
    scope_type character varying(32) NOT NULL,
    scope_id character varying(128) NOT NULL,
    settings_key character varying(128) NOT NULL,
    settings_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    updated_by_user_id character varying(36),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT settings_pkey PRIMARY KEY (id),
    CONSTRAINT ck_settings_json_object CHECK ((jsonb_typeof(settings_json) = 'object'::text)),
    CONSTRAINT ck_settings_scope_type CHECK (((scope_type)::text = ANY ((ARRAY['instance'::character varying, 'space'::character varying, 'user'::character varying, 'space_user'::character varying])::text[]))),
    CONSTRAINT uq_settings_scope_key UNIQUE (scope_type, scope_id, settings_key)
);

CREATE TABLE public.proposals (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    created_by_run_id character varying(36),
    proposal_type character varying(64) NOT NULL,
    status character varying(32) NOT NULL,
    risk_level character varying(32) NOT NULL,
    urgency character varying(32) NOT NULL,
    preview boolean DEFAULT false NOT NULL,
    title character varying(512) NOT NULL,
    summary text,
    payload_json jsonb NOT NULL,
    review_deadline timestamp with time zone,
    expires_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    reviewed_at timestamp with time zone,
    reviewed_by character varying(36),
    workspace_id character varying(36),
    rationale text,
    created_by_agent_id character varying(36),
    created_by_user_id character varying(36),
    required_approver_role character varying(64),
    visibility character varying(32) DEFAULT 'space_shared'::character varying NOT NULL,
    project_id character varying(36),
    CONSTRAINT proposals_pkey PRIMARY KEY (id),
    CONSTRAINT ck_proposals_risk_level CHECK (((risk_level)::text = ANY ((ARRAY['low'::character varying, 'medium'::character varying, 'high'::character varying, 'critical'::character varying])::text[]))),
    CONSTRAINT ck_proposals_urgency CHECK (((urgency)::text = ANY ((ARRAY['low'::character varying, 'normal'::character varying, 'high'::character varying, 'critical'::character varying])::text[])))
);

CREATE TABLE public.proposal_approvals (
    id character varying(36) NOT NULL,
    proposal_id character varying(36) NOT NULL,
    approval_type character varying(64) NOT NULL,
    approver_user_id character varying(36) NOT NULL,
    grant_id character varying(36),
    target_space_id character varying(36),
    status character varying(32) NOT NULL,
    metadata_json jsonb,
    created_at timestamp with time zone NOT NULL,
    revoked_at timestamp with time zone,
    CONSTRAINT proposal_approvals_pkey PRIMARY KEY (id)
);

CREATE TABLE public.runs (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    instructed_by_user_id character varying(36),
    CONSTRAINT runs_pkey PRIMARY KEY (id)
);

CREATE TABLE public.space_memberships (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    role character varying(32) NOT NULL,
    status character varying(32) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT space_memberships_pkey PRIMARY KEY (id),
    CONSTRAINT uq_space_memberships_space_user UNIQUE (space_id, user_id)
);

CREATE TABLE public.policy_decision_records (
    id character varying(36) NOT NULL,
    space_id character varying(36),
    actor_type character varying(64),
    actor_id character varying(36),
    actor_ref_json jsonb,
    action character varying(128) NOT NULL,
    resource_type character varying(64),
    resource_id character varying(256),
    decision character varying(32) NOT NULL,
    risk_level character varying(32) NOT NULL,
    required_approver_role character varying(32),
    approval_capability character varying(128),
    policy_rule_id character varying(128),
    policy_source character varying(64),
    policy_id character varying(36),
    audit_code character varying(128),
    run_id character varying(36),
    proposal_id character varying(36),
    metadata_json jsonb,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT policy_decision_records_pkey PRIMARY KEY (id)
);

CREATE TABLE public.artifacts (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    artifact_type character varying(64) NOT NULL,
    title character varying(512) NOT NULL,
    content text,
    storage_path character varying(1024),
    mime_type character varying(256),
    exportable boolean DEFAULT true NOT NULL,
    export_formats_json jsonb NOT NULL,
    canonical_format character varying(64),
    preview boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    visibility character varying(32) DEFAULT 'space_shared'::character varying NOT NULL,
    trust_level character varying(32),
    CONSTRAINT artifacts_pkey PRIMARY KEY (id),
    CONSTRAINT ck_artifacts_storage_path_relative CHECK (((storage_path IS NULL) OR ((storage_path)::text !~~ '/%'::text))),
    CONSTRAINT ck_artifacts_trust_level CHECK (((trust_level IS NULL) OR ((trust_level)::text = ANY ((ARRAY['high'::character varying, 'medium'::character varying, 'low'::character varying, 'unknown'::character varying])::text[]))))
);

-- Phase 12: pruneSupersededCustomSourceHandlerArtifacts must clear this FK
-- before deleting the referenced artifacts row (no ON DELETE clause here,
-- matching the real baseline) — this constraint is what makes that ordering
-- bug reproducible in a test instead of only against a live database.
ALTER TABLE public.source_handler_versions
    ADD CONSTRAINT source_handler_versions_handler_artifact_id_fkey FOREIGN KEY (handler_artifact_id) REFERENCES public.artifacts(id);

CREATE TABLE public.extraction_jobs (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    connection_id character varying(36),
    source_item_id character varying(36),
    source_snapshot_id character varying(36),
    source_object_type character varying(64),
    source_object_id character varying(36),
    job_type character varying(64) NOT NULL,
    status character varying(32) NOT NULL,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    items_seen integer,
    items_created integer,
    items_updated integer,
    error_code character varying(64),
    error_message character varying(512),
    metadata_json jsonb,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT extraction_jobs_pkey PRIMARY KEY (id),
    CONSTRAINT ck_extraction_jobs_job_type CHECK (((job_type)::text = ANY ((ARRAY['connection_scan'::character varying, 'manual_url'::character varying, 'extract_text'::character varying, 'snapshot'::character varying, 'normalize_activity'::character varying, 'normalize_artifact'::character varying, 'normalize_run_event'::character varying])::text[]))),
    CONSTRAINT ck_extraction_jobs_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'running'::character varying, 'succeeded'::character varying, 'failed'::character varying, 'skipped'::character varying])::text[])))
);

CREATE TABLE public.source_items (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    connection_id character varying(36),
    item_type character varying(64) NOT NULL,
    source_object_type character varying(64),
    source_object_id character varying(36),
    title character varying(1024) NOT NULL,
    source_uri text,
    canonical_uri text,
    source_domain character varying(256),
    source_external_id character varying(512),
    author character varying(512),
    occurred_at timestamp with time zone,
    first_seen_at timestamp with time zone NOT NULL,
    last_seen_at timestamp with time zone NOT NULL,
    content_hash character varying(128),
    excerpt character varying(2048),
    created_by_user_id character varying(36),
    content_state character varying(64) NOT NULL,
    retention_policy character varying(32) NOT NULL,
    relevance_score double precision,
    novelty_score double precision,
    raw_artifact_id character varying(36),
    extracted_artifact_id character varying(36),
    summary_artifact_id character varying(36),
    search_index_ref character varying(1024),
    embedding_index_ref character varying(1024),
    metadata_json jsonb,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    deleted_at timestamp with time zone,
    CONSTRAINT source_items_pkey PRIMARY KEY (id)
);

CREATE TABLE public.source_snapshots (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    source_item_id character varying(36),
    connection_id character varying(36),
    snapshot_type character varying(32) NOT NULL,
    artifact_id character varying(36),
    content_hash character varying(128),
    source_uri text,
    capture_method character varying(64) NOT NULL,
    trust_level character varying(32) NOT NULL,
    metadata_json jsonb,
    captured_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT source_snapshots_pkey PRIMARY KEY (id)
);

CREATE TABLE public.extracted_evidence (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    source_item_id character varying(36),
    extraction_job_id character varying(36),
    source_snapshot_id character varying(36),
    source_object_type character varying(64),
    source_object_id character varying(36),
    evidence_type character varying(64) NOT NULL,
    title character varying(1024) NOT NULL,
    content_excerpt character varying(4096),
    content_hash character varying(128),
    artifact_id character varying(36),
    source_uri text,
    source_title character varying(1024),
    source_author character varying(512),
    occurred_at timestamp with time zone,
    trust_level character varying(32) NOT NULL,
    extraction_method character varying(64) NOT NULL,
    confidence double precision,
    status character varying(32) NOT NULL,
    metadata_json jsonb,
    created_by_user_id character varying(36),
    created_by_agent_id character varying(36),
    created_by_run_id character varying(36),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    deleted_at timestamp with time zone,
    CONSTRAINT extracted_evidence_pkey PRIMARY KEY (id)
);

CREATE TABLE public.retrieval_objects (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    object_type character varying(64) NOT NULL,
    object_id character varying(36) NOT NULL,
    workspace_id character varying(36),
    owner_user_id character varying(36),
    visibility character varying(32),
    status character varying(32) NOT NULL,
    title character varying(512) NOT NULL,
    slug character varying(512),
    object_kind character varying(64),
    content_hash character varying(64) NOT NULL,
    source_connection_ids_json jsonb DEFAULT '[]'::jsonb NOT NULL,
    indexed_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    source_updated_at timestamp with time zone,
    CONSTRAINT retrieval_objects_pkey PRIMARY KEY (id),
    CONSTRAINT ck_retrieval_objects_source_connections_array CHECK ((jsonb_typeof(source_connection_ids_json) = 'array'::text))
);

CREATE TABLE public.retrieval_aliases (
    id character varying(36) NOT NULL,
    retrieval_object_id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    object_type character varying(64) NOT NULL,
    object_id character varying(36) NOT NULL,
    alias text NOT NULL,
    normalized_alias text NOT NULL,
    alias_kind character varying(32) NOT NULL,
    confidence double precision NOT NULL,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT retrieval_aliases_pkey PRIMARY KEY (id),
    CONSTRAINT ck_retrieval_aliases_confidence CHECK (((confidence >= (0)::double precision) AND (confidence <= (1)::double precision)))
);

CREATE TABLE public.retrieval_chunks (
    id character varying(36) NOT NULL,
    retrieval_object_id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    object_type character varying(64) NOT NULL,
    object_id character varying(36) NOT NULL,
    chunk_index integer NOT NULL,
    plain_text text NOT NULL,
    tsv tsvector,
    content_hash character varying(64) NOT NULL,
    embedding text,
    embedding_model character varying(128),
    embedding_dimensions integer,
    embedding_generated_at timestamp with time zone,
    embedding_claim_id character varying(64),
    embedding_claimed_at timestamp with time zone,
    embedding_attempts integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT retrieval_chunks_pkey PRIMARY KEY (id)
);

CREATE TABLE public.retrieval_edges (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    from_object_type character varying(64) NOT NULL,
    from_object_id character varying(36) NOT NULL,
    to_object_type character varying(64) NOT NULL,
    to_object_id character varying(36) NOT NULL,
    relation_type character varying(64) NOT NULL,
    edge_origin character varying(64) NOT NULL,
    edge_status character varying(32) NOT NULL,
    confidence double precision NOT NULL,
    evidence_json jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT retrieval_edges_pkey PRIMARY KEY (id),
    CONSTRAINT ck_retrieval_edges_confidence CHECK (((confidence >= (0)::double precision) AND (confidence <= (1)::double precision))),
    CONSTRAINT ck_retrieval_edges_status CHECK (((edge_status)::text = ANY ((ARRAY['derived'::character varying, 'suggested'::character varying])::text[])))
);

CREATE UNIQUE INDEX ix_retrieval_objects_space_object_unique ON public.retrieval_objects USING btree (space_id, object_type, object_id);
CREATE UNIQUE INDEX ix_retrieval_aliases_unique ON public.retrieval_aliases USING btree (space_id, object_type, object_id, normalized_alias, alias_kind);
CREATE UNIQUE INDEX ix_retrieval_chunks_object_chunk_unique ON public.retrieval_chunks USING btree (retrieval_object_id, chunk_index);
CREATE UNIQUE INDEX ix_retrieval_edges_unique ON public.retrieval_edges USING btree (space_id, from_object_type, from_object_id, to_object_type, to_object_id, relation_type, edge_origin);

CREATE TABLE public.jobs (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    job_type character varying(128) NOT NULL,
    status character varying(32) NOT NULL,
    priority integer NOT NULL,
    payload_json jsonb NOT NULL,
    result_json jsonb,
    error text,
    attempts integer NOT NULL,
    max_attempts integer NOT NULL,
    scheduled_at timestamp with time zone DEFAULT now() NOT NULL,
    claimed_by character varying(64),
    claimed_at timestamp with time zone,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    heartbeat_at timestamp with time zone,
    user_id character varying(36),
    workspace_id character varying(36),
    agent_id character varying(36),
    CONSTRAINT jobs_pkey PRIMARY KEY (id),
    CONSTRAINT ck_jobs_attempts_nonneg CHECK ((attempts >= 0)),
    CONSTRAINT ck_jobs_max_attempts_positive CHECK ((max_attempts > 0)),
    CONSTRAINT ck_jobs_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'claimed'::character varying, 'running'::character varying, 'completed'::character varying, 'failed'::character varying, 'cancelled'::character varying])::text[])))
);

CREATE INDEX ix_jobs_space_id ON public.jobs USING btree (space_id);
CREATE INDEX ix_jobs_status ON public.jobs USING btree (status);
CREATE INDEX ix_jobs_job_type ON public.jobs USING btree (job_type);
