-- Schema fixture for server memory APPLY integration tests
-- (testcontainers). SOURCE OF TRUTH: server migrations for
-- MemoryEntry + ProvenanceLink + MemoryRelation + Space.
-- Cross-table FOREIGN KEYs are stripped so it loads into an empty DB.
-- This fixture intentionally mirrors NOT NULL columns without server defaults;
-- columns the appliers write are provided explicitly.

CREATE TABLE public.spaces (
    id character varying(36) NOT NULL,
    type character varying(32) NOT NULL,
    CONSTRAINT spaces_pkey PRIMARY KEY (id)
);

CREATE TABLE public.memory_entries (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    scope_type character varying(32) NOT NULL,
    scope_id character varying(36),
    memory_type character varying(64) NOT NULL,
    content text NOT NULL,
    status character varying(32) NOT NULL DEFAULT 'active',
    source_proposal_id character varying(36),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    subject_user_id character varying(36),
    owner_user_id character varying(36),
    sensitivity_level character varying(32) NOT NULL DEFAULT 'normal',
    selected_user_ids jsonb,
    last_confirmed_at timestamp with time zone,
    workspace_id character varying(36),
    project_id character varying(36),
    agent_id character varying(36),
    namespace character varying(255),
    title character varying(512),
    visibility character varying(32) NOT NULL DEFAULT 'private',
    confidence double precision NOT NULL DEFAULT 1,
    importance double precision NOT NULL DEFAULT 0.5,
    source_id character varying(36),
    source_activity_id character varying(36),
    created_by character varying(64),
    approved_by character varying(64),
    deleted_at timestamp with time zone,
    version integer NOT NULL DEFAULT 1,
    access_count integer NOT NULL,
    last_accessed_at timestamp with time zone,
    tags jsonb,
    memory_layer character varying(32),
    memory_kind character varying(64),
    created_from_proposal_id character varying(36),
    root_memory_id character varying(36),
    supersedes_memory_id character varying(36),
    source_trust character varying(64),
    CONSTRAINT memory_entries_pkey PRIMARY KEY (id)
);

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
    CONSTRAINT provenance_links_pkey PRIMARY KEY (id)
);

CREATE TABLE public.proposals (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    proposal_type character varying(64) NOT NULL,
    status character varying(32) NOT NULL,
    payload_json jsonb NOT NULL,
    reviewed_at timestamp with time zone,
    reviewed_by character varying(36),
    created_by_user_id character varying(36),
    created_by_run_id character varying(36),
    workspace_id character varying(36),
    title character varying(512),
    CONSTRAINT proposals_pkey PRIMARY KEY (id)
);

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
    CONSTRAINT memory_relations_pkey PRIMARY KEY (id)
);
