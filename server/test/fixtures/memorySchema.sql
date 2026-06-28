-- Schema fixture for server memory-read integration tests
-- (testcontainers). SOURCE OF TRUTH: server/migrations.
-- Mirrors the columns the server memory
-- read model SELECTs and the constraints that affect parsing (jsonb,
-- timestamptz, float8, integer). Cross-table FOREIGN KEYs are stripped so it
-- loads into an empty DB. Regenerate when these columns change.

CREATE TABLE public.memory_entries (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    subject_user_id character varying(36),
    owner_user_id character varying(36),
    workspace_id character varying(36),
    scope_type character varying(32) NOT NULL,
    namespace character varying(255),
    memory_type character varying(64) NOT NULL,
    title character varying(512),
    content text,
    status character varying(32) NOT NULL,
    visibility character varying(32) NOT NULL,
    sensitivity_level character varying(32) NOT NULL DEFAULT 'normal',
    selected_user_ids jsonb,
    last_confirmed_at timestamp with time zone,
    confidence double precision NOT NULL DEFAULT 1,
    importance double precision NOT NULL DEFAULT 0.5,
    source_id character varying(36),
    created_by character varying(36),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    deleted_at timestamp with time zone,
    version integer NOT NULL DEFAULT 1,
    tags jsonb,
    memory_layer character varying(64),
    source_trust character varying(64),
    created_from_proposal_id character varying(36),
    root_memory_id character varying(36),
    supersedes_memory_id character varying(36),
    project_id character varying(36),
    access_count integer NOT NULL DEFAULT 0,
    last_accessed_at timestamp with time zone,
    last_retrieved_at timestamp with time zone,
    CONSTRAINT memory_entries_pkey PRIMARY KEY (id)
);

CREATE TABLE public.projects (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    owner_user_id character varying(36),
    deleted_at timestamp with time zone,
    CONSTRAINT projects_pkey PRIMARY KEY (id)
);

-- Minimal spaces + project_members for the project-level memory access gate
-- (canAccessProject / accessibleProjectIds). SOURCE OF TRUTH: server/migrations.
CREATE TABLE public.spaces (
    id character varying(36) NOT NULL,
    type character varying(32) NOT NULL DEFAULT 'household',
    CONSTRAINT spaces_pkey PRIMARY KEY (id)
);

CREATE TABLE public.project_members (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    project_id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    role character varying(32) NOT NULL,
    status character varying(32) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT project_members_pkey PRIMARY KEY (id)
);

-- Read-access audit (slice 7a). SOURCE OF TRUTH: models.py MemoryReadTrace.
-- Cross-table FOREIGN KEYs are stripped so the fixture loads into an empty DB.
CREATE TABLE public.memory_access_logs (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    memory_id character varying(36) NOT NULL,
    user_id character varying(36),
    agent_id character varying(36),
    run_id character varying(36),
    access_type character varying(64) NOT NULL,
    reason text,
    accessed_at timestamp with time zone NOT NULL,
    CONSTRAINT memory_access_logs_pkey PRIMARY KEY (id)
);

CREATE TABLE public.proposals (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    created_by_run_id character varying(36),
    proposal_type character varying(64) NOT NULL,
    status character varying(32) NOT NULL,
    risk_level character varying(32) NOT NULL,
    urgency character varying(32) NOT NULL,
    preview boolean NOT NULL DEFAULT false,
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
    visibility character varying(32) NOT NULL DEFAULT 'space_shared',
    project_id character varying(36),
    CONSTRAINT proposals_pkey PRIMARY KEY (id),
    CONSTRAINT ck_proposals_risk_level CHECK (((risk_level)::text = ANY ((ARRAY['low'::character varying, 'medium'::character varying, 'high'::character varying, 'critical'::character varying])::text[]))),
    CONSTRAINT ck_proposals_urgency CHECK (((urgency)::text = ANY ((ARRAY['low'::character varying, 'normal'::character varying, 'high'::character varying, 'critical'::character varying])::text[])))
);
