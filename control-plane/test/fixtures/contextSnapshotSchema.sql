-- Schema fixture for control-plane context-snapshot integration tests
-- (testcontainers). SOURCE OF TRUTH: backend alembic migrations /
-- backend/app/models.py. Mirrors the two tables the TS context snapshot
-- repository touches. Cross-table FOREIGN KEYs are stripped so it loads into an
-- empty DB; CHECK / NOT NULL / column-type constraints (the ones that catch real
-- SQL bugs — the Python-only default columns id/metadata_json/created_at a raw
-- INSERT must supply, and the item_type CHECK) are kept verbatim. Regenerate
-- when these tables' columns/constraints change.

CREATE TABLE public.context_snapshots (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    source_refs_json jsonb NOT NULL,
    compiled_summary text,
    token_estimate integer,
    relevant_period_start timestamp with time zone,
    relevant_period_end timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    retrieval_trace_json jsonb,
    token_budget_json jsonb,
    agent_id character varying(36),
    session_id character varying(36),
    run_id character varying(36),
    request_json jsonb,
    CONSTRAINT context_snapshots_pkey PRIMARY KEY (id)
);

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
    CONSTRAINT context_snapshot_items_pkey PRIMARY KEY (id),
    CONSTRAINT ck_context_snapshot_items_item_type CHECK (
        ((item_type)::text = ANY ((ARRAY[
            'memory'::character varying, 'knowledge_item'::character varying,
            'source'::character varying, 'activity_record'::character varying,
            'task'::character varying, 'idea'::character varying,
            'project'::character varying, 'workspace'::character varying,
            'run'::character varying, 'proposal'::character varying,
            'artifact'::character varying, 'manual_context'::character varying
        ])::text[]))
    )
);

CREATE INDEX ix_context_snapshot_items_snapshot
    ON public.context_snapshot_items USING btree (context_snapshot_id);
