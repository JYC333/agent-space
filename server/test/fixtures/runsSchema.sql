-- Schema fixture for server runs integration tests (testcontainers).
-- SOURCE OF TRUTH: server/migrations.
-- Generated via pg_dump -s of the dev PostgreSQL for the tables the server runs
-- repositories touch. Cross-table FOREIGN KEYs are stripped so it loads into an
-- empty DB; CHECK / UNIQUE / column-type constraints (the ones that catch real
-- SQL bugs) are kept verbatim where this fixture carries the full table surface.
-- Regenerate when these tables' columns/constraints change: see
-- server/test/integration/README or runsIntegration.test.ts.


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
    created_at timestamp with time zone NOT NULL
);

-- Minimal model_providers: the columns run-create model-config resolution reads
-- (space default provider lookup). SOURCE OF TRUTH: server/migrations.
CREATE TABLE public.model_providers (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    name character varying(256),
    provider_type character varying(64),
    default_model character varying(256),
    enabled boolean DEFAULT true NOT NULL,
    credential_id character varying(36),
    capabilities_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    config_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL
);

CREATE TABLE public.agents (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    owner_user_id character varying(36),
    name character varying(256) NOT NULL,
    status character varying(32) NOT NULL,
    current_version_id character varying(36),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    visibility character varying(32) NOT NULL,
    CONSTRAINT ck_agents_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'inactive'::character varying, 'archived'::character varying, 'disabled'::character varying])::text[])))
);

CREATE TABLE public.context_snapshots (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    source_refs_json jsonb NOT NULL,
    compiled_summary text,
    token_estimate integer,
    created_at timestamp with time zone NOT NULL,
    agent_id character varying(36),
    session_id character varying(36),
    run_id character varying(36),
    request_json jsonb
);

CREATE TABLE public.job_events (
    id character varying(36) NOT NULL,
    job_id character varying(36) NOT NULL,
    event_type character varying(32) NOT NULL,
    message text NOT NULL,
    data jsonb,
    created_at timestamp with time zone NOT NULL
);

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

-- Minimal artifacts table for post-run finalization's task-evaluation bridge.
CREATE TABLE public.artifacts (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    run_id character varying(36),
    created_at timestamp with time zone NOT NULL
);

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

CREATE TABLE public.run_execution_locks (
    run_id character varying(36) NOT NULL,
    locked_at timestamp with time zone NOT NULL,
    worker_id character varying(64) NOT NULL,
    job_id character varying(36)
);

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

CREATE TABLE public.runs (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    agent_id character varying(36) NOT NULL,
    agent_version_id character varying(36) NOT NULL,
    context_snapshot_id character varying(36),
    workspace_id character varying(36),
    session_id character varying(36),
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

-- Minimal task-domain tables for post-run finalization's task-evaluation bridge.
CREATE TABLE public.tasks (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    title character varying(512) NOT NULL,
    status character varying(32) NOT NULL,
    deleted_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

CREATE TABLE public.task_runs (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    task_id character varying(36) NOT NULL,
    run_id character varying(36) NOT NULL,
    role character varying(32) NOT NULL,
    created_at timestamp with time zone NOT NULL
);

CREATE TABLE public.task_evaluations (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    task_id character varying(36) NOT NULL,
    run_id character varying(36),
    run_evaluation_id character varying(36),
    evaluator_type character varying(64) NOT NULL,
    score double precision,
    confidence double precision,
    summary text,
    checklist_json jsonb,
    known_issues_json jsonb,
    evidence_artifact_ids jsonb,
    recommendation character varying(64),
    created_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY public.actors
    ADD CONSTRAINT actors_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.agent_versions
    ADD CONSTRAINT agent_versions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.agents
    ADD CONSTRAINT agents_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.context_snapshots
    ADD CONSTRAINT context_snapshots_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.job_events
    ADD CONSTRAINT job_events_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.jobs
    ADD CONSTRAINT jobs_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.run_events
    ADD CONSTRAINT run_events_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.run_execution_locks
    ADD CONSTRAINT run_execution_locks_pkey PRIMARY KEY (run_id);

ALTER TABLE ONLY public.run_evaluations
    ADD CONSTRAINT run_evaluations_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.run_finalizations
    ADD CONSTRAINT run_finalizations_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.run_steps
    ADD CONSTRAINT run_steps_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.runs
    ADD CONSTRAINT runs_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.task_runs
    ADD CONSTRAINT task_runs_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.task_evaluations
    ADD CONSTRAINT task_evaluations_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.run_events
    ADD CONSTRAINT uq_run_events_space_run_event_index UNIQUE (space_id, run_id, event_index);

ALTER TABLE ONLY public.run_steps
    ADD CONSTRAINT uq_run_steps_run_step_index UNIQUE (run_id, step_index);

ALTER TABLE ONLY public.run_finalizations
    ADD CONSTRAINT uq_run_finalizations_run_version UNIQUE (run_id, finalizer_version);

ALTER TABLE ONLY public.task_runs
    ADD CONSTRAINT uq_task_runs_task_run UNIQUE (task_id, run_id);

CREATE INDEX ix_actors_actor_type ON public.actors USING btree (actor_type);

CREATE INDEX ix_actors_agent_id ON public.actors USING btree (agent_id);

CREATE INDEX ix_actors_service_name ON public.actors USING btree (service_name);

CREATE INDEX ix_actors_space_id ON public.actors USING btree (space_id);

CREATE INDEX ix_actors_status ON public.actors USING btree (status);

CREATE INDEX ix_actors_user_id ON public.actors USING btree (user_id);

CREATE INDEX ix_job_events_job_id ON public.job_events USING btree (job_id);

CREATE INDEX ix_jobs_agent_id ON public.jobs USING btree (agent_id);

CREATE INDEX ix_jobs_claim_pending ON public.jobs USING btree (priority DESC, scheduled_at) WHERE ((status)::text = 'pending'::text);

CREATE INDEX ix_jobs_job_type ON public.jobs USING btree (job_type);

CREATE INDEX ix_jobs_space_id ON public.jobs USING btree (space_id);

CREATE INDEX ix_jobs_status ON public.jobs USING btree (status);

CREATE INDEX ix_jobs_type_claim_pending ON public.jobs USING btree (job_type, priority DESC, scheduled_at) WHERE ((status)::text = 'pending'::text);

CREATE INDEX ix_jobs_user_id ON public.jobs USING btree (user_id);

CREATE INDEX ix_jobs_workspace_id ON public.jobs USING btree (workspace_id);

CREATE INDEX ix_run_events_actor_id ON public.run_events USING btree (actor_id);

CREATE INDEX ix_run_events_artifact_id ON public.run_events USING btree (artifact_id);

CREATE INDEX ix_run_events_created_at ON public.run_events USING btree (created_at);

CREATE INDEX ix_run_events_error_code ON public.run_events USING btree (error_code);

CREATE INDEX ix_run_events_event_type ON public.run_events USING btree (event_type);

CREATE INDEX ix_run_events_proposal_id ON public.run_events USING btree (proposal_id);

CREATE INDEX ix_run_events_run_id ON public.run_events USING btree (run_id);

CREATE INDEX ix_run_events_space_id ON public.run_events USING btree (space_id);

CREATE INDEX ix_run_events_status ON public.run_events USING btree (status);

CREATE INDEX ix_run_events_step_id ON public.run_events USING btree (step_id);

CREATE INDEX ix_run_events_workspace_id ON public.run_events USING btree (workspace_id);

CREATE INDEX ix_run_steps_actor_id ON public.run_steps USING btree (actor_id);

CREATE INDEX ix_run_steps_artifact_id ON public.run_steps USING btree (artifact_id);

CREATE INDEX ix_run_steps_parent_step_id ON public.run_steps USING btree (parent_step_id);

CREATE INDEX ix_run_steps_proposal_id ON public.run_steps USING btree (proposal_id);

CREATE INDEX ix_run_steps_run_id ON public.run_steps USING btree (run_id);

CREATE INDEX ix_run_steps_session_id ON public.run_steps USING btree (session_id);

CREATE INDEX ix_run_steps_space_id ON public.run_steps USING btree (space_id);

CREATE INDEX ix_run_steps_space_run_index ON public.run_steps USING btree (space_id, run_id, step_index);

CREATE INDEX ix_run_steps_status ON public.run_steps USING btree (status);

CREATE INDEX ix_run_steps_step_type ON public.run_steps USING btree (step_type);

CREATE INDEX ix_run_steps_task_id ON public.run_steps USING btree (task_id);

CREATE INDEX ix_run_steps_workspace_id ON public.run_steps USING btree (workspace_id);

CREATE INDEX ix_runs_agent_id ON public.runs USING btree (agent_id);

CREATE INDEX ix_runs_agent_version_id ON public.runs USING btree (agent_version_id);

CREATE INDEX ix_runs_context_snapshot_id ON public.runs USING btree (context_snapshot_id);

CREATE INDEX ix_runs_execution_plane_id ON public.runs USING btree (execution_plane_id);

CREATE INDEX ix_runs_instructed_by_user_id ON public.runs USING btree (instructed_by_user_id);

CREATE INDEX ix_runs_mode ON public.runs USING btree (mode);

CREATE INDEX ix_runs_model_provider_id ON public.runs USING btree (model_provider_id);

CREATE INDEX ix_runs_parent_run_id ON public.runs USING btree (parent_run_id);

CREATE INDEX ix_runs_project_id ON public.runs USING btree (project_id);

CREATE INDEX ix_runs_run_type ON public.runs USING btree (run_type);

CREATE INDEX ix_runs_session_id ON public.runs USING btree (session_id);

CREATE INDEX ix_runs_space_id ON public.runs USING btree (space_id);

CREATE INDEX ix_runs_status ON public.runs USING btree (status);

CREATE INDEX ix_runs_task_id ON public.runs USING btree (task_id);

CREATE INDEX ix_runs_trigger_origin ON public.runs USING btree (trigger_origin);

CREATE INDEX ix_runs_workspace_id ON public.runs USING btree (workspace_id);
