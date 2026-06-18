-- server/migrations/0001_baseline.sql
-- GENERATED, then FROZEN — do not edit by hand.
-- Source: pg_dump --schema-only of the canonical initial schema.
-- The schema was frozen during the server cutover. Future changes are added
-- as new NNNN_*.sql files in this directory, not by editing this baseline.

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
    consolidation_status character varying(32) DEFAULT 'pending'::character varying NOT NULL,
    processed_at timestamp with time zone,
    discarded_at timestamp with time zone,
    visibility character varying(32) DEFAULT 'space_shared'::character varying NOT NULL,
    owner_user_id character varying(36),
    project_id character varying(36),
    CONSTRAINT ck_activity_records_consolidation_status CHECK (((consolidation_status)::text = ANY ((ARRAY['pending'::character varying, 'skipped'::character varying, 'proposals_generated'::character varying, 'processed'::character varying, 'failed'::character varying])::text[]))),
    CONSTRAINT ck_activity_records_source_kind CHECK (((source_kind IS NULL) OR ((source_kind)::text = ANY ((ARRAY['user_capture'::character varying, 'chat_message'::character varying, 'external_chat'::character varying, 'file_import'::character varying, 'web_capture'::character varying, 'run_event'::character varying, 'workspace_event'::character varying, 'system_event'::character varying, 'external_source'::character varying, 'intake'::character varying])::text[])))),
    CONSTRAINT ck_activity_records_source_trust CHECK (((source_trust IS NULL) OR ((source_trust)::text = ANY ((ARRAY['user_confirmed'::character varying, 'internal_system'::character varying, 'trusted_external'::character varying, 'untrusted_external'::character varying, 'agent_inferred'::character varying])::text[])))),
    CONSTRAINT ck_activity_records_status CHECK (((status)::text = ANY ((ARRAY['raw'::character varying, 'processed'::character varying, 'proposals_generated'::character varying, 'archived'::character varying])::text[])))
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


--
-- Name: agent_template_versions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_template_versions (
    id character varying(36) NOT NULL,
    template_id character varying(36) NOT NULL,
    version character varying(64) NOT NULL,
    system_prompt text,
    model_config_json jsonb NOT NULL,
    context_policy_json jsonb NOT NULL,
    memory_policy_json jsonb NOT NULL,
    tool_policy_json jsonb NOT NULL,
    runtime_policy_json jsonb NOT NULL,
    output_policy_json jsonb NOT NULL,
    schedule_defaults_json jsonb NOT NULL,
    output_schema_json jsonb NOT NULL,
    created_by_user_id character varying(36),
    created_at timestamp with time zone NOT NULL,
    published_at timestamp with time zone
);


--
-- Name: agent_templates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_templates (
    id character varying(36) NOT NULL,
    key character varying(128) NOT NULL,
    name character varying(256) NOT NULL,
    description text,
    category character varying(64),
    scope character varying(16) NOT NULL,
    space_id character varying(36),
    owner_user_id character varying(36),
    visibility character varying(32) NOT NULL,
    status character varying(16) NOT NULL,
    current_version_id character varying(36),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_agent_templates_scope CHECK (((scope)::text = ANY ((ARRAY['system'::character varying, 'space'::character varying, 'user'::character varying])::text[]))),
    CONSTRAINT ck_agent_templates_scope_ownership CHECK (((((scope)::text = 'system'::text) AND (space_id IS NULL) AND (owner_user_id IS NULL)) OR (((scope)::text = 'space'::text) AND (space_id IS NOT NULL)) OR (((scope)::text = 'user'::text) AND (owner_user_id IS NOT NULL)))),
    CONSTRAINT ck_agent_templates_status CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'published'::character varying, 'archived'::character varying])::text[]))),
    CONSTRAINT ck_agent_templates_visibility CHECK (((visibility)::text = ANY ((ARRAY['private'::character varying, 'space_shared'::character varying, 'system_public'::character varying, 'system_internal'::character varying])::text[])))
);


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
    source_template_id character varying(36),
    source_template_version_id character varying(36),
    current_version_id character varying(36),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    visibility character varying(32) NOT NULL,
    CONSTRAINT ck_agents_agent_kind CHECK (((agent_kind)::text = ANY ((ARRAY['standard'::character varying, 'system_assistant'::character varying])::text[]))),
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
    source_execution_plane_id character varying(36),
    trust_level character varying(32),
    project_id character varying(36),
    CONSTRAINT ck_artifacts_storage_path_relative CHECK (((storage_path IS NULL) OR ((storage_path)::text !~~ '/%'::text))),
    CONSTRAINT ck_artifacts_trust_level CHECK (((trust_level IS NULL) OR ((trust_level)::text = ANY ((ARRAY['high'::character varying, 'medium'::character varying, 'low'::character varying, 'unknown'::character varying])::text[]))))
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
    next_run_at timestamp with time zone,
    last_fired_at timestamp with time zone,
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
    CONSTRAINT ck_context_snapshot_items_item_type CHECK (((item_type)::text = ANY ((ARRAY['memory'::character varying, 'knowledge_item'::character varying, 'source'::character varying, 'activity_record'::character varying, 'task'::character varying, 'idea'::character varying, 'project'::character varying, 'workspace'::character varying, 'run'::character varying, 'proposal'::character varying, 'artifact'::character varying, 'manual_context'::character varying])::text[])))
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
    execution_plane_id character varying(36),
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
-- Name: daily_capture_report_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.daily_capture_report_settings (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    enabled boolean NOT NULL,
    local_time character varying(5) NOT NULL,
    timezone character varying(64) NOT NULL,
    include_source_types_json jsonb CONSTRAINT daily_capture_report_setting_include_source_types_json_not_null NOT NULL,
    create_experience_proposals boolean CONSTRAINT daily_capture_report_settin_create_experience_proposal_not_null NOT NULL,
    create_memory_proposals boolean NOT NULL,
    experience_confidence_threshold double precision CONSTRAINT daily_capture_report_settin_experience_confidence_thre_not_null NOT NULL,
    memory_confidence_threshold double precision CONSTRAINT daily_capture_report_settin_memory_confidence_threshol_not_null NOT NULL,
    max_experience_proposals_per_day integer CONSTRAINT daily_capture_report_settin_max_experience_proposals_p_not_null NOT NULL,
    max_memory_proposals_per_day integer CONSTRAINT daily_capture_report_settin_max_memory_proposals_per_d_not_null NOT NULL,
    last_report_date character varying(10),
    next_run_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_daily_capture_report_settings_experience_threshold CHECK (((experience_confidence_threshold >= (0.0)::double precision) AND (experience_confidence_threshold <= (1.0)::double precision))),
    CONSTRAINT ck_daily_capture_report_settings_max_experience CHECK (((max_experience_proposals_per_day >= 0) AND (max_experience_proposals_per_day <= 20))),
    CONSTRAINT ck_daily_capture_report_settings_max_memory CHECK (((max_memory_proposals_per_day >= 0) AND (max_memory_proposals_per_day <= 10))),
    CONSTRAINT ck_daily_capture_report_settings_memory_threshold CHECK (((memory_confidence_threshold >= (0.0)::double precision) AND (memory_confidence_threshold <= (1.0)::double precision)))
);


--
-- Name: entity_links; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.entity_links (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    source_type character varying(32) NOT NULL,
    source_id character varying(36) NOT NULL,
    target_type character varying(32) NOT NULL,
    target_id character varying(36) NOT NULL,
    link_type character varying(32) NOT NULL,
    confidence double precision,
    status character varying(32) NOT NULL,
    created_by_user_id character varying(36),
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_entity_links_confidence CHECK (((confidence IS NULL) OR ((confidence >= (0)::double precision) AND (confidence <= (1)::double precision)))),
    CONSTRAINT ck_entity_links_link_type CHECK (((link_type)::text = ANY ((ARRAY['references'::character varying, 'related_to'::character varying, 'belongs_to'::character varying, 'captured_from'::character varying, 'source_for'::character varying, 'derived_from'::character varying])::text[]))),
    CONSTRAINT ck_entity_links_source_type CHECK (((source_type)::text = ANY ((ARRAY['note'::character varying, 'knowledge_item'::character varying, 'source'::character varying, 'project'::character varying, 'workspace'::character varying, 'activity'::character varying, 'run'::character varying, 'proposal'::character varying])::text[]))),
    CONSTRAINT ck_entity_links_status CHECK (((status)::text = ANY ((ARRAY['suggested'::character varying, 'accepted'::character varying, 'rejected'::character varying])::text[]))),
    CONSTRAINT ck_entity_links_target_type CHECK (((target_type)::text = ANY ((ARRAY['note'::character varying, 'knowledge_item'::character varying, 'source'::character varying, 'project'::character varying, 'workspace'::character varying, 'activity'::character varying, 'run'::character varying, 'proposal'::character varying])::text[])))
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
    CONSTRAINT ck_evidence_links_link_type CHECK (((link_type)::text = ANY ((ARRAY['supports'::character varying, 'contradicts'::character varying, 'derived_from'::character varying, 'mentions'::character varying, 'context_candidate'::character varying, 'used_in_context'::character varying, 'provenance'::character varying])::text[]))),
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
-- Name: execution_planes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.execution_planes (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    name character varying(256) NOT NULL,
    type character varying(32) NOT NULL,
    provider character varying(64) NOT NULL,
    execution_location character varying(32) NOT NULL,
    runtime_origin character varying(64) NOT NULL,
    trust_level character varying(32) DEFAULT 'unknown'::character varying NOT NULL,
    observability_level character varying(64) DEFAULT 'black_box'::character varying NOT NULL,
    data_exposure_level character varying(64) DEFAULT 'unknown'::character varying NOT NULL,
    credential_mode character varying(32) DEFAULT 'unknown'::character varying NOT NULL,
    config_json jsonb NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_execution_planes_credential_mode CHECK (((credential_mode)::text = ANY ((ARRAY['agent_space_vault'::character varying, 'vendor_account'::character varying, 'user_local'::character varying, 'none'::character varying, 'unknown'::character varying])::text[]))),
    CONSTRAINT ck_execution_planes_data_exposure_level CHECK (((data_exposure_level)::text = ANY ((ARRAY['local_only'::character varying, 'model_provider'::character varying, 'vendor_platform'::character varying, 'third_party_tools'::character varying, 'unknown'::character varying])::text[]))),
    CONSTRAINT ck_execution_planes_execution_location CHECK (((execution_location)::text = ANY ((ARRAY['local'::character varying, 'remote'::character varying, 'hybrid'::character varying, 'manual'::character varying])::text[]))),
    CONSTRAINT ck_execution_planes_observability_level CHECK (((observability_level)::text = ANY ((ARRAY['full_trace'::character varying, 'structured_events'::character varying, 'artifacts_only'::character varying, 'final_output_only'::character varying, 'black_box'::character varying])::text[]))),
    CONSTRAINT ck_execution_planes_provider CHECK (((provider)::text = ANY ((ARRAY['agent_space'::character varying, 'openai'::character varying, 'anthropic'::character varying, 'opencode'::character varying, 'cursor'::character varying, 'other'::character varying])::text[]))),
    CONSTRAINT ck_execution_planes_runtime_origin CHECK (((runtime_origin)::text = ANY ((ARRAY['native'::character varying, 'external_vendor'::character varying, 'open_source_external'::character varying, 'manual'::character varying])::text[]))),
    CONSTRAINT ck_execution_planes_trust_level CHECK (((trust_level)::text = ANY ((ARRAY['high'::character varying, 'medium'::character varying, 'low'::character varying, 'unknown'::character varying])::text[]))),
    CONSTRAINT ck_execution_planes_type CHECK (((type)::text = ANY ((ARRAY['native'::character varying, 'local'::character varying, 'remote_vendor'::character varying, 'hybrid'::character varying, 'manual'::character varying])::text[])))
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
    execution_plane_id character varying(36),
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
-- Name: knowledge_item_relations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.knowledge_item_relations (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    from_item_id character varying(36) NOT NULL,
    to_item_id character varying(36) NOT NULL,
    relation_type character varying(64) NOT NULL,
    status character varying(32) NOT NULL,
    confidence double precision,
    evidence_summary text,
    source_proposal_id character varying(36),
    created_by_user_id character varying(36),
    created_by_agent_id character varying(36),
    created_from_assessment_id character varying(36),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_knowledge_item_relations_confidence CHECK (((confidence IS NULL) OR ((confidence >= (0)::double precision) AND (confidence <= (1)::double precision)))),
    CONSTRAINT ck_knowledge_item_relations_relation_type CHECK (((relation_type)::text = ANY ((ARRAY['related_to'::character varying, 'explains'::character varying, 'depends_on'::character varying, 'prerequisite_of'::character varying, 'part_of'::character varying, 'example_of'::character varying, 'applies_to'::character varying, 'supports'::character varying, 'contradicts'::character varying, 'derived_from'::character varying, 'summarizes'::character varying, 'updates'::character varying])::text[]))),
    CONSTRAINT ck_knowledge_item_relations_status CHECK (((status)::text = ANY ((ARRAY['candidate'::character varying, 'active'::character varying, 'rejected'::character varying, 'archived'::character varying])::text[])))
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
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    project_id character varying(36),
    workspace_id character varying(36),
    root_item_id character varying(36),
    supersedes_item_id character varying(36),
    item_type character varying(32) NOT NULL,
    slug character varying(512),
    aliases_json jsonb,
    title character varying(512) NOT NULL,
    content text NOT NULL,
    content_json jsonb,
    content_format character varying(32) NOT NULL,
    content_schema_version integer NOT NULL,
    plain_text text,
    excerpt character varying(512),
    status character varying(32) NOT NULL,
    visibility character varying(32) NOT NULL,
    verification_status character varying(32) NOT NULL,
    reflection_status character varying(32) NOT NULL,
    tags_json jsonb NOT NULL,
    confidence double precision,
    source_url text,
    owner_user_id character varying(36),
    created_by_user_id character varying(36),
    created_by_agent_id character varying(36),
    created_by_run_id character varying(36),
    source_activity_id character varying(36),
    source_artifact_id character varying(36),
    created_from_proposal_id character varying(36),
    approved_by_user_id character varying(36),
    redirect_to_item_id character varying(36),
    version integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    archived_at timestamp with time zone,
    deprecated_at timestamp with time zone,
    CONSTRAINT ck_knowledge_items_confidence CHECK (((confidence IS NULL) OR ((confidence >= (0)::double precision) AND (confidence <= (1)::double precision)))),
    CONSTRAINT ck_knowledge_items_content_format CHECK (((content_format)::text = ANY ((ARRAY['markdown'::character varying, 'plain'::character varying, 'prosemirror_json'::character varying])::text[]))),
    CONSTRAINT ck_knowledge_items_item_type CHECK (((item_type)::text = ANY ((ARRAY['concept'::character varying, 'claim'::character varying, 'lesson'::character varying, 'procedure'::character varying, 'decision'::character varying, 'question'::character varying, 'answer'::character varying, 'summary'::character varying])::text[]))),
    CONSTRAINT ck_knowledge_items_reflection_status CHECK (((reflection_status)::text = ANY ((ARRAY['unreviewed'::character varying, 'reviewed'::character varying, 'distilled'::character varying])::text[]))),
    CONSTRAINT ck_knowledge_items_status CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'active'::character varying, 'superseded'::character varying, 'archived'::character varying])::text[]))),
    CONSTRAINT ck_knowledge_items_verification_status CHECK (((verification_status)::text = ANY ((ARRAY['unverified'::character varying, 'needs_review'::character varying, 'verified'::character varying])::text[]))),
    CONSTRAINT ck_knowledge_items_visibility CHECK (((visibility)::text = ANY ((ARRAY['private'::character varying, 'space_shared'::character varying, 'workspace_shared'::character varying, 'restricted'::character varying])::text[])))
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
-- Name: memory_entries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.memory_entries (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    scope_type character varying(32) NOT NULL,
    scope_id character varying(36),
    memory_type character varying(32) NOT NULL,
    content text NOT NULL,
    status character varying(32) NOT NULL,
    source_proposal_id character varying(36),
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
    capability_id character varying(128),
    namespace character varying(255),
    title character varying(512),
    visibility character varying(32) NOT NULL,
    confidence double precision NOT NULL,
    importance double precision NOT NULL,
    source_id character varying(36),
    source_activity_id character varying(36),
    source_artifact_id character varying(36),
    created_by character varying(64),
    approved_by character varying(64),
    deleted_at timestamp with time zone,
    version integer NOT NULL,
    access_count integer NOT NULL,
    last_accessed_at timestamp with time zone,
    tags jsonb,
    memory_layer character varying(32),
    memory_kind character varying(64),
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
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    title character varying(512) NOT NULL,
    content_json jsonb,
    content_format character varying(32) NOT NULL,
    content_schema_version integer NOT NULL,
    plain_text text,
    excerpt character varying(512),
    status character varying(32) NOT NULL,
    primary_project_id character varying(36),
    created_from_activity_id character varying(36),
    created_by_user_id character varying(36),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    archived_at timestamp with time zone,
    deleted_at timestamp with time zone,
    CONSTRAINT ck_notes_content_format CHECK (((content_format)::text = ANY ((ARRAY['markdown'::character varying, 'plain'::character varying, 'prosemirror_json'::character varying])::text[]))),
    CONSTRAINT ck_notes_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'archived'::character varying, 'deleted'::character varying])::text[])))
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
-- Name: project_workspaces; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.project_workspaces (
    id character varying(36) NOT NULL,
    project_id character varying(36) NOT NULL,
    workspace_id character varying(36) NOT NULL,
    role character varying(64) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_project_workspaces_role CHECK (((role)::text = ANY ((ARRAY['primary_codebase'::character varying, 'capability_library'::character varying, 'docs'::character varying, 'data'::character varying, 'deployment'::character varying, 'reference'::character varying])::text[])))
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
    task_id character varying(36),
    adapter_type character varying(64),
    capability_id character varying(128),
    model_selection_mode character varying(32) DEFAULT 'cli_default'::character varying NOT NULL,
    model_override_json jsonb,
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
    execution_plane_id character varying(36),
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
    execution_plane_id character varying(36),
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
    last_checked_at timestamp with time zone,
    next_check_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    deleted_at timestamp with time zone,
    CONSTRAINT ck_source_connections_capture_policy CHECK (((capture_policy)::text = ANY ((ARRAY['metadata_only'::character varying, 'excerpt_only'::character varying, 'auto_extract_relevant'::character varying, 'auto_extract_all_text'::character varying, 'archive_all_snapshots'::character varying])::text[]))),
    CONSTRAINT ck_source_connections_fetch_frequency CHECK (((fetch_frequency)::text = ANY ((ARRAY['manual'::character varying, 'hourly'::character varying, 'daily'::character varying, 'weekly'::character varying])::text[]))),
    CONSTRAINT ck_source_connections_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'paused'::character varying, 'archived'::character varying])::text[]))),
    CONSTRAINT ck_source_connections_trust_level CHECK (((trust_level)::text = ANY ((ARRAY['trusted'::character varying, 'normal'::character varying, 'untrusted'::character varying])::text[])))
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
    metadata_json jsonb,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_source_pointers_access_mode CHECK (((access_mode)::text = ANY ((ARRAY['read'::character varying, 'subscribe'::character varying, 'federated'::character varying])::text[])))
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
    CONSTRAINT ck_source_snapshots_capture_method CHECK (((capture_method)::text = ANY ((ARRAY['manual'::character varying, 'connection_scan'::character varying, 'full_text'::character varying, 'snapshot'::character varying, 'internal'::character varying])::text[]))),
    CONSTRAINT ck_source_snapshots_snapshot_type CHECK (((snapshot_type)::text = ANY ((ARRAY['metadata'::character varying, 'raw'::character varying, 'extracted'::character varying, 'summary'::character varying])::text[]))),
    CONSTRAINT ck_source_snapshots_trust_level CHECK (((trust_level)::text = ANY ((ARRAY['trusted'::character varying, 'normal'::character varying, 'untrusted'::character varying])::text[])))
);


--
-- Name: sources; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sources (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    source_type character varying(64) NOT NULL,
    title character varying(512) NOT NULL,
    uri text,
    content_ref character varying(1024),
    raw_text text,
    summary text,
    metadata_json jsonb NOT NULL,
    status character varying(32) NOT NULL,
    source_activity_id character varying(36),
    created_by_user_id character varying(36),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_sources_source_type CHECK (((source_type)::text = ANY ((ARRAY['activity_record'::character varying, 'chat_capture'::character varying, 'webpage'::character varying, 'article'::character varying, 'paper'::character varying, 'pdf'::character varying, 'file'::character varying, 'email'::character varying, 'manual_reference'::character varying, 'external_note'::character varying])::text[]))),
    CONSTRAINT ck_sources_status CHECK (((status)::text = ANY ((ARRAY['raw'::character varying, 'processing'::character varying, 'processed'::character varying, 'archived'::character varying, 'error'::character varying])::text[])))
);


--
-- Name: space_assistant_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.space_assistant_settings (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    assistant_agent_id character varying(36),
    response_style character varying(32),
    verbosity character varying(32),
    default_context_toggles_json jsonb NOT NULL,
    default_project_id character varying(36),
    proposal_style character varying(32),
    model_preferences_json jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_space_assistant_settings_proposal_style CHECK (((proposal_style IS NULL) OR ((proposal_style)::text = ANY ((ARRAY['proactive'::character varying, 'balanced'::character varying, 'conservative'::character varying])::text[])))),
    CONSTRAINT ck_space_assistant_settings_response_style CHECK (((response_style IS NULL) OR ((response_style)::text = ANY ((ARRAY['neutral'::character varying, 'friendly'::character varying, 'direct'::character varying, 'formal'::character varying])::text[])))),
    CONSTRAINT ck_space_assistant_settings_verbosity CHECK (((verbosity IS NULL) OR ((verbosity)::text = ANY ((ARRAY['concise'::character varying, 'balanced'::character varying, 'detailed'::character varying])::text[]))))
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
    allow_external_root boolean DEFAULT false NOT NULL
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
-- Name: agent_template_versions agent_template_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_template_versions
    ADD CONSTRAINT agent_template_versions_pkey PRIMARY KEY (id);


--
-- Name: agent_templates agent_templates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_templates
    ADD CONSTRAINT agent_templates_pkey PRIMARY KEY (id);


--
-- Name: agent_versions agent_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_versions
    ADD CONSTRAINT agent_versions_pkey PRIMARY KEY (id);


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
-- Name: capability_overlays capability_overlays_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.capability_overlays
    ADD CONSTRAINT capability_overlays_pkey PRIMARY KEY (id);


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
-- Name: context_digests context_digests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.context_digests
    ADD CONSTRAINT context_digests_pkey PRIMARY KEY (id);


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
-- Name: daily_capture_report_settings daily_capture_report_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_capture_report_settings
    ADD CONSTRAINT daily_capture_report_settings_pkey PRIMARY KEY (id);


--
-- Name: entity_links entity_links_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entity_links
    ADD CONSTRAINT entity_links_pkey PRIMARY KEY (id);


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
-- Name: evolution_targets evolution_targets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evolution_targets
    ADD CONSTRAINT evolution_targets_pkey PRIMARY KEY (id);


--
-- Name: execution_planes execution_planes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.execution_planes
    ADD CONSTRAINT execution_planes_pkey PRIMARY KEY (id);


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
-- Name: knowledge_item_relations knowledge_item_relations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_item_relations
    ADD CONSTRAINT knowledge_item_relations_pkey PRIMARY KEY (id);


--
-- Name: knowledge_item_sources knowledge_item_sources_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_item_sources
    ADD CONSTRAINT knowledge_item_sources_pkey PRIMARY KEY (id);


--
-- Name: knowledge_items knowledge_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_items
    ADD CONSTRAINT knowledge_items_pkey PRIMARY KEY (id);


--
-- Name: memory_access_logs memory_access_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_access_logs
    ADD CONSTRAINT memory_access_logs_pkey PRIMARY KEY (id);


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
-- Name: notes notes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notes
    ADD CONSTRAINT notes_pkey PRIMARY KEY (id);


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
-- Name: project_workspaces project_workspaces_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_workspaces
    ADD CONSTRAINT project_workspaces_pkey PRIMARY KEY (id);


--
-- Name: projects projects_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_pkey PRIMARY KEY (id);


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
-- Name: source_connections source_connections_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_connections
    ADD CONSTRAINT source_connections_pkey PRIMARY KEY (id);


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
    ADD CONSTRAINT sources_pkey PRIMARY KEY (id);


--
-- Name: space_assistant_settings space_assistant_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.space_assistant_settings
    ADD CONSTRAINT space_assistant_settings_pkey PRIMARY KEY (id);


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
-- Name: agent_template_versions uq_agent_template_versions_template_version; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_template_versions
    ADD CONSTRAINT uq_agent_template_versions_template_version UNIQUE (template_id, version);


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
-- Name: daily_capture_report_settings uq_daily_capture_report_settings_space_user; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_capture_report_settings
    ADD CONSTRAINT uq_daily_capture_report_settings_space_user UNIQUE (space_id, user_id);


--
-- Name: execution_planes uq_execution_planes_space_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.execution_planes
    ADD CONSTRAINT uq_execution_planes_space_name UNIQUE (space_id, name);


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
    ADD CONSTRAINT uq_note_collection_items_collection_note UNIQUE (collection_id, note_id);


--
-- Name: project_workspaces uq_project_workspaces_project_workspace_role; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_workspaces
    ADD CONSTRAINT uq_project_workspaces_project_workspace_role UNIQUE (project_id, workspace_id, role);


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
-- Name: space_assistant_settings uq_space_assistant_settings_space_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.space_assistant_settings
    ADD CONSTRAINT uq_space_assistant_settings_space_id UNIQUE (space_id);


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


--
-- Name: ix_activity_records_activity_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_activity_records_activity_type ON public.activity_records USING btree (activity_type);


--
-- Name: ix_activity_records_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_activity_records_agent_id ON public.activity_records USING btree (agent_id);


--
-- Name: ix_activity_records_consolidation_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_activity_records_consolidation_status ON public.activity_records USING btree (consolidation_status);


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
-- Name: ix_agent_template_versions_created_by_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_template_versions_created_by_user_id ON public.agent_template_versions USING btree (created_by_user_id);


--
-- Name: ix_agent_template_versions_template_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_template_versions_template_id ON public.agent_template_versions USING btree (template_id);


--
-- Name: ix_agent_templates_current_version_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_templates_current_version_id ON public.agent_templates USING btree (current_version_id);


--
-- Name: ix_agent_templates_owner_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_templates_owner_user_id ON public.agent_templates USING btree (owner_user_id);


--
-- Name: ix_agent_templates_scope; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_templates_scope ON public.agent_templates USING btree (scope);


--
-- Name: ix_agent_templates_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_templates_space_id ON public.agent_templates USING btree (space_id);


--
-- Name: ix_agent_templates_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_templates_status ON public.agent_templates USING btree (status);


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
-- Name: ix_agents_source_template_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agents_source_template_id ON public.agents USING btree (source_template_id);


--
-- Name: ix_agents_source_template_version_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agents_source_template_version_id ON public.agents USING btree (source_template_version_id);


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
-- Name: ix_artifacts_proposal_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_artifacts_proposal_id ON public.artifacts USING btree (proposal_id);


--
-- Name: ix_artifacts_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_artifacts_run_id ON public.artifacts USING btree (run_id);


--
-- Name: ix_artifacts_source_execution_plane_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_artifacts_source_execution_plane_id ON public.artifacts USING btree (source_execution_plane_id);


--
-- Name: ix_artifacts_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_artifacts_space_id ON public.artifacts USING btree (space_id);


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
-- Name: ix_automations_next_run_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_automations_next_run_at ON public.automations USING btree (next_run_at);


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
-- Name: ix_daily_capture_report_settings_next_run_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_daily_capture_report_settings_next_run_at ON public.daily_capture_report_settings USING btree (next_run_at);


--
-- Name: ix_daily_capture_report_settings_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_daily_capture_report_settings_space_id ON public.daily_capture_report_settings USING btree (space_id);


--
-- Name: ix_daily_capture_report_settings_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_daily_capture_report_settings_user_id ON public.daily_capture_report_settings USING btree (user_id);


--
-- Name: ix_entity_links_link_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_entity_links_link_type ON public.entity_links USING btree (link_type);


--
-- Name: ix_entity_links_source_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_entity_links_source_id ON public.entity_links USING btree (source_id);


--
-- Name: ix_entity_links_source_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_entity_links_source_type ON public.entity_links USING btree (source_type);


--
-- Name: ix_entity_links_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_entity_links_space_id ON public.entity_links USING btree (space_id);


--
-- Name: ix_entity_links_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_entity_links_status ON public.entity_links USING btree (status);


--
-- Name: ix_entity_links_target_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_entity_links_target_id ON public.entity_links USING btree (target_id);


--
-- Name: ix_entity_links_target_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_entity_links_target_type ON public.entity_links USING btree (target_type);


--
-- Name: ix_entity_links_unique_accepted; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_entity_links_unique_accepted ON public.entity_links USING btree (space_id, source_type, source_id, target_type, target_id, link_type) WHERE ((status)::text = 'accepted'::text);


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
-- Name: ix_execution_planes_enabled; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_execution_planes_enabled ON public.execution_planes USING btree (enabled);


--
-- Name: ix_execution_planes_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_execution_planes_space_id ON public.execution_planes USING btree (space_id);


--
-- Name: ix_external_run_records_execution_plane_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_external_run_records_execution_plane_id ON public.external_run_records USING btree (execution_plane_id);


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
-- Name: ix_knowledge_item_relations_from_item_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_knowledge_item_relations_from_item_id ON public.knowledge_item_relations USING btree (from_item_id);


--
-- Name: ix_knowledge_item_relations_relation_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_knowledge_item_relations_relation_type ON public.knowledge_item_relations USING btree (relation_type);


--
-- Name: ix_knowledge_item_relations_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_knowledge_item_relations_space_id ON public.knowledge_item_relations USING btree (space_id);


--
-- Name: ix_knowledge_item_relations_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_knowledge_item_relations_status ON public.knowledge_item_relations USING btree (status);


--
-- Name: ix_knowledge_item_relations_to_item_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_knowledge_item_relations_to_item_id ON public.knowledge_item_relations USING btree (to_item_id);


--
-- Name: ix_knowledge_item_relations_unique_active; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_knowledge_item_relations_unique_active ON public.knowledge_item_relations USING btree (space_id, from_item_id, to_item_id, relation_type) WHERE ((status)::text = 'active'::text);


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
-- Name: ix_knowledge_items_item_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_knowledge_items_item_type ON public.knowledge_items USING btree (item_type);


--
-- Name: ix_knowledge_items_owner_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_knowledge_items_owner_user_id ON public.knowledge_items USING btree (owner_user_id);


--
-- Name: ix_knowledge_items_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_knowledge_items_project_id ON public.knowledge_items USING btree (project_id);


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
-- Name: ix_knowledge_items_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_knowledge_items_status ON public.knowledge_items USING btree (status);


--
-- Name: ix_knowledge_items_supersedes_item_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_knowledge_items_supersedes_item_id ON public.knowledge_items USING btree (supersedes_item_id);


--
-- Name: ix_knowledge_items_visibility; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_knowledge_items_visibility ON public.knowledge_items USING btree (visibility);


--
-- Name: ix_knowledge_items_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_knowledge_items_workspace_id ON public.knowledge_items USING btree (workspace_id);


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
-- Name: ix_memory_entries_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_entries_agent_id ON public.memory_entries USING btree (agent_id);


--
-- Name: ix_memory_entries_capability_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_entries_capability_id ON public.memory_entries USING btree (capability_id);


--
-- Name: ix_memory_entries_created_from_proposal_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_entries_created_from_proposal_id ON public.memory_entries USING btree (created_from_proposal_id);


--
-- Name: ix_memory_entries_memory_kind; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_entries_memory_kind ON public.memory_entries USING btree (memory_kind);


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
-- Name: ix_memory_entries_scope_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_entries_scope_id ON public.memory_entries USING btree (scope_id);


--
-- Name: ix_memory_entries_scope_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_entries_scope_type ON public.memory_entries USING btree (scope_type);


--
-- Name: ix_memory_entries_sensitivity_level; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_entries_sensitivity_level ON public.memory_entries USING btree (sensitivity_level);


--
-- Name: ix_memory_entries_source_activity_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_entries_source_activity_id ON public.memory_entries USING btree (source_activity_id);


--
-- Name: ix_memory_entries_source_proposal_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_entries_source_proposal_id ON public.memory_entries USING btree (source_proposal_id);


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

CREATE INDEX ix_note_collection_items_collection_id ON public.note_collection_items USING btree (collection_id);


--
-- Name: ix_note_collection_items_note_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_note_collection_items_note_id ON public.note_collection_items USING btree (note_id);


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
-- Name: ix_notes_created_by_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_notes_created_by_user_id ON public.notes USING btree (created_by_user_id);


--
-- Name: ix_notes_deleted_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_notes_deleted_at ON public.notes USING btree (deleted_at);


--
-- Name: ix_notes_primary_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_notes_primary_project_id ON public.notes USING btree (primary_project_id);


--
-- Name: ix_notes_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_notes_space_id ON public.notes USING btree (space_id);


--
-- Name: ix_notes_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_notes_status ON public.notes USING btree (status);


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
-- Name: ix_project_workspaces_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_project_workspaces_project_id ON public.project_workspaces USING btree (project_id);


--
-- Name: ix_project_workspaces_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_project_workspaces_workspace_id ON public.project_workspaces USING btree (workspace_id);


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
-- Name: ix_runs_execution_plane_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runs_execution_plane_id ON public.runs USING btree (execution_plane_id);


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
-- Name: ix_runs_task_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runs_task_id ON public.runs USING btree (task_id);


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
-- Name: ix_runtime_tool_bindings_execution_plane_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_tool_bindings_execution_plane_id ON public.runtime_tool_bindings USING btree (execution_plane_id);


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
-- Name: ix_source_connections_due; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_source_connections_due ON public.source_connections USING btree (status, next_check_at);


--
-- Name: ix_source_connections_next_check_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_source_connections_next_check_at ON public.source_connections USING btree (next_check_at);


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
-- Name: ix_sources_created_by_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sources_created_by_user_id ON public.sources USING btree (created_by_user_id);


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
-- Name: ix_sources_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sources_status ON public.sources USING btree (status);


--
-- Name: ix_space_assistant_settings_assistant_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_space_assistant_settings_assistant_agent_id ON public.space_assistant_settings USING btree (assistant_agent_id);


--
-- Name: ix_space_assistant_settings_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_space_assistant_settings_space_id ON public.space_assistant_settings USING btree (space_id);


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
-- Name: uq_agent_templates_space_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_agent_templates_space_key ON public.agent_templates USING btree (space_id, key) WHERE ((scope)::text = 'space'::text);


--
-- Name: uq_agent_templates_system_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_agent_templates_system_key ON public.agent_templates USING btree (key) WHERE ((scope)::text = 'system'::text);


--
-- Name: uq_agent_templates_user_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_agent_templates_user_key ON public.agent_templates USING btree (owner_user_id, key) WHERE ((scope)::text = 'user'::text);


--
-- Name: uq_agents_system_assistant_per_space; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_agents_system_assistant_per_space ON public.agents USING btree (space_id) WHERE (((agent_kind)::text = 'system_assistant'::text) AND ((status)::text = 'active'::text));


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
    ADD CONSTRAINT activity_records_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id);


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
-- Name: agent_template_versions agent_template_versions_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_template_versions
    ADD CONSTRAINT agent_template_versions_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id);


--
-- Name: agent_template_versions agent_template_versions_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_template_versions
    ADD CONSTRAINT agent_template_versions_template_id_fkey FOREIGN KEY (template_id) REFERENCES public.agent_templates(id) ON DELETE CASCADE;


--
-- Name: agent_templates agent_templates_owner_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_templates
    ADD CONSTRAINT agent_templates_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES public.users(id);


--
-- Name: agent_templates agent_templates_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_templates
    ADD CONSTRAINT agent_templates_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


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
-- Name: artifacts artifacts_source_execution_plane_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_source_execution_plane_id_fkey FOREIGN KEY (source_execution_plane_id) REFERENCES public.execution_planes(id);


--
-- Name: artifacts artifacts_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


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
    ADD CONSTRAINT automations_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id);


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
    ADD CONSTRAINT boards_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id);


--
-- Name: capability_overlays capability_overlays_proposal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.capability_overlays
    ADD CONSTRAINT capability_overlays_proposal_id_fkey FOREIGN KEY (proposal_id) REFERENCES public.proposals(id);


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
-- Name: daily_capture_report_settings daily_capture_report_settings_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_capture_report_settings
    ADD CONSTRAINT daily_capture_report_settings_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: daily_capture_report_settings daily_capture_report_settings_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_capture_report_settings
    ADD CONSTRAINT daily_capture_report_settings_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: entity_links entity_links_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entity_links
    ADD CONSTRAINT entity_links_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id);


--
-- Name: entity_links entity_links_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entity_links
    ADD CONSTRAINT entity_links_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


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
-- Name: evolution_targets evolution_targets_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evolution_targets
    ADD CONSTRAINT evolution_targets_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: execution_planes execution_planes_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.execution_planes
    ADD CONSTRAINT execution_planes_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: external_run_records external_run_records_execution_plane_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_run_records
    ADD CONSTRAINT external_run_records_execution_plane_id_fkey FOREIGN KEY (execution_plane_id) REFERENCES public.execution_planes(id);


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
    ADD CONSTRAINT fk_activity_records_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE SET NULL;


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
-- Name: agent_templates fk_agent_templates_current_version_id_agent_template_versions; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_templates
    ADD CONSTRAINT fk_agent_templates_current_version_id_agent_template_versions FOREIGN KEY (current_version_id) REFERENCES public.agent_template_versions(id) ON DELETE SET NULL;


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
-- Name: agents fk_agents_source_template_id_agent_templates; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agents
    ADD CONSTRAINT fk_agents_source_template_id_agent_templates FOREIGN KEY (source_template_id) REFERENCES public.agent_templates(id) ON DELETE SET NULL;


--
-- Name: agents fk_agents_source_template_version_id_agent_template_versions; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agents
    ADD CONSTRAINT fk_agents_source_template_version_id_agent_template_versions FOREIGN KEY (source_template_version_id) REFERENCES public.agent_template_versions(id) ON DELETE SET NULL;


--
-- Name: artifacts fk_artifacts_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT fk_artifacts_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE SET NULL;


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
-- Name: context_snapshots fk_context_snapshots_execution_plane_id_execution_planes; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.context_snapshots
    ADD CONSTRAINT fk_context_snapshots_execution_plane_id_execution_planes FOREIGN KEY (execution_plane_id) REFERENCES public.execution_planes(id) ON DELETE SET NULL;


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
    ADD CONSTRAINT fk_knowledge_items_redirect_to_item_id_knowledge_items FOREIGN KEY (redirect_to_item_id) REFERENCES public.knowledge_items(id) ON DELETE SET NULL;


--
-- Name: knowledge_items fk_knowledge_items_root_item_id_knowledge_items; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_items
    ADD CONSTRAINT fk_knowledge_items_root_item_id_knowledge_items FOREIGN KEY (root_item_id) REFERENCES public.knowledge_items(id) ON DELETE SET NULL;


--
-- Name: knowledge_items fk_knowledge_items_supersedes_item_id_knowledge_items; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_items
    ADD CONSTRAINT fk_knowledge_items_supersedes_item_id_knowledge_items FOREIGN KEY (supersedes_item_id) REFERENCES public.knowledge_items(id) ON DELETE SET NULL;


--
-- Name: memory_entries fk_memory_entries_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_entries
    ADD CONSTRAINT fk_memory_entries_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE SET NULL;


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
    ADD CONSTRAINT fk_proposals_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE SET NULL;


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
    ADD CONSTRAINT fk_runs_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE SET NULL;


--
-- Name: runs fk_runs_task_id_tasks; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runs
    ADD CONSTRAINT fk_runs_task_id_tasks FOREIGN KEY (task_id) REFERENCES public.tasks(id) ON DELETE SET NULL;


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
    ADD CONSTRAINT jobs_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id);


--
-- Name: knowledge_item_relations knowledge_item_relations_created_by_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_item_relations
    ADD CONSTRAINT knowledge_item_relations_created_by_agent_id_fkey FOREIGN KEY (created_by_agent_id) REFERENCES public.agents(id);


--
-- Name: knowledge_item_relations knowledge_item_relations_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_item_relations
    ADD CONSTRAINT knowledge_item_relations_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id);


--
-- Name: knowledge_item_relations knowledge_item_relations_from_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_item_relations
    ADD CONSTRAINT knowledge_item_relations_from_item_id_fkey FOREIGN KEY (from_item_id) REFERENCES public.knowledge_items(id);


--
-- Name: knowledge_item_relations knowledge_item_relations_source_proposal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_item_relations
    ADD CONSTRAINT knowledge_item_relations_source_proposal_id_fkey FOREIGN KEY (source_proposal_id) REFERENCES public.proposals(id);


--
-- Name: knowledge_item_relations knowledge_item_relations_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_item_relations
    ADD CONSTRAINT knowledge_item_relations_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: knowledge_item_relations knowledge_item_relations_to_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_item_relations
    ADD CONSTRAINT knowledge_item_relations_to_item_id_fkey FOREIGN KEY (to_item_id) REFERENCES public.knowledge_items(id);


--
-- Name: knowledge_item_sources knowledge_item_sources_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_item_sources
    ADD CONSTRAINT knowledge_item_sources_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id);


--
-- Name: knowledge_item_sources knowledge_item_sources_knowledge_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_item_sources
    ADD CONSTRAINT knowledge_item_sources_knowledge_item_id_fkey FOREIGN KEY (knowledge_item_id) REFERENCES public.knowledge_items(id);


--
-- Name: knowledge_item_sources knowledge_item_sources_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_item_sources
    ADD CONSTRAINT knowledge_item_sources_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.sources(id);


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
-- Name: knowledge_items knowledge_items_created_by_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_items
    ADD CONSTRAINT knowledge_items_created_by_agent_id_fkey FOREIGN KEY (created_by_agent_id) REFERENCES public.agents(id);


--
-- Name: knowledge_items knowledge_items_created_by_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_items
    ADD CONSTRAINT knowledge_items_created_by_run_id_fkey FOREIGN KEY (created_by_run_id) REFERENCES public.runs(id);


--
-- Name: knowledge_items knowledge_items_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_items
    ADD CONSTRAINT knowledge_items_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id);


--
-- Name: knowledge_items knowledge_items_created_from_proposal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_items
    ADD CONSTRAINT knowledge_items_created_from_proposal_id_fkey FOREIGN KEY (created_from_proposal_id) REFERENCES public.proposals(id);


--
-- Name: knowledge_items knowledge_items_owner_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_items
    ADD CONSTRAINT knowledge_items_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES public.users(id);


--
-- Name: knowledge_items knowledge_items_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_items
    ADD CONSTRAINT knowledge_items_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- Name: knowledge_items knowledge_items_source_activity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_items
    ADD CONSTRAINT knowledge_items_source_activity_id_fkey FOREIGN KEY (source_activity_id) REFERENCES public.activity_records(id);


--
-- Name: knowledge_items knowledge_items_source_artifact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_items
    ADD CONSTRAINT knowledge_items_source_artifact_id_fkey FOREIGN KEY (source_artifact_id) REFERENCES public.artifacts(id);


--
-- Name: knowledge_items knowledge_items_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_items
    ADD CONSTRAINT knowledge_items_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: knowledge_items knowledge_items_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_items
    ADD CONSTRAINT knowledge_items_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id);


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
-- Name: memory_entries memory_entries_source_activity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_entries
    ADD CONSTRAINT memory_entries_source_activity_id_fkey FOREIGN KEY (source_activity_id) REFERENCES public.activity_records(id);


--
-- Name: memory_entries memory_entries_source_artifact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_entries
    ADD CONSTRAINT memory_entries_source_artifact_id_fkey FOREIGN KEY (source_artifact_id) REFERENCES public.artifacts(id);


--
-- Name: memory_entries memory_entries_source_proposal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_entries
    ADD CONSTRAINT memory_entries_source_proposal_id_fkey FOREIGN KEY (source_proposal_id) REFERENCES public.proposals(id);


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
    ADD CONSTRAINT memory_entries_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id);


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
-- Name: note_collection_items note_collection_items_collection_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.note_collection_items
    ADD CONSTRAINT note_collection_items_collection_id_fkey FOREIGN KEY (collection_id) REFERENCES public.note_collections(id) ON DELETE CASCADE;


--
-- Name: note_collection_items note_collection_items_note_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.note_collection_items
    ADD CONSTRAINT note_collection_items_note_id_fkey FOREIGN KEY (note_id) REFERENCES public.notes(id) ON DELETE CASCADE;


--
-- Name: note_collections note_collections_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.note_collections
    ADD CONSTRAINT note_collections_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.note_collections(id) ON DELETE SET NULL;


--
-- Name: note_collections note_collections_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.note_collections
    ADD CONSTRAINT note_collections_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: notes notes_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notes
    ADD CONSTRAINT notes_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id);


--
-- Name: notes notes_created_from_activity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notes
    ADD CONSTRAINT notes_created_from_activity_id_fkey FOREIGN KEY (created_from_activity_id) REFERENCES public.activity_records(id);


--
-- Name: notes notes_primary_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notes
    ADD CONSTRAINT notes_primary_project_id_fkey FOREIGN KEY (primary_project_id) REFERENCES public.projects(id);


--
-- Name: notes notes_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notes
    ADD CONSTRAINT notes_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


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
-- Name: project_workspaces project_workspaces_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_workspaces
    ADD CONSTRAINT project_workspaces_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- Name: project_workspaces project_workspaces_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_workspaces
    ADD CONSTRAINT project_workspaces_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id);


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
    ADD CONSTRAINT proposals_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id);


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
    ADD CONSTRAINT run_events_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id);


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
    ADD CONSTRAINT run_steps_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id);


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
-- Name: runs runs_execution_plane_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runs
    ADD CONSTRAINT runs_execution_plane_id_fkey FOREIGN KEY (execution_plane_id) REFERENCES public.execution_planes(id);


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
    ADD CONSTRAINT runs_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id);


--
-- Name: runtime_tool_bindings runtime_tool_bindings_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_tool_bindings
    ADD CONSTRAINT runtime_tool_bindings_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id);


--
-- Name: runtime_tool_bindings runtime_tool_bindings_execution_plane_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_tool_bindings
    ADD CONSTRAINT runtime_tool_bindings_execution_plane_id_fkey FOREIGN KEY (execution_plane_id) REFERENCES public.execution_planes(id);


--
-- Name: runtime_tool_bindings runtime_tool_bindings_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_tool_bindings
    ADD CONSTRAINT runtime_tool_bindings_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


--
-- Name: runtime_tool_bindings runtime_tool_bindings_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_tool_bindings
    ADD CONSTRAINT runtime_tool_bindings_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id);


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
    ADD CONSTRAINT sessions_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id);


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
-- Name: sources sources_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sources
    ADD CONSTRAINT sources_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id);


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
-- Name: space_assistant_settings space_assistant_settings_space_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.space_assistant_settings
    ADD CONSTRAINT space_assistant_settings_space_id_fkey FOREIGN KEY (space_id) REFERENCES public.spaces(id);


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
    ADD CONSTRAINT tasks_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id);


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
    ADD CONSTRAINT validation_recipes_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id);


--
-- Name: working_dirs working_dirs_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.working_dirs
    ADD CONSTRAINT working_dirs_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);


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
    ADD CONSTRAINT workspace_intake_profiles_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id);


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
    ADD CONSTRAINT workspace_profiles_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id);


--
-- Name: workspace_source_bindings workspace_source_bindings_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_source_bindings
    ADD CONSTRAINT workspace_source_bindings_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id);


--
-- Name: workspace_source_bindings workspace_source_bindings_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_source_bindings
    ADD CONSTRAINT workspace_source_bindings_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);


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
    ADD CONSTRAINT workspace_source_bindings_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id);


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
-- PostgreSQL database dump complete
--
