-- Schema fixture for server Custom Source materializer integration tests
-- (testcontainers). SOURCE OF TRUTH: server/migrations/0001_baseline.sql.
-- Mirrors the tables CustomSourceMaterializationService touches. Cross-table
-- FOREIGN KEYs to tables outside this fixture are stripped so it loads into
-- an empty DB; CHECK / NOT NULL constraints are kept verbatim. Regenerate
-- when these tables' columns/constraints change.

CREATE TABLE public.source_connections (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    last_handler_run_id character varying(36),
    CONSTRAINT source_connections_pkey PRIMARY KEY (id)
);

CREATE TABLE public.source_handler_runs (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    source_connection_id character varying(36) NOT NULL,
    handler_version_id character varying(36) NOT NULL,
    status character varying(32) NOT NULL,
    output_artifact_id character varying(36),
    validation_result_json jsonb,
    created_at timestamp with time zone NOT NULL,
    completed_at timestamp with time zone,
    CONSTRAINT source_handler_runs_pkey PRIMARY KEY (id),
    CONSTRAINT ck_source_handler_runs_status CHECK (((status)::text = ANY ((ARRAY['queued'::character varying, 'running'::character varying, 'succeeded'::character varying, 'failed'::character varying, 'validation_failed'::character varying, 'blocked'::character varying])::text[])))
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

CREATE TABLE public.intake_items (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    connection_id character varying(36),
    item_type character varying(64) NOT NULL,
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
    metadata_json jsonb,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT intake_items_pkey PRIMARY KEY (id),
    CONSTRAINT ck_intake_items_content_state CHECK (((content_state)::text = ANY ((ARRAY['metadata_only'::character varying, 'excerpt_saved'::character varying, 'content_queued'::character varying, 'content_saved'::character varying, 'snapshot_queued'::character varying, 'snapshot_saved'::character varying, 'extraction_failed'::character varying, 'content_unavailable'::character varying])::text[]))),
    CONSTRAINT ck_intake_items_item_type CHECK (((item_type)::text = ANY ((ARRAY['external_url'::character varying, 'feed_entry'::character varying, 'activity_record'::character varying, 'artifact'::character varying, 'run_event'::character varying, 'file'::character varying, 'document'::character varying, 'log'::character varying])::text[]))),
    CONSTRAINT ck_intake_items_read_status CHECK (((read_status)::text = ANY ((ARRAY['unread'::character varying, 'skimmed'::character varying, 'read'::character varying, 'discussed'::character varying])::text[]))),
    CONSTRAINT ck_intake_items_retention_policy CHECK (((retention_policy)::text = ANY ((ARRAY['metadata_only'::character varying, 'summary_only'::character varying, 'full_text'::character varying, 'full_snapshot'::character varying, 'archived'::character varying])::text[]))),
    CONSTRAINT ck_intake_items_status CHECK (((status)::text = ANY ((ARRAY['new'::character varying, 'triaged'::character varying, 'selected'::character varying, 'ignored'::character varying, 'archived'::character varying])::text[])))
);

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
    CONSTRAINT source_snapshots_pkey PRIMARY KEY (id),
    CONSTRAINT ck_source_snapshots_capture_method CHECK (((capture_method)::text = ANY ((ARRAY['manual'::character varying, 'connection_scan'::character varying, 'full_text'::character varying, 'snapshot'::character varying, 'internal'::character varying, 'custom_source_handler'::character varying, 'source_recipe'::character varying])::text[]))),
    CONSTRAINT ck_source_snapshots_snapshot_type CHECK (((snapshot_type)::text = ANY ((ARRAY['metadata'::character varying, 'raw'::character varying, 'extracted'::character varying, 'summary'::character varying])::text[]))),
    CONSTRAINT ck_source_snapshots_trust_level CHECK (((trust_level)::text = ANY ((ARRAY['trusted'::character varying, 'normal'::character varying, 'untrusted'::character varying])::text[])))
);

CREATE TABLE public.extracted_evidence (
    id character varying(36) NOT NULL,
    space_id character varying(36) NOT NULL,
    intake_item_id character varying(36),
    source_object_type character varying(64),
    source_object_id character varying(36),
    evidence_type character varying(64) NOT NULL,
    title character varying(1024) NOT NULL,
    content_excerpt character varying(4096),
    content_hash character varying(128),
    trust_level character varying(32) NOT NULL,
    extraction_method character varying(64) NOT NULL,
    confidence double precision,
    status character varying(32) NOT NULL,
    metadata_json jsonb,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT extracted_evidence_pkey PRIMARY KEY (id),
    CONSTRAINT ck_extracted_evidence_evidence_type CHECK (((evidence_type)::text = ANY ((ARRAY['document'::character varying, 'excerpt'::character varying, 'event'::character varying, 'log'::character varying, 'artifact'::character varying, 'claim'::character varying, 'summary'::character varying])::text[]))),
    CONSTRAINT ck_extracted_evidence_status CHECK (((status)::text = ANY ((ARRAY['candidate'::character varying, 'active'::character varying, 'rejected'::character varying, 'archived'::character varying])::text[]))),
    CONSTRAINT ck_extracted_evidence_trust_level CHECK (((trust_level)::text = ANY ((ARRAY['trusted'::character varying, 'normal'::character varying, 'untrusted'::character varying])::text[])))
);
