-- server/migrations/0001_baseline.sql

--
-- PostgreSQL database dump
--


-- Dumped from database version 18.4 (Debian 18.4-1.pgdg13+1)
-- Dumped by pg_dump version 18.4 (Debian 18.4-1.pgdg13+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--
-- Hybrid-retrieval (Phase 2) embedding store. pgvector provides the `vector`
-- type and distance operators used by retrieval_chunks.embedding.
-- Requires a pgvector-enabled Postgres image (pgvector/pgvector:pg18).

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;


--
-- Name: activity_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.activity_records (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    source_run_id character varying(36),
    session_id character varying(36),
    user_id character varying(36),
    workspace_id character varying(36),
    agent_id character varying(36),
    source_task_id character varying(36),
    source_url text,
    activity_type character varying(64) NOT NULL,
    title character varying(512),
    content text,
    payload_json jsonb NOT NULL,
    occurred_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone NOT NULL,
    status character varying(32) DEFAULT 'raw'::character varying NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    source_kind character varying(64),
    source_trust character varying(32),
    source_integrity_json jsonb,
    entity_refs_json jsonb,
    subject_user_id character varying(36),
    processed_at timestamp with time zone,
    discarded_at timestamp with time zone,
    visibility character varying(32) DEFAULT 'space_shared'::character varying NOT NULL,
    owner_user_id character varying(36),
    project_id character varying(36),
    CONSTRAINT ck_activity_records_source_kind CHECK (((source_kind IS NULL) OR ((source_kind)::text = ANY ((ARRAY['user_capture'::character varying, 'chat_message'::character varying, 'external_chat'::character varying, 'file_import'::character varying, 'web_capture'::character varying, 'run_event'::character varying, 'workspace_event'::character varying, 'system_event'::character varying, 'external_source'::character varying, 'intake'::character varying])::text[])))),
    CONSTRAINT ck_activity_records_source_trust CHECK (((source_trust IS NULL) OR ((source_trust)::text = ANY ((ARRAY['user_confirmed'::character varying, 'internal_system'::character varying, 'trusted_external'::character varying, 'untrusted_external'::character varying, 'agent_inferred'::character varying])::text[])))),
    CONSTRAINT ck_activity_records_status CHECK (((status)::text = ANY ((ARRAY['raw'::character varying, 'processed'::character varying, 'proposals_generated'::character varying, 'failed'::character varying, 'archived'::character varying])::text[])))
);


--
-- Name: actors; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.actors (
    id character varying(36) NOT NULL,
    space_id character varying(36),
    actor_type character varying(32) NOT NULL,
    user_id character varying(36),
    agent_id character varying(36),
    service_name character varying(128),
    display_name character varying(256),
    status character varying(32) DEFAULT 'active'::character varying NOT NULL,
    metadata_json jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_actors_actor_type CHECK (((actor_type)::text = ANY ((ARRAY['user'::character varying, 'agent'::character varying, 'system'::character varying, 'automation'::character varying, 'connector'::character varying, 'integration'::character varying, 'service'::character varying, 'job'::character varying])::text[]))),
    CONSTRAINT ck_actors_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'disabled'::character varying, 'archived'::character varying])::text[])))
);


-- agent_template_versions and agent_templates tables removed:
-- template catalog is served from YAML files in catalog/agent_templates/;
-- the DB tables were unused (zero application queries).


--
-- Name: agent_versions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_versions (
    id character varying(36) NOT NULL,
    agent_id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    version_label character varying(64) NOT NULL,
    model_provider_id character varying(36),
    model_name character varying(256),
    system_prompt text,
    model_config_json jsonb NOT NULL,
    runtime_config_json jsonb NOT NULL,
    context_policy_json jsonb NOT NULL,
    memory_policy_json jsonb NOT NULL,
    capabilities_json jsonb NOT NULL,
    tool_permissions_json jsonb NOT NULL,
    runtime_policy_json jsonb NOT NULL,
    tool_policy_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    output_policy_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    schedule_config_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    output_schema_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    source_proposal_id character varying(36),
    source_activity_id character varying(36),
    created_at timestamp with time zone NOT NULL,
    published_at timestamp with time zone,
    archived_at timestamp with time zone
);


--
-- Name: agent_runtime_profiles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_runtime_profiles (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    agent_id character varying(36) NOT NULL,
    name character varying(128) NOT NULL,
    adapter_type character varying(64) NOT NULL,
    model_provider_id character varying(36),
    model_name character varying(256),
    credential_profile_id character varying(36),
    runtime_config_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    runtime_policy_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    is_default boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: agents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agents (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    owner_user_id character varying(36),
    name character varying(256) NOT NULL,
    description text,
    role_instruction text,
    status character varying(32) NOT NULL,
    agent_kind character varying(32) DEFAULT 'standard'::character varying NOT NULL,
    current_version_id character varying(36),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    visibility character varying(32) NOT NULL,
    CONSTRAINT ck_agents_agent_kind CHECK (((agent_kind)::text = ANY ((ARRAY['standard'::character varying, 'system_assistant'::character varying, 'system_evolver'::character varying])::text[]))),
    CONSTRAINT ck_agents_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'inactive'::character varying, 'archived'::character varying, 'disabled'::character varying])::text[])))
);


--
-- Name: artifacts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.artifacts (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    run_id character varying(36),
    proposal_id character varying(36),
    artifact_type character varying(64) NOT NULL,
    title character varying(512) NOT NULL,
    content text,
    storage_ref character varying(1024),
    storage_path character varying(1024),
    mime_type character varying(256),
    exportable boolean DEFAULT true NOT NULL,
    export_formats_json jsonb NOT NULL,
    canonical_format character varying(64),
    preview boolean DEFAULT false NOT NULL,
    relevant_period_start timestamp with time zone,
    relevant_period_end timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    metadata_json jsonb,
    visibility character varying(32) DEFAULT 'space_shared'::character varying NOT NULL,
    owner_user_id character varying(36),
    trust_level character varying(32),
    project_id character varying(36),
    workspace_id character varying(36),
    CONSTRAINT ck_artifacts_storage_path_relative CHECK (((storage_path IS NULL) OR ((storage_path)::text !~~ '/%'::text))),
    CONSTRAINT ck_artifacts_trust_level CHECK (((trust_level IS NULL) OR ((trust_level)::text = ANY ((ARRAY['high'::character varying, 'medium'::character varying, 'low'::character varying, 'unknown'::character varying])::text[])))),
    CONSTRAINT ck_artifacts_workspace_shared_workspace CHECK (((visibility)::text <> 'workspace_shared'::text) OR (workspace_id IS NOT NULL))
);


--
-- Name: context_artifact_revocations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.context_artifact_revocations (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    artifact_id character varying(36) NOT NULL,
    scope_type character varying(16) NOT NULL,
    scope_id character varying(36) NOT NULL,
    reason text,
    created_by_user_id character varying(36),
    deleted_by_user_id character varying(36),
    created_at timestamp with time zone NOT NULL,
    deleted_at timestamp with time zone,
    CONSTRAINT ck_context_artifact_revocations_scope_type CHECK (((scope_type)::text = ANY ((ARRAY['workspace'::character varying, 'project'::character varying])::text[])))
);


--
-- Name: auth_accounts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_accounts (
    id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    provider character varying(32) NOT NULL,
    provider_user_id character varying(256) NOT NULL,
    email character varying(256) NOT NULL,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: automation_credential_grants; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.automation_credential_grants (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    automation_id character varying(36) NOT NULL,
    granted_by_user_id character varying(36) NOT NULL,
    status character varying(32) DEFAULT 'active'::character varying NOT NULL,
    created_at timestamp with time zone NOT NULL,
    revoked_at timestamp with time zone,
    revoked_by_user_id character varying(36),
    CONSTRAINT ck_automation_credential_grants_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'revoked'::character varying])::text[])))
);


--
-- Name: automation_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.automation_runs (
    id character varying(36) NOT NULL,
    automation_id character varying(36) NOT NULL,
    run_id character varying(36) NOT NULL,
    triggered_by_user_id character varying(36),
    trigger_type character varying(64) DEFAULT 'manual'::character varying NOT NULL,
    preflight_snapshot_json jsonb,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: automations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.automations (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    owner_user_id character varying(36) NOT NULL,
    agent_id character varying(36) NOT NULL,
    workspace_id character varying(36),
    name character varying(256) NOT NULL,
    description text,
    trigger_type character varying(64) DEFAULT 'manual'::character varying NOT NULL,
    status character varying(32) DEFAULT 'active'::character varying NOT NULL,
    preflight_snapshot_json jsonb,
    config_json jsonb,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_automations_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'paused'::character varying, 'archived'::character varying])::text[]))),
    CONSTRAINT ck_automations_trigger_type CHECK (((trigger_type)::text = ANY ((ARRAY['manual'::character varying, 'schedule'::character varying])::text[])))
);


--
-- Name: board_columns; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.board_columns (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    board_id character varying(36) NOT NULL,
    name character varying(256) NOT NULL,
    description text,
    status_key character varying(64) NOT NULL,
    "position" integer DEFAULT 0 NOT NULL,
    wip_limit integer,
    is_done_column boolean DEFAULT false NOT NULL,
    is_default_column boolean DEFAULT false NOT NULL,
    metadata_json jsonb,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    deleted_at timestamp with time zone
);


--
-- Name: boards; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.boards (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    workspace_id character varying(36),
    project_id character varying(36),
    name character varying(512) NOT NULL,
    description text,
    board_type character varying(64) DEFAULT 'workspace'::character varying NOT NULL,
    status character varying(32) DEFAULT 'active'::character varying NOT NULL,
    default_view character varying(64),
    sort_order integer,
    metadata_json jsonb,
    created_by_user_id character varying(36),
    created_by_agent_id character varying(36),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    deleted_at timestamp with time zone
);


--
-- Name: capability_enablements; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.capability_enablements (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    project_id character varying(36),
    agent_id character varying(36),
    user_id character varying(36),
    capability_key character varying(128) NOT NULL,
    capability_version_id character varying(36),
    enabled boolean NOT NULL,
    config_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_capability_enablements_config_object CHECK ((jsonb_typeof(config_json) = 'object'::text)),
    CONSTRAINT ck_capability_enablements_single_scope CHECK (((((project_id IS NOT NULL))::integer + ((agent_id IS NOT NULL))::integer + ((user_id IS NOT NULL))::integer) <= 1))
);


--
-- Name: capability_overlays; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.capability_overlays (
    id character varying(36) NOT NULL,
    capability_key character varying(128) NOT NULL,
    scope_type character varying(32) NOT NULL,
    scope_id character varying(128),
    base_version_id character varying(36),
    overlay_type character varying(64) NOT NULL,
    patch_json jsonb NOT NULL,
    status character varying(32) NOT NULL,
    proposal_id character varying(36),
    metadata_json jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: capability_runtime_bindings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.capability_runtime_bindings (
    id character varying(36) NOT NULL,
    space_id character varying(36),
    capability_key character varying(128) NOT NULL,
    capability_version_id character varying(36),
    runtime_adapter_type character varying(64) NOT NULL,
    render_mode character varying(32) NOT NULL,
    binding_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_capability_runtime_bindings_binding_object CHECK ((jsonb_typeof(binding_json) = 'object'::text)),
    CONSTRAINT ck_capability_runtime_bindings_render_mode CHECK (((render_mode)::text = ANY ((ARRAY['render_skill'::character varying, 'inline_prompt'::character varying, 'native_executor'::character varying, 'mcp_tool'::character varying])::text[])))
);


--
-- Name: capability_versions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.capability_versions (
    id character varying(36) NOT NULL,
    capability_key character varying(128) NOT NULL,
    scope_type character varying(32) NOT NULL,
    scope_id character varying(128),
    parent_version_id character varying(36),
    version character varying(64) NOT NULL,
    source character varying(32) NOT NULL,
    artifact_uri character varying(1024),
    content_ref character varying(1024),
    content_hash character varying(128),
    status character varying(32) NOT NULL,
    proposal_id character varying(36),
    metadata_json jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: card_review_states; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.card_review_states (
    id character varying(36) NOT NULL,
    card_id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    due_at timestamp with time zone,
    stability double precision,
    difficulty double precision,
    elapsed_days double precision,
    scheduled_days double precision,
    reps integer NOT NULL,
    lapses integer NOT NULL,
    state character varying(32),
    last_reviewed_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_card_review_states_state CHECK (((state IS NULL) OR ((state)::text = ANY ((ARRAY['new'::character varying, 'learning'::character varying, 'review'::character varying, 'relearning'::character varying])::text[]))))
);


--
-- Name: card_reviews; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.card_reviews (
    id character varying(36) NOT NULL,
    card_id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    rating character varying(16) NOT NULL,
    reviewed_at timestamp with time zone NOT NULL,
    review_state_snapshot_json jsonb,
    duration_ms integer,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_card_reviews_rating CHECK (((rating)::text = ANY ((ARRAY['again'::character varying, 'hard'::character varying, 'good'::character varying, 'easy'::character varying])::text[])))
);


--
-- Name: cards; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cards (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    card_type character varying(32) NOT NULL,
    front text NOT NULL,
    back text NOT NULL,
    source_type character varying(32),
    source_id character varying(36),
    status character varying(32) NOT NULL,
    created_by_user_id character varying(36),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    archived_at timestamp with time zone,
    metadata_json jsonb,
    CONSTRAINT ck_cards_card_type CHECK (((card_type)::text = ANY ((ARRAY['basic'::character varying, 'cloze'::character varying])::text[]))),
    CONSTRAINT ck_cards_source_type CHECK (((source_type IS NULL) OR ((source_type)::text = ANY ((ARRAY['note'::character varying, 'knowledge_item'::character varying, 'source'::character varying, 'activity'::character varying, 'run'::character varying, 'proposal'::character varying])::text[])))),
    CONSTRAINT ck_cards_status CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'active'::character varying, 'suspended'::character varying, 'archived'::character varying])::text[])))
);


--
-- Name: cli_credential_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cli_credential_events (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    run_id character varying(36),
    runtime_adapter_type character varying(64),
    credential_profile_id character varying(128),
    credential_source character varying(32) NOT NULL,
    trigger_origin character varying(64),
    fallback_used boolean NOT NULL,
    fallback_reason character varying(128),
    broker_error boolean NOT NULL,
    cleanup_status character varying(32) NOT NULL,
    action character varying(64) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_cli_credential_events_credential_source CHECK (((credential_source)::text = ANY ((ARRAY['profile'::character varying, 'container_default'::character varying, 'none'::character varying])::text[])))
);


--
-- Name: cli_credential_profiles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cli_credential_profiles (
    id character varying(36) NOT NULL,
    owner_user_id character varying(36) NOT NULL,
    runtime character varying(64) NOT NULL,
    name character varying(128) NOT NULL,
    source_path text NOT NULL,
    target_path text NOT NULL,
    readonly boolean NOT NULL,
    notes text NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: cli_credential_space_grants; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cli_credential_space_grants (
    id character varying(36) NOT NULL,
    profile_id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    owner_user_id character varying(36) NOT NULL,
    granted_by_user_id character varying(36),
    enabled boolean NOT NULL,
    is_default boolean NOT NULL,
    network_profile_id character varying(36),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: code_patch_snapshots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.code_patch_snapshots (
    id character varying(36) NOT NULL,
    proposal_id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    workspace_id character varying(36) NOT NULL,
    files_json jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    status character varying(32) DEFAULT 'available'::character varying NOT NULL,
    rolled_back_by_user_id character varying(36),
    rolled_back_at timestamp with time zone,
    CONSTRAINT ck_code_patch_snapshots_status CHECK (((status)::text = ANY ((ARRAY['available'::character varying, 'rolled_back'::character varying, 'pruned'::character varying])::text[])))
);


--
-- Name: context_digests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.context_digests (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    scope_type character varying(32) NOT NULL,
    scope_id character varying(36),
    digest_type character varying(32) NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    status character varying(32) DEFAULT 'active'::character varying NOT NULL,
    content text,
    source_memory_ids_json jsonb,
    source_policy_ids_json jsonb,
    source_relation_ids_json jsonb,
    source_hash character varying(128),
    content_hash character varying(128),
    dirty_since timestamp with time zone,
    dirty_reason_json jsonb,
    dirty_count integer DEFAULT 0 NOT NULL,
    generated_at timestamp with time zone,
    created_from_run_id character varying(36),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_context_digests_digest_type CHECK (((digest_type)::text = ANY ((ARRAY['policy_bundle'::character varying, 'workspace'::character varying, 'agent'::character varying])::text[]))),
    CONSTRAINT ck_context_digests_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'dirty'::character varying, 'superseded'::character varying, 'disabled'::character varying])::text[])))
);


--
-- Name: context_profiles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.context_profiles (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    scope_type character varying(32) NOT NULL,
    scope_id character varying(128),
    status character varying(32) NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    context_pack_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    routing_manifest_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_by_user_id character varying(36),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_context_profiles_context_pack_object CHECK ((jsonb_typeof(context_pack_json) = 'object'::text)),
    CONSTRAINT ck_context_profiles_routing_manifest_object CHECK ((jsonb_typeof(routing_manifest_json) = 'object'::text)),
    CONSTRAINT ck_context_profiles_scope_id CHECK (((scope_type)::text = 'space'::text AND scope_id IS NULL) OR ((scope_type)::text <> 'space'::text AND scope_id IS NOT NULL)),
    CONSTRAINT ck_context_profiles_scope_type CHECK (((scope_type)::text = ANY ((ARRAY['space'::character varying, 'project'::character varying, 'workspace'::character varying, 'agent'::character varying, 'user'::character varying])::text[]))),
    CONSTRAINT ck_context_profiles_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'archived'::character varying])::text[]))),
    CONSTRAINT ck_context_profiles_version_positive CHECK ((version >= 1))
);


--
-- Name: context_snapshot_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.context_snapshot_items (
    id character varying(36) NOT NULL,
    context_snapshot_id character varying(36) NOT NULL,
    item_type character varying(32) NOT NULL,
    item_id character varying(36),
    title character varying(512),
    excerpt text,
    score double precision,
    reason character varying(256),
    token_count integer,
    metadata_json jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_context_snapshot_items_item_type CHECK (((item_type)::text = ANY ((ARRAY['memory'::character varying, 'knowledge_item'::character varying, 'source'::character varying, 'activity_record'::character varying, 'project_public_summary'::character varying, 'task'::character varying, 'idea'::character varying, 'project'::character varying, 'workspace'::character varying, 'run'::character varying, 'proposal'::character varying, 'artifact'::character varying, 'manual_context'::character varying])::text[])))
);


--
-- Name: context_snapshots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.context_snapshots (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    source_refs_json jsonb NOT NULL,
    compiled_summary text,
    token_estimate integer,
    relevant_period_start timestamp with time zone,
    relevant_period_end timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    compiled_prefix_text text,
    compiled_tail_text text,
    compiled_prefix_ref character varying(1024),
    compiled_tail_ref character varying(1024),
    prefix_hash character varying(128),
    tail_hash character varying(128),
    compiler_version character varying(64),
    retrieval_trace_json jsonb,
    token_budget_json jsonb,
    policy_bundle_version character varying(64),
    memory_digest_version character varying(64),
    workspace_digest_version character varying(64),
    included_memory_refs_json jsonb,
    included_evidence_refs_json jsonb,
    included_file_refs_json jsonb,
    included_doc_refs_json jsonb,
    redactions_json jsonb,
    data_exposure_level character varying(64),
    rendered_context_uri character varying(1024),
    rendered_context_text text,
    agent_id character varying(36),
    session_id character varying(36),
    run_id character varying(36),
    request_json jsonb,
    CONSTRAINT ck_context_snapshots_data_exposure_level CHECK (((data_exposure_level IS NULL) OR ((data_exposure_level)::text = ANY ((ARRAY['local_only'::character varying, 'model_provider'::character varying, 'vendor_platform'::character varying, 'third_party_tools'::character varying, 'unknown'::character varying])::text[]))))
);


--
-- Name: credentials; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.credentials (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    owner_user_id character varying(36),
    name character varying(256) NOT NULL,
    credential_type character varying(64) NOT NULL,
    secret_ref text NOT NULL,
    scopes_json jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: scheduler_tasks; Type: TABLE; Schema: public; Owner: -
--

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
    CONSTRAINT ck_scheduler_tasks_scope_type CHECK (((scope_type)::text = ANY ((ARRAY['instance'::character varying, 'space'::character varying, 'user'::character varying, 'space_user'::character varying])::text[]))),
    CONSTRAINT ck_scheduler_tasks_state_json_object CHECK ((jsonb_typeof(state_json) = 'object'::text)),
    CONSTRAINT ck_scheduler_tasks_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'paused'::character varying, 'archived'::character varying])::text[])))
);



--
-- Name: evidence_links; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.evidence_links (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    evidence_id character varying(36) NOT NULL,
    target_type character varying(64) NOT NULL,
    target_id character varying(36),
    link_type character varying(64) NOT NULL,
    status character varying(32) NOT NULL,
    confidence double precision,
    reason character varying(1024),
    created_by_user_id character varying(36),
    created_by_agent_id character varying(36),
    created_by_run_id character varying(36),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_evidence_links_link_type CHECK (((link_type)::text = ANY ((ARRAY['supports'::character varying, 'contradicts'::character varying, 'derived_from'::character varying, 'mentions'::character varying, 'context_candidate'::character varying, 'used_in_context'::character varying])::text[]))),
    CONSTRAINT ck_evidence_links_status CHECK (((status)::text = ANY ((ARRAY['candidate'::character varying, 'active'::character varying, 'rejected'::character varying, 'archived'::character varying])::text[]))),
    CONSTRAINT ck_evidence_links_target_type CHECK (((target_type)::text = ANY ((ARRAY['space'::character varying, 'workspace'::character varying, 'project'::character varying, 'user'::character varying, 'agent'::character varying, 'run'::character varying, 'proposal'::character varying, 'artifact'::character varying, 'knowledge'::character varying, 'memory'::character varying, 'task'::character varying])::text[])))
);


--
-- Name: evolution_signals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.evolution_signals (
    id character varying(36) NOT NULL,
    space_id character varying(36),
    target_id character varying(36) NOT NULL,
    signal_type character varying(128) NOT NULL,
    source_type character varying(64) NOT NULL,
    source_id character varying(128),
    severity character varying(32) NOT NULL,
    summary text,
    payload_json jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: evolution_strategy_assets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.evolution_strategy_assets (
    id character varying(36) NOT NULL,
    space_id character varying(36),
    strategy_key character varying(128) NOT NULL,
    name character varying(256) NOT NULL,
    description text,
    category character varying(32) NOT NULL,
    target_type character varying(64) NOT NULL,
    status character varying(32) DEFAULT 'draft'::character varying NOT NULL,
    risk_level character varying(32) NOT NULL,
    signals_match_json jsonb DEFAULT '[]'::jsonb NOT NULL,
    preconditions_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    strategy_steps_json jsonb DEFAULT '[]'::jsonb NOT NULL,
    constraints_json jsonb DEFAULT '[]'::jsonb NOT NULL,
    validation_policy_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    tool_policy_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    routing_hint_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    provenance_type character varying(32) NOT NULL,
    source_ref_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    success_count integer DEFAULT 0 NOT NULL,
    failure_count integer DEFAULT 0 NOT NULL,
    confidence_score double precision DEFAULT 0.5 NOT NULL,
    last_selected_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_evolution_strategy_assets_category CHECK (((category)::text = ANY ((ARRAY['repair'::character varying, 'optimize'::character varying, 'innovate'::character varying, 'maintain'::character varying, 'harden'::character varying, 'review'::character varying])::text[]))),
    CONSTRAINT ck_evolution_strategy_assets_confidence_score CHECK (((confidence_score >= (0)::double precision) AND (confidence_score <= (1)::double precision))),
    CONSTRAINT ck_evolution_strategy_assets_counts CHECK (((success_count >= 0) AND (failure_count >= 0))),
    CONSTRAINT ck_evolution_strategy_assets_provenance_type CHECK (((provenance_type)::text = ANY ((ARRAY['built_in'::character varying, 'user_authored'::character varying, 'imported'::character varying, 'evolved'::character varying, 'distilled'::character varying])::text[]))),
    CONSTRAINT ck_evolution_strategy_assets_risk_level CHECK (((risk_level)::text = ANY ((ARRAY['low'::character varying, 'medium'::character varying, 'high'::character varying, 'critical'::character varying])::text[]))),
    CONSTRAINT ck_evolution_strategy_assets_status CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'active'::character varying, 'disabled'::character varying, 'archived'::character varying])::text[]))),
    CONSTRAINT ck_evolution_strategy_assets_target_type CHECK (((target_type)::text = ANY ((ARRAY['agent_version'::character varying, 'capability'::character varying, 'runtime_skill_binding'::character varying, 'memory'::character varying, 'knowledge'::character varying, 'workflow'::character varying, 'workspace'::character varying, 'system'::character varying])::text[])))
);


--
-- Name: evolution_experiences; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.evolution_experiences (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    strategy_asset_id character varying(36),
    target_id character varying(36),
    source_run_id character varying(36),
    source_proposal_id character varying(36),
    experience_key character varying(160) NOT NULL,
    summary text NOT NULL,
    trigger_signals_json jsonb DEFAULT '[]'::jsonb NOT NULL,
    outcome_status character varying(32) NOT NULL,
    confidence_score double precision DEFAULT 0.5 NOT NULL,
    blast_radius_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    validation_trace_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    execution_trace_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    lessons_json jsonb DEFAULT '[]'::jsonb NOT NULL,
    anti_patterns_json jsonb DEFAULT '[]'::jsonb NOT NULL,
    environment_fingerprint_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    provenance_type character varying(32) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_evolution_experiences_confidence_score CHECK (((confidence_score >= (0)::double precision) AND (confidence_score <= (1)::double precision))),
    CONSTRAINT ck_evolution_experiences_outcome_status CHECK (((outcome_status)::text = ANY ((ARRAY['success'::character varying, 'failed'::character varying, 'partial'::character varying, 'unknown'::character varying])::text[]))),
    CONSTRAINT ck_evolution_experiences_provenance_type CHECK (((provenance_type)::text = ANY ((ARRAY['run_observed'::character varying, 'proposal_accepted'::character varying, 'imported'::character varying, 'user_authored'::character varying])::text[])))
);


--
-- Name: evolution_selector_decisions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.evolution_selector_decisions (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    target_id character varying(36) NOT NULL,
    run_id character varying(36),
    selected_strategy_asset_id character varying(36),
    candidate_strategy_ids_json jsonb DEFAULT '[]'::jsonb NOT NULL,
    input_signal_ids_json jsonb DEFAULT '[]'::jsonb NOT NULL,
    decision_reason text,
    score_trace_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    rejected_reasons_json jsonb DEFAULT '[]'::jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: evolution_targets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.evolution_targets (
    id character varying(36) NOT NULL,
    space_id character varying(36),
    target_type character varying(64) NOT NULL,
    target_ref_type character varying(64),
    target_ref_id character varying(128),
    capability_key character varying(128),
    current_version_id character varying(36),
    risk_level character varying(32) NOT NULL,
    status character varying(32) NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    engine_policy_json jsonb NOT NULL,
    metadata_json jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: external_run_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.external_run_records (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    run_id character varying(36) NOT NULL,
    vendor character varying(64) NOT NULL,
    vendor_run_id character varying(256),
    runtime_adapter_type character varying(64),
    external_url text,
    observability_level character varying(64) DEFAULT 'black_box'::character varying NOT NULL,
    data_exposure_level character varying(64) DEFAULT 'unknown'::character varying NOT NULL,
    trace_available boolean DEFAULT false NOT NULL,
    raw_summary text,
    raw_output_uri character varying(1024),
    imported_diff_uri character varying(1024),
    imported_artifacts_json jsonb,
    imported_logs_uri character varying(1024),
    status character varying(32) DEFAULT 'imported'::character varying NOT NULL,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_external_run_records_data_exposure_level CHECK (((data_exposure_level)::text = ANY ((ARRAY['local_only'::character varying, 'model_provider'::character varying, 'vendor_platform'::character varying, 'third_party_tools'::character varying, 'unknown'::character varying])::text[]))),
    CONSTRAINT ck_external_run_records_observability_level CHECK (((observability_level)::text = ANY ((ARRAY['full_trace'::character varying, 'structured_events'::character varying, 'artifacts_only'::character varying, 'final_output_only'::character varying, 'black_box'::character varying])::text[]))),
    CONSTRAINT ck_external_run_records_vendor CHECK (((vendor)::text = ANY ((ARRAY['openai'::character varying, 'anthropic'::character varying, 'cursor'::character varying, 'opencode'::character varying, 'manual'::character varying, 'other'::character varying])::text[])))
);


--
-- Name: extracted_evidence; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.extracted_evidence (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    intake_item_id character varying(36),
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
    CONSTRAINT ck_extracted_evidence_evidence_type CHECK (((evidence_type)::text = ANY ((ARRAY['document'::character varying, 'excerpt'::character varying, 'event'::character varying, 'log'::character varying, 'artifact'::character varying, 'claim'::character varying, 'summary'::character varying])::text[]))),
    CONSTRAINT ck_extracted_evidence_status CHECK (((status)::text = ANY ((ARRAY['candidate'::character varying, 'active'::character varying, 'rejected'::character varying, 'archived'::character varying])::text[]))),
    CONSTRAINT ck_extracted_evidence_trust_level CHECK (((trust_level)::text = ANY ((ARRAY['trusted'::character varying, 'normal'::character varying, 'untrusted'::character varying])::text[])))
);


--
-- Name: extraction_jobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.extraction_jobs (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    connection_id character varying(36),
    intake_item_id character varying(36),
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
    CONSTRAINT ck_extraction_jobs_job_type CHECK (((job_type)::text = ANY ((ARRAY['connection_scan'::character varying, 'manual_url'::character varying, 'extract_text'::character varying, 'snapshot'::character varying, 'normalize_activity'::character varying, 'normalize_artifact'::character varying, 'normalize_run_event'::character varying])::text[]))),
    CONSTRAINT ck_extraction_jobs_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'running'::character varying, 'succeeded'::character varying, 'failed'::character varying, 'skipped'::character varying])::text[])))
);


--
-- Name: intake_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.intake_items (
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
    status character varying(32) NOT NULL,
    read_status character varying(32) NOT NULL,
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
    CONSTRAINT ck_intake_items_content_state CHECK (((content_state)::text = ANY ((ARRAY['metadata_only'::character varying, 'excerpt_saved'::character varying, 'content_queued'::character varying, 'content_saved'::character varying, 'snapshot_queued'::character varying, 'snapshot_saved'::character varying, 'extraction_failed'::character varying, 'content_unavailable'::character varying])::text[]))),
    CONSTRAINT ck_intake_items_item_type CHECK (((item_type)::text = ANY ((ARRAY['external_url'::character varying, 'feed_entry'::character varying, 'activity_record'::character varying, 'artifact'::character varying, 'run_event'::character varying, 'file'::character varying, 'document'::character varying, 'log'::character varying])::text[]))),
    CONSTRAINT ck_intake_items_read_status CHECK (((read_status)::text = ANY ((ARRAY['unread'::character varying, 'skimmed'::character varying, 'read'::character varying, 'discussed'::character varying])::text[]))),
    CONSTRAINT ck_intake_items_retention_policy CHECK (((retention_policy)::text = ANY ((ARRAY['metadata_only'::character varying, 'summary_only'::character varying, 'full_text'::character varying, 'full_snapshot'::character varying, 'archived'::character varying])::text[]))),
    CONSTRAINT ck_intake_items_status CHECK (((status)::text = ANY ((ARRAY['new'::character varying, 'triaged'::character varying, 'selected'::character varying, 'ignored'::character varying, 'archived'::character varying])::text[])))
);


--
-- Name: job_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.job_events (
    id character varying(36) NOT NULL,
    job_id character varying(36) NOT NULL,
    event_type character varying(32) NOT NULL,
    message text NOT NULL,
    data jsonb,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: jobs; Type: TABLE; Schema: public; Owner: -
--

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
    CONSTRAINT ck_jobs_attempts_nonneg CHECK ((attempts >= 0)),
    CONSTRAINT ck_jobs_max_attempts_positive CHECK ((max_attempts > 0)),
    CONSTRAINT ck_jobs_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'claimed'::character varying, 'running'::character varying, 'completed'::character varying, 'failed'::character varying, 'cancelled'::character varying])::text[])))
);


--
-- Name: space_objects; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.space_objects (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    object_type character varying(32) NOT NULL,
    title character varying(512) NOT NULL,
    summary text,
    status character varying(32) NOT NULL,
    visibility character varying(32) DEFAULT 'space_shared'::character varying NOT NULL,
    owner_user_id character varying(36),
    primary_project_id character varying(36),
    workspace_id character varying(36),
    created_by_user_id character varying(36),
    created_by_agent_id character varying(36),
    created_by_run_id character varying(36),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    archived_at timestamp with time zone,
    deleted_at timestamp with time zone,
    CONSTRAINT ck_space_objects_object_type CHECK (((object_type)::text = ANY ((ARRAY['knowledge_item'::character varying, 'note'::character varying, 'source'::character varying, 'project'::character varying, 'person'::character varying, 'relationship'::character varying, 'asset'::character varying, 'event'::character varying, 'task'::character varying, 'document'::character varying, 'claim'::character varying])::text[]))),
    CONSTRAINT ck_space_objects_status CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'active'::character varying, 'disputed'::character varying, 'superseded'::character varying, 'rejected'::character varying, 'archived'::character varying, 'deleted'::character varying, 'raw'::character varying, 'processing'::character varying, 'processed'::character varying, 'error'::character varying])::text[]))),
    CONSTRAINT ck_space_objects_status_by_type CHECK (CASE (object_type)::text WHEN 'knowledge_item'::text THEN ((status)::text = ANY ((ARRAY['draft'::character varying, 'active'::character varying, 'superseded'::character varying, 'archived'::character varying, 'deleted'::character varying])::text[])) WHEN 'note'::text THEN ((status)::text = ANY ((ARRAY['active'::character varying, 'archived'::character varying, 'deleted'::character varying])::text[])) WHEN 'source'::text THEN ((status)::text = ANY ((ARRAY['raw'::character varying, 'processing'::character varying, 'processed'::character varying, 'archived'::character varying, 'error'::character varying])::text[])) WHEN 'claim'::text THEN ((status)::text = ANY ((ARRAY['active'::character varying, 'disputed'::character varying, 'superseded'::character varying, 'rejected'::character varying, 'archived'::character varying])::text[])) ELSE true END),
    CONSTRAINT ck_space_objects_visibility CHECK (((visibility)::text = ANY ((ARRAY['private'::character varying, 'space_shared'::character varying, 'workspace_shared'::character varying, 'restricted'::character varying])::text[])))
);


--
-- Name: space_object_kinds; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.space_object_kinds (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    key character varying(64) NOT NULL,
    label character varying(160) NOT NULL,
    description text,
    base_object_type character varying(64) NOT NULL,
    status character varying(32) DEFAULT 'active'::character varying NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    field_schema_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    extraction_policy_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    retrieval_policy_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    ui_config_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_by_user_id character varying(36),
    created_from_proposal_id character varying(36),
    updated_from_proposal_id character varying(36),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_space_object_kinds_base_object_type CHECK (((base_object_type)::text = ANY ((ARRAY['knowledge_item'::character varying, 'note'::character varying, 'source'::character varying, 'claim'::character varying, 'memory_entry'::character varying, 'project_public_summary'::character varying])::text[]))),
    CONSTRAINT ck_space_object_kinds_extraction_policy_object CHECK ((jsonb_typeof(extraction_policy_json) = 'object'::text)),
    CONSTRAINT ck_space_object_kinds_field_schema_object CHECK ((jsonb_typeof(field_schema_json) = 'object'::text)),
    CONSTRAINT ck_space_object_kinds_key CHECK (((key)::text ~ '^[a-z][a-z0-9_]{0,63}$'::text)),
    CONSTRAINT ck_space_object_kinds_key_by_base_object_type CHECK (CASE (base_object_type)::text WHEN 'knowledge_item'::text THEN ((key)::text = ANY ((ARRAY['concept'::character varying, 'lesson'::character varying, 'procedure'::character varying, 'decision'::character varying, 'question'::character varying, 'answer'::character varying, 'summary'::character varying])::text[])) WHEN 'note'::text THEN ((key)::text = 'note'::text) WHEN 'source'::text THEN ((key)::text = ANY ((ARRAY['activity_record'::character varying, 'chat_capture'::character varying, 'webpage'::character varying, 'article'::character varying, 'paper'::character varying, 'pdf'::character varying, 'file'::character varying, 'email'::character varying, 'manual_reference'::character varying, 'external_note'::character varying])::text[])) WHEN 'claim'::text THEN ((key)::text = ANY ((ARRAY['fact'::character varying, 'hypothesis'::character varying, 'belief'::character varying, 'preference'::character varying, 'commitment'::character varying, 'question'::character varying, 'interpretation'::character varying, 'instruction'::character varying, 'metric'::character varying, 'relationship'::character varying, 'event'::character varying])::text[])) WHEN 'memory_entry'::text THEN ((key)::text = ANY ((ARRAY['preference'::character varying, 'semantic'::character varying, 'episodic'::character varying, 'procedural'::character varying, 'project'::character varying])::text[])) WHEN 'project_public_summary'::text THEN ((key)::text = 'project_public_summary'::text) ELSE false END),
    CONSTRAINT ck_space_object_kinds_retrieval_policy_object CHECK ((jsonb_typeof(retrieval_policy_json) = 'object'::text)),
    CONSTRAINT ck_space_object_kinds_status CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'active'::character varying, 'deprecated'::character varying, 'archived'::character varying])::text[]))),
    CONSTRAINT ck_space_object_kinds_ui_config_object CHECK ((jsonb_typeof(ui_config_json) = 'object'::text)),
    CONSTRAINT ck_space_object_kinds_version_positive CHECK ((version >= 1))
);


--
-- Name: space_object_kind_relation_hints; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.space_object_kind_relation_hints (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    object_kind_id character varying(36) NOT NULL,
    endpoint_object_type character varying(64) NOT NULL,
    endpoint_object_kind_id character varying(36),
    relation_type character varying(64) NOT NULL,
    direction character varying(16) DEFAULT 'from'::character varying NOT NULL,
    confidence_default double precision DEFAULT 0.55 NOT NULL,
    required boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_space_object_kind_relation_hints_confidence CHECK (((confidence_default >= (0)::double precision) AND (confidence_default <= (1)::double precision))),
    CONSTRAINT ck_space_object_kind_relation_hints_direction CHECK (((direction)::text = ANY ((ARRAY['from'::character varying, 'to'::character varying, 'either'::character varying])::text[]))),
    CONSTRAINT ck_space_object_kind_relation_hints_endpoint_type CHECK (((endpoint_object_type)::text = ANY ((ARRAY['knowledge_item'::character varying, 'note'::character varying, 'source'::character varying, 'claim'::character varying, 'memory_entry'::character varying, 'project_public_summary'::character varying])::text[]))),
    CONSTRAINT ck_space_object_kind_relation_hints_relation_type CHECK (((relation_type)::text = ANY ((ARRAY['related_to'::character varying, 'explains'::character varying, 'depends_on'::character varying, 'prerequisite_of'::character varying, 'part_of'::character varying, 'example_of'::character varying, 'applies_to'::character varying, 'supports'::character varying, 'contradicts'::character varying, 'derived_from'::character varying, 'summarizes'::character varying, 'updates'::character varying, 'references'::character varying, 'source_for'::character varying, 'about'::character varying, 'supersedes'::character varying, 'refines'::character varying, 'same_as'::character varying])::text[])))
);



--
-- Name: knowledge_item_sources; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.knowledge_item_sources (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    knowledge_item_id character varying(36) NOT NULL,
    source_id character varying(36) NOT NULL,
    relation_type character varying(32) NOT NULL,
    locator character varying(1024),
    quote text,
    note text,
    confidence double precision,
    created_by_user_id character varying(36),
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_knowledge_item_sources_confidence CHECK (((confidence IS NULL) OR ((confidence >= (0)::double precision) AND (confidence <= (1)::double precision)))),
    CONSTRAINT ck_knowledge_item_sources_relation_type CHECK (((relation_type)::text = ANY ((ARRAY['derived_from'::character varying, 'supported_by'::character varying, 'cites'::character varying, 'summarizes'::character varying, 'mentions'::character varying])::text[])))
);


--
-- Name: knowledge_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.knowledge_items (
    object_id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    root_item_id character varying(36),
    supersedes_item_id character varying(36),
    knowledge_kind character varying(32) NOT NULL,
    slug character varying(512),
    aliases_json jsonb,
    content text NOT NULL,
    content_json jsonb,
    content_format character varying(32) NOT NULL,
    content_schema_version integer NOT NULL,
    plain_text text,
    verification_status character varying(32) NOT NULL,
    reflection_status character varying(32) NOT NULL,
    tags_json jsonb NOT NULL,
    confidence double precision,
    created_from_proposal_id character varying(36),
    approved_by_user_id character varying(36),
    redirect_to_item_id character varying(36),
    version integer NOT NULL,
    deprecated_at timestamp with time zone,
    CONSTRAINT ck_knowledge_items_confidence CHECK (((confidence IS NULL) OR ((confidence >= (0)::double precision) AND (confidence <= (1)::double precision)))),
    CONSTRAINT ck_knowledge_items_content_format CHECK (((content_format)::text = ANY ((ARRAY['markdown'::character varying, 'plain'::character varying, 'prosemirror_json'::character varying])::text[]))),
    CONSTRAINT ck_knowledge_items_knowledge_kind CHECK (((knowledge_kind)::text = ANY ((ARRAY['concept'::character varying, 'lesson'::character varying, 'procedure'::character varying, 'decision'::character varying, 'question'::character varying, 'answer'::character varying, 'summary'::character varying])::text[]))),
    CONSTRAINT ck_knowledge_items_reflection_status CHECK (((reflection_status)::text = ANY ((ARRAY['unreviewed'::character varying, 'reviewed'::character varying, 'distilled'::character varying])::text[]))),
    CONSTRAINT ck_knowledge_items_verification_status CHECK (((verification_status)::text = ANY ((ARRAY['unverified'::character varying, 'needs_review'::character varying, 'verified'::character varying])::text[])))
);


--
-- Name: claims; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.claims (
    object_id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    subject_object_id character varying(36),
    subject_text text,
    claim_kind character varying(32) NOT NULL,
    claim_text text NOT NULL,
    normalized_claim_hash character varying(128) NOT NULL,
    holder_object_id character varying(36),
    holder_type character varying(64),
    holder_id character varying(128),
    confidence double precision,
    confidence_method character varying(32) NOT NULL,
    resolution_state character varying(32) NOT NULL,
    valid_from timestamp with time zone,
    valid_until timestamp with time zone,
    observed_at timestamp with time zone,
    metadata_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_from_proposal_id character varying(36),
    approved_by_user_id character varying(36),
    CONSTRAINT ck_claims_claim_kind CHECK (((claim_kind)::text = ANY ((ARRAY['fact'::character varying, 'hypothesis'::character varying, 'belief'::character varying, 'preference'::character varying, 'commitment'::character varying, 'question'::character varying, 'interpretation'::character varying, 'instruction'::character varying, 'metric'::character varying, 'relationship'::character varying, 'event'::character varying])::text[]))),
    CONSTRAINT ck_claims_claim_text CHECK ((btrim(claim_text) <> ''::text)),
    CONSTRAINT ck_claims_confidence CHECK (((confidence IS NULL) OR ((confidence >= (0)::double precision) AND (confidence <= (1)::double precision)))),
    CONSTRAINT ck_claims_confidence_method CHECK (((confidence_method)::text = ANY ((ARRAY['human_confirmed'::character varying, 'source_extracted'::character varying, 'llm_extracted'::character varying, 'inferred'::character varying, 'imported'::character varying])::text[]))),
    CONSTRAINT ck_claims_holder_ref CHECK ((((holder_object_id IS NOT NULL) AND (holder_type IS NULL) AND (holder_id IS NULL)) OR ((holder_object_id IS NULL) AND (((holder_type IS NULL) AND (holder_id IS NULL)) OR ((holder_type IS NOT NULL) AND (holder_id IS NOT NULL)))))),
    CONSTRAINT ck_claims_metadata_object CHECK ((jsonb_typeof(metadata_json) = 'object'::text)),
    CONSTRAINT ck_claims_resolution_state CHECK (((resolution_state)::text = ANY ((ARRAY['unreviewed'::character varying, 'confirmed'::character varying, 'contradicted'::character varying, 'stale'::character varying, 'needs_source'::character varying])::text[]))),
    CONSTRAINT ck_claims_subject CHECK (((subject_object_id IS NOT NULL) OR ((subject_text IS NOT NULL) AND (btrim(subject_text) <> ''::text)))),
    CONSTRAINT ck_claims_valid_range CHECK (((valid_from IS NULL) OR (valid_until IS NULL) OR (valid_from <= valid_until)))
);


--
-- Name: claim_sources; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.claim_sources (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    claim_id character varying(36) NOT NULL,
    source_object_id character varying(36),
    source_ref_type character varying(64),
    source_ref_id character varying(36),
    source_connection_id character varying(36),
    source_policy_snapshot_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    locator character varying(1024),
    quote_excerpt text,
    evidence_role character varying(32) NOT NULL,
    source_trust character varying(32),
    confidence double precision,
    metadata_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_by_user_id character varying(36),
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_claim_sources_confidence CHECK (((confidence IS NULL) OR ((confidence >= (0)::double precision) AND (confidence <= (1)::double precision)))),
    CONSTRAINT ck_claim_sources_evidence_role CHECK (((evidence_role)::text = ANY ((ARRAY['supports'::character varying, 'contradicts'::character varying, 'mentions'::character varying, 'derived_from'::character varying, 'cites'::character varying, 'summarizes'::character varying])::text[]))),
    CONSTRAINT ck_claim_sources_metadata_object CHECK ((jsonb_typeof(metadata_json) = 'object'::text)),
    CONSTRAINT ck_claim_sources_policy_snapshot_object CHECK ((jsonb_typeof(source_policy_snapshot_json) = 'object'::text)),
    CONSTRAINT ck_claim_sources_has_source CHECK (((source_object_id IS NOT NULL) OR ((source_ref_type IS NOT NULL) AND (source_ref_id IS NOT NULL)) OR (source_connection_id IS NOT NULL))),
    CONSTRAINT ck_claim_sources_source_ref CHECK ((((source_ref_type IS NULL) AND (source_ref_id IS NULL)) OR ((source_ref_type IS NOT NULL) AND (source_ref_id IS NOT NULL)))),
    CONSTRAINT ck_claim_sources_source_ref_connection CHECK (((source_ref_type IS NULL) OR (source_connection_id IS NOT NULL))),
    CONSTRAINT ck_claim_sources_source_ref_type CHECK (((source_ref_type IS NULL) OR ((source_ref_type)::text = ANY ((ARRAY['activity'::character varying, 'artifact'::character varying, 'run_event'::character varying, 'extracted_evidence'::character varying, 'source_snapshot'::character varying, 'external_pointer'::character varying, 'intake_item'::character varying])::text[])))),
    CONSTRAINT ck_claim_sources_source_trust CHECK (((source_trust IS NULL) OR ((source_trust)::text = ANY ((ARRAY['trusted'::character varying, 'normal'::character varying, 'untrusted'::character varying, 'unknown'::character varying])::text[]))))
);



--
-- Name: object_relations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.object_relations (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    from_object_id character varying(36) NOT NULL,
    to_object_id character varying(36) NOT NULL,
    relation_type character varying(64) NOT NULL,
    status character varying(32) NOT NULL,
    confidence double precision,
    evidence_summary text,
    source_claim_id character varying(36),
    source_object_id character varying(36),
    source_proposal_id character varying(36),
    metadata_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_by_user_id character varying(36),
    created_by_agent_id character varying(36),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_object_relations_confidence CHECK (((confidence IS NULL) OR ((confidence >= (0)::double precision) AND (confidence <= (1)::double precision)))),
    CONSTRAINT ck_object_relations_metadata_object CHECK ((jsonb_typeof(metadata_json) = 'object'::text)),
    CONSTRAINT ck_object_relations_no_self CHECK (((from_object_id)::text <> (to_object_id)::text)),
    CONSTRAINT ck_object_relations_relation_type CHECK (((relation_type)::text = ANY ((ARRAY['related_to'::character varying, 'references'::character varying, 'depends_on'::character varying, 'part_of'::character varying, 'source_for'::character varying, 'derived_from'::character varying, 'about'::character varying, 'supports'::character varying, 'contradicts'::character varying, 'supersedes'::character varying, 'refines'::character varying, 'same_as'::character varying])::text[]))),
    CONSTRAINT ck_object_relations_status CHECK (((status)::text = ANY ((ARRAY['candidate'::character varying, 'active'::character varying, 'rejected'::character varying, 'archived'::character varying])::text[])))
);


--
-- Name: memory_access_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.memory_access_logs (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    memory_id character varying(36) NOT NULL,
    user_id character varying(36),
    agent_id character varying(36),
    run_id character varying(36),
    access_type character varying(64) NOT NULL,
    reason text,
    accessed_at timestamp with time zone NOT NULL
);


--
-- Name: memory_maintenance_jobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.memory_maintenance_jobs (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    owner_user_id character varying(36) NOT NULL,
    status character varying(32) DEFAULT 'pending'::character varying NOT NULL,
    review_scope character varying(32) DEFAULT 'private'::character varying NOT NULL,
    scan_options_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    cursor character varying(256),
    total_scanned integer DEFAULT 0 NOT NULL,
    total_findings integer DEFAULT 0 NOT NULL,
    last_report_artifact_id character varying(36),
    last_packet_proposal_id character varying(36),
    error_message text,
    run_after timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    completed_at timestamp with time zone,
    CONSTRAINT ck_memory_maintenance_jobs_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'running'::character varying, 'completed'::character varying, 'failed'::character varying])::text[]))),
    CONSTRAINT ck_memory_maintenance_jobs_review_scope CHECK (((review_scope)::text = ANY ((ARRAY['private'::character varying, 'space_ops'::character varying])::text[]))),
    CONSTRAINT ck_memory_maintenance_jobs_total_scanned CHECK ((total_scanned >= 0)),
    CONSTRAINT ck_memory_maintenance_jobs_total_findings CHECK ((total_findings >= 0))
);


--
-- Name: memory_entries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.memory_entries (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    scope_type character varying(32) NOT NULL,
    memory_type character varying(32) NOT NULL,
    content text NOT NULL,
    status character varying(32) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    valid_from timestamp with time zone,
    valid_to timestamp with time zone,
    subject_user_id character varying(36),
    owner_user_id character varying(36),
    sensitivity_level character varying(32) DEFAULT 'normal'::character varying NOT NULL,
    selected_user_ids jsonb,
    last_confirmed_at timestamp with time zone,
    workspace_id character varying(36),
    agent_id character varying(36),
    namespace character varying(255),
    title character varying(512),
    visibility character varying(32) NOT NULL,
    confidence double precision NOT NULL,
    importance double precision NOT NULL,
    source_id character varying(36),
    created_by character varying(64),
    approved_by character varying(64),
    deleted_at timestamp with time zone,
    version integer NOT NULL,
    access_count integer NOT NULL,
    last_accessed_at timestamp with time zone,
    tags jsonb,
    memory_layer character varying(32),
    event_time timestamp with time zone,
    event_type character varying(64),
    last_retrieved_at timestamp with time zone,
    root_memory_id character varying(36),
    supersedes_memory_id character varying(36),
    source_trust character varying(32),
    created_from_proposal_id character varying(36),
    project_id character varying(36),
    CONSTRAINT ck_memory_entries_memory_layer CHECK (((memory_layer IS NULL) OR ((memory_layer)::text = ANY ((ARRAY['episodic'::character varying, 'semantic'::character varying])::text[])))),
    CONSTRAINT ck_memory_entries_sensitivity_level CHECK (((sensitivity_level)::text = ANY ((ARRAY['normal'::character varying, 'sensitive'::character varying, 'restricted'::character varying, 'highly_restricted'::character varying])::text[]))),
    CONSTRAINT ck_memory_entries_source_trust CHECK (((source_trust IS NULL) OR ((source_trust)::text = ANY ((ARRAY['user_confirmed'::character varying, 'internal_system'::character varying, 'trusted_external'::character varying, 'untrusted_external'::character varying, 'agent_inferred'::character varying])::text[]))))
);


--
-- Name: memory_relations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.memory_relations (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    source_type character varying(64) NOT NULL,
    source_id character varying(36) NOT NULL,
    target_type character varying(64) NOT NULL,
    target_id character varying(36) NOT NULL,
    relation_type character varying(64) NOT NULL,
    confidence double precision,
    evidence_json jsonb,
    created_from_proposal_id character varying(36),
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_memory_relations_relation_type CHECK (((relation_type)::text = ANY ((ARRAY['derived_from'::character varying, 'supersedes'::character varying, 'contradicts'::character varying, 'related_to'::character varying, 'caused_by'::character varying, 'supports'::character varying, 'applies_to'::character varying, 'mentions'::character varying])::text[])))
);


--
-- Name: messages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.messages (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    session_id character varying(36) NOT NULL,
    user_id character varying(36),
    role character varying(32) NOT NULL,
    content text NOT NULL,
    metadata_json jsonb,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_messages_role CHECK (((role)::text = ANY ((ARRAY['user'::character varying, 'assistant'::character varying, 'system'::character varying, 'tool'::character varying])::text[])))
);


--
-- Name: network_profiles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.network_profiles (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    name character varying(128) NOT NULL,
    mode character varying(32) NOT NULL,
    proxy_url character varying(512),
    no_proxy text,
    enabled boolean NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_network_profiles_mode CHECK (((mode)::text = ANY ((ARRAY['direct'::character varying, 'http_proxy'::character varying])::text[])))
);


--
-- Name: model_provider_credentials; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.model_provider_credentials (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    provider_id character varying(36) NOT NULL,
    credential_id character varying(36) NOT NULL,
    "position" integer NOT NULL,
    enabled boolean NOT NULL,
    healthy boolean NOT NULL,
    cooldown_until timestamp with time zone,
    last_failure_class character varying(32),
    request_count bigint NOT NULL,
    failure_count bigint NOT NULL,
    last_used_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_model_provider_credentials_failure_class CHECK ((((last_failure_class)::text = ANY ((ARRAY['rate_limit'::character varying, 'payment_required'::character varying, 'unauthorized'::character varying, 'quota_exhausted'::character varying, 'transient'::character varying, 'permanent'::character varying])::text[])) OR (last_failure_class IS NULL)))
);


--
-- Name: model_providers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.model_providers (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    owner_user_id character varying(36),
    name character varying(128) NOT NULL,
    provider_type character varying(64) NOT NULL,
    base_url character varying(512),
    network_profile_id character varying(36),
    default_model character varying(256),
    enabled boolean NOT NULL,
    credential_id character varying(36),
    capabilities_json jsonb NOT NULL,
    config_json jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: model_provider_space_grants; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.model_provider_space_grants (
    id character varying(36) NOT NULL,
    provider_id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    owner_user_id character varying(36),
    granted_by_user_id character varying(36),
    enabled boolean NOT NULL,
    is_default boolean NOT NULL,
    network_profile_id character varying(36),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: note_collection_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.note_collection_items (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    collection_id character varying(36) NOT NULL,
    note_id character varying(36) NOT NULL,
    sort_order integer NOT NULL,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: note_collections; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.note_collections (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    parent_id character varying(36),
    name character varying(256) NOT NULL,
    system_role character varying(32) NOT NULL,
    sort_order integer NOT NULL,
    is_system boolean NOT NULL,
    is_hidden boolean NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_note_collections_not_self_parent CHECK (((parent_id IS NULL) OR ((parent_id)::text <> (id)::text))),
    CONSTRAINT ck_note_collections_system_role CHECK (((system_role)::text = ANY ((ARRAY['normal'::character varying, 'inbox'::character varying, 'archive'::character varying])::text[])))
);


--
-- Name: notes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notes (
    object_id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    content_json jsonb,
    content_format character varying(32) NOT NULL,
    content_schema_version integer NOT NULL,
    plain_text text,
    created_from_activity_id character varying(36),
    CONSTRAINT ck_notes_content_format CHECK (((content_format)::text = ANY ((ARRAY['markdown'::character varying, 'plain'::character varying, 'prosemirror_json'::character varying])::text[])))
);


--
-- Name: note_links; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.note_links (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    from_object_id character varying(36) NOT NULL,
    from_object_type character varying(64) NOT NULL,
    to_object_id character varying(36) NOT NULL,
    to_object_type character varying(64) NOT NULL,
    link_type character varying(64) NOT NULL,
    status character varying(32) DEFAULT 'active'::character varying NOT NULL,
    confidence double precision,
    metadata_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_by_user_id character varying(36),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_note_links_confidence CHECK (((confidence IS NULL) OR ((confidence >= (0)::double precision) AND (confidence <= (1)::double precision)))),
    CONSTRAINT ck_note_links_endpoint_type CHECK ((((from_object_type)::text = ANY ((ARRAY['knowledge_item'::character varying, 'note'::character varying, 'source'::character varying, 'claim'::character varying, 'memory_entry'::character varying, 'project_public_summary'::character varying])::text[])) AND ((to_object_type)::text = ANY ((ARRAY['knowledge_item'::character varying, 'note'::character varying, 'source'::character varying, 'claim'::character varying, 'memory_entry'::character varying, 'project_public_summary'::character varying])::text[])))),
    CONSTRAINT ck_note_links_has_note_endpoint CHECK ((((from_object_type)::text = 'note'::text) OR ((to_object_type)::text = 'note'::text))),
    CONSTRAINT ck_note_links_link_type CHECK (((link_type)::text = ANY ((ARRAY['related_to'::character varying, 'references'::character varying, 'depends_on'::character varying, 'part_of'::character varying, 'source_for'::character varying, 'derived_from'::character varying, 'about'::character varying, 'supports'::character varying, 'contradicts'::character varying, 'supersedes'::character varying, 'refines'::character varying, 'same_as'::character varying, 'explains'::character varying, 'prerequisite_of'::character varying, 'example_of'::character varying, 'applies_to'::character varying, 'summarizes'::character varying, 'updates'::character varying])::text[]))),
    CONSTRAINT ck_note_links_metadata_object CHECK ((jsonb_typeof(metadata_json) = 'object'::text)),
    CONSTRAINT ck_note_links_no_self CHECK (((from_object_id)::text <> (to_object_id)::text)),
    CONSTRAINT ck_note_links_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'archived'::character varying])::text[])))
);


--
-- Name: official_plugin_enablements; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.official_plugin_enablements (
    id character varying(36) NOT NULL,
    space_id character varying(36),
    user_id character varying(36),
    plugin_id character varying(128) NOT NULL,
    enabled boolean NOT NULL,
    visible boolean NOT NULL DEFAULT true,
    settings_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    enabled_at timestamp with time zone,
    enabled_by_user_id character varying(36),
    disabled_at timestamp with time zone,
    disabled_by_user_id character varying(36),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT official_plugin_enablements_plugin_id_non_empty CHECK ((plugin_id)::text <> ''),
    CONSTRAINT official_plugin_enablements_settings_is_object CHECK (jsonb_typeof(settings_json) = 'object'),
    CONSTRAINT official_plugin_enablements_scope_check CHECK (
        (space_id IS NOT NULL AND user_id IS NULL) OR
        (space_id IS NULL AND user_id IS NOT NULL)
    )
);


--
-- Name: official_plugin_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.official_plugin_events (
    id character varying(36) NOT NULL,
    space_id character varying(36),
    plugin_id character varying(128) NOT NULL,
    event_type character varying(64) NOT NULL,
    actor_user_id character varying(36),
    target_user_id character varying(36),
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT official_plugin_events_event_type_non_empty CHECK ((event_type)::text <> ''),
    CONSTRAINT official_plugin_events_metadata_is_object CHECK (jsonb_typeof(metadata_json) = 'object'),
    CONSTRAINT official_plugin_events_plugin_id_non_empty CHECK ((plugin_id)::text <> '')
);


--
-- Name: participation_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.participation_records (
    id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    personal_space_id character varying(36) NOT NULL,
    source_space_id character varying(36) NOT NULL,
    source_object_type character varying(64) NOT NULL,
    source_object_id character varying(36) NOT NULL,
    role character varying(64) NOT NULL,
    occurred_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: personal_memory_grant_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.personal_memory_grant_events (
    id character varying(36) NOT NULL,
    grant_id character varying(36) NOT NULL,
    event_type character varying(64) NOT NULL,
    actor_user_id character varying(36),
    run_id character varying(36),
    proposal_id character varying(36),
    source_space_id character varying(36),
    target_space_id character varying(36),
    metadata_json jsonb,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_personal_memory_grant_events_event_type CHECK (((event_type)::text = ANY ((ARRAY['created'::character varying, 'previewed'::character varying, 'consuming'::character varying, 'used'::character varying, 'revoked'::character varying, 'expired'::character varying, 'failed'::character varying, 'denied'::character varying, 'egress_proposal_created'::character varying, 'egress_approved'::character varying])::text[])))
);


--
-- Name: personal_memory_grants; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.personal_memory_grants (
    id character varying(36) NOT NULL,
    granting_user_id character varying(36) NOT NULL,
    personal_space_id character varying(36) NOT NULL,
    target_space_id character varying(36) NOT NULL,
    target_run_id character varying(36) NOT NULL,
    target_agent_id character varying(36),
    grant_scope character varying(32) NOT NULL,
    access_mode character varying(32) NOT NULL,
    status character varying(32) NOT NULL,
    memory_filter_json jsonb,
    read_expires_at timestamp with time zone NOT NULL,
    egress_review_expires_at timestamp with time zone,
    consume_started_at timestamp with time zone,
    revoked_at timestamp with time zone,
    used_at timestamp with time zone,
    failed_at timestamp with time zone,
    failure_stage character varying(64),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_personal_memory_grants_access_mode CHECK (((access_mode)::text = 'summary_only'::text)),
    CONSTRAINT ck_personal_memory_grants_grant_scope CHECK (((grant_scope)::text = 'run'::text)),
    CONSTRAINT ck_personal_memory_grants_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'consuming'::character varying, 'used'::character varying, 'revoked'::character varying, 'expired'::character varying, 'failed'::character varying])::text[]))),
    CONSTRAINT ck_personal_memory_grants_target_agent_id_null CHECK ((target_agent_id IS NULL))
);


--
-- Name: plugin_installs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.plugin_installs (
    id                   character varying(36)  NOT NULL DEFAULT gen_random_uuid(),
    plugin_id            character varying(64)  NOT NULL,
    installed_version    character varying(32)  NOT NULL,
    status               character varying(16)  NOT NULL DEFAULT 'active',
    source               character varying(16)  NOT NULL DEFAULT 'official',
    installed_at         timestamp with time zone NOT NULL DEFAULT now(),
    installed_by_user_id character varying(36),
    package_hash         text,
    manifest_json        jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT plugin_installs_plugin_id_nonempty CHECK ((length(trim((plugin_id)::text)) > 0)),
    CONSTRAINT plugin_installs_source_valid CHECK ((source = ANY (ARRAY['built_in'::character varying, 'official'::character varying, 'local'::character varying]))),
    CONSTRAINT plugin_installs_status_valid CHECK ((status = ANY (ARRAY['active'::character varying, 'disabled'::character varying, 'removed'::character varying])))
);


--
-- Name: plugin_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.plugin_migrations (
    id               character varying(36)  NOT NULL DEFAULT gen_random_uuid(),
    plugin_id        character varying(64)  NOT NULL,
    plugin_version   character varying(32)  NOT NULL,
    migration_id     character varying(128) NOT NULL,
    checksum         text,
    applied_at       timestamp with time zone NOT NULL DEFAULT now(),
    status           character varying(16)  NOT NULL DEFAULT 'applied',
    error_message    text,
    CONSTRAINT plugin_migrations_status_valid CHECK ((status = ANY (ARRAY['applied'::character varying, 'failed'::character varying])))
);


--
-- Name: policies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.policies (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    name character varying(256) NOT NULL,
    domain character varying(64) NOT NULL,
    policy_json jsonb NOT NULL,
    enabled boolean NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    policy_key character varying(256),
    policy_version integer DEFAULT 1 NOT NULL,
    status character varying(32) DEFAULT 'active'::character varying NOT NULL,
    enforcement_mode character varying(32),
    priority integer DEFAULT 0 NOT NULL,
    rule_json jsonb,
    applies_to_json jsonb,
    supersedes_policy_id character varying(36),
    created_from_proposal_id character varying(36),
    CONSTRAINT ck_policies_enforcement_mode CHECK (((enforcement_mode IS NULL) OR ((enforcement_mode)::text = ANY ((ARRAY['allow'::character varying, 'deny'::character varying, 'require_approval'::character varying, 'allow_with_log'::character varying])::text[])))),
    CONSTRAINT ck_policies_status CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'active'::character varying, 'superseded'::character varying, 'disabled'::character varying])::text[])))
);


--
-- Name: policy_decision_records; Type: TABLE; Schema: public; Owner: -
--

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
    CONSTRAINT ck_policy_decision_records_decision CHECK (((decision)::text = ANY ((ARRAY['allow'::character varying, 'deny'::character varying, 'require_approval'::character varying])::text[]))),
    CONSTRAINT ck_policy_decision_records_risk_level CHECK (((risk_level)::text = ANY ((ARRAY['low'::character varying, 'medium'::character varying, 'high'::character varying, 'critical'::character varying])::text[])))
);


--
-- Name: project_workflow_profiles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.project_workflow_profiles (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    project_id character varying(36) NOT NULL,
    workflow_template_id character varying(128) NOT NULL,
    name character varying(256) NOT NULL,
    enabled boolean NOT NULL,
    config_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_by_user_id character varying(36),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_project_workflow_profiles_config_object CHECK ((jsonb_typeof(config_json) = 'object'::text))
);


--
-- Name: project_workspaces; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.project_workspaces (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    project_id character varying(36) NOT NULL,
    workspace_id character varying(36) NOT NULL,
    role character varying(64) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_project_workspaces_role CHECK (((role)::text = ANY ((ARRAY['primary_codebase'::character varying, 'capability_library'::character varying, 'docs'::character varying, 'data'::character varying, 'deployment'::character varying, 'reference'::character varying])::text[])))
);


--
-- Name: project_public_summaries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.project_public_summaries (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    project_id character varying(36) NOT NULL,
    summary_text text NOT NULL,
    topics_json jsonb DEFAULT '[]'::jsonb NOT NULL,
    highlights_json jsonb DEFAULT '[]'::jsonb NOT NULL,
    source_refs_json jsonb DEFAULT '[]'::jsonb NOT NULL,
    redaction_version character varying(64) NOT NULL,
    review_status character varying(32) DEFAULT 'pending'::character varying NOT NULL,
    updated_by_user_id character varying(36),
    generated_by_run_id character varying(36),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_project_public_summaries_highlights_array CHECK ((jsonb_typeof(highlights_json) = 'array'::text)),
    CONSTRAINT ck_project_public_summaries_review_status CHECK (((review_status)::text = ANY ((ARRAY['draft'::character varying, 'approved'::character varying, 'archived'::character varying])::text[]))),
    CONSTRAINT ck_project_public_summaries_source_refs_array CHECK ((jsonb_typeof(source_refs_json) = 'array'::text)),
    CONSTRAINT ck_project_public_summaries_topics_array CHECK ((jsonb_typeof(topics_json) = 'array'::text))
);


--
-- Name: projects; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.projects (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    owner_user_id character varying(36),
    name character varying(256) NOT NULL,
    description text,
    status character varying(32) NOT NULL,
    current_focus text,
    settings_json jsonb,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    archived_at timestamp with time zone,
    deleted_at timestamp with time zone,
    CONSTRAINT ck_projects_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'archived'::character varying, 'deleted'::character varying])::text[])))
);


--
-- Name: project_members; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.project_members (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    project_id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    role character varying(32) NOT NULL,
    status character varying(32) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_project_members_role CHECK (((role)::text = ANY ((ARRAY['owner'::character varying, 'member'::character varying, 'viewer'::character varying])::text[]))),
    CONSTRAINT ck_project_members_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'invited'::character varying, 'revoked'::character varying])::text[])))
);


--
-- Name: proposal_approvals; Type: TABLE; Schema: public; Owner: -
--

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
    CONSTRAINT ck_proposal_approvals_approval_type CHECK (((approval_type)::text = 'egress_granting_user'::text)),
    CONSTRAINT ck_proposal_approvals_status CHECK (((status)::text = ANY ((ARRAY['approved'::character varying, 'revoked'::character varying])::text[])))
);


--
-- Name: proposals; Type: TABLE; Schema: public; Owner: -
--

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
    CONSTRAINT ck_proposals_risk_level CHECK (((risk_level)::text = ANY ((ARRAY['low'::character varying, 'medium'::character varying, 'high'::character varying, 'critical'::character varying])::text[]))),
    CONSTRAINT ck_proposals_urgency CHECK (((urgency)::text = ANY ((ARRAY['low'::character varying, 'normal'::character varying, 'high'::character varying, 'critical'::character varying])::text[])))
);


--
-- Name: provenance_links; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.provenance_links (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    target_type character varying(64) NOT NULL,
    target_id character varying(36) NOT NULL,
    source_type character varying(64) NOT NULL,
    source_id character varying(36) NOT NULL,
    source_trust character varying(32),
    evidence_json jsonb,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_provenance_links_source_trust CHECK (((source_trust IS NULL) OR ((source_trust)::text = ANY ((ARRAY['user_confirmed'::character varying, 'internal_system'::character varying, 'trusted_external'::character varying, 'untrusted_external'::character varying, 'agent_inferred'::character varying])::text[])))),
    CONSTRAINT ck_provenance_links_source_type CHECK (((source_type)::text = ANY ((ARRAY['activity'::character varying, 'proposal'::character varying, 'memory'::character varying, 'artifact'::character varying, 'run_step'::character varying, 'external_source'::character varying, 'user_confirmation'::character varying, 'intake_item'::character varying, 'source_snapshot'::character varying, 'extracted_evidence'::character varying, 'run_event'::character varying])::text[])))
);


--
-- Name: provider_task_policies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.provider_task_policies (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    task character varying(64) NOT NULL,
    chain_json jsonb NOT NULL,
    enabled boolean NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: run_evaluations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.run_evaluations (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    run_id character varying(36) NOT NULL,
    evaluator_type character varying(64) DEFAULT 'deterministic_harness'::character varying NOT NULL,
    evaluator_version character varying(64) DEFAULT 'harness_eval.v1'::character varying NOT NULL,
    outcome_status character varying(32) NOT NULL,
    failure_layer character varying(32),
    failure_reason_code character varying(128),
    trajectory_status character varying(32) NOT NULL,
    evidence_json jsonb,
    rule_trace_json jsonb,
    notes text,
    evaluated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_run_evaluations_failure_layer CHECK (((failure_layer IS NULL) OR ((failure_layer)::text = ANY ((ARRAY['context'::character varying, 'sandbox'::character varying, 'runtime'::character varying, 'tool'::character varying, 'validation'::character varying, 'policy'::character varying, 'task_spec'::character varying, 'orchestration'::character varying, 'evaluator'::character varying, 'unknown'::character varying])::text[])))),
    CONSTRAINT ck_run_evaluations_outcome_status CHECK (((outcome_status)::text = ANY ((ARRAY['passed'::character varying, 'failed'::character varying, 'partial'::character varying, 'unknown'::character varying])::text[]))),
    CONSTRAINT ck_run_evaluations_trajectory_status CHECK (((trajectory_status)::text = ANY ((ARRAY['acceptable'::character varying, 'incomplete'::character varying, 'unsafe'::character varying, 'insufficient_evidence'::character varying])::text[])))
);


--
-- Name: run_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.run_events (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    run_id character varying(36) NOT NULL,
    step_id character varying(36),
    actor_id character varying(36),
    event_index integer NOT NULL,
    event_type character varying(64) NOT NULL,
    status character varying(32) NOT NULL,
    summary text,
    error_code character varying(128),
    error_message text,
    workspace_id character varying(36),
    artifact_id character varying(36),
    proposal_id character varying(36),
    data_exposure_level character varying(64),
    trust_level character varying(32),
    metadata_json jsonb,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_run_events_data_exposure_level CHECK (((data_exposure_level IS NULL) OR ((data_exposure_level)::text = ANY ((ARRAY['local_only'::character varying, 'model_provider'::character varying, 'vendor_platform'::character varying, 'third_party_tools'::character varying, 'unknown'::character varying])::text[])))),
    CONSTRAINT ck_run_events_event_type CHECK (((event_type)::text = ANY ((ARRAY['context_compiled'::character varying, 'runtime_selected'::character varying, 'credential_granted'::character varying, 'sandbox_created'::character varying, 'policy_checked'::character varying, 'adapter_invoked'::character varying, 'adapter_completed'::character varying, 'artifact_ingested'::character varying, 'patch_collected'::character varying, 'validation_started'::character varying, 'validation_completed'::character varying, 'proposal_created'::character varying, 'evaluation_created'::character varying, 'run_finalized'::character varying])::text[]))),
    CONSTRAINT ck_run_events_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'running'::character varying, 'succeeded'::character varying, 'failed'::character varying, 'skipped'::character varying, 'warning'::character varying, 'cancelled'::character varying])::text[]))),
    CONSTRAINT ck_run_events_trust_level CHECK (((trust_level IS NULL) OR ((trust_level)::text = ANY ((ARRAY['high'::character varying, 'medium'::character varying, 'low'::character varying, 'unknown'::character varying])::text[]))))
);


--
-- Name: run_execution_locks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.run_execution_locks (
    run_id character varying(36) NOT NULL,
    locked_at timestamp with time zone NOT NULL,
    worker_id character varying(64) NOT NULL,
    job_id character varying(36)
);


--
-- Name: run_finalizations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.run_finalizations (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    run_id character varying(36) NOT NULL,
    finalizer_version character varying(64) DEFAULT 'post_run_finalization.v1'::character varying NOT NULL,
    status character varying(32) NOT NULL,
    run_evaluation_id character varying(36),
    task_evaluation_id character varying(36),
    outcome_status character varying(32),
    failure_layer character varying(32),
    failure_reason_code character varying(128),
    trajectory_status character varying(32),
    skipped_reasons_json jsonb,
    error_json jsonb,
    metadata_json jsonb,
    finalized_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_run_finalizations_failure_layer CHECK (((failure_layer IS NULL) OR ((failure_layer)::text = ANY ((ARRAY['context'::character varying, 'sandbox'::character varying, 'runtime'::character varying, 'tool'::character varying, 'validation'::character varying, 'policy'::character varying, 'task_spec'::character varying, 'orchestration'::character varying, 'evaluator'::character varying, 'unknown'::character varying])::text[])))),
    CONSTRAINT ck_run_finalizations_outcome_status CHECK (((outcome_status IS NULL) OR ((outcome_status)::text = ANY ((ARRAY['passed'::character varying, 'failed'::character varying, 'partial'::character varying, 'unknown'::character varying])::text[])))),
    CONSTRAINT ck_run_finalizations_status CHECK (((status)::text = ANY ((ARRAY['completed'::character varying, 'failed'::character varying])::text[]))),
    CONSTRAINT ck_run_finalizations_trajectory_status CHECK (((trajectory_status IS NULL) OR ((trajectory_status)::text = ANY ((ARRAY['acceptable'::character varying, 'incomplete'::character varying, 'unsafe'::character varying, 'insufficient_evidence'::character varying])::text[]))))
);


--
-- Name: run_reflections; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.run_reflections (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    run_id character varying(36) NOT NULL,
    source character varying(32) DEFAULT 'native'::character varying NOT NULL,
    what_changed text,
    what_worked text,
    what_failed text,
    reusable_rules_json jsonb,
    reusable_commands_json jsonb,
    workspace_facts_json jsonb,
    memory_candidates_json jsonb,
    capability_candidates_json jsonb,
    policy_candidates_json jsonb,
    validation_candidates_json jsonb,
    follow_up_tasks_json jsonb,
    confidence double precision,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_run_reflections_source CHECK (((source)::text = ANY ((ARRAY['native'::character varying, 'external_import'::character varying, 'manual'::character varying, 'evaluator'::character varying])::text[])))
);


--
-- Name: run_steps; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.run_steps (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    run_id character varying(36) NOT NULL,
    parent_step_id character varying(36),
    actor_id character varying(36) NOT NULL,
    step_index integer NOT NULL,
    step_type character varying(64) NOT NULL,
    status character varying(32) NOT NULL,
    title character varying(512),
    workspace_id character varying(36),
    session_id character varying(36),
    task_id character varying(36),
    artifact_id character varying(36),
    proposal_id character varying(36),
    started_at timestamp with time zone,
    ended_at timestamp with time zone,
    input_summary text,
    output_summary text,
    error_type character varying(128),
    error_message text,
    metadata_json jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_run_steps_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'running'::character varying, 'succeeded'::character varying, 'failed'::character varying, 'skipped'::character varying, 'cancelled'::character varying])::text[]))),
    CONSTRAINT ck_run_steps_step_type CHECK (((step_type)::text = ANY ((ARRAY['run_created'::character varying, 'queued'::character varying, 'context_prepared'::character varying, 'runtime_selected'::character varying, 'adapter_started'::character varying, 'adapter_completed'::character varying, 'artifact_created'::character varying, 'proposal_created'::character varying, 'failed'::character varying, 'completed'::character varying, 'validation_started'::character varying, 'validation_completed'::character varying, 'cancelled'::character varying])::text[])))
);


--
-- Name: runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.runs (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    agent_id character varying(36) NOT NULL,
    agent_version_id character varying(36) NOT NULL,
    runtime_profile_id character varying(36),
    context_snapshot_id character varying(36),
    workspace_id character varying(36),
    session_id character varying(36),
    working_dir_id character varying(36),
    parent_run_id character varying(36),
    instructed_by character varying(128),
    instructed_by_user_id character varying(36),
    run_type character varying(32) NOT NULL,
    trigger_origin character varying(32) NOT NULL,
    status character varying(32) NOT NULL,
    mode character varying(32) NOT NULL,
    prompt text,
    instruction text,
    scheduled_at timestamp with time zone,
    started_at timestamp with time zone,
    ended_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    model_provider_id character varying(36),
    error_message text,
    error_json jsonb,
    output_json jsonb,
    usage_json jsonb,
    adapter_type character varying(64),
    capability_id character varying(128),
    capabilities_json jsonb DEFAULT '[]'::jsonb NOT NULL,
    model_selection_mode character varying(32) DEFAULT 'cli_default'::character varying NOT NULL,
    model_override_json jsonb,
    runtime_profile_snapshot_json jsonb,
    permission_snapshot_json jsonb,
    required_sandbox_level character varying(32) DEFAULT 'none'::character varying NOT NULL,
    sandbox_path text,
    runtime_seconds double precision,
    usage_accuracy character varying(32) NOT NULL,
    estimated_input_tokens integer,
    estimated_output_tokens integer,
    estimated_cost double precision,
    exit_code integer,
    visibility character varying(32) DEFAULT 'space_shared'::character varying NOT NULL,
    has_personal_grant_context boolean DEFAULT false NOT NULL,
    personal_grant_context_json jsonb,
    source character varying(32),
    observability_level character varying(64),
    data_exposure_level character varying(64),
    trust_level character varying(32),
    externality_level character varying(32),
    project_id character varying(36),
    CONSTRAINT ck_runs_data_exposure_level CHECK (((data_exposure_level IS NULL) OR ((data_exposure_level)::text = ANY ((ARRAY['local_only'::character varying, 'model_provider'::character varying, 'vendor_platform'::character varying, 'third_party_tools'::character varying, 'unknown'::character varying])::text[])))),
    CONSTRAINT ck_runs_externality_level CHECK (((externality_level IS NULL) OR ((externality_level)::text = ANY ((ARRAY['native'::character varying, 'local_external'::character varying, 'remote_external'::character varying, 'hybrid'::character varying, 'manual'::character varying])::text[])))),
    CONSTRAINT ck_runs_mode CHECK (((mode)::text = ANY ((ARRAY['live'::character varying, 'dry_run'::character varying])::text[]))),
    CONSTRAINT ck_runs_observability_level CHECK (((observability_level IS NULL) OR ((observability_level)::text = ANY ((ARRAY['full_trace'::character varying, 'structured_events'::character varying, 'artifacts_only'::character varying, 'final_output_only'::character varying, 'black_box'::character varying])::text[])))),
    CONSTRAINT ck_runs_required_sandbox_level CHECK (((required_sandbox_level)::text = ANY ((ARRAY['none'::character varying, 'dry_run'::character varying, 'ephemeral'::character varying, 'worktree'::character varying, 'one_shot_docker'::character varying])::text[]))),
    CONSTRAINT ck_runs_run_type CHECK (((run_type)::text = ANY ((ARRAY['agent'::character varying, 'system'::character varying, 'workflow'::character varying, 'validation'::character varying, 'reflection'::character varying, 'export'::character varying, 'evolution'::character varying])::text[]))),
    CONSTRAINT ck_runs_source CHECK (((source IS NULL) OR ((source)::text = ANY ((ARRAY['managed'::character varying, 'ide_assist'::character varying, 'manual_import'::character varying, 'remote_import'::character varying, 'scheduled'::character varying, 'webhook'::character varying])::text[])))),
    CONSTRAINT ck_runs_status CHECK (((status)::text = ANY ((ARRAY['queued'::character varying, 'running'::character varying, 'succeeded'::character varying, 'degraded'::character varying, 'failed'::character varying, 'cancelled'::character varying, 'waiting_for_review'::character varying])::text[]))),
    CONSTRAINT ck_runs_trigger_origin CHECK (((trigger_origin)::text = ANY ((ARRAY['manual'::character varying, 'automation'::character varying, 'job'::character varying, 'system'::character varying])::text[]))),
    CONSTRAINT ck_runs_trust_level CHECK (((trust_level IS NULL) OR ((trust_level)::text = ANY ((ARRAY['high'::character varying, 'medium'::character varying, 'low'::character varying, 'unknown'::character varying])::text[]))))
);


--
-- Name: runtime_tool_bindings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.runtime_tool_bindings (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    workspace_id character varying(36),
    agent_id character varying(36),
    capability_id character varying(128),
    runtime_adapter_type character varying(64) NOT NULL,
    external_type character varying(64) NOT NULL,
    external_ref character varying(512) NOT NULL,
    display_name character varying(256) NOT NULL,
    required_scopes_json jsonb,
    credential_ref character varying(256),
    data_exposure_level character varying(64) DEFAULT 'unknown'::character varying NOT NULL,
    observability_level character varying(64) DEFAULT 'black_box'::character varying NOT NULL,
    side_effect_level character varying(32) DEFAULT 'none'::character varying NOT NULL,
    approval_required boolean DEFAULT true NOT NULL,
    enabled boolean DEFAULT false NOT NULL,
    notes text,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_runtime_tool_bindings_data_exposure_level CHECK (((data_exposure_level)::text = ANY ((ARRAY['local_only'::character varying, 'model_provider'::character varying, 'vendor_platform'::character varying, 'third_party_tools'::character varying, 'unknown'::character varying])::text[]))),
    CONSTRAINT ck_runtime_tool_bindings_external_type CHECK (((external_type)::text = ANY ((ARRAY['codex_plugin'::character varying, 'claude_skill'::character varying, 'claude_hook'::character varying, 'mcp_server'::character varying, 'app_integration'::character varying, 'cli_tool'::character varying])::text[]))),
    CONSTRAINT ck_runtime_tool_bindings_observability_level CHECK (((observability_level)::text = ANY ((ARRAY['full_trace'::character varying, 'structured_events'::character varying, 'artifacts_only'::character varying, 'final_output_only'::character varying, 'black_box'::character varying])::text[]))),
    CONSTRAINT ck_runtime_tool_bindings_side_effect_level CHECK (((side_effect_level)::text = ANY ((ARRAY['none'::character varying, 'local_files'::character varying, 'external_read'::character varying, 'external_write'::character varying, 'sensitive'::character varying])::text[])))
);


--
-- Name: session_summaries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.session_summaries (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    session_id character varying(36) NOT NULL,
    user_id character varying(36),
    version integer NOT NULL,
    status character varying(32) NOT NULL,
    summary_text text NOT NULL,
    source_message_count integer NOT NULL,
    source_first_message_id character varying(36),
    source_last_message_id character varying(36),
    summary_json jsonb,
    token_estimate_before integer,
    token_estimate_after integer,
    condenser_version character varying(64) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_session_summaries_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'superseded'::character varying])::text[])))
);


--
-- Name: sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sessions (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    user_id character varying(36),
    agent_id character varying(36),
    workspace_id character varying(36),
    title character varying(512),
    status character varying(32) NOT NULL,
    metadata_json jsonb,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: skill_packages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.skill_packages (
    id character varying(36) NOT NULL,
    space_id character varying(36),
    source_id character varying(36) NOT NULL,
    package_name character varying(256) NOT NULL,
    version character varying(64),
    license character varying(128),
    raw_storage_ref text,
    manifest_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    normalized_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    risk_level character varying(32) NOT NULL,
    status character varying(32) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_skill_packages_manifest_object CHECK ((jsonb_typeof(manifest_json) = 'object'::text)),
    CONSTRAINT ck_skill_packages_normalized_object CHECK ((jsonb_typeof(normalized_json) = 'object'::text)),
    CONSTRAINT ck_skill_packages_risk_level CHECK (((risk_level)::text = ANY ((ARRAY['low'::character varying, 'medium'::character varying, 'high'::character varying, 'critical'::character varying])::text[]))),
    CONSTRAINT ck_skill_packages_status CHECK (((status)::text = ANY ((ARRAY['imported'::character varying, 'reviewed'::character varying, 'rejected'::character varying, 'converted'::character varying, 'archived'::character varying, 'superseded'::character varying])::text[])))
);


--
-- Name: skill_local_overlays; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.skill_local_overlays (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    skill_package_id character varying(36) NOT NULL,
    scope_type character varying(32) NOT NULL,
    scope_id character varying(128),
    overlay_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    status character varying(32) NOT NULL,
    created_by_user_id character varying(36),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_skill_local_overlays_overlay_object CHECK ((jsonb_typeof(overlay_json) = 'object'::text)),
    CONSTRAINT ck_skill_local_overlays_scope_id CHECK (((scope_type)::text = 'space'::text AND scope_id IS NULL) OR ((scope_type)::text <> 'space'::text AND scope_id IS NOT NULL)),
    CONSTRAINT ck_skill_local_overlays_scope_type CHECK (((scope_type)::text = ANY ((ARRAY['space'::character varying, 'project'::character varying, 'workspace'::character varying, 'agent'::character varying, 'user'::character varying])::text[]))),
    CONSTRAINT ck_skill_local_overlays_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'archived'::character varying])::text[])))
);


--
-- Name: skill_package_files; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.skill_package_files (
    id character varying(36) NOT NULL,
    skill_package_id character varying(36) NOT NULL,
    path text NOT NULL,
    kind character varying(64) NOT NULL,
    content_hash character varying(128),
    content_type character varying(256),
    byte_length integer,
    storage_ref text,
    included boolean DEFAULT true NOT NULL,
    executable boolean DEFAULT false NOT NULL,
    risk_flags_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_skill_package_files_byte_length CHECK (((byte_length IS NULL) OR (byte_length >= 0))),
    CONSTRAINT ck_skill_package_files_path_nonempty CHECK ((length(path) > 0)),
    CONSTRAINT ck_skill_package_files_risk_flags_object CHECK ((jsonb_typeof(risk_flags_json) = 'object'::text))
);


--
-- Name: skill_sources; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.skill_sources (
    id character varying(36) NOT NULL,
    space_id character varying(36),
    source_type character varying(32) NOT NULL,
    url text,
    repo character varying(512),
    path text,
    ref character varying(256),
    commit_sha character varying(128),
    content_hash character varying(128) NOT NULL,
    fetched_at timestamp with time zone NOT NULL,
    created_by_user_id character varying(36),
    metadata_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_skill_sources_content_hash_nonempty CHECK ((length((content_hash)::text) > 0)),
    CONSTRAINT ck_skill_sources_metadata_object CHECK ((jsonb_typeof(metadata_json) = 'object'::text)),
    CONSTRAINT ck_skill_sources_source_type CHECK (((source_type)::text = ANY ((ARRAY['github'::character varying, 'registry'::character varying, 'local_workspace'::character varying, 'upload'::character varying, 'builtin'::character varying])::text[])))
);


--
-- Name: source_connections; Type: TABLE; Schema: public; Owner: -
--

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
    handler_kind character varying(32) NOT NULL DEFAULT 'built_in',
    active_handler_version_id character varying(36),
    active_recipe_version_id character varying(36),
    repair_status character varying(32) NOT NULL DEFAULT 'ok',
    last_handler_run_id character varying(36),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    deleted_at timestamp with time zone,
    CONSTRAINT ck_source_connections_capture_policy CHECK (((capture_policy)::text = ANY ((ARRAY['metadata_only'::character varying, 'excerpt_only'::character varying, 'auto_extract_relevant'::character varying, 'auto_extract_all_text'::character varying, 'archive_all_snapshots'::character varying])::text[]))),
    CONSTRAINT ck_source_connections_fetch_frequency CHECK (((fetch_frequency)::text = ANY ((ARRAY['manual'::character varying, 'hourly'::character varying, 'daily'::character varying, 'weekly'::character varying])::text[]))),
    CONSTRAINT ck_source_connections_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'paused'::character varying, 'archived'::character varying])::text[]))),
    CONSTRAINT ck_source_connections_trust_level CHECK (((trust_level)::text = ANY ((ARRAY['trusted'::character varying, 'normal'::character varying, 'untrusted'::character varying])::text[]))),
    CONSTRAINT ck_source_connections_handler_kind CHECK (((handler_kind)::text = ANY ((ARRAY['built_in'::character varying, 'generated_custom'::character varying, 'recipe'::character varying])::text[]))),
    CONSTRAINT ck_source_connections_repair_status CHECK (((repair_status)::text = ANY ((ARRAY['ok'::character varying, 'repair_required'::character varying, 'repair_pending'::character varying, 'disabled'::character varying])::text[])))
);

--
-- Name: source_handler_versions; Type: TABLE; Schema: public; Owner: -
--
-- Generated, source-specific handler code versions for Intake Custom
-- Source. See .agent/architecture/INTAKE_CUSTOM_SOURCE_HANDLERS.md. Handler
-- code never writes this table directly.
--

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
    CONSTRAINT ck_source_handler_versions_version_number CHECK ((version_number > 0))
);

--
-- Name: source_recipe_versions; Type: TABLE; Schema: public; Owner: -
--
-- Level 2 Source recipes: versioned, structured recipe JSON interpreted by
-- trusted server code (no generated/untrusted code). Recipe sources use
-- source_connections.handler_kind = 'recipe' and active_recipe_version_id;
-- generated-handler (Level 3) sources keep using
-- source_handler_versions/active_handler_version_id unchanged.
--

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
    CONSTRAINT ck_source_recipe_versions_version_number CHECK ((version_number > 0))
);

--
-- Name: source_handler_runs; Type: TABLE; Schema: public; Owner: -
--

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
    CONSTRAINT ck_source_handler_runs_status CHECK (((status)::text = ANY ((ARRAY['queued'::character varying, 'running'::character varying, 'succeeded'::character varying, 'failed'::character varying, 'validation_failed'::character varying, 'blocked'::character varying])::text[])))
);

--
-- Name: settings; Type: TABLE; Schema: public; Owner: -
--
-- Generic scoped settings store for low-frequency product/admin settings.
-- scope_type/scope_id supports instance, space, user, and space_user
-- settings without adding one singleton table per feature.
--

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


--
-- Name: source_connectors; Type: TABLE; Schema: public; Owner: -
--

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
    CONSTRAINT ck_source_connectors_connector_type CHECK (((connector_type)::text = ANY ((ARRAY['external_feed'::character varying, 'external_url'::character varying, 'internal_activity'::character varying, 'internal_artifact'::character varying, 'internal_run'::character varying, 'file'::character varying, 'document'::character varying])::text[]))),
    CONSTRAINT ck_source_connectors_ingestion_mode CHECK (((ingestion_mode)::text = ANY ((ARRAY['pull'::character varying, 'manual'::character varying, 'internal'::character varying])::text[]))),
    CONSTRAINT ck_source_connectors_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'disabled'::character varying])::text[])))
);


--
-- Name: source_pointers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.source_pointers (
    id character varying(36) NOT NULL,
    owner_space_id character varying(36) NOT NULL,
    source_space_id character varying(36) NOT NULL,
    source_object_type character varying(64) NOT NULL,
    source_object_id character varying(36) NOT NULL,
    access_mode character varying(32) NOT NULL,
    granted_by_user_id character varying(36),
    expires_at timestamp with time zone,
    metadata_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_source_pointers_access_mode CHECK (((access_mode)::text = ANY ((ARRAY['read'::character varying, 'subscribe'::character varying, 'federated'::character varying])::text[]))),
    CONSTRAINT ck_source_pointers_metadata_object CHECK ((jsonb_typeof(metadata_json) = 'object'::text)),
    CONSTRAINT ck_source_pointers_source_object_type CHECK (((source_object_type)::text = ANY ((ARRAY['memory_entry'::character varying, 'artifact'::character varying, 'activity_record'::character varying, 'run'::character varying, 'proposal'::character varying, 'knowledge_item'::character varying, 'note'::character varying, 'source'::character varying, 'claim'::character varying, 'project'::character varying, 'workspace'::character varying])::text[])))
);


--
-- Name: source_snapshots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.source_snapshots (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    intake_item_id character varying(36),
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
    CONSTRAINT ck_source_snapshots_capture_method CHECK (((capture_method)::text = ANY ((ARRAY['manual'::character varying, 'connection_scan'::character varying, 'full_text'::character varying, 'snapshot'::character varying, 'internal'::character varying, 'custom_source_handler'::character varying, 'source_recipe'::character varying])::text[]))),
    CONSTRAINT ck_source_snapshots_snapshot_type CHECK (((snapshot_type)::text = ANY ((ARRAY['metadata'::character varying, 'raw'::character varying, 'extracted'::character varying, 'summary'::character varying])::text[]))),
    CONSTRAINT ck_source_snapshots_trust_level CHECK (((trust_level)::text = ANY ((ARRAY['trusted'::character varying, 'normal'::character varying, 'untrusted'::character varying])::text[])))
);


--
-- Name: sources; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sources (
    object_id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    source_type character varying(64) NOT NULL,
    uri text,
    content_ref character varying(1024),
    raw_text text,
    summary text,
    metadata_json jsonb NOT NULL,
    source_activity_id character varying(36),
    CONSTRAINT ck_sources_source_type CHECK (((source_type)::text = ANY ((ARRAY['activity_record'::character varying, 'chat_capture'::character varying, 'webpage'::character varying, 'article'::character varying, 'paper'::character varying, 'pdf'::character varying, 'file'::character varying, 'email'::character varying, 'manual_reference'::character varying, 'external_note'::character varying])::text[])))
);


--
-- Name: retrieval_objects; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.retrieval_objects (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    object_type character varying(32) NOT NULL,
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
    CONSTRAINT ck_retrieval_objects_source_connections_array CHECK ((jsonb_typeof(source_connection_ids_json) = 'array'::text)),
    CONSTRAINT ck_retrieval_objects_object_type CHECK (((object_type)::text = ANY ((ARRAY['knowledge_item'::character varying, 'note'::character varying, 'source'::character varying, 'claim'::character varying, 'memory_entry'::character varying, 'project_public_summary'::character varying])::text[])))
);


--
-- Name: retrieval_aliases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.retrieval_aliases (
    id character varying(36) NOT NULL,
    retrieval_object_id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    object_type character varying(32) NOT NULL,
    object_id character varying(36) NOT NULL,
    alias text NOT NULL,
    normalized_alias text NOT NULL,
    alias_kind character varying(32) NOT NULL,
    confidence double precision NOT NULL,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_retrieval_aliases_confidence CHECK (((confidence >= (0)::double precision) AND (confidence <= (1)::double precision))),
    CONSTRAINT ck_retrieval_aliases_object_type CHECK (((object_type)::text = ANY ((ARRAY['knowledge_item'::character varying, 'note'::character varying, 'source'::character varying, 'claim'::character varying, 'memory_entry'::character varying, 'project_public_summary'::character varying])::text[])))
);


--
-- Name: retrieval_chunks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.retrieval_chunks (
    id character varying(36) NOT NULL,
    retrieval_object_id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    object_type character varying(32) NOT NULL,
    object_id character varying(36) NOT NULL,
    chunk_index integer NOT NULL,
    plain_text text NOT NULL,
    tsv tsvector,
    content_hash character varying(64) NOT NULL,
    embedding public.vector,
    embedding_model character varying(128),
    embedding_dimensions integer,
    embedding_generated_at timestamp with time zone,
    embedding_claim_id character varying(64),
    embedding_claimed_at timestamp with time zone,
    embedding_attempts integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_retrieval_chunks_embedding_dimensions CHECK ((((embedding IS NULL) AND (embedding_dimensions IS NULL)) OR ((embedding IS NOT NULL) AND (embedding_dimensions = public.vector_dims(embedding)) AND (embedding_dimensions >= 1) AND (embedding_dimensions <= 4096)))),
    CONSTRAINT ck_retrieval_chunks_object_type CHECK (((object_type)::text = ANY ((ARRAY['knowledge_item'::character varying, 'note'::character varying, 'source'::character varying, 'claim'::character varying, 'memory_entry'::character varying, 'project_public_summary'::character varying])::text[])))
);


--
-- Name: retrieval_edges; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.retrieval_edges (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    from_object_type character varying(32) NOT NULL,
    from_object_id character varying(36) NOT NULL,
    to_object_type character varying(32) NOT NULL,
    to_object_id character varying(36) NOT NULL,
    relation_type character varying(64) NOT NULL,
    edge_origin character varying(64) NOT NULL,
    edge_status character varying(32) NOT NULL,
    confidence double precision NOT NULL,
    evidence_json jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_retrieval_edges_confidence CHECK (((confidence >= (0)::double precision) AND (confidence <= (1)::double precision))),
    CONSTRAINT ck_retrieval_edges_from_object_type CHECK (((from_object_type)::text = ANY ((ARRAY['knowledge_item'::character varying, 'note'::character varying, 'source'::character varying, 'claim'::character varying, 'memory_entry'::character varying, 'project_public_summary'::character varying])::text[]))),
    CONSTRAINT ck_retrieval_edges_to_object_type CHECK (((to_object_type)::text = ANY ((ARRAY['knowledge_item'::character varying, 'note'::character varying, 'source'::character varying, 'claim'::character varying, 'memory_entry'::character varying, 'project_public_summary'::character varying])::text[]))),
    CONSTRAINT ck_retrieval_edges_status CHECK (((edge_status)::text = ANY ((ARRAY['derived'::character varying, 'suggested'::character varying])::text[])))
);


--
-- Name: retrieval_feedback_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.retrieval_feedback_events (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    actor_user_id character varying(36) NOT NULL,
    surface character varying(64) NOT NULL,
    query_hash character varying(64) NOT NULL,
    object_type character varying(32) NOT NULL,
    object_id character varying(36) NOT NULL,
    signal_type character varying(32) NOT NULL,
    dwell_ms integer,
    metadata_json jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_retrieval_feedback_events_dwell_ms CHECK (((dwell_ms IS NULL) OR (dwell_ms >= 0))),
    CONSTRAINT ck_retrieval_feedback_events_object_type CHECK (((object_type)::text = ANY ((ARRAY['knowledge_item'::character varying, 'note'::character varying, 'source'::character varying, 'claim'::character varying, 'memory_entry'::character varying, 'project_public_summary'::character varying])::text[]))),
    CONSTRAINT ck_retrieval_feedback_events_signal_type CHECK (((signal_type)::text = ANY ((ARRAY['opened'::character varying, 'dwell'::character varying, 'used'::character varying, 'explicit_relevant'::character varying, 'accepted'::character varying, 'pinned'::character varying])::text[])))
);


--
-- Name: space_retrieval_prompts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.space_retrieval_prompts (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    task character varying(64) NOT NULL,
    system_prompt text NOT NULL,
    user_template text NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_space_retrieval_prompts_task CHECK (((task)::text = ANY ((ARRAY['query_rewrite'::character varying])::text[]))),
    CONSTRAINT ck_space_retrieval_prompts_system_prompt CHECK ((length(btrim(system_prompt)) > 0)),
    CONSTRAINT ck_space_retrieval_prompts_user_template CHECK ((strpos(user_template, '{query}'::text) > 0))
);


--
-- Name: space_runtime_tool_policies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.space_runtime_tool_policies (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    runtime character varying(64) NOT NULL,
    enabled boolean DEFAULT false NOT NULL,
    default_version character varying(128),
    allowed_versions_json jsonb DEFAULT '[]'::jsonb NOT NULL,
    updated_by_user_id character varying(36),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: space_invitations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.space_invitations (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    invited_email character varying(256) NOT NULL,
    role character varying(32) NOT NULL,
    token_hash character varying(128) NOT NULL,
    status character varying(32) NOT NULL,
    invited_by_user_id character varying(36) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    accepted_at timestamp with time zone,
    expires_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_space_invitations_role CHECK (((role)::text = ANY ((ARRAY['owner'::character varying, 'admin'::character varying, 'reviewer'::character varying, 'member'::character varying, 'guest'::character varying])::text[])))
);


--
-- Name: space_memberships; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.space_memberships (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    role character varying(32) NOT NULL,
    status character varying(32) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_space_memberships_role CHECK (((role)::text = ANY ((ARRAY['owner'::character varying, 'admin'::character varying, 'reviewer'::character varying, 'member'::character varying, 'guest'::character varying])::text[])))
);


--
-- Name: spaces; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.spaces (
    id character varying(36) NOT NULL,
    name character varying(256) NOT NULL,
    type character varying(32) NOT NULL,
    created_by_user_id character varying(36),
    snapshot_retention_days_default integer,
    snapshot_max_count_default integer,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_spaces_type CHECK (((type)::text = ANY ((ARRAY['personal'::character varying, 'household'::character varying, 'team'::character varying])::text[])))
);


--
-- Name: task_artifacts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.task_artifacts (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    task_id character varying(36) NOT NULL,
    artifact_id character varying(36) NOT NULL,
    run_id character varying(36),
    role character varying(32) DEFAULT 'output'::character varying NOT NULL,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: task_dependencies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.task_dependencies (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    task_id character varying(36) NOT NULL,
    depends_on_task_id character varying(36) NOT NULL,
    dependency_type character varying(32) DEFAULT 'requires'::character varying NOT NULL,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: task_evaluations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.task_evaluations (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    task_id character varying(36) NOT NULL,
    run_id character varying(36),
    run_evaluation_id character varying(36),
    evaluator_type character varying(32) NOT NULL,
    evaluator_user_id character varying(36),
    evaluator_agent_id character varying(36),
    score double precision,
    confidence double precision,
    summary text,
    checklist_json jsonb,
    known_issues_json jsonb,
    evidence_artifact_ids jsonb,
    recommendation character varying(64),
    created_at timestamp with time zone NOT NULL
);


--
-- Name: task_proposals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.task_proposals (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    task_id character varying(36) NOT NULL,
    proposal_id character varying(36) NOT NULL,
    role character varying(32) DEFAULT 'main_change'::character varying NOT NULL,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: task_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.task_runs (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    task_id character varying(36) NOT NULL,
    run_id character varying(36) NOT NULL,
    role character varying(32) DEFAULT 'primary'::character varying NOT NULL,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: tasks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tasks (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    workspace_id character varying(36),
    project_id character varying(36),
    board_id character varying(36),
    column_id character varying(36),
    parent_task_id character varying(36),
    title character varying(512) NOT NULL,
    description text,
    task_type character varying(64) DEFAULT 'general'::character varying NOT NULL,
    status character varying(64) DEFAULT 'inbox'::character varying NOT NULL,
    priority character varying(32) DEFAULT 'normal'::character varying NOT NULL,
    risk_level character varying(32) DEFAULT 'low'::character varying NOT NULL,
    created_by_user_id character varying(36),
    created_by_agent_id character varying(36),
    assigned_user_id character varying(36),
    assigned_agent_id character varying(36),
    claimed_by_user_id character varying(36),
    claimed_by_agent_id character varying(36),
    source_activity_id character varying(36),
    source_run_id character varying(36),
    source_proposal_id character varying(36),
    source_artifact_id character varying(36),
    acceptance_criteria_json jsonb,
    definition_of_done text,
    required_outputs_json jsonb,
    due_at timestamp with time zone,
    start_after timestamp with time zone,
    completed_at timestamp with time zone,
    cancelled_at timestamp with time zone,
    blocked_reason text,
    estimated_effort character varying(64),
    actual_effort character varying(64),
    max_runs integer,
    max_cost double precision,
    max_duration_seconds integer,
    policy_json jsonb,
    metadata_json jsonb,
    tags jsonb,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    deleted_at timestamp with time zone,
    visibility character varying(32) DEFAULT 'space_shared'::character varying NOT NULL
);


--
-- Name: user_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_sessions (
    id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    token_hash character varying(128) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    last_seen_at timestamp with time zone
);


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id character varying(36) NOT NULL,
    email character varying(256),
    display_name character varying(256) NOT NULL,
    avatar_url text,
    status character varying(32) NOT NULL,
    last_login_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: validation_recipes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.validation_recipes (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    workspace_id character varying(36),
    name character varying(256) NOT NULL,
    task_type character varying(64),
    risk_level character varying(32) DEFAULT 'low'::character varying NOT NULL,
    commands_json jsonb NOT NULL,
    required_checks_json jsonb NOT NULL,
    artifact_expectations_json jsonb,
    timeout_seconds integer,
    requires_clean_git_state boolean DEFAULT false NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_validation_recipes_risk_level CHECK (((risk_level)::text = ANY ((ARRAY['low'::character varying, 'medium'::character varying, 'high'::character varying])::text[])))
);


--
-- Name: working_dirs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.working_dirs (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    scope character varying(16) NOT NULL,
    session_id character varying(36),
    project_id character varying(36),
    rel_path character varying(1024) NOT NULL,
    status character varying(16) DEFAULT 'active'::character varying NOT NULL,
    metadata_json jsonb,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    last_used_at timestamp with time zone,
    cleaned_at timestamp with time zone,
    CONSTRAINT ck_working_dirs_owner CHECK (((((scope)::text = 'session'::text) AND (session_id IS NOT NULL) AND (project_id IS NULL)) OR (((scope)::text = 'project'::text) AND (project_id IS NOT NULL) AND (session_id IS NULL)))),
    CONSTRAINT ck_working_dirs_scope CHECK (((scope)::text = ANY ((ARRAY['session'::character varying, 'project'::character varying])::text[]))),
    CONSTRAINT ck_working_dirs_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'cleaning'::character varying, 'cleaned'::character varying])::text[])))
);


--
-- Name: workspace_intake_profiles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workspace_intake_profiles (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    workspace_id character varying(36) NOT NULL,
    name character varying(256) NOT NULL,
    status character varying(32) NOT NULL,
    observation_policy character varying(32) NOT NULL,
    routing_policy_json jsonb NOT NULL,
    filters_json jsonb NOT NULL,
    extraction_policy_json jsonb NOT NULL,
    context_policy_json jsonb NOT NULL,
    created_by_user_id character varying(36),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_workspace_intake_profiles_observation_policy CHECK (((observation_policy)::text = ANY ((ARRAY['disabled'::character varying, 'manual'::character varying, 'auto_select'::character varying, 'auto_extract'::character varying])::text[]))),
    CONSTRAINT ck_workspace_intake_profiles_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'paused'::character varying, 'archived'::character varying])::text[])))
);


--
-- Name: workspace_profiles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workspace_profiles (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    workspace_id character varying(36) NOT NULL,
    repo_type character varying(64),
    tech_stack_json jsonb,
    important_paths_json jsonb,
    forbidden_paths_json jsonb,
    test_commands_json jsonb,
    build_commands_json jsonb,
    architecture_boundaries_json jsonb,
    current_focus text,
    known_failures_json jsonb,
    validation_recipe_id character varying(36),
    cloud_allowed boolean DEFAULT false NOT NULL,
    max_data_exposure_level character varying(64),
    min_observability_level character varying(64),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_workspace_profiles_max_data_exposure_level CHECK (((max_data_exposure_level IS NULL) OR ((max_data_exposure_level)::text = ANY ((ARRAY['local_only'::character varying, 'model_provider'::character varying, 'vendor_platform'::character varying, 'third_party_tools'::character varying, 'unknown'::character varying])::text[])))),
    CONSTRAINT ck_workspace_profiles_min_observability_level CHECK (((min_observability_level IS NULL) OR ((min_observability_level)::text = ANY ((ARRAY['full_trace'::character varying, 'structured_events'::character varying, 'artifacts_only'::character varying, 'final_output_only'::character varying, 'black_box'::character varying])::text[]))))
);


--
-- Name: workspace_source_bindings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workspace_source_bindings (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    workspace_id character varying(36) NOT NULL,
    project_id character varying(36),
    source_connection_id character varying(36) NOT NULL,
    binding_key character varying(128) DEFAULT 'default'::character varying NOT NULL,
    status character varying(32) NOT NULL,
    priority integer NOT NULL,
    filters_json jsonb NOT NULL,
    routing_policy_json jsonb NOT NULL,
    extraction_policy_json jsonb NOT NULL,
    created_by_user_id character varying(36),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_workspace_source_bindings_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'paused'::character varying, 'archived'::character varying])::text[])))
);


--
-- Name: workspaces; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workspaces (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    name character varying(256) NOT NULL,
    description text,
    root_path character varying(1024),
    repo_url text,
    status character varying(32) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    created_by_user_id character varying(36),
    slug character varying(256),
    workspace_type character varying(32) NOT NULL,
    kind character varying(32) NOT NULL,
    default_branch character varying(256),
    visibility character varying(32) NOT NULL,
    protected boolean NOT NULL,
    system_managed boolean NOT NULL,
    registered_from character varying(32),
    metadata_json jsonb,
    allow_external_root boolean DEFAULT false NOT NULL,
    snapshot_retention_days integer,
    snapshot_max_count integer
);


--
-- Name: activity_records activity_records_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_records
    ADD CONSTRAINT activity_records_pkey PRIMARY KEY (id);


--
-- Name: actors actors_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.actors
    ADD CONSTRAINT actors_pkey PRIMARY KEY (id);




--
-- Name: agent_versions agent_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_versions
    ADD CONSTRAINT agent_versions_pkey PRIMARY KEY (id);


--
-- Name: agent_runtime_profiles agent_runtime_profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runtime_profiles
    ADD CONSTRAINT agent_runtime_profiles_pkey PRIMARY KEY (id);


--
-- Name: agent_runtime_profiles uq_agent_runtime_profiles_agent_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runtime_profiles
    ADD CONSTRAINT uq_agent_runtime_profiles_agent_name UNIQUE (agent_id, name);


--
-- Name: agents agents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agents
    ADD CONSTRAINT agents_pkey PRIMARY KEY (id);


--
-- Name: artifacts artifacts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_pkey PRIMARY KEY (id);


--
-- Name: context_artifact_revocations context_artifact_revocations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.context_artifact_revocations
    ADD CONSTRAINT context_artifact_revocations_pkey PRIMARY KEY (id);


--
-- Name: auth_accounts auth_accounts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_accounts
    ADD CONSTRAINT auth_accounts_pkey PRIMARY KEY (id);


--
-- Name: automation_credential_grants automation_credential_grants_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automation_credential_grants
    ADD CONSTRAINT automation_credential_grants_pkey PRIMARY KEY (id);


--
-- Name: automation_runs automation_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automation_runs
    ADD CONSTRAINT automation_runs_pkey PRIMARY KEY (id);


--
-- Name: automations automations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automations
    ADD CONSTRAINT automations_pkey PRIMARY KEY (id);


--
-- Name: board_columns board_columns_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.board_columns
    ADD CONSTRAINT board_columns_pkey PRIMARY KEY (id);


--
-- Name: boards boards_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.boards
    ADD CONSTRAINT boards_pkey PRIMARY KEY (id);


--
-- Name: capability_enablements capability_enablements_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.capability_enablements
    ADD CONSTRAINT capability_enablements_pkey PRIMARY KEY (id);


--
-- Name: capability_overlays capability_overlays_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.capability_overlays
    ADD CONSTRAINT capability_overlays_pkey PRIMARY KEY (id);


--
-- Name: capability_runtime_bindings capability_runtime_bindings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.capability_runtime_bindings
    ADD CONSTRAINT capability_runtime_bindings_pkey PRIMARY KEY (id);


--
-- Name: capability_versions capability_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.capability_versions
    ADD CONSTRAINT capability_versions_pkey PRIMARY KEY (id);


--
-- Name: card_review_states card_review_states_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.card_review_states
    ADD CONSTRAINT card_review_states_pkey PRIMARY KEY (id);


--
-- Name: card_reviews card_reviews_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.card_reviews
    ADD CONSTRAINT card_reviews_pkey PRIMARY KEY (id);


--
-- Name: cards cards_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cards
    ADD CONSTRAINT cards_pkey PRIMARY KEY (id);


--
-- Name: cli_credential_events cli_credential_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cli_credential_events
    ADD CONSTRAINT cli_credential_events_pkey PRIMARY KEY (id);


--
-- Name: cli_credential_profiles cli_credential_profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cli_credential_profiles
    ADD CONSTRAINT cli_credential_profiles_pkey PRIMARY KEY (id);


--
-- Name: cli_credential_space_grants cli_credential_space_grants_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cli_credential_space_grants
    ADD CONSTRAINT cli_credential_space_grants_pkey PRIMARY KEY (id);


--
-- Name: code_patch_snapshots code_patch_snapshots_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.code_patch_snapshots
    ADD CONSTRAINT code_patch_snapshots_pkey PRIMARY KEY (id);


--
-- Name: context_digests context_digests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.context_digests
    ADD CONSTRAINT context_digests_pkey PRIMARY KEY (id);


--
-- Name: context_profiles context_profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.context_profiles
    ADD CONSTRAINT context_profiles_pkey PRIMARY KEY (id);


--
-- Name: context_snapshot_items context_snapshot_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.context_snapshot_items
    ADD CONSTRAINT context_snapshot_items_pkey PRIMARY KEY (id);


--
-- Name: context_snapshots context_snapshots_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.context_snapshots
    ADD CONSTRAINT context_snapshots_pkey PRIMARY KEY (id);


--
-- Name: credentials credentials_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credentials
    ADD CONSTRAINT credentials_pkey PRIMARY KEY (id);


--
-- Name: scheduler_tasks scheduler_tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduler_tasks
    ADD CONSTRAINT scheduler_tasks_pkey PRIMARY KEY (id);



--
-- Name: evidence_links evidence_links_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evidence_links
    ADD CONSTRAINT evidence_links_pkey PRIMARY KEY (id);


--
-- Name: evolution_signals evolution_signals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evolution_signals
    ADD CONSTRAINT evolution_signals_pkey PRIMARY KEY (id);


--
-- Name: evolution_strategy_assets evolution_strategy_assets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evolution_strategy_assets
    ADD CONSTRAINT evolution_strategy_assets_pkey PRIMARY KEY (id);


--
-- Name: evolution_experiences evolution_experiences_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evolution_experiences
    ADD CONSTRAINT evolution_experiences_pkey PRIMARY KEY (id);


--
-- Name: evolution_selector_decisions evolution_selector_decisions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evolution_selector_decisions
    ADD CONSTRAINT evolution_selector_decisions_pkey PRIMARY KEY (id);


--
-- Name: evolution_targets evolution_targets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evolution_targets
    ADD CONSTRAINT evolution_targets_pkey PRIMARY KEY (id);


--
-- Name: external_run_records external_run_records_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_run_records
    ADD CONSTRAINT external_run_records_pkey PRIMARY KEY (id);


--
-- Name: extracted_evidence extracted_evidence_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.extracted_evidence
    ADD CONSTRAINT extracted_evidence_pkey PRIMARY KEY (id);


--
-- Name: extraction_jobs extraction_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.extraction_jobs
    ADD CONSTRAINT extraction_jobs_pkey PRIMARY KEY (id);


--
-- Name: intake_items intake_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.intake_items
    ADD CONSTRAINT intake_items_pkey PRIMARY KEY (id);


--
-- Name: job_events job_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_events
    ADD CONSTRAINT job_events_pkey PRIMARY KEY (id);


--
-- Name: jobs jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jobs
    ADD CONSTRAINT jobs_pkey PRIMARY KEY (id);


--
-- Name: space_objects space_objects_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.space_objects
    ADD CONSTRAINT space_objects_pkey PRIMARY KEY (id);


--
-- Name: space_objects space_objects_id_space_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.space_objects
    ADD CONSTRAINT space_objects_id_space_id_key UNIQUE (id, space_id);


--
-- Name: space_object_kinds space_object_kinds_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.space_object_kinds
    ADD CONSTRAINT space_object_kinds_pkey PRIMARY KEY (id);


--
-- Name: space_object_kinds space_object_kinds_space_base_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.space_object_kinds
    ADD CONSTRAINT space_object_kinds_space_base_key_key UNIQUE (space_id, base_object_type, key);


--
-- Name: space_object_kind_relation_hints space_object_kind_relation_hints_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.space_object_kind_relation_hints
    ADD CONSTRAINT space_object_kind_relation_hints_pkey PRIMARY KEY (id);



--
-- Name: knowledge_item_sources knowledge_item_sources_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_item_sources
    ADD CONSTRAINT knowledge_item_sources_pkey PRIMARY KEY (id);


--
-- Name: knowledge_items knowledge_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_items
    ADD CONSTRAINT knowledge_items_pkey PRIMARY KEY (object_id);


--
-- Name: knowledge_items knowledge_items_object_id_space_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_items
    ADD CONSTRAINT knowledge_items_object_id_space_id_key UNIQUE (object_id, space_id);


--
-- Name: claims claims_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.claims
    ADD CONSTRAINT claims_pkey PRIMARY KEY (object_id);


--
-- Name: claims claims_object_id_space_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.claims
    ADD CONSTRAINT claims_object_id_space_id_key UNIQUE (object_id, space_id);


--
-- Name: claim_sources claim_sources_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.claim_sources
    ADD CONSTRAINT claim_sources_pkey PRIMARY KEY (id);



--
-- Name: object_relations object_relations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.object_relations
    ADD CONSTRAINT object_relations_pkey PRIMARY KEY (id);


--
-- Name: memory_access_logs memory_access_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_access_logs
    ADD CONSTRAINT memory_access_logs_pkey PRIMARY KEY (id);


--
-- Name: memory_maintenance_jobs memory_maintenance_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_maintenance_jobs
    ADD CONSTRAINT memory_maintenance_jobs_pkey PRIMARY KEY (id);


--
-- Name: memory_entries memory_entries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_entries
    ADD CONSTRAINT memory_entries_pkey PRIMARY KEY (id);


--
-- Name: memory_relations memory_relations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_relations
    ADD CONSTRAINT memory_relations_pkey PRIMARY KEY (id);


--
-- Name: messages messages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.messages
    ADD CONSTRAINT messages_pkey PRIMARY KEY (id);


--
-- Name: network_profiles network_profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.network_profiles
    ADD CONSTRAINT network_profiles_pkey PRIMARY KEY (id);


--
-- Name: model_provider_credentials model_provider_credentials_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_provider_credentials
    ADD CONSTRAINT model_provider_credentials_pkey PRIMARY KEY (id);


--
-- Name: model_provider_space_grants model_provider_space_grants_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_provider_space_grants
    ADD CONSTRAINT model_provider_space_grants_pkey PRIMARY KEY (id);


--
-- Name: model_providers model_providers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_providers
    ADD CONSTRAINT model_providers_pkey PRIMARY KEY (id);


--
-- Name: note_collection_items note_collection_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.note_collection_items
    ADD CONSTRAINT note_collection_items_pkey PRIMARY KEY (id);


--
-- Name: note_collections note_collections_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.note_collections
    ADD CONSTRAINT note_collections_pkey PRIMARY KEY (id);


--
-- Name: note_collections note_collections_id_space_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.note_collections
    ADD CONSTRAINT note_collections_id_space_id_key UNIQUE (id, space_id);


--
-- Name: notes notes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notes
    ADD CONSTRAINT notes_pkey PRIMARY KEY (object_id);


--
-- Name: notes notes_object_id_space_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notes
    ADD CONSTRAINT notes_object_id_space_id_key UNIQUE (object_id, space_id);


--
-- Name: note_links note_links_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.note_links
    ADD CONSTRAINT note_links_pkey PRIMARY KEY (id);


--
-- Name: official_plugin_enablements official_plugin_enablements_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.official_plugin_enablements
    ADD CONSTRAINT official_plugin_enablements_pkey PRIMARY KEY (id);


--
-- Name: official_plugin_events official_plugin_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.official_plugin_events
    ADD CONSTRAINT official_plugin_events_pkey PRIMARY KEY (id);


--
-- Name: participation_records participation_records_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.participation_records
    ADD CONSTRAINT participation_records_pkey PRIMARY KEY (id);


--
-- Name: personal_memory_grant_events personal_memory_grant_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.personal_memory_grant_events
    ADD CONSTRAINT personal_memory_grant_events_pkey PRIMARY KEY (id);


--
-- Name: personal_memory_grants personal_memory_grants_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.personal_memory_grants
    ADD CONSTRAINT personal_memory_grants_pkey PRIMARY KEY (id);


--
-- Name: plugin_installs plugin_installs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.plugin_installs
    ADD CONSTRAINT plugin_installs_pkey PRIMARY KEY (id);


--
-- Name: plugin_installs plugin_installs_plugin_id_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.plugin_installs
    ADD CONSTRAINT plugin_installs_plugin_id_unique UNIQUE (plugin_id);


--
-- Name: plugin_migrations plugin_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.plugin_migrations
    ADD CONSTRAINT plugin_migrations_pkey PRIMARY KEY (id);


--
-- Name: plugin_migrations plugin_migrations_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.plugin_migrations
    ADD CONSTRAINT plugin_migrations_unique UNIQUE (plugin_id, migration_id);


--
-- Name: policies policies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.policies
    ADD CONSTRAINT policies_pkey PRIMARY KEY (id);


--
-- Name: policy_decision_records policy_decision_records_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.policy_decision_records
    ADD CONSTRAINT policy_decision_records_pkey PRIMARY KEY (id);


--
-- Name: project_workflow_profiles project_workflow_profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_workflow_profiles
    ADD CONSTRAINT project_workflow_profiles_pkey PRIMARY KEY (id);


--
-- Name: project_workspaces project_workspaces_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_workspaces
    ADD CONSTRAINT project_workspaces_pkey PRIMARY KEY (id);


--
-- Name: project_public_summaries project_public_summaries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_public_summaries
    ADD CONSTRAINT project_public_summaries_pkey PRIMARY KEY (id);


--
-- Name: projects projects_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_pkey PRIMARY KEY (id);


--
-- Name: project_members project_members_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_members
    ADD CONSTRAINT project_members_pkey PRIMARY KEY (id);


--
-- Name: proposal_approvals proposal_approvals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.proposal_approvals
    ADD CONSTRAINT proposal_approvals_pkey PRIMARY KEY (id);


--
-- Name: proposals proposals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.proposals
    ADD CONSTRAINT proposals_pkey PRIMARY KEY (id);


--
-- Name: provenance_links provenance_links_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.provenance_links
    ADD CONSTRAINT provenance_links_pkey PRIMARY KEY (id);


--
-- Name: provider_task_policies provider_task_policies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.provider_task_policies
    ADD CONSTRAINT provider_task_policies_pkey PRIMARY KEY (id);


--
-- Name: run_evaluations run_evaluations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_evaluations
    ADD CONSTRAINT run_evaluations_pkey PRIMARY KEY (id);


--
-- Name: run_events run_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_events
    ADD CONSTRAINT run_events_pkey PRIMARY KEY (id);


--
-- Name: run_execution_locks run_execution_locks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_execution_locks
    ADD CONSTRAINT run_execution_locks_pkey PRIMARY KEY (run_id);


--
-- Name: run_finalizations run_finalizations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_finalizations
    ADD CONSTRAINT run_finalizations_pkey PRIMARY KEY (id);


--
-- Name: run_reflections run_reflections_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_reflections
    ADD CONSTRAINT run_reflections_pkey PRIMARY KEY (id);


--
-- Name: run_steps run_steps_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_steps
    ADD CONSTRAINT run_steps_pkey PRIMARY KEY (id);


--
-- Name: runs runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runs
    ADD CONSTRAINT runs_pkey PRIMARY KEY (id);


--
-- Name: runtime_tool_bindings runtime_tool_bindings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_tool_bindings
    ADD CONSTRAINT runtime_tool_bindings_pkey PRIMARY KEY (id);


--
-- Name: session_summaries session_summaries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_summaries
    ADD CONSTRAINT session_summaries_pkey PRIMARY KEY (id);


--
-- Name: sessions sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT sessions_pkey PRIMARY KEY (id);


--
-- Name: skill_packages skill_packages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skill_packages
    ADD CONSTRAINT skill_packages_pkey PRIMARY KEY (id);


--
-- Name: skill_local_overlays skill_local_overlays_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skill_local_overlays
    ADD CONSTRAINT skill_local_overlays_pkey PRIMARY KEY (id);


--
-- Name: skill_package_files skill_package_files_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skill_package_files
    ADD CONSTRAINT skill_package_files_pkey PRIMARY KEY (id);


--
-- Name: skill_sources skill_sources_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skill_sources
    ADD CONSTRAINT skill_sources_pkey PRIMARY KEY (id);


--
-- Name: source_connections source_connections_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_connections
    ADD CONSTRAINT source_connections_pkey PRIMARY KEY (id);


--
-- Name: source_connections source_connections_id_space_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_connections
    ADD CONSTRAINT source_connections_id_space_id_key UNIQUE (id, space_id);


--
-- Name: source_connectors source_connectors_connector_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_connectors
    ADD CONSTRAINT source_connectors_connector_key_key UNIQUE (connector_key);


--
-- Name: source_connectors source_connectors_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_connectors
    ADD CONSTRAINT source_connectors_pkey PRIMARY KEY (id);


--
-- Name: source_pointers source_pointers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_pointers
    ADD CONSTRAINT source_pointers_pkey PRIMARY KEY (id);


--
-- Name: source_snapshots source_snapshots_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_snapshots
    ADD CONSTRAINT source_snapshots_pkey PRIMARY KEY (id);


--
-- Name: sources sources_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sources
    ADD CONSTRAINT sources_pkey PRIMARY KEY (object_id);


--
-- Name: sources sources_object_id_space_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sources
    ADD CONSTRAINT sources_object_id_space_id_key UNIQUE (object_id, space_id);


--
-- Name: retrieval_objects retrieval_objects_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.retrieval_objects
    ADD CONSTRAINT retrieval_objects_pkey PRIMARY KEY (id);


--
-- Name: retrieval_aliases retrieval_aliases_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.retrieval_aliases
    ADD CONSTRAINT retrieval_aliases_pkey PRIMARY KEY (id);


--
-- Name: retrieval_chunks retrieval_chunks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.retrieval_chunks
    ADD CONSTRAINT retrieval_chunks_pkey PRIMARY KEY (id);


--
-- Name: retrieval_edges retrieval_edges_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.retrieval_edges
    ADD CONSTRAINT retrieval_edges_pkey PRIMARY KEY (id);


--
-- Name: retrieval_feedback_events retrieval_feedback_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.retrieval_feedback_events
    ADD CONSTRAINT retrieval_feedback_events_pkey PRIMARY KEY (id);


--
-- Name: space_retrieval_prompts space_retrieval_prompts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.space_retrieval_prompts
    ADD CONSTRAINT space_retrieval_prompts_pkey PRIMARY KEY (id);


--
-- Name: space_runtime_tool_policies space_runtime_tool_policies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.space_runtime_tool_policies
    ADD CONSTRAINT space_runtime_tool_policies_pkey PRIMARY KEY (id);


--
-- Name: space_invitations space_invitations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.space_invitations
    ADD CONSTRAINT space_invitations_pkey PRIMARY KEY (id);


--
-- Name: space_invitations space_invitations_token_hash_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.space_invitations
    ADD CONSTRAINT space_invitations_token_hash_key UNIQUE (token_hash);


--
-- Name: space_memberships space_memberships_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.space_memberships
    ADD CONSTRAINT space_memberships_pkey PRIMARY KEY (id);


--
-- Name: spaces spaces_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.spaces
    ADD CONSTRAINT spaces_pkey PRIMARY KEY (id);


--
-- Name: task_artifacts task_artifacts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_artifacts
    ADD CONSTRAINT task_artifacts_pkey PRIMARY KEY (id);


--
-- Name: task_dependencies task_dependencies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_dependencies
    ADD CONSTRAINT task_dependencies_pkey PRIMARY KEY (id);


--
-- Name: task_evaluations task_evaluations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_evaluations
    ADD CONSTRAINT task_evaluations_pkey PRIMARY KEY (id);


--
-- Name: task_proposals task_proposals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_proposals
    ADD CONSTRAINT task_proposals_pkey PRIMARY KEY (id);


--
-- Name: task_runs task_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_runs
    ADD CONSTRAINT task_runs_pkey PRIMARY KEY (id);


--
-- Name: tasks tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_pkey PRIMARY KEY (id);




--
-- Name: agent_versions uq_agent_versions_agent_label; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_versions
    ADD CONSTRAINT uq_agent_versions_agent_label UNIQUE (agent_id, version_label);


--
-- Name: auth_accounts uq_auth_accounts_provider_user; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_accounts
    ADD CONSTRAINT uq_auth_accounts_provider_user UNIQUE (provider, provider_user_id);


--
-- Name: card_review_states uq_card_review_states_card_user; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.card_review_states
    ADD CONSTRAINT uq_card_review_states_card_user UNIQUE (card_id, user_id);


--
-- Name: scheduler_tasks uq_scheduler_tasks_type_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduler_tasks
    ADD CONSTRAINT uq_scheduler_tasks_type_key UNIQUE (task_type, task_key);


--
-- Name: cli_credential_profiles uq_cli_credential_profiles_owner_runtime_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cli_credential_profiles
    ADD CONSTRAINT uq_cli_credential_profiles_owner_runtime_name UNIQUE (owner_user_id, runtime, name);


--
-- Name: cli_credential_space_grants uq_cli_credential_space_grants_profile_space; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cli_credential_space_grants
    ADD CONSTRAINT uq_cli_credential_space_grants_profile_space UNIQUE (profile_id, space_id);


--
-- Name: model_provider_credentials uq_model_provider_credentials_provider_credential; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_provider_credentials
    ADD CONSTRAINT uq_model_provider_credentials_provider_credential UNIQUE (provider_id, credential_id);


--
-- Name: model_provider_space_grants uq_model_provider_space_grants_provider_space; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_provider_space_grants
    ADD CONSTRAINT uq_model_provider_space_grants_provider_space UNIQUE (provider_id, space_id);


--
-- Name: note_collection_items uq_note_collection_items_collection_note; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.note_collection_items
    ADD CONSTRAINT uq_note_collection_items_collection_note UNIQUE (space_id, collection_id, note_id);


--
-- Name: project_workspaces uq_project_workspaces_project_workspace_role; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_workspaces
    ADD CONSTRAINT uq_project_workspaces_project_workspace_role UNIQUE (space_id, project_id, workspace_id, role);


--
-- Name: projects uq_projects_space_id_id; Type: CONSTRAINT; Schema: public; Owner: -
--
-- Composite candidate key so child tables can carry a (space_id, project_id)
-- foreign key into projects. This makes a row's space_id provably equal to its
-- project's space_id at the database level, not only by service-layer checks.

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT uq_projects_space_id_id UNIQUE (space_id, id);


--
-- Name: provider_task_policies uq_provider_task_policies_space_task; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.provider_task_policies
    ADD CONSTRAINT uq_provider_task_policies_space_task UNIQUE (space_id, task);


--
-- Name: run_events uq_run_events_space_run_event_index; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_events
    ADD CONSTRAINT uq_run_events_space_run_event_index UNIQUE (space_id, run_id, event_index);


--
-- Name: run_finalizations uq_run_finalizations_run_version; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_finalizations
    ADD CONSTRAINT uq_run_finalizations_run_version UNIQUE (run_id, finalizer_version);


--
-- Name: run_steps uq_run_steps_run_step_index; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_steps
    ADD CONSTRAINT uq_run_steps_run_step_index UNIQUE (run_id, step_index);


--
-- Name: session_summaries uq_session_summaries_session_version; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_summaries
    ADD CONSTRAINT uq_session_summaries_session_version UNIQUE (session_id, version);


--
-- Name: space_retrieval_prompts uq_space_retrieval_prompts_space_task; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.space_retrieval_prompts
    ADD CONSTRAINT uq_space_retrieval_prompts_space_task UNIQUE (space_id, task);


--
-- Name: space_runtime_tool_policies uq_space_runtime_tool_policies_space_runtime; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.space_runtime_tool_policies
    ADD CONSTRAINT uq_space_runtime_tool_policies_space_runtime UNIQUE (space_id, runtime);


--
-- Name: space_memberships uq_space_memberships_space_user; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.space_memberships
    ADD CONSTRAINT uq_space_memberships_space_user UNIQUE (space_id, user_id);


--
-- Name: task_artifacts uq_task_artifacts_task_artifact; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_artifacts
    ADD CONSTRAINT uq_task_artifacts_task_artifact UNIQUE (task_id, artifact_id);


--
-- Name: task_dependencies uq_task_dependencies_task_depends; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_dependencies
    ADD CONSTRAINT uq_task_dependencies_task_depends UNIQUE (task_id, depends_on_task_id);


--
-- Name: task_proposals uq_task_proposals_task_proposal; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_proposals
    ADD CONSTRAINT uq_task_proposals_task_proposal UNIQUE (task_id, proposal_id);


--
-- Name: task_runs uq_task_runs_task_run; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_runs
    ADD CONSTRAINT uq_task_runs_task_run UNIQUE (task_id, run_id);


--
-- Name: workspace_intake_profiles uq_workspace_intake_profiles_workspace; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_intake_profiles
    ADD CONSTRAINT uq_workspace_intake_profiles_workspace UNIQUE (space_id, workspace_id);


--
-- Name: workspace_profiles uq_workspace_profiles_workspace; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_profiles
    ADD CONSTRAINT uq_workspace_profiles_workspace UNIQUE (workspace_id);


--
-- Name: workspace_source_bindings uq_workspace_source_bindings_connection; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_source_bindings
    ADD CONSTRAINT uq_workspace_source_bindings_connection UNIQUE (space_id, workspace_id, source_connection_id, binding_key);


--
-- Name: user_sessions user_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_sessions
    ADD CONSTRAINT user_sessions_pkey PRIMARY KEY (id);


--
-- Name: user_sessions user_sessions_token_hash_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_sessions
    ADD CONSTRAINT user_sessions_token_hash_key UNIQUE (token_hash);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: validation_recipes validation_recipes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.validation_recipes
    ADD CONSTRAINT validation_recipes_pkey PRIMARY KEY (id);


--
-- Name: working_dirs working_dirs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.working_dirs
    ADD CONSTRAINT working_dirs_pkey PRIMARY KEY (id);


--
-- Name: workspace_intake_profiles workspace_intake_profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_intake_profiles
    ADD CONSTRAINT workspace_intake_profiles_pkey PRIMARY KEY (id);


--
-- Name: workspace_profiles workspace_profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_profiles
    ADD CONSTRAINT workspace_profiles_pkey PRIMARY KEY (id);


--
-- Name: workspace_source_bindings workspace_source_bindings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_source_bindings
    ADD CONSTRAINT workspace_source_bindings_pkey PRIMARY KEY (id);


--
-- Name: workspaces workspaces_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspaces
    ADD CONSTRAINT workspaces_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.workspaces
    ADD CONSTRAINT ck_workspaces_workspace_type CHECK ((workspace_type::text = ANY (ARRAY['project'::text, 'repo'::text, 'knowledge_base'::text, 'personal'::text, 'team'::text, 'system_core'::text])));

ALTER TABLE ONLY public.workspaces
    ADD CONSTRAINT ck_workspaces_status CHECK ((status::text = ANY (ARRAY['active'::text, 'archived'::text, 'stale'::text])));

ALTER TABLE ONLY public.workspaces
    ADD CONSTRAINT ck_workspaces_visibility CHECK ((visibility::text = ANY (ARRAY['private'::text, 'space_shared'::text, 'workspace_shared'::text, 'restricted'::text])));


--
-- Name: workspaces uq_workspaces_space_id_id; Type: CONSTRAINT; Schema: public; Owner: -
--
-- Composite candidate key so child tables can carry a (space_id, workspace_id)
-- foreign key into workspaces, enforcing same-space membership at DB level.
--

ALTER TABLE ONLY public.workspaces
    ADD CONSTRAINT uq_workspaces_space_id_id UNIQUE (space_id, id);


--
-- Name: ix_activity_records_activity_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_activity_records_activity_type ON public.activity_records USING btree (activity_type);


--
-- Name: ix_activity_records_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_activity_records_agent_id ON public.activity_records USING btree (agent_id);


--
-- Name: ix_activity_records_owner_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_activity_records_owner_user_id ON public.activity_records USING btree (owner_user_id);


--
-- Name: ix_activity_records_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_activity_records_project_id ON public.activity_records USING btree (project_id);


--
-- Name: ix_activity_records_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_activity_records_session_id ON public.activity_records USING btree (session_id);


--
-- Name: ix_activity_records_source_kind; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_activity_records_source_kind ON public.activity_records USING btree (source_kind);


--
-- Name: ix_activity_records_source_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_activity_records_source_run_id ON public.activity_records USING btree (source_run_id);


--
-- Name: ix_activity_records_source_task_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_activity_records_source_task_id ON public.activity_records USING btree (source_task_id);


--
-- Name: ix_activity_records_source_trust; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_activity_records_source_trust ON public.activity_records USING btree (source_trust);


--
-- Name: ix_activity_records_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_activity_records_space_id ON public.activity_records USING btree (space_id);


--
-- Name: ix_activity_records_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_activity_records_status ON public.activity_records USING btree (status);


--
-- Name: ix_activity_records_subject_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_activity_records_subject_user_id ON public.activity_records USING btree (subject_user_id);


--
-- Name: ix_activity_records_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_activity_records_user_id ON public.activity_records USING btree (user_id);


--
-- Name: ix_activity_records_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_activity_records_workspace_id ON public.activity_records USING btree (workspace_id);


--
-- Name: ix_actors_actor_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_actors_actor_type ON public.actors USING btree (actor_type);


--
-- Name: ix_actors_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_actors_agent_id ON public.actors USING btree (agent_id);


--
-- Name: ix_actors_service_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_actors_service_name ON public.actors USING btree (service_name);


--
-- Name: ix_actors_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_actors_space_id ON public.actors USING btree (space_id);


--
-- Name: ix_actors_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_actors_status ON public.actors USING btree (status);


--
-- Name: ix_actors_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_actors_user_id ON public.actors USING btree (user_id);




--
-- Name: ix_agent_versions_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_versions_agent_id ON public.agent_versions USING btree (agent_id);


--
-- Name: ix_agent_versions_model_provider_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_versions_model_provider_id ON public.agent_versions USING btree (model_provider_id);


--
-- Name: ix_agent_versions_source_activity_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_versions_source_activity_id ON public.agent_versions USING btree (source_activity_id);


--
-- Name: ix_agent_versions_source_proposal_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_versions_source_proposal_id ON public.agent_versions USING btree (source_proposal_id);


--
-- Name: ix_agent_versions_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_versions_space_id ON public.agent_versions USING btree (space_id);


--
-- Name: ix_agent_runtime_profiles_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_runtime_profiles_agent_id ON public.agent_runtime_profiles USING btree (agent_id);


--
-- Name: ix_agent_runtime_profiles_credential_profile_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_runtime_profiles_credential_profile_id ON public.agent_runtime_profiles USING btree (credential_profile_id);


--
-- Name: ix_agent_runtime_profiles_model_provider_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_runtime_profiles_model_provider_id ON public.agent_runtime_profiles USING btree (model_provider_id);


--
-- Name: ix_agent_runtime_profiles_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_runtime_profiles_space_id ON public.agent_runtime_profiles USING btree (space_id);


--
-- Name: ix_agents_agent_kind; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agents_agent_kind ON public.agents USING btree (agent_kind);


--
-- Name: ix_agents_current_version_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agents_current_version_id ON public.agents USING btree (current_version_id);


--
-- Name: ix_agents_owner_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agents_owner_user_id ON public.agents USING btree (owner_user_id);


--
-- Name: ix_agents_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agents_space_id ON public.agents USING btree (space_id);


--
-- Name: ix_agents_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agents_status ON public.agents USING btree (status);


--
-- Name: ix_artifacts_artifact_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_artifacts_artifact_type ON public.artifacts USING btree (artifact_type);


--
-- Name: ix_artifacts_owner_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_artifacts_owner_user_id ON public.artifacts USING btree (owner_user_id);


--
-- Name: ix_artifacts_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_artifacts_project_id ON public.artifacts USING btree (project_id);


--
-- Name: ix_artifacts_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_artifacts_workspace_id ON public.artifacts USING btree (workspace_id);


--
-- Name: ix_artifacts_proposal_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_artifacts_proposal_id ON public.artifacts USING btree (proposal_id);


--
-- Name: ix_artifacts_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_artifacts_run_id ON public.artifacts USING btree (run_id);


--
-- Name: ix_artifacts_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_artifacts_space_id ON public.artifacts USING btree (space_id);


--
-- Name: ix_context_artifact_revocations_artifact_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_context_artifact_revocations_artifact_id ON public.context_artifact_revocations USING btree (artifact_id);


--
-- Name: ix_context_artifact_revocations_space_scope; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_context_artifact_revocations_space_scope ON public.context_artifact_revocations USING btree (space_id, scope_type, scope_id);


--
-- Name: uq_context_artifact_revocations_active_scope; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_context_artifact_revocations_active_scope ON public.context_artifact_revocations USING btree (space_id, artifact_id, scope_type, scope_id) WHERE (deleted_at IS NULL);


--
-- Name: ix_auth_accounts_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_auth_accounts_user_id ON public.auth_accounts USING btree (user_id);


--
-- Name: ix_automation_credential_grants_automation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_automation_credential_grants_automation_id ON public.automation_credential_grants USING btree (automation_id);


--
-- Name: ix_automation_credential_grants_granted_by_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_automation_credential_grants_granted_by_user_id ON public.automation_credential_grants USING btree (granted_by_user_id);


--
-- Name: ix_automation_credential_grants_lookup; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_automation_credential_grants_lookup ON public.automation_credential_grants USING btree (space_id, automation_id, status);


--
-- Name: ix_automation_credential_grants_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_automation_credential_grants_space_id ON public.automation_credential_grants USING btree (space_id);


--
-- Name: ix_automation_credential_grants_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_automation_credential_grants_status ON public.automation_credential_grants USING btree (status);


--
-- Name: ix_automation_runs_automation_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_automation_runs_automation_created ON public.automation_runs USING btree (automation_id, created_at);


--
-- Name: ix_automation_runs_automation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_automation_runs_automation_id ON public.automation_runs USING btree (automation_id);


--
-- Name: ix_automation_runs_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_automation_runs_run_id ON public.automation_runs USING btree (run_id);


--
-- Name: ix_automation_runs_triggered_by_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_automation_runs_triggered_by_user_id ON public.automation_runs USING btree (triggered_by_user_id);


--
-- Name: ix_automations_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_automations_agent_id ON public.automations USING btree (agent_id);


--
-- Name: ix_automations_owner_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_automations_owner_user_id ON public.automations USING btree (owner_user_id);


--
-- Name: ix_automations_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_automations_space_id ON public.automations USING btree (space_id);


--
-- Name: ix_automations_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_automations_status ON public.automations USING btree (status);


--
-- Name: ix_automations_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_automations_workspace_id ON public.automations USING btree (workspace_id);


--
-- Name: ix_board_columns_board_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_board_columns_board_id ON public.board_columns USING btree (board_id);


--
-- Name: ix_board_columns_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_board_columns_space_id ON public.board_columns USING btree (space_id);


--
-- Name: ix_boards_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_boards_space_id ON public.boards USING btree (space_id);


--
-- Name: ix_boards_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_boards_workspace_id ON public.boards USING btree (workspace_id);


--
-- Name: ix_boards_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_boards_project_id ON public.boards USING btree (project_id);


--
-- Name: ix_capability_enablements_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_capability_enablements_agent_id ON public.capability_enablements USING btree (agent_id);


--
-- Name: ix_capability_enablements_capability_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_capability_enablements_capability_key ON public.capability_enablements USING btree (capability_key);


--
-- Name: ix_capability_enablements_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_capability_enablements_project_id ON public.capability_enablements USING btree (project_id);


--
-- Name: ix_capability_enablements_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_capability_enablements_space_id ON public.capability_enablements USING btree (space_id);


--
-- Name: ix_capability_enablements_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_capability_enablements_user_id ON public.capability_enablements USING btree (user_id);


--
-- Name: ix_capability_overlays_base_version_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_capability_overlays_base_version_id ON public.capability_overlays USING btree (base_version_id);


--
-- Name: ix_capability_overlays_capability_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_capability_overlays_capability_key ON public.capability_overlays USING btree (capability_key);


--
-- Name: ix_capability_overlays_key_scope_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_capability_overlays_key_scope_status ON public.capability_overlays USING btree (capability_key, scope_type, scope_id, status);


--
-- Name: ix_capability_overlays_overlay_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_capability_overlays_overlay_type ON public.capability_overlays USING btree (overlay_type);


--
-- Name: ix_capability_overlays_proposal_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_capability_overlays_proposal_id ON public.capability_overlays USING btree (proposal_id);


--
-- Name: ix_capability_overlays_scope_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_capability_overlays_scope_id ON public.capability_overlays USING btree (scope_id);


--
-- Name: ix_capability_overlays_scope_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_capability_overlays_scope_type ON public.capability_overlays USING btree (scope_type);


--
-- Name: ix_capability_overlays_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_capability_overlays_status ON public.capability_overlays USING btree (status);


--
-- Name: ix_capability_runtime_bindings_capability_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_capability_runtime_bindings_capability_key ON public.capability_runtime_bindings USING btree (capability_key);


--
-- Name: ix_capability_runtime_bindings_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_capability_runtime_bindings_space_id ON public.capability_runtime_bindings USING btree (space_id);


--
-- Name: ix_capability_runtime_bindings_version_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_capability_runtime_bindings_version_id ON public.capability_runtime_bindings USING btree (capability_version_id);


--
-- Name: uq_capability_enablements_agent; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_capability_enablements_agent ON public.capability_enablements USING btree (space_id, agent_id, capability_key) WHERE ((agent_id IS NOT NULL) AND (project_id IS NULL) AND (user_id IS NULL));


--
-- Name: uq_capability_enablements_project; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_capability_enablements_project ON public.capability_enablements USING btree (space_id, project_id, capability_key) WHERE ((project_id IS NOT NULL) AND (agent_id IS NULL) AND (user_id IS NULL));


--
-- Name: uq_capability_enablements_space; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_capability_enablements_space ON public.capability_enablements USING btree (space_id, capability_key) WHERE ((project_id IS NULL) AND (agent_id IS NULL) AND (user_id IS NULL));


--
-- Name: uq_capability_enablements_user; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_capability_enablements_user ON public.capability_enablements USING btree (space_id, user_id, capability_key) WHERE ((user_id IS NOT NULL) AND (project_id IS NULL) AND (agent_id IS NULL));


--
-- Name: uq_capability_runtime_bindings_scope_runtime; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_capability_runtime_bindings_scope_runtime ON public.capability_runtime_bindings USING btree (COALESCE(space_id, '__global__'::character varying), capability_key, COALESCE(capability_version_id, '__none__'::character varying), runtime_adapter_type, render_mode);


--
-- Name: ix_capability_versions_capability_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_capability_versions_capability_key ON public.capability_versions USING btree (capability_key);


--
-- Name: ix_capability_versions_key_scope_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_capability_versions_key_scope_status ON public.capability_versions USING btree (capability_key, scope_type, scope_id, status);


--
-- Name: ix_capability_versions_parent_version_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_capability_versions_parent_version_id ON public.capability_versions USING btree (parent_version_id);


--
-- Name: ix_capability_versions_proposal_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_capability_versions_proposal_id ON public.capability_versions USING btree (proposal_id);


--
-- Name: ix_capability_versions_scope_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_capability_versions_scope_id ON public.capability_versions USING btree (scope_id);


--
-- Name: ix_capability_versions_scope_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_capability_versions_scope_type ON public.capability_versions USING btree (scope_type);


--
-- Name: ix_capability_versions_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_capability_versions_source ON public.capability_versions USING btree (source);


--
-- Name: ix_capability_versions_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_capability_versions_status ON public.capability_versions USING btree (status);


--
-- Name: ix_card_review_states_card_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_card_review_states_card_id ON public.card_review_states USING btree (card_id);


--
-- Name: ix_card_review_states_user_due; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_card_review_states_user_due ON public.card_review_states USING btree (user_id, due_at);


--
-- Name: ix_card_reviews_card_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_card_reviews_card_id ON public.card_reviews USING btree (card_id);


--
-- Name: ix_card_reviews_rating; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_card_reviews_rating ON public.card_reviews USING btree (rating);


--
-- Name: ix_card_reviews_user_reviewed_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_card_reviews_user_reviewed_at ON public.card_reviews USING btree (user_id, reviewed_at);


--
-- Name: ix_cards_card_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_cards_card_type ON public.cards USING btree (card_type);


--
-- Name: ix_cards_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_cards_created_at ON public.cards USING btree (created_at);


--
-- Name: ix_cards_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_cards_source ON public.cards USING btree (source_type, source_id);


--
-- Name: ix_cards_source_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_cards_source_id ON public.cards USING btree (source_id);


--
-- Name: ix_cards_source_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_cards_source_type ON public.cards USING btree (source_type);


--
-- Name: ix_cards_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_cards_space_id ON public.cards USING btree (space_id);


--
-- Name: ix_cards_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_cards_status ON public.cards USING btree (status);


--
-- Name: ix_cli_credential_events_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_cli_credential_events_run_id ON public.cli_credential_events USING btree (run_id);


--
-- Name: ix_cli_credential_events_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_cli_credential_events_space_id ON public.cli_credential_events USING btree (space_id);


--
-- Name: ix_cli_credential_profiles_owner_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_cli_credential_profiles_owner_user_id ON public.cli_credential_profiles USING btree (owner_user_id);


--
-- Name: ix_cli_credential_profiles_runtime; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_cli_credential_profiles_runtime ON public.cli_credential_profiles USING btree (runtime);


--
-- Name: ix_cli_credential_space_grants_network_profile_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_cli_credential_space_grants_network_profile_id ON public.cli_credential_space_grants USING btree (network_profile_id);


--
-- Name: ix_cli_credential_space_grants_owner_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_cli_credential_space_grants_owner_user_id ON public.cli_credential_space_grants USING btree (owner_user_id);


--
-- Name: ix_cli_credential_space_grants_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_cli_credential_space_grants_space_id ON public.cli_credential_space_grants USING btree (space_id);


--
-- Name: ix_code_patch_snapshots_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_code_patch_snapshots_expires_at ON public.code_patch_snapshots USING btree (expires_at);


--
-- Name: ix_code_patch_snapshots_proposal_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_code_patch_snapshots_proposal_id ON public.code_patch_snapshots USING btree (proposal_id);


--
-- Name: ix_code_patch_snapshots_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_code_patch_snapshots_workspace_id ON public.code_patch_snapshots USING btree (workspace_id);


--
-- Name: ix_context_digests_digest_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_context_digests_digest_type ON public.context_digests USING btree (digest_type);


--
-- Name: ix_context_digests_scope_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_context_digests_scope_id ON public.context_digests USING btree (scope_id);


--
-- Name: ix_context_digests_scope_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_context_digests_scope_type ON public.context_digests USING btree (scope_type);


--
-- Name: ix_context_digests_source_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_context_digests_source_hash ON public.context_digests USING btree (source_hash);


--
-- Name: ix_context_digests_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_context_digests_space_id ON public.context_digests USING btree (space_id);


--
-- Name: ix_context_digests_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_context_digests_status ON public.context_digests USING btree (status);


--
-- Name: ix_context_profiles_scope; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_context_profiles_scope ON public.context_profiles USING btree (space_id, scope_type, scope_id);


--
-- Name: ix_context_profiles_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_context_profiles_status ON public.context_profiles USING btree (status);


--
-- Name: uq_context_profiles_active_scope; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_context_profiles_active_scope ON public.context_profiles USING btree (space_id, scope_type, COALESCE(scope_id, ''::character varying)) WHERE ((status)::text = 'active'::text);


--
-- Name: uq_context_digests_current_scope; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_context_digests_current_scope ON public.context_digests USING btree (space_id, scope_type, COALESCE(scope_id, ''::character varying), digest_type) WHERE ((status)::text = ANY ((ARRAY['active'::character varying, 'dirty'::character varying])::text[]));


--
-- Name: ix_context_snapshot_items_context_snapshot_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_context_snapshot_items_context_snapshot_id ON public.context_snapshot_items USING btree (context_snapshot_id);


--
-- Name: ix_context_snapshot_items_item_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_context_snapshot_items_item_type ON public.context_snapshot_items USING btree (item_type);


--
-- Name: ix_context_snapshots_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_context_snapshots_agent_id ON public.context_snapshots USING btree (agent_id);


--
-- Name: ix_context_snapshots_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_context_snapshots_run_id ON public.context_snapshots USING btree (run_id);


--
-- Name: ix_context_snapshots_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_context_snapshots_session_id ON public.context_snapshots USING btree (session_id);


--
-- Name: ix_context_snapshots_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_context_snapshots_space_id ON public.context_snapshots USING btree (space_id);


--
-- Name: ix_credentials_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_credentials_space_id ON public.credentials USING btree (space_id);


--
-- Name: ix_credentials_owner_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_credentials_owner_user_id ON public.credentials USING btree (owner_user_id);


--
-- Name: ix_scheduler_tasks_due; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scheduler_tasks_due ON public.scheduler_tasks USING btree (task_type, status, next_run_at);


--
-- Name: ix_scheduler_tasks_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scheduler_tasks_space_id ON public.scheduler_tasks USING btree (space_id);


--
-- Name: ix_scheduler_tasks_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scheduler_tasks_user_id ON public.scheduler_tasks USING btree (user_id);










--
-- Name: ix_evidence_links_created_by_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_evidence_links_created_by_agent_id ON public.evidence_links USING btree (created_by_agent_id);


--
-- Name: ix_evidence_links_created_by_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_evidence_links_created_by_run_id ON public.evidence_links USING btree (created_by_run_id);


--
-- Name: ix_evidence_links_created_by_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_evidence_links_created_by_user_id ON public.evidence_links USING btree (created_by_user_id);


--
-- Name: ix_evidence_links_evidence_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_evidence_links_evidence_id ON public.evidence_links USING btree (evidence_id);


--
-- Name: ix_evidence_links_evidence_target; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_evidence_links_evidence_target ON public.evidence_links USING btree (evidence_id, target_type, target_id);


--
-- Name: ix_evidence_links_link_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_evidence_links_link_type ON public.evidence_links USING btree (link_type);


--
-- Name: ix_evidence_links_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_evidence_links_space_id ON public.evidence_links USING btree (space_id);


--
-- Name: ix_evidence_links_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_evidence_links_status ON public.evidence_links USING btree (status);


--
-- Name: ix_evidence_links_target; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_evidence_links_target ON public.evidence_links USING btree (space_id, target_type, target_id);


--
-- Name: ix_evidence_links_target_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_evidence_links_target_id ON public.evidence_links USING btree (target_id);


--
-- Name: ix_evidence_links_target_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_evidence_links_target_type ON public.evidence_links USING btree (target_type);


--
-- Name: ix_evolution_signals_severity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_evolution_signals_severity ON public.evolution_signals USING btree (severity);


--
-- Name: ix_evolution_signals_signal_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_evolution_signals_signal_type ON public.evolution_signals USING btree (signal_type);


--
-- Name: ix_evolution_signals_source_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_evolution_signals_source_id ON public.evolution_signals USING btree (source_id);


--
-- Name: ix_evolution_signals_source_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_evolution_signals_source_type ON public.evolution_signals USING btree (source_type);


--
-- Name: ix_evolution_signals_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_evolution_signals_space_id ON public.evolution_signals USING btree (space_id);


--
-- Name: ix_evolution_signals_space_target_type_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_evolution_signals_space_target_type_created ON public.evolution_signals USING btree (space_id, target_id, signal_type, created_at);


--
-- Name: ix_evolution_signals_target_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_evolution_signals_target_id ON public.evolution_signals USING btree (target_id);


--
-- Name: ix_evolution_strategy_assets_space_status_category_target; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_evolution_strategy_assets_space_status_category_target ON public.evolution_strategy_assets USING btree (space_id, status, category, target_type);


--
-- Name: ix_evolution_strategy_assets_strategy_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_evolution_strategy_assets_strategy_key ON public.evolution_strategy_assets USING btree (strategy_key);


--
-- Name: uq_evolution_strategy_assets_space_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_evolution_strategy_assets_space_key ON public.evolution_strategy_assets USING btree (space_id, strategy_key) WHERE (space_id IS NOT NULL);


--
-- Name: uq_evolution_strategy_assets_system_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_evolution_strategy_assets_system_key ON public.evolution_strategy_assets USING btree (strategy_key) WHERE (space_id IS NULL);


--
-- Name: ix_evolution_experiences_space_strategy_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_evolution_experiences_space_strategy_created ON public.evolution_experiences USING btree (space_id, strategy_asset_id, created_at DESC);


--
-- Name: ix_evolution_experiences_space_source_run; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_evolution_experiences_space_source_run ON public.evolution_experiences USING btree (space_id, source_run_id);

-- Name: uq_evolution_experiences_space_key; Type: INDEX; Schema: public; Owner: -

CREATE UNIQUE INDEX uq_evolution_experiences_space_key ON public.evolution_experiences USING btree (space_id, experience_key);


--
-- Name: ix_evolution_selector_decisions_space_target_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_evolution_selector_decisions_space_target_created ON public.evolution_selector_decisions USING btree (space_id, target_id, created_at DESC);


--
-- Name: ix_evolution_selector_decisions_space_run; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_evolution_selector_decisions_space_run ON public.evolution_selector_decisions USING btree (space_id, run_id);


--
-- Name: ix_evolution_targets_capability_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_evolution_targets_capability_key ON public.evolution_targets USING btree (capability_key);


--
-- Name: ix_evolution_targets_current_version_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_evolution_targets_current_version_id ON public.evolution_targets USING btree (current_version_id);


--
-- Name: ix_evolution_targets_risk_level; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_evolution_targets_risk_level ON public.evolution_targets USING btree (risk_level);


--
-- Name: ix_evolution_targets_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_evolution_targets_space_id ON public.evolution_targets USING btree (space_id);


--
-- Name: ix_evolution_targets_space_type_ref_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_evolution_targets_space_type_ref_status ON public.evolution_targets USING btree (space_id, target_type, target_ref_id, status);


--
-- Name: ix_evolution_targets_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_evolution_targets_status ON public.evolution_targets USING btree (status);


--
-- Name: ix_evolution_targets_target_ref_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_evolution_targets_target_ref_id ON public.evolution_targets USING btree (target_ref_id);


--
-- Name: ix_evolution_targets_target_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_evolution_targets_target_type ON public.evolution_targets USING btree (target_type);


--
-- Name: ix_external_run_records_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_external_run_records_run_id ON public.external_run_records USING btree (run_id);


--
-- Name: ix_external_run_records_runtime_adapter_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_external_run_records_runtime_adapter_type ON public.external_run_records USING btree (runtime_adapter_type);


--
-- Name: ix_external_run_records_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_external_run_records_space_id ON public.external_run_records USING btree (space_id);


--
-- Name: ix_extracted_evidence_artifact_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_extracted_evidence_artifact_id ON public.extracted_evidence USING btree (artifact_id);


--
-- Name: ix_extracted_evidence_content_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_extracted_evidence_content_hash ON public.extracted_evidence USING btree (content_hash);


--
-- Name: ix_extracted_evidence_created_by_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_extracted_evidence_created_by_agent_id ON public.extracted_evidence USING btree (created_by_agent_id);


--
-- Name: ix_extracted_evidence_created_by_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_extracted_evidence_created_by_run_id ON public.extracted_evidence USING btree (created_by_run_id);


--
-- Name: ix_extracted_evidence_created_by_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_extracted_evidence_created_by_user_id ON public.extracted_evidence USING btree (created_by_user_id);


--
-- Name: ix_extracted_evidence_deleted_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_extracted_evidence_deleted_at ON public.extracted_evidence USING btree (deleted_at);


--
-- Name: ix_extracted_evidence_evidence_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_extracted_evidence_evidence_type ON public.extracted_evidence USING btree (evidence_type);


--
-- Name: ix_extracted_evidence_extraction_job_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_extracted_evidence_extraction_job_id ON public.extracted_evidence USING btree (extraction_job_id);


--
-- Name: ix_extracted_evidence_intake_item_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_extracted_evidence_intake_item_id ON public.extracted_evidence USING btree (intake_item_id);


--
-- Name: ix_extracted_evidence_occurred_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_extracted_evidence_occurred_at ON public.extracted_evidence USING btree (occurred_at);


--
-- Name: ix_extracted_evidence_source_object; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_extracted_evidence_source_object ON public.extracted_evidence USING btree (space_id, source_object_type, source_object_id);


--
-- Name: ix_extracted_evidence_source_object_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_extracted_evidence_source_object_id ON public.extracted_evidence USING btree (source_object_id);


--
-- Name: ix_extracted_evidence_source_object_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_extracted_evidence_source_object_type ON public.extracted_evidence USING btree (source_object_type);


--
-- Name: ix_extracted_evidence_source_snapshot_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_extracted_evidence_source_snapshot_id ON public.extracted_evidence USING btree (source_snapshot_id);


--
-- Name: ix_extracted_evidence_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_extracted_evidence_space_id ON public.extracted_evidence USING btree (space_id);


--
-- Name: ix_extracted_evidence_space_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_extracted_evidence_space_status ON public.extracted_evidence USING btree (space_id, status);


--
-- Name: ix_extracted_evidence_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_extracted_evidence_status ON public.extracted_evidence USING btree (status);


--
-- Name: ix_extracted_evidence_trust_level; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_extracted_evidence_trust_level ON public.extracted_evidence USING btree (trust_level);


--
-- Name: ix_extraction_jobs_connection_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_extraction_jobs_connection_id ON public.extraction_jobs USING btree (connection_id);


--
-- Name: ix_extraction_jobs_intake_item_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_extraction_jobs_intake_item_id ON public.extraction_jobs USING btree (intake_item_id);


--
-- Name: ix_extraction_jobs_source_object; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_extraction_jobs_source_object ON public.extraction_jobs USING btree (space_id, source_object_type, source_object_id);


--
-- Name: ix_extraction_jobs_source_object_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_extraction_jobs_source_object_id ON public.extraction_jobs USING btree (source_object_id);


--
-- Name: ix_extraction_jobs_source_object_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_extraction_jobs_source_object_type ON public.extraction_jobs USING btree (source_object_type);


--
-- Name: ix_extraction_jobs_source_snapshot_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_extraction_jobs_source_snapshot_id ON public.extraction_jobs USING btree (source_snapshot_id);


--
-- Name: ix_extraction_jobs_space_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_extraction_jobs_space_created ON public.extraction_jobs USING btree (space_id, created_at);


--
-- Name: ix_extraction_jobs_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_extraction_jobs_space_id ON public.extraction_jobs USING btree (space_id);


--
-- Name: ix_extraction_jobs_space_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_extraction_jobs_space_status ON public.extraction_jobs USING btree (space_id, status);


--
-- Name: ix_extraction_jobs_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_extraction_jobs_status ON public.extraction_jobs USING btree (status);


--
-- Name: ix_intake_items_canonical_uri; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_intake_items_canonical_uri ON public.intake_items USING btree (space_id, canonical_uri);


--
-- Name: ix_intake_items_connection_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_intake_items_connection_id ON public.intake_items USING btree (connection_id);


--
-- Name: ix_intake_items_content_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_intake_items_content_hash ON public.intake_items USING btree (content_hash);


--
-- Name: ix_intake_items_deleted_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_intake_items_deleted_at ON public.intake_items USING btree (deleted_at);


--
-- Name: ix_intake_items_extracted_artifact_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_intake_items_extracted_artifact_id ON public.intake_items USING btree (extracted_artifact_id);


--
-- Name: ix_intake_items_item_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_intake_items_item_type ON public.intake_items USING btree (item_type);


--
-- Name: ix_intake_items_occurred_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_intake_items_occurred_at ON public.intake_items USING btree (occurred_at);


--
-- Name: ix_intake_items_raw_artifact_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_intake_items_raw_artifact_id ON public.intake_items USING btree (raw_artifact_id);


--
-- Name: ix_intake_items_source_domain; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_intake_items_source_domain ON public.intake_items USING btree (source_domain);


--
-- Name: ix_intake_items_source_external_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_intake_items_source_external_id ON public.intake_items USING btree (source_external_id);


--
-- Name: ix_intake_items_source_object; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_intake_items_source_object ON public.intake_items USING btree (space_id, source_object_type, source_object_id);


--
-- Name: ix_intake_items_source_object_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_intake_items_source_object_id ON public.intake_items USING btree (source_object_id);


--
-- Name: ix_intake_items_source_object_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_intake_items_source_object_type ON public.intake_items USING btree (source_object_type);


--
-- Name: ix_intake_items_space_connection; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_intake_items_space_connection ON public.intake_items USING btree (space_id, connection_id);


--
-- Name: ix_intake_items_space_domain; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_intake_items_space_domain ON public.intake_items USING btree (space_id, source_domain);


--
-- Name: ix_intake_items_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_intake_items_space_id ON public.intake_items USING btree (space_id);


--
-- Name: ix_intake_items_space_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_intake_items_space_status ON public.intake_items USING btree (space_id, status);


--
-- Name: ix_intake_items_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_intake_items_status ON public.intake_items USING btree (status);


--
-- Name: ix_intake_items_summary_artifact_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_intake_items_summary_artifact_id ON public.intake_items USING btree (summary_artifact_id);


--
-- Name: ix_job_events_job_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_job_events_job_id ON public.job_events USING btree (job_id);


--
-- Name: ix_jobs_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_jobs_agent_id ON public.jobs USING btree (agent_id);


--
-- Name: ix_jobs_claim_pending; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_jobs_claim_pending ON public.jobs USING btree (priority DESC, scheduled_at) WHERE ((status)::text = 'pending'::text);


--
-- Name: ix_jobs_job_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_jobs_job_type ON public.jobs USING btree (job_type);


--
-- Name: ix_jobs_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_jobs_space_id ON public.jobs USING btree (space_id);


--
-- Name: ix_jobs_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_jobs_status ON public.jobs USING btree (status);


--
-- Name: ix_jobs_type_claim_pending; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_jobs_type_claim_pending ON public.jobs USING btree (job_type, priority DESC, scheduled_at) WHERE ((status)::text = 'pending'::text);


--
-- Name: ix_jobs_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_jobs_user_id ON public.jobs USING btree (user_id);


--
-- Name: ix_jobs_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_jobs_workspace_id ON public.jobs USING btree (workspace_id);








--
-- Name: ix_knowledge_item_sources_knowledge_item_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_knowledge_item_sources_knowledge_item_id ON public.knowledge_item_sources USING btree (knowledge_item_id);


--
-- Name: ix_knowledge_item_sources_relation_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_knowledge_item_sources_relation_type ON public.knowledge_item_sources USING btree (relation_type);


--
-- Name: ix_knowledge_item_sources_source_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_knowledge_item_sources_source_id ON public.knowledge_item_sources USING btree (source_id);


--
-- Name: ix_knowledge_item_sources_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_knowledge_item_sources_space_id ON public.knowledge_item_sources USING btree (space_id);


--
-- Name: ix_knowledge_item_sources_unique; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_knowledge_item_sources_unique ON public.knowledge_item_sources USING btree (knowledge_item_id, source_id, relation_type);


--
-- Name: ix_knowledge_items_created_from_proposal_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_knowledge_items_created_from_proposal_id ON public.knowledge_items USING btree (created_from_proposal_id);


--
-- Name: ix_knowledge_items_knowledge_kind; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_knowledge_items_knowledge_kind ON public.knowledge_items USING btree (knowledge_kind);


--
-- Name: ix_space_objects_owner_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_space_objects_owner_user_id ON public.space_objects USING btree (owner_user_id);


--
-- Name: ix_space_objects_primary_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_space_objects_primary_project_id ON public.space_objects USING btree (primary_project_id);


--
-- Name: ix_knowledge_items_redirect_to_item_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_knowledge_items_redirect_to_item_id ON public.knowledge_items USING btree (redirect_to_item_id);


--
-- Name: ix_knowledge_items_root_item_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_knowledge_items_root_item_id ON public.knowledge_items USING btree (root_item_id);


--
-- Name: ix_knowledge_items_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_knowledge_items_slug ON public.knowledge_items USING btree (slug);


--
-- Name: ix_knowledge_items_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_knowledge_items_space_id ON public.knowledge_items USING btree (space_id);


--
-- Name: ix_knowledge_items_space_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_knowledge_items_space_slug ON public.knowledge_items USING btree (space_id, slug);


--
-- Name: ix_space_objects_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_space_objects_status ON public.space_objects USING btree (status);


--
-- Name: ix_knowledge_items_supersedes_item_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_knowledge_items_supersedes_item_id ON public.knowledge_items USING btree (supersedes_item_id);


--
-- Name: ix_space_objects_visibility; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_space_objects_visibility ON public.space_objects USING btree (visibility);


--
-- Name: ix_space_objects_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_space_objects_workspace_id ON public.space_objects USING btree (workspace_id);


--
-- Name: ix_space_objects_space_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_space_objects_space_type ON public.space_objects USING btree (space_id, object_type);


--
-- Name: ix_space_objects_created_by_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_space_objects_created_by_user_id ON public.space_objects USING btree (created_by_user_id);


--
-- Name: ix_space_objects_deleted_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_space_objects_deleted_at ON public.space_objects USING btree (deleted_at);


--
-- Name: ix_space_object_kinds_base_object_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_space_object_kinds_base_object_type ON public.space_object_kinds USING btree (base_object_type);


--
-- Name: ix_space_object_kinds_created_by_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_space_object_kinds_created_by_user_id ON public.space_object_kinds USING btree (created_by_user_id);


--
-- Name: ix_space_object_kinds_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_space_object_kinds_space_id ON public.space_object_kinds USING btree (space_id);


--
-- Name: ix_space_object_kinds_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_space_object_kinds_status ON public.space_object_kinds USING btree (status);


--
-- Name: ix_space_object_kind_relation_hints_endpoint_kind; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_space_object_kind_relation_hints_endpoint_kind ON public.space_object_kind_relation_hints USING btree (endpoint_object_kind_id);


--
-- Name: ix_space_object_kind_relation_hints_object_kind; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_space_object_kind_relation_hints_object_kind ON public.space_object_kind_relation_hints USING btree (object_kind_id);


--
-- Name: ix_space_object_kind_relation_hints_required; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_space_object_kind_relation_hints_required ON public.space_object_kind_relation_hints USING btree (space_id, required);


--
-- Name: ix_claims_claim_kind; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_claims_claim_kind ON public.claims USING btree (claim_kind);


--
-- Name: ix_claims_created_from_proposal_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_claims_created_from_proposal_id ON public.claims USING btree (created_from_proposal_id);


--
-- Name: ix_claims_holder_object_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_claims_holder_object_id ON public.claims USING btree (holder_object_id);


--
-- Name: ix_claims_normalized_claim_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_claims_normalized_claim_hash ON public.claims USING btree (normalized_claim_hash);


--
-- Name: ix_claims_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_claims_space_id ON public.claims USING btree (space_id);


--
-- Name: ix_claims_subject_object_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_claims_subject_object_id ON public.claims USING btree (subject_object_id);


--
-- Name: ix_claim_sources_claim_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_claim_sources_claim_id ON public.claim_sources USING btree (claim_id);


--
-- Name: ix_claim_sources_source_connection_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_claim_sources_source_connection_id ON public.claim_sources USING btree (source_connection_id);


--
-- Name: ix_claim_sources_source_object_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_claim_sources_source_object_id ON public.claim_sources USING btree (source_object_id);


--
-- Name: ix_claim_sources_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_claim_sources_space_id ON public.claim_sources USING btree (space_id);








--
-- Name: ix_object_relations_from_object_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_object_relations_from_object_id ON public.object_relations USING btree (from_object_id);


--
-- Name: ix_object_relations_relation_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_object_relations_relation_type ON public.object_relations USING btree (relation_type);


--
-- Name: ix_object_relations_source_claim_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_object_relations_source_claim_id ON public.object_relations USING btree (source_claim_id);


--
-- Name: ix_object_relations_source_object_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_object_relations_source_object_id ON public.object_relations USING btree (source_object_id);


--
-- Name: ix_object_relations_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_object_relations_space_id ON public.object_relations USING btree (space_id);


--
-- Name: ix_object_relations_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_object_relations_status ON public.object_relations USING btree (status);


--
-- Name: ix_object_relations_to_object_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_object_relations_to_object_id ON public.object_relations USING btree (to_object_id);


--
-- Name: ix_object_relations_unique_active; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_object_relations_unique_active ON public.object_relations USING btree (space_id, from_object_id, to_object_id, relation_type) WHERE ((status)::text = 'active'::text);


--
-- Name: ix_memory_access_logs_accessed_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_access_logs_accessed_at ON public.memory_access_logs USING btree (accessed_at);


--
-- Name: ix_memory_access_logs_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_access_logs_agent_id ON public.memory_access_logs USING btree (agent_id);


--
-- Name: ix_memory_access_logs_memory_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_access_logs_memory_id ON public.memory_access_logs USING btree (memory_id);


--
-- Name: ix_memory_access_logs_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_access_logs_run_id ON public.memory_access_logs USING btree (run_id);


--
-- Name: ix_memory_access_logs_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_access_logs_space_id ON public.memory_access_logs USING btree (space_id);


--
-- Name: ix_memory_access_logs_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_access_logs_user_id ON public.memory_access_logs USING btree (user_id);


--
-- Name: ix_memory_maintenance_jobs_due; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_maintenance_jobs_due ON public.memory_maintenance_jobs USING btree (status, run_after, updated_at);


--
-- Name: ix_memory_maintenance_jobs_owner; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_maintenance_jobs_owner ON public.memory_maintenance_jobs USING btree (space_id, owner_user_id, status, updated_at);


--
-- Name: ix_memory_entries_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_entries_agent_id ON public.memory_entries USING btree (agent_id);



--
-- Name: ix_memory_entries_created_from_proposal_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_entries_created_from_proposal_id ON public.memory_entries USING btree (created_from_proposal_id);



--
-- Name: ix_memory_entries_memory_layer; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_entries_memory_layer ON public.memory_entries USING btree (memory_layer);


--
-- Name: ix_memory_entries_memory_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_entries_memory_type ON public.memory_entries USING btree (memory_type);


--
-- Name: ix_memory_entries_namespace; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_entries_namespace ON public.memory_entries USING btree (namespace);


--
-- Name: ix_memory_entries_owner_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_entries_owner_user_id ON public.memory_entries USING btree (owner_user_id);


--
-- Name: ix_memory_entries_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_entries_project_id ON public.memory_entries USING btree (project_id);


--
-- Name: ix_memory_entries_root_memory_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_entries_root_memory_id ON public.memory_entries USING btree (root_memory_id);



--
-- Name: ix_memory_entries_scope_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_entries_scope_type ON public.memory_entries USING btree (scope_type);


--
-- Name: ix_memory_entries_sensitivity_level; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_entries_sensitivity_level ON public.memory_entries USING btree (sensitivity_level);



--
-- Name: ix_memory_entries_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_entries_space_id ON public.memory_entries USING btree (space_id);


--
-- Name: ix_memory_entries_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_entries_status ON public.memory_entries USING btree (status);


--
-- Name: ix_memory_entries_subject_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_entries_subject_user_id ON public.memory_entries USING btree (subject_user_id);


--
-- Name: ix_memory_entries_supersedes_memory_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_entries_supersedes_memory_id ON public.memory_entries USING btree (supersedes_memory_id);


--
-- Name: ix_memory_entries_visibility; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_entries_visibility ON public.memory_entries USING btree (visibility);


--
-- Name: ix_memory_entries_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_entries_workspace_id ON public.memory_entries USING btree (workspace_id);


--
-- Name: ix_memory_relations_created_from_proposal_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_relations_created_from_proposal_id ON public.memory_relations USING btree (created_from_proposal_id);


--
-- Name: ix_memory_relations_relation_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_relations_relation_type ON public.memory_relations USING btree (relation_type);


--
-- Name: ix_memory_relations_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_relations_source ON public.memory_relations USING btree (space_id, source_type, source_id);


--
-- Name: ix_memory_relations_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_relations_space_id ON public.memory_relations USING btree (space_id);


--
-- Name: ix_memory_relations_target; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_relations_target ON public.memory_relations USING btree (space_id, target_type, target_id);


--
-- Name: ix_messages_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_messages_session_id ON public.messages USING btree (session_id);


--
-- Name: ix_messages_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_messages_space_id ON public.messages USING btree (space_id);


--
-- Name: ix_messages_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_messages_user_id ON public.messages USING btree (user_id);


--
-- Name: ix_network_profiles_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_network_profiles_space_id ON public.network_profiles USING btree (space_id);


--
-- Name: ix_model_provider_credentials_provider_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_model_provider_credentials_provider_id ON public.model_provider_credentials USING btree (provider_id);


--
-- Name: ix_model_provider_credentials_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_model_provider_credentials_space_id ON public.model_provider_credentials USING btree (space_id);


--
-- Name: ix_model_provider_space_grants_network_profile_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_model_provider_space_grants_network_profile_id ON public.model_provider_space_grants USING btree (network_profile_id);


--
-- Name: ix_model_provider_space_grants_owner_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_model_provider_space_grants_owner_user_id ON public.model_provider_space_grants USING btree (owner_user_id);


--
-- Name: ix_model_provider_space_grants_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_model_provider_space_grants_space_id ON public.model_provider_space_grants USING btree (space_id);


--
-- Name: ix_model_providers_credential_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_model_providers_credential_id ON public.model_providers USING btree (credential_id);


--
-- Name: ix_model_providers_network_profile_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_model_providers_network_profile_id ON public.model_providers USING btree (network_profile_id);


--
-- Name: ix_model_providers_owner_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_model_providers_owner_user_id ON public.model_providers USING btree (owner_user_id);


--
-- Name: ix_model_providers_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_model_providers_space_id ON public.model_providers USING btree (space_id);


--
-- Name: ix_note_collection_items_collection_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_note_collection_items_collection_id ON public.note_collection_items USING btree (space_id, collection_id);


--
-- Name: ix_note_collection_items_note_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_note_collection_items_note_id ON public.note_collection_items USING btree (space_id, note_id);


--
-- Name: ix_note_collections_one_archive_per_space; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_note_collections_one_archive_per_space ON public.note_collections USING btree (space_id) WHERE ((system_role)::text = 'archive'::text);


--
-- Name: ix_note_collections_one_inbox_per_space; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_note_collections_one_inbox_per_space ON public.note_collections USING btree (space_id) WHERE ((system_role)::text = 'inbox'::text);


--
-- Name: ix_note_collections_parent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_note_collections_parent_id ON public.note_collections USING btree (parent_id);


--
-- Name: ix_note_collections_parent_sort; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_note_collections_parent_sort ON public.note_collections USING btree (space_id, parent_id, sort_order);


--
-- Name: ix_note_collections_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_note_collections_space_id ON public.note_collections USING btree (space_id);


--
-- Name: ix_note_collections_system_role; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_note_collections_system_role ON public.note_collections USING btree (system_role);


--
-- Name: ix_notes_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_notes_space_id ON public.notes USING btree (space_id);


--
-- Name: ix_note_links_from_object; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_note_links_from_object ON public.note_links USING btree (space_id, from_object_id);


--
-- Name: ix_note_links_link_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_note_links_link_type ON public.note_links USING btree (link_type);


--
-- Name: ix_note_links_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_note_links_space_id ON public.note_links USING btree (space_id);


--
-- Name: ix_note_links_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_note_links_status ON public.note_links USING btree (status);


--
-- Name: ix_note_links_to_object; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_note_links_to_object ON public.note_links USING btree (space_id, to_object_id);


--
-- Name: ix_note_links_unique_active; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_note_links_unique_active ON public.note_links USING btree (space_id, from_object_id, to_object_id, link_type) WHERE ((status)::text = 'active'::text);


--
-- Name: ix_sources_source_activity_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sources_source_activity_id ON public.sources USING btree (source_activity_id);


--
-- Name: ix_sources_source_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sources_source_type ON public.sources USING btree (source_type);


--
-- Name: ix_sources_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sources_space_id ON public.sources USING btree (space_id);


--
-- Name: ix_notes_created_from_activity_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_notes_created_from_activity_id ON public.notes USING btree (created_from_activity_id);


--
-- Name: ix_participation_records_personal_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_participation_records_personal_space_id ON public.participation_records USING btree (personal_space_id);


--
-- Name: ix_participation_records_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_participation_records_source ON public.participation_records USING btree (source_space_id, source_object_type, source_object_id);


--
-- Name: ix_participation_records_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_participation_records_user_id ON public.participation_records USING btree (user_id);


--
-- Name: ix_personal_memory_grant_events_actor_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_personal_memory_grant_events_actor_user_id ON public.personal_memory_grant_events USING btree (actor_user_id);


--
-- Name: ix_personal_memory_grant_events_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_personal_memory_grant_events_created_at ON public.personal_memory_grant_events USING btree (created_at);


--
-- Name: ix_personal_memory_grant_events_grant_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_personal_memory_grant_events_grant_id ON public.personal_memory_grant_events USING btree (grant_id);


--
-- Name: ix_personal_memory_grant_events_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_personal_memory_grant_events_run_id ON public.personal_memory_grant_events USING btree (run_id);


--
-- Name: ix_personal_memory_grants_granting_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_personal_memory_grants_granting_user_id ON public.personal_memory_grants USING btree (granting_user_id);


--
-- Name: ix_personal_memory_grants_personal_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_personal_memory_grants_personal_space_id ON public.personal_memory_grants USING btree (personal_space_id);


--
-- Name: ix_personal_memory_grants_read_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_personal_memory_grants_read_expires_at ON public.personal_memory_grants USING btree (read_expires_at);


--
-- Name: ix_personal_memory_grants_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_personal_memory_grants_status ON public.personal_memory_grants USING btree (status);


--
-- Name: ix_personal_memory_grants_target_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_personal_memory_grants_target_run_id ON public.personal_memory_grants USING btree (target_run_id);


--
-- Name: ix_personal_memory_grants_target_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_personal_memory_grants_target_space_id ON public.personal_memory_grants USING btree (target_space_id);


--
-- Name: ix_personal_memory_grants_unique_active_consuming; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_personal_memory_grants_unique_active_consuming ON public.personal_memory_grants USING btree (granting_user_id, target_run_id) WHERE ((status)::text = ANY ((ARRAY['active'::character varying, 'consuming'::character varying])::text[]));


--
-- Name: ix_policies_created_from_proposal_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_policies_created_from_proposal_id ON public.policies USING btree (created_from_proposal_id);


--
-- Name: ix_policies_domain; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_policies_domain ON public.policies USING btree (domain);


--
-- Name: ix_policies_policy_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_policies_policy_key ON public.policies USING btree (policy_key);


--
-- Name: ix_policies_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_policies_space_id ON public.policies USING btree (space_id);


--
-- Name: ix_policies_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_policies_status ON public.policies USING btree (status);


--
-- Name: ix_policies_supersedes_policy_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_policies_supersedes_policy_id ON public.policies USING btree (supersedes_policy_id);


--
-- Name: ix_policy_decision_records_action; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_policy_decision_records_action ON public.policy_decision_records USING btree (action);


--
-- Name: ix_policy_decision_records_actor_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_policy_decision_records_actor_id ON public.policy_decision_records USING btree (actor_id);


--
-- Name: ix_policy_decision_records_audit_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_policy_decision_records_audit_code ON public.policy_decision_records USING btree (audit_code);


--
-- Name: ix_policy_decision_records_audit_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_policy_decision_records_audit_created ON public.policy_decision_records USING btree (audit_code, created_at);


--
-- Name: ix_policy_decision_records_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_policy_decision_records_created_at ON public.policy_decision_records USING btree (created_at);


--
-- Name: ix_policy_decision_records_decision; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_policy_decision_records_decision ON public.policy_decision_records USING btree (decision);


--
-- Name: ix_policy_decision_records_proposal_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_policy_decision_records_proposal_created ON public.policy_decision_records USING btree (proposal_id, created_at);


--
-- Name: ix_policy_decision_records_proposal_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_policy_decision_records_proposal_id ON public.policy_decision_records USING btree (proposal_id);


--
-- Name: ix_policy_decision_records_resource_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_policy_decision_records_resource_id ON public.policy_decision_records USING btree (resource_id);


--
-- Name: ix_policy_decision_records_resource_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_policy_decision_records_resource_type ON public.policy_decision_records USING btree (resource_type);


--
-- Name: ix_policy_decision_records_risk_level; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_policy_decision_records_risk_level ON public.policy_decision_records USING btree (risk_level);


--
-- Name: ix_policy_decision_records_run_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_policy_decision_records_run_created ON public.policy_decision_records USING btree (run_id, created_at);


--
-- Name: ix_policy_decision_records_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_policy_decision_records_run_id ON public.policy_decision_records USING btree (run_id);


--
-- Name: ix_policy_decision_records_space_action_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_policy_decision_records_space_action_created ON public.policy_decision_records USING btree (space_id, action, created_at);


--
-- Name: ix_policy_decision_records_space_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_policy_decision_records_space_created ON public.policy_decision_records USING btree (space_id, created_at);


--
-- Name: ix_policy_decision_records_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_policy_decision_records_space_id ON public.policy_decision_records USING btree (space_id);


--
-- Name: ix_project_workflow_profiles_space_project; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_project_workflow_profiles_space_project ON public.project_workflow_profiles USING btree (space_id, project_id);


--
-- Name: ix_project_workflow_profiles_template; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_project_workflow_profiles_template ON public.project_workflow_profiles USING btree (workflow_template_id);


--
-- Name: uq_project_workflow_profiles_name; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_project_workflow_profiles_name ON public.project_workflow_profiles USING btree (space_id, project_id, workflow_template_id, name);


--
-- Name: ix_project_workspaces_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_project_workspaces_project_id ON public.project_workspaces USING btree (project_id);


--
-- Name: ix_project_workspaces_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_project_workspaces_workspace_id ON public.project_workspaces USING btree (workspace_id);


--
-- Name: ix_project_public_summaries_project_unique; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_project_public_summaries_project_unique ON public.project_public_summaries USING btree (project_id);


--
-- Name: ix_project_public_summaries_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_project_public_summaries_space_id ON public.project_public_summaries USING btree (space_id);


--
-- Name: ix_project_public_summaries_review_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_project_public_summaries_review_status ON public.project_public_summaries USING btree (review_status);


--
-- Name: ix_projects_owner_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_projects_owner_user_id ON public.projects USING btree (owner_user_id);


--
-- Name: ix_projects_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_projects_space_id ON public.projects USING btree (space_id);


--
-- Name: ix_projects_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_projects_status ON public.projects USING btree (status);


--
-- Name: uq_projects_space_name_active; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_projects_space_name_active ON public.projects USING btree (space_id, name) WHERE ((status)::text = 'active'::text);


--
-- Name: ix_project_members_project_user_unique; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_project_members_project_user_unique ON public.project_members USING btree (project_id, user_id);


--
-- Name: ix_project_members_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_project_members_user_id ON public.project_members USING btree (user_id);


--
-- Name: ix_project_members_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_project_members_space_id ON public.project_members USING btree (space_id);


--
-- Name: ix_proposal_approvals_approval_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_proposal_approvals_approval_type ON public.proposal_approvals USING btree (approval_type);


--
-- Name: ix_proposal_approvals_approver_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_proposal_approvals_approver_user_id ON public.proposal_approvals USING btree (approver_user_id);


--
-- Name: ix_proposal_approvals_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_proposal_approvals_created_at ON public.proposal_approvals USING btree (created_at);


--
-- Name: ix_proposal_approvals_grant_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_proposal_approvals_grant_id ON public.proposal_approvals USING btree (grant_id);


--
-- Name: ix_proposal_approvals_proposal_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_proposal_approvals_proposal_id ON public.proposal_approvals USING btree (proposal_id);


--
-- Name: ix_proposal_approvals_target_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_proposal_approvals_target_space_id ON public.proposal_approvals USING btree (target_space_id);


--
-- Name: ix_proposal_approvals_unique_active; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_proposal_approvals_unique_active ON public.proposal_approvals USING btree (proposal_id, approval_type, approver_user_id, grant_id) WHERE ((status)::text = 'approved'::text);


--
-- Name: ix_proposals_created_by_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_proposals_created_by_run_id ON public.proposals USING btree (created_by_run_id);


--
-- Name: ix_proposals_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_proposals_project_id ON public.proposals USING btree (project_id);


--
-- Name: ix_proposals_proposal_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_proposals_proposal_type ON public.proposals USING btree (proposal_type);


--
-- Name: ix_proposals_risk_level; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_proposals_risk_level ON public.proposals USING btree (risk_level);


--
-- Name: ix_proposals_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_proposals_space_id ON public.proposals USING btree (space_id);


--
-- Name: ix_proposals_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_proposals_status ON public.proposals USING btree (status);


--
-- Name: ix_proposals_urgency; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_proposals_urgency ON public.proposals USING btree (urgency);


--
-- Name: ix_proposals_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_proposals_workspace_id ON public.proposals USING btree (workspace_id);


--
-- Name: ix_provenance_links_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_provenance_links_source ON public.provenance_links USING btree (space_id, source_type, source_id);


--
-- Name: ix_provenance_links_source_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_provenance_links_source_type ON public.provenance_links USING btree (source_type);


--
-- Name: ix_provenance_links_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_provenance_links_space_id ON public.provenance_links USING btree (space_id);


--
-- Name: ix_provenance_links_target; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_provenance_links_target ON public.provenance_links USING btree (space_id, target_type, target_id);


--
-- Name: ix_provider_task_policies_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_provider_task_policies_space_id ON public.provider_task_policies USING btree (space_id);


--
-- Name: ix_run_evaluations_evaluated_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_run_evaluations_evaluated_at ON public.run_evaluations USING btree (evaluated_at);


--
-- Name: ix_run_evaluations_evaluator_version; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_run_evaluations_evaluator_version ON public.run_evaluations USING btree (evaluator_version);


--
-- Name: ix_run_evaluations_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_run_evaluations_run_id ON public.run_evaluations USING btree (run_id);


--
-- Name: ix_run_evaluations_run_id_evaluated_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_run_evaluations_run_id_evaluated_at ON public.run_evaluations USING btree (run_id, evaluated_at);


--
-- Name: ix_run_evaluations_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_run_evaluations_space_id ON public.run_evaluations USING btree (space_id);


--
-- Name: ix_run_events_actor_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_run_events_actor_id ON public.run_events USING btree (actor_id);


--
-- Name: ix_run_events_artifact_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_run_events_artifact_id ON public.run_events USING btree (artifact_id);


--
-- Name: ix_run_events_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_run_events_created_at ON public.run_events USING btree (created_at);


--
-- Name: ix_run_events_error_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_run_events_error_code ON public.run_events USING btree (error_code);


--
-- Name: ix_run_events_event_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_run_events_event_type ON public.run_events USING btree (event_type);


--
-- Name: ix_run_events_proposal_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_run_events_proposal_id ON public.run_events USING btree (proposal_id);


--
-- Name: ix_run_events_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_run_events_run_id ON public.run_events USING btree (run_id);


--
-- Name: ix_run_events_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_run_events_space_id ON public.run_events USING btree (space_id);


--
-- Name: ix_run_events_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_run_events_status ON public.run_events USING btree (status);


--
-- Name: ix_run_events_step_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_run_events_step_id ON public.run_events USING btree (step_id);


--
-- Name: ix_run_events_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_run_events_workspace_id ON public.run_events USING btree (workspace_id);


--
-- Name: ix_run_finalizations_finalized_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_run_finalizations_finalized_at ON public.run_finalizations USING btree (finalized_at);


--
-- Name: ix_run_finalizations_run_evaluation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_run_finalizations_run_evaluation_id ON public.run_finalizations USING btree (run_evaluation_id);


--
-- Name: ix_run_finalizations_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_run_finalizations_run_id ON public.run_finalizations USING btree (run_id);


--
-- Name: ix_run_finalizations_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_run_finalizations_space_id ON public.run_finalizations USING btree (space_id);


--
-- Name: ix_run_finalizations_task_evaluation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_run_finalizations_task_evaluation_id ON public.run_finalizations USING btree (task_evaluation_id);


--
-- Name: ix_run_reflections_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_run_reflections_run_id ON public.run_reflections USING btree (run_id);


--
-- Name: ix_run_reflections_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_run_reflections_space_id ON public.run_reflections USING btree (space_id);


--
-- Name: ix_run_steps_actor_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_run_steps_actor_id ON public.run_steps USING btree (actor_id);


--
-- Name: ix_run_steps_artifact_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_run_steps_artifact_id ON public.run_steps USING btree (artifact_id);


--
-- Name: ix_run_steps_parent_step_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_run_steps_parent_step_id ON public.run_steps USING btree (parent_step_id);


--
-- Name: ix_run_steps_proposal_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_run_steps_proposal_id ON public.run_steps USING btree (proposal_id);


--
-- Name: ix_run_steps_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_run_steps_run_id ON public.run_steps USING btree (run_id);


--
-- Name: ix_run_steps_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_run_steps_session_id ON public.run_steps USING btree (session_id);


--
-- Name: ix_run_steps_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_run_steps_space_id ON public.run_steps USING btree (space_id);


--
-- Name: ix_run_steps_space_run_index; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_run_steps_space_run_index ON public.run_steps USING btree (space_id, run_id, step_index);


--
-- Name: ix_run_steps_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_run_steps_status ON public.run_steps USING btree (status);


--
-- Name: ix_run_steps_step_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_run_steps_step_type ON public.run_steps USING btree (step_type);


--
-- Name: ix_run_steps_task_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_run_steps_task_id ON public.run_steps USING btree (task_id);


--
-- Name: ix_run_steps_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_run_steps_workspace_id ON public.run_steps USING btree (workspace_id);


--
-- Name: ix_runs_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runs_agent_id ON public.runs USING btree (agent_id);


--
-- Name: ix_runs_agent_version_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runs_agent_version_id ON public.runs USING btree (agent_version_id);


--
-- Name: ix_runs_context_snapshot_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runs_context_snapshot_id ON public.runs USING btree (context_snapshot_id);


--
-- Name: ix_runs_instructed_by_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runs_instructed_by_user_id ON public.runs USING btree (instructed_by_user_id);


--
-- Name: ix_runs_mode; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runs_mode ON public.runs USING btree (mode);


--
-- Name: ix_runs_model_provider_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runs_model_provider_id ON public.runs USING btree (model_provider_id);


--
-- Name: ix_runs_parent_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runs_parent_run_id ON public.runs USING btree (parent_run_id);


--
-- Name: ix_runs_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runs_project_id ON public.runs USING btree (project_id);


--
-- Name: ix_runs_runtime_profile_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runs_runtime_profile_id ON public.runs USING btree (runtime_profile_id);


--
-- Name: ix_runs_run_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runs_run_type ON public.runs USING btree (run_type);


--
-- Name: ix_runs_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runs_session_id ON public.runs USING btree (session_id);


--
-- Name: ix_runs_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runs_space_id ON public.runs USING btree (space_id);


--
-- Name: ix_runs_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runs_status ON public.runs USING btree (status);


--

--
-- Name: ix_runs_trigger_origin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runs_trigger_origin ON public.runs USING btree (trigger_origin);


--
-- Name: ix_runs_working_dir_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runs_working_dir_id ON public.runs USING btree (working_dir_id);


--
-- Name: ix_runs_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runs_workspace_id ON public.runs USING btree (workspace_id);


--
-- Name: ix_runtime_tool_bindings_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_tool_bindings_agent_id ON public.runtime_tool_bindings USING btree (agent_id);


--
-- Name: ix_runtime_tool_bindings_capability_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_tool_bindings_capability_id ON public.runtime_tool_bindings USING btree (capability_id);


--
-- Name: ix_runtime_tool_bindings_enabled; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_tool_bindings_enabled ON public.runtime_tool_bindings USING btree (enabled);


--
-- Name: ix_runtime_tool_bindings_runtime_adapter_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_tool_bindings_runtime_adapter_type ON public.runtime_tool_bindings USING btree (runtime_adapter_type);


--
-- Name: ix_runtime_tool_bindings_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_tool_bindings_space_id ON public.runtime_tool_bindings USING btree (space_id);


--
-- Name: ix_runtime_tool_bindings_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_tool_bindings_workspace_id ON public.runtime_tool_bindings USING btree (workspace_id);


--
-- Name: ix_session_summaries_one_active_per_session; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_session_summaries_one_active_per_session ON public.session_summaries USING btree (session_id) WHERE ((status)::text = 'active'::text);


--
-- Name: ix_session_summaries_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_session_summaries_session_id ON public.session_summaries USING btree (session_id);


--
-- Name: ix_session_summaries_session_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_session_summaries_session_status ON public.session_summaries USING btree (session_id, status);


--
-- Name: ix_session_summaries_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_session_summaries_space_id ON public.session_summaries USING btree (space_id);


--
-- Name: ix_session_summaries_space_session_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_session_summaries_space_session_status ON public.session_summaries USING btree (space_id, session_id, status);


--
-- Name: ix_session_summaries_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_session_summaries_status ON public.session_summaries USING btree (status);


--
-- Name: ix_session_summaries_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_session_summaries_user_id ON public.session_summaries USING btree (user_id);


--
-- Name: ix_sessions_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sessions_agent_id ON public.sessions USING btree (agent_id);


--
-- Name: ix_sessions_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sessions_space_id ON public.sessions USING btree (space_id);


--
-- Name: ix_sessions_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sessions_status ON public.sessions USING btree (status);


--
-- Name: ix_sessions_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sessions_user_id ON public.sessions USING btree (user_id);


--
-- Name: ix_sessions_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sessions_workspace_id ON public.sessions USING btree (workspace_id);


--
-- Name: ix_skill_packages_risk_level; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_skill_packages_risk_level ON public.skill_packages USING btree (risk_level);


--
-- Name: ix_skill_packages_source_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_skill_packages_source_id ON public.skill_packages USING btree (source_id);


--
-- Name: ix_skill_packages_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_skill_packages_space_id ON public.skill_packages USING btree (space_id);


--
-- Name: ix_skill_packages_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_skill_packages_status ON public.skill_packages USING btree (status);


--
-- Name: ix_skill_local_overlays_package_scope; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_skill_local_overlays_package_scope ON public.skill_local_overlays USING btree (space_id, skill_package_id, scope_type, scope_id);


--
-- Name: ix_skill_local_overlays_scope; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_skill_local_overlays_scope ON public.skill_local_overlays USING btree (space_id, scope_type, scope_id);


--
-- Name: ix_skill_local_overlays_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_skill_local_overlays_status ON public.skill_local_overlays USING btree (status);


--
-- Name: uq_skill_local_overlays_active_scope; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_skill_local_overlays_active_scope ON public.skill_local_overlays USING btree (space_id, skill_package_id, scope_type, COALESCE(scope_id, ''::character varying)) WHERE ((status)::text = 'active'::text);


--
-- Name: ix_skill_package_files_kind; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_skill_package_files_kind ON public.skill_package_files USING btree (kind);


--
-- Name: ix_skill_package_files_package_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_skill_package_files_package_id ON public.skill_package_files USING btree (skill_package_id);


--
-- Name: ux_skill_package_files_package_path; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ux_skill_package_files_package_path ON public.skill_package_files USING btree (skill_package_id, path);


--
-- Name: ix_skill_sources_content_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_skill_sources_content_hash ON public.skill_sources USING btree (content_hash);


--
-- Name: ix_skill_sources_source_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_skill_sources_source_type ON public.skill_sources USING btree (source_type);


--
-- Name: ix_skill_sources_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_skill_sources_space_id ON public.skill_sources USING btree (space_id);


--
-- Name: ix_source_connections_connector_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_source_connections_connector_id ON public.source_connections USING btree (connector_id);


--
-- Name: ix_source_connections_credential_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_source_connections_credential_id ON public.source_connections USING btree (credential_id);


--
-- Name: ix_source_connections_deleted_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_source_connections_deleted_at ON public.source_connections USING btree (deleted_at);


--
-- Name: ix_source_connections_owner_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_source_connections_owner_user_id ON public.source_connections USING btree (owner_user_id);


--
-- Name: ix_source_connections_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_source_connections_space_id ON public.source_connections USING btree (space_id);


--
-- Name: ix_source_connections_space_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_source_connections_space_status ON public.source_connections USING btree (space_id, status);


--
-- Name: ix_source_connections_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_source_connections_status ON public.source_connections USING btree (status);


--
-- Name: ix_source_connectors_connector_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_source_connectors_connector_key ON public.source_connectors USING btree (connector_key);


--
-- Name: ix_source_connectors_connector_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_source_connectors_connector_type ON public.source_connectors USING btree (connector_type);


--
-- Name: ix_source_connectors_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_source_connectors_status ON public.source_connectors USING btree (status);


--
-- Name: ix_source_pointers_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_source_pointers_expires_at ON public.source_pointers USING btree (expires_at);


--
-- Name: ix_source_pointers_granted_by_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_source_pointers_granted_by_user_id ON public.source_pointers USING btree (granted_by_user_id);


--
-- Name: ix_source_pointers_owner_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_source_pointers_owner_space_id ON public.source_pointers USING btree (owner_space_id);


--
-- Name: ix_source_pointers_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_source_pointers_source ON public.source_pointers USING btree (source_space_id, source_object_type, source_object_id);


--
-- Name: ix_source_snapshots_artifact_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_source_snapshots_artifact_id ON public.source_snapshots USING btree (artifact_id);


--
-- Name: ix_source_snapshots_connection_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_source_snapshots_connection_id ON public.source_snapshots USING btree (connection_id);


--
-- Name: ix_source_snapshots_content_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_source_snapshots_content_hash ON public.source_snapshots USING btree (content_hash);


--
-- Name: ix_source_snapshots_intake_item_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_source_snapshots_intake_item_id ON public.source_snapshots USING btree (intake_item_id);


--
-- Name: ix_source_snapshots_snapshot_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_source_snapshots_snapshot_type ON public.source_snapshots USING btree (snapshot_type);


--
-- Name: ix_source_snapshots_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_source_snapshots_space_id ON public.source_snapshots USING btree (space_id);


--
-- Name: ix_source_snapshots_space_item; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_source_snapshots_space_item ON public.source_snapshots USING btree (space_id, intake_item_id);


--
-- Name: ix_retrieval_objects_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_retrieval_objects_space_id ON public.retrieval_objects USING btree (space_id);


--
-- Name: ix_retrieval_objects_object; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_retrieval_objects_object ON public.retrieval_objects USING btree (object_type, object_id);


--
-- Name: ix_retrieval_objects_space_object_unique; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_retrieval_objects_space_object_unique ON public.retrieval_objects USING btree (space_id, object_type, object_id);


--
-- Name: ix_retrieval_objects_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_retrieval_objects_status ON public.retrieval_objects USING btree (status);


--
-- Name: ix_retrieval_objects_source_connections; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_retrieval_objects_source_connections ON public.retrieval_objects USING gin (source_connection_ids_json);


--
-- Name: ix_retrieval_aliases_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_retrieval_aliases_space_id ON public.retrieval_aliases USING btree (space_id);


--
-- Name: ix_retrieval_aliases_normalized_alias; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_retrieval_aliases_normalized_alias ON public.retrieval_aliases USING btree (normalized_alias);


--
-- Name: ix_retrieval_aliases_object; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_retrieval_aliases_object ON public.retrieval_aliases USING btree (object_type, object_id);


--
-- Name: ix_retrieval_aliases_unique; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_retrieval_aliases_unique ON public.retrieval_aliases USING btree (space_id, object_type, object_id, normalized_alias, alias_kind);


--
-- Name: ix_retrieval_chunks_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_retrieval_chunks_space_id ON public.retrieval_chunks USING btree (space_id);


--
-- Name: ix_retrieval_chunks_object; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_retrieval_chunks_object ON public.retrieval_chunks USING btree (object_type, object_id);


--
-- Name: ix_retrieval_chunks_object_chunk_unique; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_retrieval_chunks_object_chunk_unique ON public.retrieval_chunks USING btree (retrieval_object_id, chunk_index);


--
-- Name: ix_retrieval_chunks_tsv; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_retrieval_chunks_tsv ON public.retrieval_chunks USING gin (tsv);


--
-- Name: ix_retrieval_chunks_embedding_filter; Type: INDEX; Schema: public; Owner: -
--
-- Filter index for the hybrid vector arm, narrowing by space, object type, and
-- embedding_dimensions before the distance ordering. It also backs the
-- exact-scan fallback used for non-ANN-indexed embedding dimensions.

CREATE INDEX ix_retrieval_chunks_embedding_filter ON public.retrieval_chunks USING btree (space_id, object_type, embedding_dimensions) WHERE embedding IS NOT NULL;


--
-- Name: ix_retrieval_chunks_embedding_hnsw_2560; Type: INDEX; Schema: public; Owner: -
--
-- ANN index for the hybrid vector arm at the default embedding dimension (2560,
-- W5). The `vector` type's HNSW support caps at 2000 dimensions, so the index is
-- built over a `halfvec` cast (HNSW supports halfvec up to 4000 dims). It is
-- PARTIAL on `embedding_dimensions = 2560` so the fixed-dimension cast is valid
-- over the variable-dimension `embedding` column and only the default-dimension
-- rows are indexed. The vector arm emits a matching constant-dimension halfvec
-- cosine query (`embedding::halfvec(2560) <=> $q::halfvec(2560)` with the same
-- predicate) so the planner uses this index; other dimensions fall back to the
-- exact `vector` scan via ix_retrieval_chunks_embedding_filter. Keep this
-- dimension in sync with ANN_HALFVEC_DIMENSIONS in the retrieval engine.

CREATE INDEX ix_retrieval_chunks_embedding_hnsw_2560 ON public.retrieval_chunks USING hnsw ((embedding::public.halfvec(2560)) public.halfvec_cosine_ops) WHERE ((embedding IS NOT NULL) AND (embedding_dimensions = 2560));


--
-- Name: ix_retrieval_chunks_embedding_pending; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_retrieval_chunks_embedding_pending ON public.retrieval_chunks USING btree (space_id, embedding_claimed_at, created_at, id) WHERE embedding IS NULL;


--
-- Name: ix_retrieval_edges_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_retrieval_edges_space_id ON public.retrieval_edges USING btree (space_id);


--
-- Name: ix_retrieval_edges_from; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_retrieval_edges_from ON public.retrieval_edges USING btree (from_object_type, from_object_id);


--
-- Name: ix_retrieval_edges_to; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_retrieval_edges_to ON public.retrieval_edges USING btree (to_object_type, to_object_id);


--
-- Name: ix_retrieval_edges_unique; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_retrieval_edges_unique ON public.retrieval_edges USING btree (space_id, from_object_type, from_object_id, to_object_type, to_object_id, relation_type, edge_origin);


--
-- Name: ix_retrieval_feedback_events_lookup; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_retrieval_feedback_events_lookup ON public.retrieval_feedback_events USING btree (space_id, actor_user_id, surface, query_hash, object_type, object_id, created_at);


--
-- Name: ix_retrieval_feedback_events_object; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_retrieval_feedback_events_object ON public.retrieval_feedback_events USING btree (space_id, object_type, object_id, created_at);


--
-- Name: ix_retrieval_feedback_events_space_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_retrieval_feedback_events_space_created ON public.retrieval_feedback_events USING btree (space_id, created_at);


--
-- Name: ix_space_retrieval_prompts_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_space_retrieval_prompts_space_id ON public.space_retrieval_prompts USING btree (space_id);


--
-- Name: ix_space_invitations_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_space_invitations_space_id ON public.space_invitations USING btree (space_id);


--
-- Name: ix_space_invitations_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_space_invitations_status ON public.space_invitations USING btree (status);


--
-- Name: ix_space_runtime_tool_policies_runtime; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_space_runtime_tool_policies_runtime ON public.space_runtime_tool_policies USING btree (runtime);


--
-- Name: ix_space_runtime_tool_policies_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_space_runtime_tool_policies_space_id ON public.space_runtime_tool_policies USING btree (space_id);


--
-- Name: ix_space_runtime_tool_policies_updated_by_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_space_runtime_tool_policies_updated_by_user_id ON public.space_runtime_tool_policies USING btree (updated_by_user_id);


--
-- Name: ix_space_memberships_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_space_memberships_space_id ON public.space_memberships USING btree (space_id);


--
-- Name: ix_space_memberships_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_space_memberships_user_id ON public.space_memberships USING btree (user_id);


--
-- Name: ix_task_artifacts_artifact_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_task_artifacts_artifact_id ON public.task_artifacts USING btree (artifact_id);


--
-- Name: ix_task_artifacts_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_task_artifacts_run_id ON public.task_artifacts USING btree (run_id);


--
-- Name: ix_task_artifacts_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_task_artifacts_space_id ON public.task_artifacts USING btree (space_id);


--
-- Name: ix_task_artifacts_task_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_task_artifacts_task_id ON public.task_artifacts USING btree (task_id);


--
-- Name: ix_task_dependencies_depends_on_task_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_task_dependencies_depends_on_task_id ON public.task_dependencies USING btree (depends_on_task_id);


--
-- Name: ix_task_dependencies_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_task_dependencies_space_id ON public.task_dependencies USING btree (space_id);


--
-- Name: ix_task_dependencies_task_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_task_dependencies_task_id ON public.task_dependencies USING btree (task_id);


--
-- Name: ix_task_evaluations_run_evaluation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_task_evaluations_run_evaluation_id ON public.task_evaluations USING btree (run_evaluation_id);


--
-- Name: ix_task_evaluations_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_task_evaluations_run_id ON public.task_evaluations USING btree (run_id);


--
-- Name: ix_task_evaluations_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_task_evaluations_space_id ON public.task_evaluations USING btree (space_id);


--
-- Name: ix_task_evaluations_task_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_task_evaluations_task_id ON public.task_evaluations USING btree (task_id);


--
-- Name: ix_task_proposals_proposal_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_task_proposals_proposal_id ON public.task_proposals USING btree (proposal_id);


--
-- Name: ix_task_proposals_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_task_proposals_space_id ON public.task_proposals USING btree (space_id);


--
-- Name: ix_task_proposals_task_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_task_proposals_task_id ON public.task_proposals USING btree (task_id);


--
-- Name: ix_task_runs_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_task_runs_run_id ON public.task_runs USING btree (run_id);


--
-- Name: ix_task_runs_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_task_runs_space_id ON public.task_runs USING btree (space_id);


--
-- Name: ix_task_runs_task_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_task_runs_task_id ON public.task_runs USING btree (task_id);


--
-- Name: ix_tasks_board_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tasks_board_id ON public.tasks USING btree (board_id);


--
-- Name: ix_tasks_column_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tasks_column_id ON public.tasks USING btree (column_id);


--
-- Name: ix_tasks_parent_task_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tasks_parent_task_id ON public.tasks USING btree (parent_task_id);


--
-- Name: ix_tasks_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tasks_space_id ON public.tasks USING btree (space_id);


--
-- Name: ix_tasks_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tasks_project_id ON public.tasks USING btree (project_id);


--
-- Name: ix_tasks_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tasks_workspace_id ON public.tasks USING btree (workspace_id);


--
-- Name: ix_user_sessions_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_user_sessions_user_id ON public.user_sessions USING btree (user_id);


--
-- Name: ix_users_email; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_users_email ON public.users USING btree (email);


--
-- Name: ix_users_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_users_status ON public.users USING btree (status);


--
-- Name: ix_validation_recipes_enabled; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_validation_recipes_enabled ON public.validation_recipes USING btree (enabled);


--
-- Name: ix_validation_recipes_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_validation_recipes_space_id ON public.validation_recipes USING btree (space_id);


--
-- Name: ix_validation_recipes_task_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_validation_recipes_task_type ON public.validation_recipes USING btree (task_type);


--
-- Name: ix_validation_recipes_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_validation_recipes_workspace_id ON public.validation_recipes USING btree (workspace_id);


--
-- Name: ix_working_dirs_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_working_dirs_project_id ON public.working_dirs USING btree (project_id);


--
-- Name: ix_working_dirs_project_uniq; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_working_dirs_project_uniq ON public.working_dirs USING btree (project_id) WHERE (project_id IS NOT NULL);


--
-- Name: ix_working_dirs_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_working_dirs_session_id ON public.working_dirs USING btree (session_id);


--
-- Name: ix_working_dirs_session_uniq; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_working_dirs_session_uniq ON public.working_dirs USING btree (session_id) WHERE (session_id IS NOT NULL);


--
-- Name: ix_working_dirs_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_working_dirs_space_id ON public.working_dirs USING btree (space_id);


--
-- Name: ix_working_dirs_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_working_dirs_status ON public.working_dirs USING btree (status);


--
-- Name: ix_workspace_intake_profiles_created_by_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_intake_profiles_created_by_user_id ON public.workspace_intake_profiles USING btree (created_by_user_id);


--
-- Name: ix_workspace_intake_profiles_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_intake_profiles_space_id ON public.workspace_intake_profiles USING btree (space_id);


--
-- Name: ix_workspace_intake_profiles_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_intake_profiles_status ON public.workspace_intake_profiles USING btree (status);


--
-- Name: ix_workspace_intake_profiles_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_intake_profiles_workspace_id ON public.workspace_intake_profiles USING btree (workspace_id);


--
-- Name: ix_workspace_profiles_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_profiles_space_id ON public.workspace_profiles USING btree (space_id);


--
-- Name: ix_workspace_profiles_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_profiles_workspace_id ON public.workspace_profiles USING btree (workspace_id);


--
-- Name: ix_workspace_source_bindings_created_by_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_source_bindings_created_by_user_id ON public.workspace_source_bindings USING btree (created_by_user_id);


--
-- Name: ix_workspace_source_bindings_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_source_bindings_project_id ON public.workspace_source_bindings USING btree (project_id);


--
-- Name: ix_workspace_source_bindings_source_connection_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_source_bindings_source_connection_id ON public.workspace_source_bindings USING btree (source_connection_id);


--
-- Name: ix_workspace_source_bindings_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_source_bindings_space_id ON public.workspace_source_bindings USING btree (space_id);


--
-- Name: ix_workspace_source_bindings_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_source_bindings_status ON public.workspace_source_bindings USING btree (status);


--
-- Name: ix_workspace_source_bindings_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_source_bindings_workspace_id ON public.workspace_source_bindings USING btree (workspace_id);


--
-- Name: ix_workspace_source_bindings_workspace_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_source_bindings_workspace_status ON public.workspace_source_bindings USING btree (workspace_id, status);


--
-- Name: ix_workspaces_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspaces_slug ON public.workspaces USING btree (slug);


--
-- Name: ix_workspaces_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspaces_space_id ON public.workspaces USING btree (space_id);


--
-- Name: ix_workspaces_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspaces_status ON public.workspaces USING btree (status);


--
-- Name: official_plugin_enablements_plugin_space_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX official_plugin_enablements_plugin_space_idx ON public.official_plugin_enablements USING btree (plugin_id, space_id) WHERE (space_id IS NOT NULL);


--
-- Name: official_plugin_enablements_space_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX official_plugin_enablements_space_idx ON public.official_plugin_enablements USING btree (space_id) WHERE (space_id IS NOT NULL);


--
-- Name: official_plugin_enablements_space_unique; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX official_plugin_enablements_space_unique ON public.official_plugin_enablements (plugin_id, space_id) WHERE (space_id IS NOT NULL AND user_id IS NULL);


--
-- Name: official_plugin_enablements_user_unique; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX official_plugin_enablements_user_unique ON public.official_plugin_enablements (plugin_id, user_id) WHERE (space_id IS NULL AND user_id IS NOT NULL);


--
-- Name: official_plugin_events_plugin_space_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX official_plugin_events_plugin_space_idx ON public.official_plugin_events USING btree (plugin_id, space_id, created_at DESC) WHERE (space_id IS NOT NULL);


--
-- Name: official_plugin_events_space_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX official_plugin_events_space_idx ON public.official_plugin_events USING btree (space_id, created_at DESC) WHERE (space_id IS NOT NULL);


--
-- Name: plugin_installs_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX plugin_installs_status_idx ON public.plugin_installs USING btree (status);


--
-- Name: plugin_migrations_plugin_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX plugin_migrations_plugin_id_idx ON public.plugin_migrations USING btree (plugin_id);




--
-- Name: uq_agents_system_assistant_per_space; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_agents_system_assistant_per_space ON public.agents USING btree (space_id) WHERE (((agent_kind)::text = 'system_assistant'::text) AND ((status)::text = 'active'::text));

-- Name: uq_agents_system_evolver_per_space; Type: INDEX; Schema: public; Owner: -

CREATE UNIQUE INDEX uq_agents_system_evolver_per_space ON public.agents USING btree (space_id) WHERE (((agent_kind)::text = 'system_evolver'::text) AND ((status)::text = 'active'::text));


--
-- Name: uq_agent_runtime_profiles_default_per_agent; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_agent_runtime_profiles_default_per_agent ON public.agent_runtime_profiles USING btree (agent_id) WHERE (is_default = true);


--
-- Name: uq_intake_items_active_canonical_uri; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_intake_items_active_canonical_uri ON public.intake_items USING btree (space_id, canonical_uri) WHERE ((canonical_uri IS NOT NULL) AND (deleted_at IS NULL));


--
-- Name: uq_intake_items_active_source_uri; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_intake_items_active_source_uri ON public.intake_items USING btree (space_id, source_uri) WHERE ((source_uri IS NOT NULL) AND (deleted_at IS NULL));


--
-- Name: uq_source_connections_active_endpoint; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_source_connections_active_endpoint ON public.source_connections USING btree (space_id, connector_id, endpoint_url) WHERE ((endpoint_url IS NOT NULL) AND (deleted_at IS NULL) AND ((status)::text <> 'archived'::text));


--
-- Name: activity_records activity_records_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_records
    ADD CONSTRAINT activity_records_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id);


--
-- Name: activity_records activity_records_owner_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_records
    ADD CONSTRAINT activity_records_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES public.users(id);


--
-- Name: activity_records activity_records_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_records
    ADD CONSTRAINT activity_records_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.sessions(id);


--
-- Name: activity_records activity_records_source_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_records
    ADD CONSTRAINT activity_records_source_run_id_fkey FOREIGN KEY (source_run_id) REFERENCES public.runs(id);


--
-- Name: activity_records activity_records_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_records
    ADD CONSTRAINT activity_records_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: activity_records activity_records_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_records
    ADD CONSTRAINT activity_records_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: activity_records activity_records_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_records
    ADD CONSTRAINT activity_records_workspace_id_fkey FOREIGN KEY (space_id, workspace_id) REFERENCES public.workspaces(space_id, id);


--
-- Name: actors actors_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.actors
    ADD CONSTRAINT actors_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id);


--
-- Name: actors actors_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.actors
    ADD CONSTRAINT actors_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: actors actors_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.actors
    ADD CONSTRAINT actors_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);




--
-- Name: agent_versions agent_versions_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_versions
    ADD CONSTRAINT agent_versions_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id);


--
-- Name: agent_versions agent_versions_model_provider_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_versions
    ADD CONSTRAINT agent_versions_model_provider_id_fkey FOREIGN KEY (model_provider_id) REFERENCES public.model_providers(id);


--
-- Name: agent_versions agent_versions_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_versions
    ADD CONSTRAINT agent_versions_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: agent_runtime_profiles agent_runtime_profiles_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runtime_profiles
    ADD CONSTRAINT agent_runtime_profiles_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE CASCADE;


--
-- Name: agent_runtime_profiles agent_runtime_profiles_credential_profile_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runtime_profiles
    ADD CONSTRAINT agent_runtime_profiles_credential_profile_id_fkey FOREIGN KEY (credential_profile_id) REFERENCES public.cli_credential_profiles(id);


--
-- Name: agent_runtime_profiles agent_runtime_profiles_model_provider_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runtime_profiles
    ADD CONSTRAINT agent_runtime_profiles_model_provider_id_fkey FOREIGN KEY (model_provider_id) REFERENCES public.model_providers(id);


--
-- Name: agent_runtime_profiles agent_runtime_profiles_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runtime_profiles
    ADD CONSTRAINT agent_runtime_profiles_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id) ON DELETE CASCADE;


--
-- Name: agents agents_owner_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agents
    ADD CONSTRAINT agents_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES public.users(id);


--
-- Name: agents agents_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agents
    ADD CONSTRAINT agents_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: artifacts artifacts_owner_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES public.users(id);


--
-- Name: artifacts artifacts_proposal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_proposal_id_fkey FOREIGN KEY (proposal_id) REFERENCES public.proposals(id);


--
-- Name: artifacts artifacts_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.runs(id);


--
-- Name: artifacts artifacts_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: artifacts artifacts_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_workspace_id_fkey FOREIGN KEY (space_id, workspace_id) REFERENCES public.workspaces(space_id, id);


--
-- Name: context_artifact_revocations context_artifact_revocations_artifact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.context_artifact_revocations
    ADD CONSTRAINT context_artifact_revocations_artifact_id_fkey FOREIGN KEY (artifact_id) REFERENCES public.artifacts(id);


--
-- Name: context_artifact_revocations context_artifact_revocations_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.context_artifact_revocations
    ADD CONSTRAINT context_artifact_revocations_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id);


--
-- Name: context_artifact_revocations context_artifact_revocations_deleted_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.context_artifact_revocations
    ADD CONSTRAINT context_artifact_revocations_deleted_by_user_id_fkey FOREIGN KEY (deleted_by_user_id) REFERENCES public.users(id);


--
-- Name: context_artifact_revocations context_artifact_revocations_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.context_artifact_revocations
    ADD CONSTRAINT context_artifact_revocations_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: auth_accounts auth_accounts_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_accounts
    ADD CONSTRAINT auth_accounts_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: automation_credential_grants automation_credential_grants_automation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automation_credential_grants
    ADD CONSTRAINT automation_credential_grants_automation_id_fkey FOREIGN KEY (automation_id) REFERENCES public.automations(id);


--
-- Name: automation_credential_grants automation_credential_grants_granted_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automation_credential_grants
    ADD CONSTRAINT automation_credential_grants_granted_by_user_id_fkey FOREIGN KEY (granted_by_user_id) REFERENCES public.users(id);


--
-- Name: automation_credential_grants automation_credential_grants_revoked_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automation_credential_grants
    ADD CONSTRAINT automation_credential_grants_revoked_by_user_id_fkey FOREIGN KEY (revoked_by_user_id) REFERENCES public.users(id);


--
-- Name: automation_credential_grants automation_credential_grants_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automation_credential_grants
    ADD CONSTRAINT automation_credential_grants_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: automation_runs automation_runs_automation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automation_runs
    ADD CONSTRAINT automation_runs_automation_id_fkey FOREIGN KEY (automation_id) REFERENCES public.automations(id);


--
-- Name: automation_runs automation_runs_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automation_runs
    ADD CONSTRAINT automation_runs_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.runs(id);


--
-- Name: automation_runs automation_runs_triggered_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automation_runs
    ADD CONSTRAINT automation_runs_triggered_by_user_id_fkey FOREIGN KEY (triggered_by_user_id) REFERENCES public.users(id);


--
-- Name: automations automations_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automations
    ADD CONSTRAINT automations_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id);


--
-- Name: automations automations_owner_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automations
    ADD CONSTRAINT automations_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES public.users(id);


--
-- Name: automations automations_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automations
    ADD CONSTRAINT automations_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: automations automations_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automations
    ADD CONSTRAINT automations_workspace_id_fkey FOREIGN KEY (space_id, workspace_id) REFERENCES public.workspaces(space_id, id);


--
-- Name: board_columns board_columns_board_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.board_columns
    ADD CONSTRAINT board_columns_board_id_fkey FOREIGN KEY (board_id) REFERENCES public.boards(id);


--
-- Name: board_columns board_columns_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.board_columns
    ADD CONSTRAINT board_columns_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: boards boards_created_by_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.boards
    ADD CONSTRAINT boards_created_by_agent_id_fkey FOREIGN KEY (created_by_agent_id) REFERENCES public.agents(id);


--
-- Name: boards boards_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.boards
    ADD CONSTRAINT boards_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id);


--
-- Name: boards boards_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.boards
    ADD CONSTRAINT boards_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: boards boards_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.boards
    ADD CONSTRAINT boards_workspace_id_fkey FOREIGN KEY (space_id, workspace_id) REFERENCES public.workspaces(space_id, id);


--
-- Name: boards boards_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.boards
    ADD CONSTRAINT boards_project_id_fkey FOREIGN KEY (space_id, project_id) REFERENCES public.projects(space_id, id) ON DELETE SET NULL (project_id);


--
-- Name: capability_enablements capability_enablements_capability_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.capability_enablements
    ADD CONSTRAINT capability_enablements_capability_version_id_fkey FOREIGN KEY (capability_version_id) REFERENCES public.capability_versions(id);


--
-- Name: capability_overlays capability_overlays_proposal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.capability_overlays
    ADD CONSTRAINT capability_overlays_proposal_id_fkey FOREIGN KEY (proposal_id) REFERENCES public.proposals(id);


--
-- Name: capability_runtime_bindings capability_runtime_bindings_capability_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.capability_runtime_bindings
    ADD CONSTRAINT capability_runtime_bindings_capability_version_id_fkey FOREIGN KEY (capability_version_id) REFERENCES public.capability_versions(id);


--
-- Name: capability_versions capability_versions_proposal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.capability_versions
    ADD CONSTRAINT capability_versions_proposal_id_fkey FOREIGN KEY (proposal_id) REFERENCES public.proposals(id);


--
-- Name: card_review_states card_review_states_card_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.card_review_states
    ADD CONSTRAINT card_review_states_card_id_fkey FOREIGN KEY (card_id) REFERENCES public.cards(id);


--
-- Name: card_review_states card_review_states_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.card_review_states
    ADD CONSTRAINT card_review_states_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: card_reviews card_reviews_card_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.card_reviews
    ADD CONSTRAINT card_reviews_card_id_fkey FOREIGN KEY (card_id) REFERENCES public.cards(id);


--
-- Name: card_reviews card_reviews_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.card_reviews
    ADD CONSTRAINT card_reviews_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: cards cards_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cards
    ADD CONSTRAINT cards_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id);


--
-- Name: cards cards_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cards
    ADD CONSTRAINT cards_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: cli_credential_events cli_credential_events_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cli_credential_events
    ADD CONSTRAINT cli_credential_events_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.runs(id);


--
-- Name: cli_credential_events cli_credential_events_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cli_credential_events
    ADD CONSTRAINT cli_credential_events_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: cli_credential_profiles cli_credential_profiles_owner_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cli_credential_profiles
    ADD CONSTRAINT cli_credential_profiles_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: cli_credential_space_grants cli_credential_space_grants_granted_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cli_credential_space_grants
    ADD CONSTRAINT cli_credential_space_grants_granted_by_user_id_fkey FOREIGN KEY (granted_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: cli_credential_space_grants cli_credential_space_grants_network_profile_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cli_credential_space_grants
    ADD CONSTRAINT cli_credential_space_grants_network_profile_id_fkey FOREIGN KEY (network_profile_id) REFERENCES public.network_profiles(id) ON DELETE SET NULL;


--
-- Name: cli_credential_space_grants cli_credential_space_grants_owner_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cli_credential_space_grants
    ADD CONSTRAINT cli_credential_space_grants_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: cli_credential_space_grants cli_credential_space_grants_profile_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cli_credential_space_grants
    ADD CONSTRAINT cli_credential_space_grants_profile_id_fkey FOREIGN KEY (profile_id) REFERENCES public.cli_credential_profiles(id) ON DELETE CASCADE;


--
-- Name: cli_credential_space_grants cli_credential_space_grants_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cli_credential_space_grants
    ADD CONSTRAINT cli_credential_space_grants_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id) ON DELETE CASCADE;


--
-- Name: context_digests context_digests_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.context_digests
    ADD CONSTRAINT context_digests_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: context_profiles context_profiles_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.context_profiles
    ADD CONSTRAINT context_profiles_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id);


--
-- Name: context_profiles context_profiles_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.context_profiles
    ADD CONSTRAINT context_profiles_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: context_snapshot_items context_snapshot_items_context_snapshot_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.context_snapshot_items
    ADD CONSTRAINT context_snapshot_items_context_snapshot_id_fkey FOREIGN KEY (context_snapshot_id) REFERENCES public.context_snapshots(id);


--
-- Name: context_snapshots context_snapshots_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.context_snapshots
    ADD CONSTRAINT context_snapshots_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: credentials credentials_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credentials
    ADD CONSTRAINT credentials_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: credentials credentials_owner_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credentials
    ADD CONSTRAINT credentials_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: scheduler_tasks scheduler_tasks_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduler_tasks
    ADD CONSTRAINT scheduler_tasks_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: scheduler_tasks scheduler_tasks_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduler_tasks
    ADD CONSTRAINT scheduler_tasks_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);




--
-- Name: evidence_links evidence_links_created_by_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evidence_links
    ADD CONSTRAINT evidence_links_created_by_agent_id_fkey FOREIGN KEY (created_by_agent_id) REFERENCES public.agents(id);


--
-- Name: evidence_links evidence_links_created_by_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evidence_links
    ADD CONSTRAINT evidence_links_created_by_run_id_fkey FOREIGN KEY (created_by_run_id) REFERENCES public.runs(id);


--
-- Name: evidence_links evidence_links_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evidence_links
    ADD CONSTRAINT evidence_links_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id);


--
-- Name: evidence_links evidence_links_evidence_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evidence_links
    ADD CONSTRAINT evidence_links_evidence_id_fkey FOREIGN KEY (evidence_id) REFERENCES public.extracted_evidence(id);


--
-- Name: evidence_links evidence_links_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evidence_links
    ADD CONSTRAINT evidence_links_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: evolution_signals evolution_signals_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evolution_signals
    ADD CONSTRAINT evolution_signals_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: evolution_signals evolution_signals_target_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evolution_signals
    ADD CONSTRAINT evolution_signals_target_id_fkey FOREIGN KEY (target_id) REFERENCES public.evolution_targets(id);


--
-- Name: evolution_strategy_assets evolution_strategy_assets_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evolution_strategy_assets
    ADD CONSTRAINT evolution_strategy_assets_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: evolution_experiences evolution_experiences_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evolution_experiences
    ADD CONSTRAINT evolution_experiences_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: evolution_experiences evolution_experiences_strategy_asset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evolution_experiences
    ADD CONSTRAINT evolution_experiences_strategy_asset_id_fkey FOREIGN KEY (strategy_asset_id) REFERENCES public.evolution_strategy_assets(id) ON DELETE SET NULL;


--
-- Name: evolution_experiences evolution_experiences_target_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evolution_experiences
    ADD CONSTRAINT evolution_experiences_target_id_fkey FOREIGN KEY (target_id) REFERENCES public.evolution_targets(id) ON DELETE SET NULL;


--
-- Name: evolution_experiences evolution_experiences_source_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evolution_experiences
    ADD CONSTRAINT evolution_experiences_source_run_id_fkey FOREIGN KEY (source_run_id) REFERENCES public.runs(id) ON DELETE SET NULL;


--
-- Name: evolution_experiences evolution_experiences_source_proposal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evolution_experiences
    ADD CONSTRAINT evolution_experiences_source_proposal_id_fkey FOREIGN KEY (source_proposal_id) REFERENCES public.proposals(id) ON DELETE SET NULL;


--
-- Name: evolution_selector_decisions evolution_selector_decisions_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evolution_selector_decisions
    ADD CONSTRAINT evolution_selector_decisions_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: evolution_selector_decisions evolution_selector_decisions_target_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evolution_selector_decisions
    ADD CONSTRAINT evolution_selector_decisions_target_id_fkey FOREIGN KEY (target_id) REFERENCES public.evolution_targets(id);


--
-- Name: evolution_selector_decisions evolution_selector_decisions_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evolution_selector_decisions
    ADD CONSTRAINT evolution_selector_decisions_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.runs(id) ON DELETE SET NULL;


--
-- Name: evolution_selector_decisions evolution_selector_decisions_selected_strategy_asset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evolution_selector_decisions
    ADD CONSTRAINT evolution_selector_decisions_selected_strategy_asset_id_fkey FOREIGN KEY (selected_strategy_asset_id) REFERENCES public.evolution_strategy_assets(id) ON DELETE SET NULL;


--
-- Name: evolution_targets evolution_targets_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evolution_targets
    ADD CONSTRAINT evolution_targets_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: external_run_records external_run_records_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_run_records
    ADD CONSTRAINT external_run_records_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.runs(id);


--
-- Name: external_run_records external_run_records_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_run_records
    ADD CONSTRAINT external_run_records_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: extracted_evidence extracted_evidence_artifact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.extracted_evidence
    ADD CONSTRAINT extracted_evidence_artifact_id_fkey FOREIGN KEY (artifact_id) REFERENCES public.artifacts(id);


--
-- Name: extracted_evidence extracted_evidence_created_by_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.extracted_evidence
    ADD CONSTRAINT extracted_evidence_created_by_agent_id_fkey FOREIGN KEY (created_by_agent_id) REFERENCES public.agents(id);


--
-- Name: extracted_evidence extracted_evidence_created_by_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.extracted_evidence
    ADD CONSTRAINT extracted_evidence_created_by_run_id_fkey FOREIGN KEY (created_by_run_id) REFERENCES public.runs(id);


--
-- Name: extracted_evidence extracted_evidence_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.extracted_evidence
    ADD CONSTRAINT extracted_evidence_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id);


--
-- Name: extracted_evidence extracted_evidence_extraction_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.extracted_evidence
    ADD CONSTRAINT extracted_evidence_extraction_job_id_fkey FOREIGN KEY (extraction_job_id) REFERENCES public.extraction_jobs(id);


--
-- Name: extracted_evidence extracted_evidence_intake_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.extracted_evidence
    ADD CONSTRAINT extracted_evidence_intake_item_id_fkey FOREIGN KEY (intake_item_id) REFERENCES public.intake_items(id);


--
-- Name: extracted_evidence extracted_evidence_source_snapshot_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.extracted_evidence
    ADD CONSTRAINT extracted_evidence_source_snapshot_id_fkey FOREIGN KEY (source_snapshot_id) REFERENCES public.source_snapshots(id);


--
-- Name: extracted_evidence extracted_evidence_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.extracted_evidence
    ADD CONSTRAINT extracted_evidence_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: extraction_jobs extraction_jobs_connection_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.extraction_jobs
    ADD CONSTRAINT extraction_jobs_connection_id_fkey FOREIGN KEY (connection_id) REFERENCES public.source_connections(id);


--
-- Name: extraction_jobs extraction_jobs_intake_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.extraction_jobs
    ADD CONSTRAINT extraction_jobs_intake_item_id_fkey FOREIGN KEY (intake_item_id) REFERENCES public.intake_items(id);


--
-- Name: extraction_jobs extraction_jobs_source_snapshot_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.extraction_jobs
    ADD CONSTRAINT extraction_jobs_source_snapshot_id_fkey FOREIGN KEY (source_snapshot_id) REFERENCES public.source_snapshots(id);


--
-- Name: extraction_jobs extraction_jobs_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.extraction_jobs
    ADD CONSTRAINT extraction_jobs_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: activity_records fk_activity_records_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_records
    ADD CONSTRAINT fk_activity_records_project_id_projects FOREIGN KEY (space_id, project_id) REFERENCES public.projects(space_id, id) ON DELETE SET NULL (project_id);


--
-- Name: activity_records fk_activity_records_source_task_id_tasks; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_records
    ADD CONSTRAINT fk_activity_records_source_task_id_tasks FOREIGN KEY (source_task_id) REFERENCES public.tasks(id) ON DELETE SET NULL;


--
-- Name: activity_records fk_activity_records_subject_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_records
    ADD CONSTRAINT fk_activity_records_subject_user_id_users FOREIGN KEY (subject_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: agent_versions fk_agent_versions_source_activity_id_activity_records; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_versions
    ADD CONSTRAINT fk_agent_versions_source_activity_id_activity_records FOREIGN KEY (source_activity_id) REFERENCES public.activity_records(id) ON DELETE SET NULL;


--
-- Name: agent_versions fk_agent_versions_source_proposal_id_proposals; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_versions
    ADD CONSTRAINT fk_agent_versions_source_proposal_id_proposals FOREIGN KEY (source_proposal_id) REFERENCES public.proposals(id) ON DELETE SET NULL;


--
-- Name: agents fk_agents_current_version_id_agent_versions; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agents
    ADD CONSTRAINT fk_agents_current_version_id_agent_versions FOREIGN KEY (current_version_id) REFERENCES public.agent_versions(id) ON DELETE SET NULL;


--
-- Name: artifacts fk_artifacts_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT fk_artifacts_project_id_projects FOREIGN KEY (space_id, project_id) REFERENCES public.projects(space_id, id) ON DELETE SET NULL (project_id);


--
-- Name: capability_overlays fk_capability_overlays_base_version_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.capability_overlays
    ADD CONSTRAINT fk_capability_overlays_base_version_id FOREIGN KEY (base_version_id) REFERENCES public.capability_versions(id);


--
-- Name: capability_versions fk_capability_versions_parent_version_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.capability_versions
    ADD CONSTRAINT fk_capability_versions_parent_version_id FOREIGN KEY (parent_version_id) REFERENCES public.capability_versions(id);


--
-- Name: context_snapshots fk_context_snapshots_agent_id_agents; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.context_snapshots
    ADD CONSTRAINT fk_context_snapshots_agent_id_agents FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE SET NULL;


--
-- Name: context_snapshots fk_context_snapshots_run_id_runs; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.context_snapshots
    ADD CONSTRAINT fk_context_snapshots_run_id_runs FOREIGN KEY (run_id) REFERENCES public.runs(id) ON DELETE SET NULL;


--
-- Name: context_snapshots fk_context_snapshots_session_id_sessions; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.context_snapshots
    ADD CONSTRAINT fk_context_snapshots_session_id_sessions FOREIGN KEY (session_id) REFERENCES public.sessions(id) ON DELETE SET NULL;


--
-- Name: evolution_targets fk_evolution_targets_current_version_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evolution_targets
    ADD CONSTRAINT fk_evolution_targets_current_version_id FOREIGN KEY (current_version_id) REFERENCES public.capability_versions(id);


--
-- Name: intake_items fk_intake_items_extracted_artifact_id_artifacts; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.intake_items
    ADD CONSTRAINT fk_intake_items_extracted_artifact_id_artifacts FOREIGN KEY (extracted_artifact_id) REFERENCES public.artifacts(id) ON DELETE SET NULL;


--
-- Name: intake_items fk_intake_items_raw_artifact_id_artifacts; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.intake_items
    ADD CONSTRAINT fk_intake_items_raw_artifact_id_artifacts FOREIGN KEY (raw_artifact_id) REFERENCES public.artifacts(id) ON DELETE SET NULL;


--
-- Name: intake_items fk_intake_items_summary_artifact_id_artifacts; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.intake_items
    ADD CONSTRAINT fk_intake_items_summary_artifact_id_artifacts FOREIGN KEY (summary_artifact_id) REFERENCES public.artifacts(id) ON DELETE SET NULL;


--
-- Name: knowledge_items fk_knowledge_items_redirect_to_item_id_knowledge_items; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_items
    ADD CONSTRAINT fk_knowledge_items_redirect_to_item_id_knowledge_items FOREIGN KEY (redirect_to_item_id, space_id) REFERENCES public.knowledge_items(object_id, space_id) ON DELETE SET NULL (redirect_to_item_id);


--
-- Name: knowledge_items fk_knowledge_items_root_item_id_knowledge_items; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_items
    ADD CONSTRAINT fk_knowledge_items_root_item_id_knowledge_items FOREIGN KEY (root_item_id, space_id) REFERENCES public.knowledge_items(object_id, space_id) ON DELETE SET NULL (root_item_id);


--
-- Name: knowledge_items fk_knowledge_items_supersedes_item_id_knowledge_items; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_items
    ADD CONSTRAINT fk_knowledge_items_supersedes_item_id_knowledge_items FOREIGN KEY (supersedes_item_id, space_id) REFERENCES public.knowledge_items(object_id, space_id) ON DELETE SET NULL (supersedes_item_id);


--
-- Name: memory_entries fk_memory_entries_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_entries
    ADD CONSTRAINT fk_memory_entries_project_id_projects FOREIGN KEY (space_id, project_id) REFERENCES public.projects(space_id, id) ON DELETE SET NULL (project_id);


--
-- Name: memory_entries fk_memory_entries_root_memory_id_memory_entries; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_entries
    ADD CONSTRAINT fk_memory_entries_root_memory_id_memory_entries FOREIGN KEY (root_memory_id) REFERENCES public.memory_entries(id) ON DELETE SET NULL;


--
-- Name: memory_entries fk_memory_entries_supersedes_memory_id_memory_entries; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_entries
    ADD CONSTRAINT fk_memory_entries_supersedes_memory_id_memory_entries FOREIGN KEY (supersedes_memory_id) REFERENCES public.memory_entries(id) ON DELETE SET NULL;


--
-- Name: policies fk_policies_created_from_proposal_id_proposals; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.policies
    ADD CONSTRAINT fk_policies_created_from_proposal_id_proposals FOREIGN KEY (created_from_proposal_id) REFERENCES public.proposals(id) ON DELETE SET NULL;


--
-- Name: policies fk_policies_supersedes_policy_id_policies; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.policies
    ADD CONSTRAINT fk_policies_supersedes_policy_id_policies FOREIGN KEY (supersedes_policy_id) REFERENCES public.policies(id) ON DELETE SET NULL;


--
-- Name: proposals fk_proposals_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.proposals
    ADD CONSTRAINT fk_proposals_project_id_projects FOREIGN KEY (space_id, project_id) REFERENCES public.projects(space_id, id) ON DELETE SET NULL (project_id);


--
-- Name: run_execution_locks fk_run_execution_locks_job_id_jobs; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_execution_locks
    ADD CONSTRAINT fk_run_execution_locks_job_id_jobs FOREIGN KEY (job_id) REFERENCES public.jobs(id) ON DELETE SET NULL;


--
-- Name: run_steps fk_run_steps_task_id_tasks; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_steps
    ADD CONSTRAINT fk_run_steps_task_id_tasks FOREIGN KEY (task_id) REFERENCES public.tasks(id) ON DELETE SET NULL;


--
-- Name: runs fk_runs_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runs
    ADD CONSTRAINT fk_runs_project_id_projects FOREIGN KEY (space_id, project_id) REFERENCES public.projects(space_id, id) ON DELETE SET NULL (project_id);


--
--
-- Name: runs fk_runs_working_dir_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runs
    ADD CONSTRAINT fk_runs_working_dir_id FOREIGN KEY (working_dir_id) REFERENCES public.working_dirs(id);


--
-- Name: session_summaries fk_session_summaries_source_first_message_id_messages; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_summaries
    ADD CONSTRAINT fk_session_summaries_source_first_message_id_messages FOREIGN KEY (source_first_message_id) REFERENCES public.messages(id) ON DELETE SET NULL;


--
-- Name: session_summaries fk_session_summaries_source_last_message_id_messages; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_summaries
    ADD CONSTRAINT fk_session_summaries_source_last_message_id_messages FOREIGN KEY (source_last_message_id) REFERENCES public.messages(id) ON DELETE SET NULL;


--
-- Name: space_invitations fk_space_invitations_invited_by_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.space_invitations
    ADD CONSTRAINT fk_space_invitations_invited_by_user_id_users FOREIGN KEY (invited_by_user_id) REFERENCES public.users(id);


--
-- Name: spaces fk_spaces_created_by_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.spaces
    ADD CONSTRAINT fk_spaces_created_by_user_id_users FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: intake_items intake_items_connection_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.intake_items
    ADD CONSTRAINT intake_items_connection_id_fkey FOREIGN KEY (connection_id) REFERENCES public.source_connections(id);


--
-- Name: intake_items intake_items_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.intake_items
    ADD CONSTRAINT intake_items_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: job_events job_events_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_events
    ADD CONSTRAINT job_events_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.jobs(id);


--
-- Name: jobs jobs_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jobs
    ADD CONSTRAINT jobs_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id);


--
-- Name: jobs jobs_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jobs
    ADD CONSTRAINT jobs_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: jobs jobs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jobs
    ADD CONSTRAINT jobs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: jobs jobs_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jobs
    ADD CONSTRAINT jobs_workspace_id_fkey FOREIGN KEY (space_id, workspace_id) REFERENCES public.workspaces(space_id, id);


--
-- Name: space_objects space_objects_created_by_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.space_objects
    ADD CONSTRAINT space_objects_created_by_agent_id_fkey FOREIGN KEY (created_by_agent_id) REFERENCES public.agents(id);


--
-- Name: space_objects space_objects_created_by_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.space_objects
    ADD CONSTRAINT space_objects_created_by_run_id_fkey FOREIGN KEY (created_by_run_id) REFERENCES public.runs(id);


--
-- Name: space_objects space_objects_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.space_objects
    ADD CONSTRAINT space_objects_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id);


--
-- Name: space_objects space_objects_owner_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.space_objects
    ADD CONSTRAINT space_objects_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES public.users(id);


--
-- Name: space_objects space_objects_primary_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.space_objects
    ADD CONSTRAINT space_objects_primary_project_id_fkey FOREIGN KEY (space_id, primary_project_id) REFERENCES public.projects(space_id, id);


--
-- Name: space_objects space_objects_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.space_objects
    ADD CONSTRAINT space_objects_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: space_objects space_objects_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.space_objects
    ADD CONSTRAINT space_objects_workspace_id_fkey FOREIGN KEY (space_id, workspace_id) REFERENCES public.workspaces(space_id, id);


--
-- Name: space_object_kinds space_object_kinds_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.space_object_kinds
    ADD CONSTRAINT space_object_kinds_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id);


--
-- Name: space_object_kinds space_object_kinds_created_from_proposal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.space_object_kinds
    ADD CONSTRAINT space_object_kinds_created_from_proposal_id_fkey FOREIGN KEY (created_from_proposal_id) REFERENCES public.proposals(id);


--
-- Name: space_object_kinds space_object_kinds_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.space_object_kinds
    ADD CONSTRAINT space_object_kinds_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: space_object_kinds space_object_kinds_updated_from_proposal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.space_object_kinds
    ADD CONSTRAINT space_object_kinds_updated_from_proposal_id_fkey FOREIGN KEY (updated_from_proposal_id) REFERENCES public.proposals(id);


--
-- Name: space_object_kind_relation_hints space_object_kind_relation_hints_endpoint_kind_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.space_object_kind_relation_hints
    ADD CONSTRAINT space_object_kind_relation_hints_endpoint_kind_fkey FOREIGN KEY (endpoint_object_kind_id) REFERENCES public.space_object_kinds(id) ON DELETE CASCADE;


--
-- Name: space_object_kind_relation_hints space_object_kind_relation_hints_object_kind_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.space_object_kind_relation_hints
    ADD CONSTRAINT space_object_kind_relation_hints_object_kind_fkey FOREIGN KEY (object_kind_id) REFERENCES public.space_object_kinds(id) ON DELETE CASCADE;


--
-- Name: space_object_kind_relation_hints space_object_kind_relation_hints_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.space_object_kind_relation_hints
    ADD CONSTRAINT space_object_kind_relation_hints_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);








--
-- Name: knowledge_item_sources knowledge_item_sources_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_item_sources
    ADD CONSTRAINT knowledge_item_sources_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id);


--
-- Name: knowledge_item_sources knowledge_item_sources_knowledge_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_item_sources
    ADD CONSTRAINT knowledge_item_sources_knowledge_item_id_fkey FOREIGN KEY (knowledge_item_id, space_id) REFERENCES public.knowledge_items(object_id, space_id);


--
-- Name: knowledge_item_sources knowledge_item_sources_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_item_sources
    ADD CONSTRAINT knowledge_item_sources_source_id_fkey FOREIGN KEY (source_id, space_id) REFERENCES public.sources(object_id, space_id);


--
-- Name: knowledge_item_sources knowledge_item_sources_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_item_sources
    ADD CONSTRAINT knowledge_item_sources_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: knowledge_items knowledge_items_approved_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_items
    ADD CONSTRAINT knowledge_items_approved_by_user_id_fkey FOREIGN KEY (approved_by_user_id) REFERENCES public.users(id);


--
-- Name: knowledge_items knowledge_items_created_from_proposal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_items
    ADD CONSTRAINT knowledge_items_created_from_proposal_id_fkey FOREIGN KEY (created_from_proposal_id) REFERENCES public.proposals(id);




--
-- Name: knowledge_items knowledge_items_object_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_items
    ADD CONSTRAINT knowledge_items_object_id_fkey FOREIGN KEY (object_id, space_id) REFERENCES public.space_objects(id, space_id) ON DELETE CASCADE;


--
-- Name: knowledge_items knowledge_items_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_items
    ADD CONSTRAINT knowledge_items_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: claims claims_approved_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.claims
    ADD CONSTRAINT claims_approved_by_user_id_fkey FOREIGN KEY (approved_by_user_id) REFERENCES public.users(id);


--
-- Name: claims claims_created_from_proposal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.claims
    ADD CONSTRAINT claims_created_from_proposal_id_fkey FOREIGN KEY (created_from_proposal_id) REFERENCES public.proposals(id);


--
-- Name: claims claims_holder_object_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.claims
    ADD CONSTRAINT claims_holder_object_id_fkey FOREIGN KEY (holder_object_id, space_id) REFERENCES public.space_objects(id, space_id);


--
-- Name: claims claims_object_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.claims
    ADD CONSTRAINT claims_object_id_fkey FOREIGN KEY (object_id, space_id) REFERENCES public.space_objects(id, space_id) ON DELETE CASCADE;


--
-- Name: claims claims_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.claims
    ADD CONSTRAINT claims_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: claims claims_subject_object_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.claims
    ADD CONSTRAINT claims_subject_object_id_fkey FOREIGN KEY (subject_object_id, space_id) REFERENCES public.space_objects(id, space_id);


--
-- Name: claim_sources claim_sources_claim_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.claim_sources
    ADD CONSTRAINT claim_sources_claim_id_fkey FOREIGN KEY (claim_id, space_id) REFERENCES public.claims(object_id, space_id) ON DELETE CASCADE;


--
-- Name: claim_sources claim_sources_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.claim_sources
    ADD CONSTRAINT claim_sources_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id);


--
-- Name: claim_sources claim_sources_source_connection_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.claim_sources
    ADD CONSTRAINT claim_sources_source_connection_id_fkey FOREIGN KEY (source_connection_id, space_id) REFERENCES public.source_connections(id, space_id);


--
-- Name: claim_sources claim_sources_source_object_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.claim_sources
    ADD CONSTRAINT claim_sources_source_object_id_fkey FOREIGN KEY (source_object_id, space_id) REFERENCES public.space_objects(id, space_id);


--
-- Name: claim_sources claim_sources_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.claim_sources
    ADD CONSTRAINT claim_sources_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);








--
-- Name: object_relations object_relations_created_by_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.object_relations
    ADD CONSTRAINT object_relations_created_by_agent_id_fkey FOREIGN KEY (created_by_agent_id) REFERENCES public.agents(id);


--
-- Name: object_relations object_relations_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.object_relations
    ADD CONSTRAINT object_relations_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id);


--
-- Name: object_relations object_relations_from_object_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.object_relations
    ADD CONSTRAINT object_relations_from_object_id_fkey FOREIGN KEY (from_object_id, space_id) REFERENCES public.space_objects(id, space_id);


--
-- Name: object_relations object_relations_source_claim_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.object_relations
    ADD CONSTRAINT object_relations_source_claim_id_fkey FOREIGN KEY (source_claim_id, space_id) REFERENCES public.claims(object_id, space_id);


--
-- Name: object_relations object_relations_source_object_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.object_relations
    ADD CONSTRAINT object_relations_source_object_id_fkey FOREIGN KEY (source_object_id, space_id) REFERENCES public.space_objects(id, space_id);


--
-- Name: object_relations object_relations_source_proposal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.object_relations
    ADD CONSTRAINT object_relations_source_proposal_id_fkey FOREIGN KEY (source_proposal_id) REFERENCES public.proposals(id);


--
-- Name: object_relations object_relations_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.object_relations
    ADD CONSTRAINT object_relations_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: object_relations object_relations_to_object_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.object_relations
    ADD CONSTRAINT object_relations_to_object_id_fkey FOREIGN KEY (to_object_id, space_id) REFERENCES public.space_objects(id, space_id);


--
-- Name: memory_access_logs memory_access_logs_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_access_logs
    ADD CONSTRAINT memory_access_logs_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id);


--
-- Name: memory_access_logs memory_access_logs_memory_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_access_logs
    ADD CONSTRAINT memory_access_logs_memory_id_fkey FOREIGN KEY (memory_id) REFERENCES public.memory_entries(id);


--
-- Name: memory_access_logs memory_access_logs_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_access_logs
    ADD CONSTRAINT memory_access_logs_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.runs(id);


--
-- Name: memory_access_logs memory_access_logs_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_access_logs
    ADD CONSTRAINT memory_access_logs_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: memory_access_logs memory_access_logs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_access_logs
    ADD CONSTRAINT memory_access_logs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: memory_maintenance_jobs memory_maintenance_jobs_last_packet_proposal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_maintenance_jobs
    ADD CONSTRAINT memory_maintenance_jobs_last_packet_proposal_id_fkey FOREIGN KEY (last_packet_proposal_id) REFERENCES public.proposals(id);


--
-- Name: memory_maintenance_jobs memory_maintenance_jobs_last_report_artifact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_maintenance_jobs
    ADD CONSTRAINT memory_maintenance_jobs_last_report_artifact_id_fkey FOREIGN KEY (last_report_artifact_id) REFERENCES public.artifacts(id);


--
-- Name: memory_maintenance_jobs memory_maintenance_jobs_owner_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_maintenance_jobs
    ADD CONSTRAINT memory_maintenance_jobs_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES public.users(id);


--
-- Name: memory_maintenance_jobs memory_maintenance_jobs_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_maintenance_jobs
    ADD CONSTRAINT memory_maintenance_jobs_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id) ON DELETE CASCADE;


--
-- Name: memory_entries memory_entries_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_entries
    ADD CONSTRAINT memory_entries_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id);


--
-- Name: memory_entries memory_entries_created_from_proposal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_entries
    ADD CONSTRAINT memory_entries_created_from_proposal_id_fkey FOREIGN KEY (created_from_proposal_id) REFERENCES public.proposals(id);


--
-- Name: memory_entries memory_entries_owner_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_entries
    ADD CONSTRAINT memory_entries_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES public.users(id);



--
-- Name: memory_entries memory_entries_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_entries
    ADD CONSTRAINT memory_entries_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: memory_entries memory_entries_subject_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_entries
    ADD CONSTRAINT memory_entries_subject_user_id_fkey FOREIGN KEY (subject_user_id) REFERENCES public.users(id);


--
-- Name: memory_entries memory_entries_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_entries
    ADD CONSTRAINT memory_entries_workspace_id_fkey FOREIGN KEY (space_id, workspace_id) REFERENCES public.workspaces(space_id, id);


--
-- Name: memory_relations memory_relations_created_from_proposal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_relations
    ADD CONSTRAINT memory_relations_created_from_proposal_id_fkey FOREIGN KEY (created_from_proposal_id) REFERENCES public.proposals(id);


--
-- Name: memory_relations memory_relations_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_relations
    ADD CONSTRAINT memory_relations_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: messages messages_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.messages
    ADD CONSTRAINT messages_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.sessions(id);


--
-- Name: messages messages_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.messages
    ADD CONSTRAINT messages_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: messages messages_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.messages
    ADD CONSTRAINT messages_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: network_profiles network_profiles_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.network_profiles
    ADD CONSTRAINT network_profiles_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: model_provider_credentials model_provider_credentials_credential_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_provider_credentials
    ADD CONSTRAINT model_provider_credentials_credential_id_fkey FOREIGN KEY (credential_id) REFERENCES public.credentials(id);


--
-- Name: model_provider_credentials model_provider_credentials_provider_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_provider_credentials
    ADD CONSTRAINT model_provider_credentials_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES public.model_providers(id) ON DELETE CASCADE;


--
-- Name: model_provider_credentials model_provider_credentials_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_provider_credentials
    ADD CONSTRAINT model_provider_credentials_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: model_provider_space_grants model_provider_space_grants_granted_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_provider_space_grants
    ADD CONSTRAINT model_provider_space_grants_granted_by_user_id_fkey FOREIGN KEY (granted_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: model_provider_space_grants model_provider_space_grants_network_profile_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_provider_space_grants
    ADD CONSTRAINT model_provider_space_grants_network_profile_id_fkey FOREIGN KEY (network_profile_id) REFERENCES public.network_profiles(id) ON DELETE SET NULL;


--
-- Name: model_provider_space_grants model_provider_space_grants_owner_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_provider_space_grants
    ADD CONSTRAINT model_provider_space_grants_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: model_provider_space_grants model_provider_space_grants_provider_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_provider_space_grants
    ADD CONSTRAINT model_provider_space_grants_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES public.model_providers(id) ON DELETE CASCADE;


--
-- Name: model_provider_space_grants model_provider_space_grants_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_provider_space_grants
    ADD CONSTRAINT model_provider_space_grants_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id) ON DELETE CASCADE;


--
-- Name: model_providers model_providers_credential_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_providers
    ADD CONSTRAINT model_providers_credential_id_fkey FOREIGN KEY (credential_id) REFERENCES public.credentials(id);


--
-- Name: model_providers model_providers_network_profile_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_providers
    ADD CONSTRAINT model_providers_network_profile_id_fkey FOREIGN KEY (network_profile_id) REFERENCES public.network_profiles(id) ON DELETE SET NULL;


--
-- Name: model_providers model_providers_owner_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_providers
    ADD CONSTRAINT model_providers_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: model_providers model_providers_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_providers
    ADD CONSTRAINT model_providers_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: note_collection_items note_collection_items_collection_id_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.note_collection_items
    ADD CONSTRAINT note_collection_items_collection_id_space_id_fkey FOREIGN KEY (collection_id, space_id) REFERENCES public.note_collections(id, space_id) ON DELETE CASCADE;


--
-- Name: note_collection_items note_collection_items_note_id_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.note_collection_items
    ADD CONSTRAINT note_collection_items_note_id_space_id_fkey FOREIGN KEY (note_id, space_id) REFERENCES public.notes(object_id, space_id) ON DELETE CASCADE;


--
-- Name: note_collections note_collections_parent_id_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.note_collections
    ADD CONSTRAINT note_collections_parent_id_space_id_fkey FOREIGN KEY (parent_id, space_id) REFERENCES public.note_collections(id, space_id) ON DELETE SET NULL (parent_id);


--
-- Name: note_collection_items note_collection_items_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.note_collection_items
    ADD CONSTRAINT note_collection_items_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: note_collections note_collections_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.note_collections
    ADD CONSTRAINT note_collections_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: notes notes_created_from_activity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notes
    ADD CONSTRAINT notes_created_from_activity_id_fkey FOREIGN KEY (created_from_activity_id) REFERENCES public.activity_records(id);


--
-- Name: notes notes_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notes
    ADD CONSTRAINT notes_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: notes notes_object_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notes
    ADD CONSTRAINT notes_object_id_fkey FOREIGN KEY (object_id, space_id) REFERENCES public.space_objects(id, space_id) ON DELETE CASCADE;


--
-- Name: note_links note_links_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.note_links
    ADD CONSTRAINT note_links_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id);


--
-- Name: note_links note_links_from_object_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.note_links
    ADD CONSTRAINT note_links_from_object_id_fkey FOREIGN KEY (from_object_id, space_id) REFERENCES public.space_objects(id, space_id) ON DELETE CASCADE;


--
-- Name: note_links note_links_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.note_links
    ADD CONSTRAINT note_links_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: note_links note_links_to_object_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.note_links
    ADD CONSTRAINT note_links_to_object_id_fkey FOREIGN KEY (to_object_id, space_id) REFERENCES public.space_objects(id, space_id) ON DELETE CASCADE;


--
-- Name: participation_records participation_records_personal_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.participation_records
    ADD CONSTRAINT participation_records_personal_space_id_fkey FOREIGN KEY (personal_space_id) REFERENCES public.spaces(id);


--
-- Name: participation_records participation_records_source_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.participation_records
    ADD CONSTRAINT participation_records_source_space_id_fkey FOREIGN KEY (source_space_id) REFERENCES public.spaces(id);


--
-- Name: participation_records participation_records_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.participation_records
    ADD CONSTRAINT participation_records_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: personal_memory_grant_events personal_memory_grant_events_actor_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.personal_memory_grant_events
    ADD CONSTRAINT personal_memory_grant_events_actor_user_id_fkey FOREIGN KEY (actor_user_id) REFERENCES public.users(id);


--
-- Name: personal_memory_grant_events personal_memory_grant_events_grant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.personal_memory_grant_events
    ADD CONSTRAINT personal_memory_grant_events_grant_id_fkey FOREIGN KEY (grant_id) REFERENCES public.personal_memory_grants(id);


--
-- Name: personal_memory_grant_events personal_memory_grant_events_proposal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.personal_memory_grant_events
    ADD CONSTRAINT personal_memory_grant_events_proposal_id_fkey FOREIGN KEY (proposal_id) REFERENCES public.proposals(id);


--
-- Name: personal_memory_grant_events personal_memory_grant_events_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.personal_memory_grant_events
    ADD CONSTRAINT personal_memory_grant_events_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.runs(id);


--
-- Name: personal_memory_grant_events personal_memory_grant_events_source_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.personal_memory_grant_events
    ADD CONSTRAINT personal_memory_grant_events_source_space_id_fkey FOREIGN KEY (source_space_id) REFERENCES public.spaces(id);


--
-- Name: personal_memory_grant_events personal_memory_grant_events_target_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.personal_memory_grant_events
    ADD CONSTRAINT personal_memory_grant_events_target_space_id_fkey FOREIGN KEY (target_space_id) REFERENCES public.spaces(id);


--
-- Name: personal_memory_grants personal_memory_grants_granting_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.personal_memory_grants
    ADD CONSTRAINT personal_memory_grants_granting_user_id_fkey FOREIGN KEY (granting_user_id) REFERENCES public.users(id);


--
-- Name: personal_memory_grants personal_memory_grants_personal_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.personal_memory_grants
    ADD CONSTRAINT personal_memory_grants_personal_space_id_fkey FOREIGN KEY (personal_space_id) REFERENCES public.spaces(id);


--
-- Name: personal_memory_grants personal_memory_grants_target_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.personal_memory_grants
    ADD CONSTRAINT personal_memory_grants_target_agent_id_fkey FOREIGN KEY (target_agent_id) REFERENCES public.agents(id);


--
-- Name: personal_memory_grants personal_memory_grants_target_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.personal_memory_grants
    ADD CONSTRAINT personal_memory_grants_target_run_id_fkey FOREIGN KEY (target_run_id) REFERENCES public.runs(id);


--
-- Name: personal_memory_grants personal_memory_grants_target_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.personal_memory_grants
    ADD CONSTRAINT personal_memory_grants_target_space_id_fkey FOREIGN KEY (target_space_id) REFERENCES public.spaces(id);


--
-- Name: policies policies_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.policies
    ADD CONSTRAINT policies_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: project_workspaces project_workspaces_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_workspaces
    ADD CONSTRAINT project_workspaces_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: project_workspaces project_workspaces_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
-- Composite FK proves project lives in the same space as this link row.
--

ALTER TABLE ONLY public.project_workspaces
    ADD CONSTRAINT project_workspaces_project_id_fkey FOREIGN KEY (space_id, project_id) REFERENCES public.projects(space_id, id);


--
-- Name: project_workspaces project_workspaces_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
-- Composite FK proves workspace lives in the same space as this link row.
--

ALTER TABLE ONLY public.project_workspaces
    ADD CONSTRAINT project_workspaces_workspace_id_fkey FOREIGN KEY (space_id, workspace_id) REFERENCES public.workspaces(space_id, id);


--
-- Name: project_public_summaries project_public_summaries_generated_by_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_public_summaries
    ADD CONSTRAINT project_public_summaries_generated_by_run_id_fkey FOREIGN KEY (generated_by_run_id) REFERENCES public.runs(id) ON DELETE SET NULL;


--
-- Name: project_public_summaries project_public_summaries_space_project_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
-- Composite FK ties the summary's (space_id, project_id) to a single project
-- row, so a summary can never be associated with a project in another space.

ALTER TABLE ONLY public.project_public_summaries
    ADD CONSTRAINT project_public_summaries_space_project_fkey FOREIGN KEY (space_id, project_id) REFERENCES public.projects(space_id, id) ON DELETE CASCADE;


--
-- Name: project_public_summaries project_public_summaries_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_public_summaries
    ADD CONSTRAINT project_public_summaries_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: project_public_summaries project_public_summaries_updated_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_public_summaries
    ADD CONSTRAINT project_public_summaries_updated_by_user_id_fkey FOREIGN KEY (updated_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: projects projects_owner_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES public.users(id);


--
-- Name: projects projects_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: project_members project_members_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_members
    ADD CONSTRAINT project_members_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: project_members project_members_space_project_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
-- Composite FK ties the membership's (space_id, project_id) to a single project
-- row, so a project memory ACL row can never cross a space boundary.

ALTER TABLE ONLY public.project_members
    ADD CONSTRAINT project_members_space_project_fkey FOREIGN KEY (space_id, project_id) REFERENCES public.projects(space_id, id) ON DELETE CASCADE;


--
-- Name: project_members project_members_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_members
    ADD CONSTRAINT project_members_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: project_members project_members_space_membership_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_members
    ADD CONSTRAINT project_members_space_membership_fkey FOREIGN KEY (space_id, user_id) REFERENCES public.space_memberships(space_id, user_id) ON DELETE CASCADE;


--
-- Name: proposal_approvals proposal_approvals_approver_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.proposal_approvals
    ADD CONSTRAINT proposal_approvals_approver_user_id_fkey FOREIGN KEY (approver_user_id) REFERENCES public.users(id);


--
-- Name: proposal_approvals proposal_approvals_grant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.proposal_approvals
    ADD CONSTRAINT proposal_approvals_grant_id_fkey FOREIGN KEY (grant_id) REFERENCES public.personal_memory_grants(id);


--
-- Name: proposal_approvals proposal_approvals_proposal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.proposal_approvals
    ADD CONSTRAINT proposal_approvals_proposal_id_fkey FOREIGN KEY (proposal_id) REFERENCES public.proposals(id);


--
-- Name: proposal_approvals proposal_approvals_target_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.proposal_approvals
    ADD CONSTRAINT proposal_approvals_target_space_id_fkey FOREIGN KEY (target_space_id) REFERENCES public.spaces(id);


--
-- Name: proposals proposals_created_by_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.proposals
    ADD CONSTRAINT proposals_created_by_agent_id_fkey FOREIGN KEY (created_by_agent_id) REFERENCES public.agents(id);


--
-- Name: proposals proposals_created_by_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.proposals
    ADD CONSTRAINT proposals_created_by_run_id_fkey FOREIGN KEY (created_by_run_id) REFERENCES public.runs(id);


--
-- Name: proposals proposals_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.proposals
    ADD CONSTRAINT proposals_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id);


--
-- Name: proposals proposals_reviewed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.proposals
    ADD CONSTRAINT proposals_reviewed_by_fkey FOREIGN KEY (reviewed_by) REFERENCES public.users(id);


--
-- Name: proposals proposals_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.proposals
    ADD CONSTRAINT proposals_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: proposals proposals_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.proposals
    ADD CONSTRAINT proposals_workspace_id_fkey FOREIGN KEY (space_id, workspace_id) REFERENCES public.workspaces(space_id, id);


--
-- Name: provenance_links provenance_links_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.provenance_links
    ADD CONSTRAINT provenance_links_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: provider_task_policies provider_task_policies_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.provider_task_policies
    ADD CONSTRAINT provider_task_policies_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: run_evaluations run_evaluations_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_evaluations
    ADD CONSTRAINT run_evaluations_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.runs(id);


--
-- Name: run_evaluations run_evaluations_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_evaluations
    ADD CONSTRAINT run_evaluations_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: run_events run_events_actor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_events
    ADD CONSTRAINT run_events_actor_id_fkey FOREIGN KEY (actor_id) REFERENCES public.actors(id);


--
-- Name: run_events run_events_artifact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_events
    ADD CONSTRAINT run_events_artifact_id_fkey FOREIGN KEY (artifact_id) REFERENCES public.artifacts(id);


--
-- Name: run_events run_events_proposal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_events
    ADD CONSTRAINT run_events_proposal_id_fkey FOREIGN KEY (proposal_id) REFERENCES public.proposals(id);


--
-- Name: run_events run_events_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_events
    ADD CONSTRAINT run_events_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.runs(id);


--
-- Name: run_events run_events_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_events
    ADD CONSTRAINT run_events_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: run_events run_events_step_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_events
    ADD CONSTRAINT run_events_step_id_fkey FOREIGN KEY (step_id) REFERENCES public.run_steps(id);


--
-- Name: run_events run_events_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_events
    ADD CONSTRAINT run_events_workspace_id_fkey FOREIGN KEY (space_id, workspace_id) REFERENCES public.workspaces(space_id, id);


--
-- Name: run_execution_locks run_execution_locks_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_execution_locks
    ADD CONSTRAINT run_execution_locks_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.runs(id);


--
-- Name: run_finalizations run_finalizations_run_evaluation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_finalizations
    ADD CONSTRAINT run_finalizations_run_evaluation_id_fkey FOREIGN KEY (run_evaluation_id) REFERENCES public.run_evaluations(id);


--
-- Name: run_finalizations run_finalizations_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_finalizations
    ADD CONSTRAINT run_finalizations_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.runs(id);


--
-- Name: run_finalizations run_finalizations_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_finalizations
    ADD CONSTRAINT run_finalizations_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: run_finalizations run_finalizations_task_evaluation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_finalizations
    ADD CONSTRAINT run_finalizations_task_evaluation_id_fkey FOREIGN KEY (task_evaluation_id) REFERENCES public.task_evaluations(id);


--
-- Name: run_reflections run_reflections_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_reflections
    ADD CONSTRAINT run_reflections_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.runs(id);


--
-- Name: run_reflections run_reflections_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_reflections
    ADD CONSTRAINT run_reflections_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: run_steps run_steps_actor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_steps
    ADD CONSTRAINT run_steps_actor_id_fkey FOREIGN KEY (actor_id) REFERENCES public.actors(id);


--
-- Name: run_steps run_steps_artifact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_steps
    ADD CONSTRAINT run_steps_artifact_id_fkey FOREIGN KEY (artifact_id) REFERENCES public.artifacts(id);


--
-- Name: run_steps run_steps_parent_step_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_steps
    ADD CONSTRAINT run_steps_parent_step_id_fkey FOREIGN KEY (parent_step_id) REFERENCES public.run_steps(id);


--
-- Name: run_steps run_steps_proposal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_steps
    ADD CONSTRAINT run_steps_proposal_id_fkey FOREIGN KEY (proposal_id) REFERENCES public.proposals(id);


--
-- Name: run_steps run_steps_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_steps
    ADD CONSTRAINT run_steps_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.runs(id);


--
-- Name: run_steps run_steps_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_steps
    ADD CONSTRAINT run_steps_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.sessions(id);


--
-- Name: run_steps run_steps_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_steps
    ADD CONSTRAINT run_steps_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: run_steps run_steps_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_steps
    ADD CONSTRAINT run_steps_workspace_id_fkey FOREIGN KEY (space_id, workspace_id) REFERENCES public.workspaces(space_id, id);


--
-- Name: runs runs_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runs
    ADD CONSTRAINT runs_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id);


--
-- Name: runs runs_agent_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runs
    ADD CONSTRAINT runs_agent_version_id_fkey FOREIGN KEY (agent_version_id) REFERENCES public.agent_versions(id);


--
-- Name: runs runs_context_snapshot_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runs
    ADD CONSTRAINT runs_context_snapshot_id_fkey FOREIGN KEY (context_snapshot_id) REFERENCES public.context_snapshots(id);


--
-- Name: runs runs_instructed_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runs
    ADD CONSTRAINT runs_instructed_by_user_id_fkey FOREIGN KEY (instructed_by_user_id) REFERENCES public.users(id);


--
-- Name: runs runs_model_provider_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runs
    ADD CONSTRAINT runs_model_provider_id_fkey FOREIGN KEY (model_provider_id) REFERENCES public.model_providers(id);


--
-- Name: runs runs_runtime_profile_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runs
    ADD CONSTRAINT runs_runtime_profile_id_fkey FOREIGN KEY (runtime_profile_id) REFERENCES public.agent_runtime_profiles(id);


--
-- Name: runs runs_parent_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runs
    ADD CONSTRAINT runs_parent_run_id_fkey FOREIGN KEY (parent_run_id) REFERENCES public.runs(id);


--
-- Name: runs runs_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runs
    ADD CONSTRAINT runs_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.sessions(id);


--
-- Name: runs runs_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runs
    ADD CONSTRAINT runs_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: runs runs_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runs
    ADD CONSTRAINT runs_workspace_id_fkey FOREIGN KEY (space_id, workspace_id) REFERENCES public.workspaces(space_id, id);


--
-- Name: runtime_tool_bindings runtime_tool_bindings_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_tool_bindings
    ADD CONSTRAINT runtime_tool_bindings_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id);


--
-- Name: runtime_tool_bindings runtime_tool_bindings_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_tool_bindings
    ADD CONSTRAINT runtime_tool_bindings_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: runtime_tool_bindings runtime_tool_bindings_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_tool_bindings
    ADD CONSTRAINT runtime_tool_bindings_workspace_id_fkey FOREIGN KEY (space_id, workspace_id) REFERENCES public.workspaces(space_id, id);


--
-- Name: session_summaries session_summaries_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_summaries
    ADD CONSTRAINT session_summaries_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.sessions(id);


--
-- Name: session_summaries session_summaries_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_summaries
    ADD CONSTRAINT session_summaries_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: session_summaries session_summaries_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_summaries
    ADD CONSTRAINT session_summaries_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: sessions sessions_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT sessions_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id);


--
-- Name: sessions sessions_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT sessions_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: sessions sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: sessions sessions_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT sessions_workspace_id_fkey FOREIGN KEY (space_id, workspace_id) REFERENCES public.workspaces(space_id, id);


--
-- Name: skill_packages skill_packages_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skill_packages
    ADD CONSTRAINT skill_packages_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.skill_sources(id);


--
-- Name: skill_local_overlays skill_local_overlays_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skill_local_overlays
    ADD CONSTRAINT skill_local_overlays_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id);


--
-- Name: skill_local_overlays skill_local_overlays_skill_package_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skill_local_overlays
    ADD CONSTRAINT skill_local_overlays_skill_package_id_fkey FOREIGN KEY (skill_package_id) REFERENCES public.skill_packages(id) ON DELETE CASCADE;


--
-- Name: skill_local_overlays skill_local_overlays_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skill_local_overlays
    ADD CONSTRAINT skill_local_overlays_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: skill_package_files skill_package_files_skill_package_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skill_package_files
    ADD CONSTRAINT skill_package_files_skill_package_id_fkey FOREIGN KEY (skill_package_id) REFERENCES public.skill_packages(id) ON DELETE CASCADE;


--
-- Name: source_connections source_connections_connector_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_connections
    ADD CONSTRAINT source_connections_connector_id_fkey FOREIGN KEY (connector_id) REFERENCES public.source_connectors(id);


--
-- Name: source_connections source_connections_credential_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_connections
    ADD CONSTRAINT source_connections_credential_id_fkey FOREIGN KEY (credential_id) REFERENCES public.credentials(id);


--
-- Name: source_connections source_connections_owner_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_connections
    ADD CONSTRAINT source_connections_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES public.users(id);


--
-- Name: source_connections source_connections_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_connections
    ADD CONSTRAINT source_connections_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: source_pointers source_pointers_granted_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_pointers
    ADD CONSTRAINT source_pointers_granted_by_user_id_fkey FOREIGN KEY (granted_by_user_id) REFERENCES public.users(id);


--
-- Name: source_pointers source_pointers_owner_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_pointers
    ADD CONSTRAINT source_pointers_owner_space_id_fkey FOREIGN KEY (owner_space_id) REFERENCES public.spaces(id);


--
-- Name: source_pointers source_pointers_source_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_pointers
    ADD CONSTRAINT source_pointers_source_space_id_fkey FOREIGN KEY (source_space_id) REFERENCES public.spaces(id);


--
-- Name: source_snapshots source_snapshots_artifact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_snapshots
    ADD CONSTRAINT source_snapshots_artifact_id_fkey FOREIGN KEY (artifact_id) REFERENCES public.artifacts(id);


--
-- Name: source_snapshots source_snapshots_connection_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_snapshots
    ADD CONSTRAINT source_snapshots_connection_id_fkey FOREIGN KEY (connection_id) REFERENCES public.source_connections(id);


--
-- Name: source_snapshots source_snapshots_intake_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_snapshots
    ADD CONSTRAINT source_snapshots_intake_item_id_fkey FOREIGN KEY (intake_item_id) REFERENCES public.intake_items(id);


--
-- Name: source_snapshots source_snapshots_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_snapshots
    ADD CONSTRAINT source_snapshots_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: sources sources_source_activity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sources
    ADD CONSTRAINT sources_source_activity_id_fkey FOREIGN KEY (source_activity_id) REFERENCES public.activity_records(id);


--
-- Name: sources sources_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sources
    ADD CONSTRAINT sources_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: sources sources_object_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sources
    ADD CONSTRAINT sources_object_id_fkey FOREIGN KEY (object_id, space_id) REFERENCES public.space_objects(id, space_id) ON DELETE CASCADE;


--
-- Name: retrieval_objects retrieval_objects_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.retrieval_objects
    ADD CONSTRAINT retrieval_objects_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: retrieval_aliases retrieval_aliases_retrieval_object_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.retrieval_aliases
    ADD CONSTRAINT retrieval_aliases_retrieval_object_id_fkey FOREIGN KEY (retrieval_object_id) REFERENCES public.retrieval_objects(id) ON DELETE CASCADE;


--
-- Name: retrieval_aliases retrieval_aliases_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.retrieval_aliases
    ADD CONSTRAINT retrieval_aliases_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: retrieval_chunks retrieval_chunks_retrieval_object_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.retrieval_chunks
    ADD CONSTRAINT retrieval_chunks_retrieval_object_id_fkey FOREIGN KEY (retrieval_object_id) REFERENCES public.retrieval_objects(id) ON DELETE CASCADE;


--
-- Name: retrieval_chunks retrieval_chunks_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.retrieval_chunks
    ADD CONSTRAINT retrieval_chunks_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: retrieval_edges retrieval_edges_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.retrieval_edges
    ADD CONSTRAINT retrieval_edges_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: retrieval_feedback_events retrieval_feedback_events_actor_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.retrieval_feedback_events
    ADD CONSTRAINT retrieval_feedback_events_actor_user_id_fkey FOREIGN KEY (actor_user_id) REFERENCES public.users(id);


--
-- Name: retrieval_feedback_events retrieval_feedback_events_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.retrieval_feedback_events
    ADD CONSTRAINT retrieval_feedback_events_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: space_retrieval_prompts space_retrieval_prompts_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.space_retrieval_prompts
    ADD CONSTRAINT space_retrieval_prompts_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id) ON DELETE CASCADE;


--
-- Name: space_runtime_tool_policies space_runtime_tool_policies_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.space_runtime_tool_policies
    ADD CONSTRAINT space_runtime_tool_policies_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id) ON DELETE CASCADE;


--
-- Name: space_runtime_tool_policies space_runtime_tool_policies_updated_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.space_runtime_tool_policies
    ADD CONSTRAINT space_runtime_tool_policies_updated_by_user_id_fkey FOREIGN KEY (updated_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: space_invitations space_invitations_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.space_invitations
    ADD CONSTRAINT space_invitations_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: space_memberships space_memberships_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.space_memberships
    ADD CONSTRAINT space_memberships_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: space_memberships space_memberships_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.space_memberships
    ADD CONSTRAINT space_memberships_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: task_artifacts task_artifacts_artifact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_artifacts
    ADD CONSTRAINT task_artifacts_artifact_id_fkey FOREIGN KEY (artifact_id) REFERENCES public.artifacts(id);


--
-- Name: task_artifacts task_artifacts_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_artifacts
    ADD CONSTRAINT task_artifacts_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.runs(id);


--
-- Name: task_artifacts task_artifacts_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_artifacts
    ADD CONSTRAINT task_artifacts_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: task_artifacts task_artifacts_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_artifacts
    ADD CONSTRAINT task_artifacts_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id);


--
-- Name: task_dependencies task_dependencies_depends_on_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_dependencies
    ADD CONSTRAINT task_dependencies_depends_on_task_id_fkey FOREIGN KEY (depends_on_task_id) REFERENCES public.tasks(id);


--
-- Name: task_dependencies task_dependencies_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_dependencies
    ADD CONSTRAINT task_dependencies_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: task_dependencies task_dependencies_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_dependencies
    ADD CONSTRAINT task_dependencies_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id);


--
-- Name: task_evaluations task_evaluations_evaluator_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_evaluations
    ADD CONSTRAINT task_evaluations_evaluator_agent_id_fkey FOREIGN KEY (evaluator_agent_id) REFERENCES public.agents(id);


--
-- Name: task_evaluations task_evaluations_evaluator_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_evaluations
    ADD CONSTRAINT task_evaluations_evaluator_user_id_fkey FOREIGN KEY (evaluator_user_id) REFERENCES public.users(id);


--
-- Name: task_evaluations task_evaluations_run_evaluation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_evaluations
    ADD CONSTRAINT task_evaluations_run_evaluation_id_fkey FOREIGN KEY (run_evaluation_id) REFERENCES public.run_evaluations(id);


--
-- Name: task_evaluations task_evaluations_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_evaluations
    ADD CONSTRAINT task_evaluations_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.runs(id);


--
-- Name: task_evaluations task_evaluations_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_evaluations
    ADD CONSTRAINT task_evaluations_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: task_evaluations task_evaluations_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_evaluations
    ADD CONSTRAINT task_evaluations_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id);


--
-- Name: task_proposals task_proposals_proposal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_proposals
    ADD CONSTRAINT task_proposals_proposal_id_fkey FOREIGN KEY (proposal_id) REFERENCES public.proposals(id);


--
-- Name: task_proposals task_proposals_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_proposals
    ADD CONSTRAINT task_proposals_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: task_proposals task_proposals_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_proposals
    ADD CONSTRAINT task_proposals_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id);


--
-- Name: task_runs task_runs_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_runs
    ADD CONSTRAINT task_runs_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.runs(id);


--
-- Name: task_runs task_runs_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_runs
    ADD CONSTRAINT task_runs_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: task_runs task_runs_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_runs
    ADD CONSTRAINT task_runs_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id);


--
-- Name: tasks tasks_assigned_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_assigned_agent_id_fkey FOREIGN KEY (assigned_agent_id) REFERENCES public.agents(id);


--
-- Name: tasks tasks_assigned_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_assigned_user_id_fkey FOREIGN KEY (assigned_user_id) REFERENCES public.users(id);


--
-- Name: tasks tasks_board_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_board_id_fkey FOREIGN KEY (board_id) REFERENCES public.boards(id);


--
-- Name: tasks tasks_claimed_by_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_claimed_by_agent_id_fkey FOREIGN KEY (claimed_by_agent_id) REFERENCES public.agents(id);


--
-- Name: tasks tasks_claimed_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_claimed_by_user_id_fkey FOREIGN KEY (claimed_by_user_id) REFERENCES public.users(id);


--
-- Name: tasks tasks_column_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_column_id_fkey FOREIGN KEY (column_id) REFERENCES public.board_columns(id);


--
-- Name: tasks tasks_created_by_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_created_by_agent_id_fkey FOREIGN KEY (created_by_agent_id) REFERENCES public.agents(id);


--
-- Name: tasks tasks_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id);


--
-- Name: tasks tasks_parent_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_parent_task_id_fkey FOREIGN KEY (parent_task_id) REFERENCES public.tasks(id);


--
-- Name: tasks tasks_source_activity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_source_activity_id_fkey FOREIGN KEY (source_activity_id) REFERENCES public.activity_records(id);


--
-- Name: tasks tasks_source_artifact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_source_artifact_id_fkey FOREIGN KEY (source_artifact_id) REFERENCES public.artifacts(id);


--
-- Name: tasks tasks_source_proposal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_source_proposal_id_fkey FOREIGN KEY (source_proposal_id) REFERENCES public.proposals(id);


--
-- Name: tasks tasks_source_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_source_run_id_fkey FOREIGN KEY (source_run_id) REFERENCES public.runs(id);


--
-- Name: tasks tasks_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: tasks tasks_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_workspace_id_fkey FOREIGN KEY (space_id, workspace_id) REFERENCES public.workspaces(space_id, id);


--
-- Name: tasks tasks_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_project_id_fkey FOREIGN KEY (space_id, project_id) REFERENCES public.projects(space_id, id) ON DELETE SET NULL (project_id);


--
-- Name: user_sessions user_sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_sessions
    ADD CONSTRAINT user_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: validation_recipes validation_recipes_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.validation_recipes
    ADD CONSTRAINT validation_recipes_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: validation_recipes validation_recipes_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.validation_recipes
    ADD CONSTRAINT validation_recipes_workspace_id_fkey FOREIGN KEY (space_id, workspace_id) REFERENCES public.workspaces(space_id, id);


--
-- Name: working_dirs working_dirs_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.working_dirs
    ADD CONSTRAINT working_dirs_project_id_fkey FOREIGN KEY (space_id, project_id) REFERENCES public.projects(space_id, id);


--
-- Name: working_dirs working_dirs_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.working_dirs
    ADD CONSTRAINT working_dirs_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.sessions(id);


--
-- Name: working_dirs working_dirs_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.working_dirs
    ADD CONSTRAINT working_dirs_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: workspace_intake_profiles workspace_intake_profiles_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_intake_profiles
    ADD CONSTRAINT workspace_intake_profiles_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id);


--
-- Name: workspace_intake_profiles workspace_intake_profiles_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_intake_profiles
    ADD CONSTRAINT workspace_intake_profiles_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: workspace_intake_profiles workspace_intake_profiles_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_intake_profiles
    ADD CONSTRAINT workspace_intake_profiles_workspace_id_fkey FOREIGN KEY (space_id, workspace_id) REFERENCES public.workspaces(space_id, id);


--
-- Name: workspace_profiles workspace_profiles_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_profiles
    ADD CONSTRAINT workspace_profiles_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: workspace_profiles workspace_profiles_validation_recipe_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_profiles
    ADD CONSTRAINT workspace_profiles_validation_recipe_id_fkey FOREIGN KEY (validation_recipe_id) REFERENCES public.validation_recipes(id);


--
-- Name: workspace_profiles workspace_profiles_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_profiles
    ADD CONSTRAINT workspace_profiles_workspace_id_fkey FOREIGN KEY (space_id, workspace_id) REFERENCES public.workspaces(space_id, id);


--
-- Name: workspace_source_bindings workspace_source_bindings_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_source_bindings
    ADD CONSTRAINT workspace_source_bindings_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id);


--
-- Name: workspace_source_bindings workspace_source_bindings_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_source_bindings
    ADD CONSTRAINT workspace_source_bindings_project_id_fkey FOREIGN KEY (space_id, project_id) REFERENCES public.projects(space_id, id);


--
-- Name: workspace_source_bindings workspace_source_bindings_source_connection_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_source_bindings
    ADD CONSTRAINT workspace_source_bindings_source_connection_id_fkey FOREIGN KEY (source_connection_id) REFERENCES public.source_connections(id);


--
-- Name: workspace_source_bindings workspace_source_bindings_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_source_bindings
    ADD CONSTRAINT workspace_source_bindings_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: workspace_source_bindings workspace_source_bindings_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_source_bindings
    ADD CONSTRAINT workspace_source_bindings_workspace_id_fkey FOREIGN KEY (space_id, workspace_id) REFERENCES public.workspaces(space_id, id);


--
-- Name: workspaces workspaces_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspaces
    ADD CONSTRAINT workspaces_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id);


--
-- Name: workspaces workspaces_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspaces
    ADD CONSTRAINT workspaces_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);



--
-- Name: reader_annotations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reader_annotations (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    intake_item_id character varying(36),
    artifact_id character varying(36),
    source_snapshot_id character varying(36),
    annotation_type character varying(32) NOT NULL,
    quote_text text NOT NULL,
    anchor_json jsonb NOT NULL,
    color character varying(32),
    label character varying(128),
    visibility character varying(32) NOT NULL DEFAULT 'private',
    status character varying(32) NOT NULL DEFAULT 'active',
    anchor_state character varying(32) NOT NULL DEFAULT 'unverified',
    created_by_user_id character varying(36) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_reader_annotations_annotation_type CHECK (((annotation_type)::text = ANY ((ARRAY['highlight'::character varying, 'comment'::character varying, 'excerpt'::character varying, 'bookmark'::character varying])::text[]))),
    CONSTRAINT ck_reader_annotations_visibility CHECK (((visibility)::text = ANY ((ARRAY['private'::character varying, 'space_shared'::character varying])::text[]))),
    CONSTRAINT ck_reader_annotations_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'archived'::character varying])::text[]))),
    CONSTRAINT ck_reader_annotations_anchor_state CHECK (((anchor_state)::text = ANY ((ARRAY['verified'::character varying, 'unverified'::character varying])::text[]))),
    CONSTRAINT ck_reader_annotations_one_target CHECK (
        ((intake_item_id IS NOT NULL)::integer + (artifact_id IS NOT NULL)::integer + (source_snapshot_id IS NOT NULL)::integer) = 1
    ),
    CONSTRAINT ck_reader_annotations_anchor_json CHECK ((jsonb_typeof(anchor_json) = 'object'::text))
);

ALTER TABLE ONLY public.reader_annotations
    ADD CONSTRAINT reader_annotations_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.reader_annotations
    ADD CONSTRAINT reader_annotations_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);

ALTER TABLE ONLY public.reader_annotations
    ADD CONSTRAINT reader_annotations_intake_item_id_fkey FOREIGN KEY (intake_item_id) REFERENCES public.intake_items(id);

ALTER TABLE ONLY public.reader_annotations
    ADD CONSTRAINT reader_annotations_artifact_id_fkey FOREIGN KEY (artifact_id) REFERENCES public.artifacts(id);

ALTER TABLE ONLY public.reader_annotations
    ADD CONSTRAINT reader_annotations_source_snapshot_id_fkey FOREIGN KEY (source_snapshot_id) REFERENCES public.source_snapshots(id);

ALTER TABLE ONLY public.reader_annotations
    ADD CONSTRAINT reader_annotations_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id);

CREATE INDEX ix_reader_annotations_space_intake_item ON public.reader_annotations USING btree (space_id, intake_item_id, status);
CREATE INDEX ix_reader_annotations_space_artifact ON public.reader_annotations USING btree (space_id, artifact_id, status);
CREATE INDEX ix_reader_annotations_space_snapshot ON public.reader_annotations USING btree (space_id, source_snapshot_id, status);
CREATE INDEX ix_reader_annotations_space_user ON public.reader_annotations USING btree (space_id, created_by_user_id, status);
CREATE INDEX ix_reader_annotations_space_visibility ON public.reader_annotations USING btree (space_id, visibility, status);


--
-- Name: reader_comment_threads; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reader_comment_threads (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    annotation_id character varying(36) NOT NULL,
    status character varying(32) NOT NULL DEFAULT 'open',
    created_by_user_id character varying(36) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_reader_comment_threads_status CHECK (((status)::text = ANY ((ARRAY['open'::character varying, 'resolved'::character varying, 'archived'::character varying])::text[])))
);

ALTER TABLE ONLY public.reader_comment_threads
    ADD CONSTRAINT reader_comment_threads_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.reader_comment_threads
    ADD CONSTRAINT reader_comment_threads_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);

ALTER TABLE ONLY public.reader_comment_threads
    ADD CONSTRAINT reader_comment_threads_annotation_id_fkey FOREIGN KEY (annotation_id) REFERENCES public.reader_annotations(id);

ALTER TABLE ONLY public.reader_comment_threads
    ADD CONSTRAINT reader_comment_threads_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id);

CREATE INDEX ix_reader_comment_threads_space_annotation ON public.reader_comment_threads USING btree (space_id, annotation_id, status);
CREATE INDEX ix_reader_comment_threads_space_user ON public.reader_comment_threads USING btree (space_id, created_by_user_id, status);


--
-- Name: reader_comments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reader_comments (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    thread_id character varying(36) NOT NULL,
    body text NOT NULL,
    status character varying(32) NOT NULL DEFAULT 'active',
    created_by_user_id character varying(36) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_reader_comments_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'archived'::character varying])::text[])))
);

ALTER TABLE ONLY public.reader_comments
    ADD CONSTRAINT reader_comments_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.reader_comments
    ADD CONSTRAINT reader_comments_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);

ALTER TABLE ONLY public.reader_comments
    ADD CONSTRAINT reader_comments_thread_id_fkey FOREIGN KEY (thread_id) REFERENCES public.reader_comment_threads(id);

ALTER TABLE ONLY public.reader_comments
    ADD CONSTRAINT reader_comments_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id);

CREATE INDEX ix_reader_comments_space_thread ON public.reader_comments USING btree (space_id, thread_id, status);
CREATE INDEX ix_reader_comments_space_user ON public.reader_comments USING btree (space_id, created_by_user_id, status);

--
-- Intake Custom Source handler constraints and indexes.
--

ALTER TABLE ONLY public.source_handler_versions
    ADD CONSTRAINT source_handler_versions_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);

ALTER TABLE ONLY public.source_handler_versions
    ADD CONSTRAINT source_handler_versions_source_connection_id_fkey FOREIGN KEY (source_connection_id) REFERENCES public.source_connections(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.source_handler_versions
    ADD CONSTRAINT source_handler_versions_handler_artifact_id_fkey FOREIGN KEY (handler_artifact_id) REFERENCES public.artifacts(id);

ALTER TABLE ONLY public.source_handler_versions
    ADD CONSTRAINT source_handler_versions_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id);

ALTER TABLE ONLY public.source_handler_versions
    ADD CONSTRAINT source_handler_versions_created_by_run_id_fkey FOREIGN KEY (created_by_run_id) REFERENCES public.runs(id);

ALTER TABLE ONLY public.source_handler_versions
    ADD CONSTRAINT source_handler_versions_proposal_id_fkey FOREIGN KEY (proposal_id) REFERENCES public.proposals(id);

CREATE INDEX ix_source_handler_versions_space_id ON public.source_handler_versions USING btree (space_id);
CREATE INDEX ix_source_handler_versions_source_connection_id ON public.source_handler_versions USING btree (source_connection_id);
CREATE INDEX ix_source_handler_versions_status ON public.source_handler_versions USING btree (status);

ALTER TABLE ONLY public.source_recipe_versions
    ADD CONSTRAINT source_recipe_versions_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);

ALTER TABLE ONLY public.source_recipe_versions
    ADD CONSTRAINT source_recipe_versions_source_connection_id_fkey FOREIGN KEY (source_connection_id) REFERENCES public.source_connections(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.source_recipe_versions
    ADD CONSTRAINT source_recipe_versions_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id);

ALTER TABLE ONLY public.source_recipe_versions
    ADD CONSTRAINT source_recipe_versions_proposal_id_fkey FOREIGN KEY (proposal_id) REFERENCES public.proposals(id);

CREATE INDEX ix_source_recipe_versions_space_id ON public.source_recipe_versions USING btree (space_id);
CREATE INDEX ix_source_recipe_versions_connection ON public.source_recipe_versions USING btree (source_connection_id);

ALTER TABLE ONLY public.source_handler_runs
    ADD CONSTRAINT source_handler_runs_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);

ALTER TABLE ONLY public.source_handler_runs
    ADD CONSTRAINT source_handler_runs_source_connection_id_fkey FOREIGN KEY (source_connection_id) REFERENCES public.source_connections(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.source_handler_runs
    ADD CONSTRAINT source_handler_runs_handler_version_id_fkey FOREIGN KEY (handler_version_id) REFERENCES public.source_handler_versions(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.source_handler_runs
    ADD CONSTRAINT source_handler_runs_extraction_job_id_fkey FOREIGN KEY (extraction_job_id) REFERENCES public.extraction_jobs(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.source_handler_runs
    ADD CONSTRAINT source_handler_runs_input_artifact_id_fkey FOREIGN KEY (input_artifact_id) REFERENCES public.artifacts(id);

ALTER TABLE ONLY public.source_handler_runs
    ADD CONSTRAINT source_handler_runs_output_artifact_id_fkey FOREIGN KEY (output_artifact_id) REFERENCES public.artifacts(id);

ALTER TABLE ONLY public.source_handler_runs
    ADD CONSTRAINT source_handler_runs_logs_artifact_id_fkey FOREIGN KEY (logs_artifact_id) REFERENCES public.artifacts(id);

CREATE INDEX ix_source_handler_runs_space_id ON public.source_handler_runs USING btree (space_id);
CREATE INDEX ix_source_handler_runs_source_connection_id ON public.source_handler_runs USING btree (source_connection_id);
CREATE INDEX ix_source_handler_runs_handler_version_id ON public.source_handler_runs USING btree (handler_version_id);
CREATE INDEX ix_source_handler_runs_status ON public.source_handler_runs USING btree (status);

ALTER TABLE ONLY public.source_connections
    ADD CONSTRAINT source_connections_active_handler_version_id_fkey FOREIGN KEY (active_handler_version_id) REFERENCES public.source_handler_versions(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.source_connections
    ADD CONSTRAINT source_connections_last_handler_run_id_fkey FOREIGN KEY (last_handler_run_id) REFERENCES public.source_handler_runs(id) ON DELETE SET NULL;

CREATE INDEX ix_source_connections_active_handler_version_id ON public.source_connections USING btree (active_handler_version_id);
ALTER TABLE ONLY public.source_connections
    ADD CONSTRAINT source_connections_active_recipe_version_id_fkey FOREIGN KEY (active_recipe_version_id) REFERENCES public.source_recipe_versions(id) ON DELETE SET NULL;

CREATE INDEX ix_source_connections_active_recipe_version_id ON public.source_connections USING btree (active_recipe_version_id);

ALTER TABLE ONLY public.settings
    ADD CONSTRAINT settings_updated_by_user_id_fkey FOREIGN KEY (updated_by_user_id) REFERENCES public.users(id);

CREATE INDEX ix_settings_scope ON public.settings USING btree (scope_type, scope_id);
CREATE INDEX ix_settings_key ON public.settings USING btree (settings_key);


--
-- PostgreSQL database dump complete
--
