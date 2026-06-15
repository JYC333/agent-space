-- Schema fixture for control-plane sessions integration tests (testcontainers).
-- SOURCE OF TRUTH: backend alembic migrations / backend/app/models.py.
-- Mirrors the tables the TS sessions repository touches. Cross-table FOREIGN
-- KEYs are stripped so it loads into an empty DB; CHECK / column-type / NOT NULL
-- constraints (the ones that catch real SQL bugs — e.g. the Python-only default
-- columns id/status/created_at/updated_at that a raw INSERT must supply) are
-- kept verbatim. Regenerate when these tables' columns/constraints change.

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
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT sessions_pkey PRIMARY KEY (id)
);

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
    CONSTRAINT session_summaries_pkey PRIMARY KEY (id),
    CONSTRAINT ck_session_summaries_status CHECK (
        ((status)::text = ANY ((ARRAY['active'::character varying, 'superseded'::character varying])::text[]))
    ),
    CONSTRAINT uq_session_summaries_session_version UNIQUE (session_id, version)
);

CREATE UNIQUE INDEX ix_session_summaries_one_active_per_session
    ON public.session_summaries USING btree (session_id)
    WHERE ((status)::text = 'active'::text);

CREATE TABLE public.messages (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    session_id character varying(36) NOT NULL,
    user_id character varying(36),
    role character varying(32) NOT NULL,
    content text NOT NULL,
    metadata_json jsonb,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT messages_pkey PRIMARY KEY (id),
    CONSTRAINT ck_messages_role CHECK (
        ((role)::text = ANY ((ARRAY['user'::character varying, 'assistant'::character varying, 'system'::character varying, 'tool'::character varying])::text[]))
    )
);
