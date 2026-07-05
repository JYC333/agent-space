CREATE TABLE public.research_atlas_venues (
    id varchar(36) NOT NULL,
    space_id varchar(36) NOT NULL,
    name varchar(512) NOT NULL,
    venue_type varchar(16) NOT NULL DEFAULT 'other',
    issns jsonb NOT NULL DEFAULT '[]'::jsonb,
    abbreviations jsonb NOT NULL DEFAULT '[]'::jsonb,
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    merged_into_id varchar(36),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT research_atlas_venues_pkey PRIMARY KEY (id),
    CONSTRAINT research_atlas_venues_space_nonempty CHECK (length(trim(space_id)) > 0),
    CONSTRAINT research_atlas_venues_name_nonempty CHECK (length(trim(name)) > 0),
    CONSTRAINT research_atlas_venues_type_check CHECK (venue_type IN ('journal', 'conference', 'workshop', 'repository', 'other')),
    CONSTRAINT research_atlas_venues_merged_fkey FOREIGN KEY (merged_into_id)
        REFERENCES public.research_atlas_venues(id) ON DELETE SET NULL
);

CREATE TABLE public.research_atlas_institutions (
    id varchar(36) NOT NULL,
    space_id varchar(36) NOT NULL,
    name varchar(512) NOT NULL,
    ror_id varchar(32),
    country_code varchar(8),
    institution_type varchar(32),
    homepage_url text,
    aliases jsonb NOT NULL DEFAULT '[]'::jsonb,
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    merged_into_id varchar(36),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT research_atlas_institutions_pkey PRIMARY KEY (id),
    CONSTRAINT research_atlas_institutions_space_nonempty CHECK (length(trim(space_id)) > 0),
    CONSTRAINT research_atlas_institutions_name_nonempty CHECK (length(trim(name)) > 0),
    CONSTRAINT research_atlas_institutions_merged_fkey FOREIGN KEY (merged_into_id)
        REFERENCES public.research_atlas_institutions(id) ON DELETE SET NULL
);

CREATE TABLE public.research_atlas_scholars (
    id varchar(36) NOT NULL,
    space_id varchar(36) NOT NULL,
    display_name varchar(512) NOT NULL,
    orcid varchar(32),
    alternate_names jsonb NOT NULL DEFAULT '[]'::jsonb,
    homepage_url text,
    h_index integer,
    works_count integer,
    last_known_institution_id varchar(36),
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    merged_into_id varchar(36),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT research_atlas_scholars_pkey PRIMARY KEY (id),
    CONSTRAINT research_atlas_scholars_space_nonempty CHECK (length(trim(space_id)) > 0),
    CONSTRAINT research_atlas_scholars_name_nonempty CHECK (length(trim(display_name)) > 0),
    CONSTRAINT research_atlas_scholars_h_index_nonnegative CHECK (h_index IS NULL OR h_index >= 0),
    CONSTRAINT research_atlas_scholars_works_count_nonnegative CHECK (works_count IS NULL OR works_count >= 0),
    CONSTRAINT research_atlas_scholars_institution_fkey FOREIGN KEY (last_known_institution_id)
        REFERENCES public.research_atlas_institutions(id) ON DELETE SET NULL,
    CONSTRAINT research_atlas_scholars_merged_fkey FOREIGN KEY (merged_into_id)
        REFERENCES public.research_atlas_scholars(id) ON DELETE SET NULL
);

CREATE TABLE public.research_atlas_papers (
    id varchar(36) NOT NULL,
    space_id varchar(36) NOT NULL,
    title text NOT NULL,
    abstract text,
    publication_date date,
    publication_year integer,
    paper_type varchar(32) NOT NULL DEFAULT 'other',
    venue_id varchar(36),
    language varchar(16),
    doi varchar(255),
    arxiv_id varchar(64),
    oa_status varchar(16) NOT NULL DEFAULT 'unknown',
    best_oa_url text,
    pdf_artifact_id varchar(36),
    cited_by_count integer,
    reference_count integer,
    raw_author_names jsonb NOT NULL DEFAULT '[]'::jsonb,
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    merged_into_id varchar(36),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT research_atlas_papers_pkey PRIMARY KEY (id),
    CONSTRAINT research_atlas_papers_space_nonempty CHECK (length(trim(space_id)) > 0),
    CONSTRAINT research_atlas_papers_title_nonempty CHECK (length(trim(title)) > 0),
    CONSTRAINT research_atlas_papers_type_check CHECK (paper_type IN ('article', 'preprint', 'book_chapter', 'thesis', 'dataset', 'other')),
    CONSTRAINT research_atlas_papers_oa_check CHECK (oa_status IN ('gold', 'green', 'hybrid', 'bronze', 'closed', 'unknown')),
    CONSTRAINT research_atlas_papers_year_check CHECK (publication_year IS NULL OR publication_year BETWEEN 1000 AND 3000),
    CONSTRAINT research_atlas_papers_cited_by_count_check CHECK (cited_by_count IS NULL OR cited_by_count >= 0),
    CONSTRAINT research_atlas_papers_reference_count_check CHECK (reference_count IS NULL OR reference_count >= 0),
    CONSTRAINT research_atlas_papers_venue_fkey FOREIGN KEY (venue_id)
        REFERENCES public.research_atlas_venues(id) ON DELETE SET NULL,
    CONSTRAINT research_atlas_papers_merged_fkey FOREIGN KEY (merged_into_id)
        REFERENCES public.research_atlas_papers(id) ON DELETE SET NULL
);

CREATE TABLE public.research_atlas_source_records (
    id varchar(36) NOT NULL,
    space_id varchar(36) NOT NULL,
    connector varchar(32) NOT NULL,
    external_id varchar(512) NOT NULL,
    entity_type varchar(32) NOT NULL,
    payload_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    payload_artifact_id varchar(36),
    content_hash varchar(128),
    fetched_at timestamptz NOT NULL DEFAULT now(),
    fetch_status varchar(16) NOT NULL DEFAULT 'ok',
    intake_item_id varchar(36),
    refresh_after timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT research_atlas_source_records_pkey PRIMARY KEY (id),
    CONSTRAINT research_atlas_source_records_space_nonempty CHECK (length(trim(space_id)) > 0),
    CONSTRAINT research_atlas_source_records_connector_check CHECK (connector IN ('openalex', 'crossref', 's2', 'arxiv', 'pubmed', 'core', 'unpaywall', 'ror', 'orcid', 'opencitations', 'zotero', 'intake', 'manual')),
    CONSTRAINT research_atlas_source_records_entity_type_check CHECK (entity_type IN ('paper', 'scholar', 'institution', 'venue', 'group', 'topic')),
    CONSTRAINT research_atlas_source_records_status_check CHECK (fetch_status IN ('ok', 'not_found', 'error'))
);

CREATE TABLE public.research_atlas_authorships (
    id varchar(36) NOT NULL,
    space_id varchar(36) NOT NULL,
    paper_id varchar(36) NOT NULL,
    scholar_id varchar(36),
    author_position integer NOT NULL,
    raw_author_name varchar(512) NOT NULL,
    is_corresponding boolean NOT NULL DEFAULT false,
    raw_affiliation_text text,
    institution_id varchar(36),
    confidence double precision,
    source varchar(32),
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT research_atlas_authorships_pkey PRIMARY KEY (id),
    CONSTRAINT research_atlas_authorships_space_nonempty CHECK (length(trim(space_id)) > 0),
    CONSTRAINT research_atlas_authorships_raw_name_nonempty CHECK (length(trim(raw_author_name)) > 0),
    CONSTRAINT research_atlas_authorships_position_positive CHECK (author_position > 0),
    CONSTRAINT research_atlas_authorships_confidence_check CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    CONSTRAINT research_atlas_authorships_paper_fkey FOREIGN KEY (paper_id)
        REFERENCES public.research_atlas_papers(id) ON DELETE CASCADE,
    CONSTRAINT research_atlas_authorships_scholar_fkey FOREIGN KEY (scholar_id)
        REFERENCES public.research_atlas_scholars(id) ON DELETE SET NULL,
    CONSTRAINT research_atlas_authorships_institution_fkey FOREIGN KEY (institution_id)
        REFERENCES public.research_atlas_institutions(id) ON DELETE SET NULL,
    CONSTRAINT research_atlas_authorships_paper_position_unique UNIQUE (paper_id, author_position)
);

CREATE TABLE public.research_atlas_external_ids (
    id varchar(36) NOT NULL,
    space_id varchar(36) NOT NULL,
    entity_type varchar(32) NOT NULL,
    entity_id varchar(36) NOT NULL,
    id_type varchar(32) NOT NULL,
    id_value varchar(512) NOT NULL,
    is_primary boolean NOT NULL DEFAULT false,
    confidence double precision,
    source_record_id varchar(36),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT research_atlas_external_ids_pkey PRIMARY KEY (id),
    CONSTRAINT research_atlas_external_ids_space_nonempty CHECK (length(trim(space_id)) > 0),
    CONSTRAINT research_atlas_external_ids_entity_type_check CHECK (entity_type IN ('paper', 'scholar', 'institution', 'venue', 'group', 'topic')),
    CONSTRAINT research_atlas_external_ids_id_type_check CHECK (id_type IN ('doi', 'arxiv', 'pmid', 'pmcid', 'openalex', 's2', 'mag', 'orcid', 'ror', 'issn', 'isbn', 'zotero_key', 'homepage_url')),
    CONSTRAINT research_atlas_external_ids_value_nonempty CHECK (length(trim(id_value)) > 0),
    CONSTRAINT research_atlas_external_ids_confidence_check CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    CONSTRAINT research_atlas_external_ids_source_record_fkey FOREIGN KEY (source_record_id)
        REFERENCES public.research_atlas_source_records(id) ON DELETE SET NULL,
    CONSTRAINT research_atlas_external_ids_unique UNIQUE (space_id, id_type, id_value)
);

CREATE TABLE public.research_atlas_entity_sources (
    id varchar(36) NOT NULL,
    space_id varchar(36) NOT NULL,
    entity_type varchar(32) NOT NULL,
    entity_id varchar(36) NOT NULL,
    source_record_id varchar(36) NOT NULL,
    role varchar(16) NOT NULL,
    confidence double precision,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT research_atlas_entity_sources_pkey PRIMARY KEY (id),
    CONSTRAINT research_atlas_entity_sources_space_nonempty CHECK (length(trim(space_id)) > 0),
    CONSTRAINT research_atlas_entity_sources_entity_type_check CHECK (entity_type IN ('paper', 'scholar', 'institution', 'venue', 'group', 'topic')),
    CONSTRAINT research_atlas_entity_sources_role_check CHECK (role IN ('created', 'enriched', 'confirmed')),
    CONSTRAINT research_atlas_entity_sources_confidence_check CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    CONSTRAINT research_atlas_entity_sources_source_record_fkey FOREIGN KEY (source_record_id)
        REFERENCES public.research_atlas_source_records(id) ON DELETE CASCADE,
    CONSTRAINT research_atlas_entity_sources_unique UNIQUE (entity_type, entity_id, source_record_id)
);

CREATE TABLE public.research_atlas_curation_events (
    id varchar(36) NOT NULL,
    space_id varchar(36) NOT NULL,
    entity_type varchar(32) NOT NULL,
    entity_id varchar(36) NOT NULL,
    event_type varchar(32) NOT NULL,
    field varchar(64),
    old_value jsonb,
    new_value jsonb,
    locked boolean NOT NULL DEFAULT false,
    actor_type varchar(16) NOT NULL,
    actor_user_id varchar(36),
    proposal_id varchar(36),
    reason text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT research_atlas_curation_events_pkey PRIMARY KEY (id),
    CONSTRAINT research_atlas_curation_events_space_nonempty CHECK (length(trim(space_id)) > 0),
    CONSTRAINT research_atlas_curation_events_entity_type_check CHECK (entity_type IN ('paper', 'scholar', 'institution', 'venue', 'group', 'topic')),
    CONSTRAINT research_atlas_curation_events_event_type_check CHECK (event_type IN ('field_correction', 'merge', 'unmerge', 'lock', 'unlock', 'delete')),
    CONSTRAINT research_atlas_curation_events_actor_type_check CHECK (actor_type IN ('user', 'agent', 'connector'))
);

CREATE TABLE public.research_atlas_sync_cursors (
    id varchar(36) NOT NULL,
    space_id varchar(36) NOT NULL,
    cursor_key varchar(128) NOT NULL,
    watermark_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    last_run_at timestamptz,
    last_error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT research_atlas_sync_cursors_pkey PRIMARY KEY (id),
    CONSTRAINT research_atlas_sync_cursors_space_nonempty CHECK (length(trim(space_id)) > 0),
    CONSTRAINT research_atlas_sync_cursors_key_nonempty CHECK (length(trim(cursor_key)) > 0),
    CONSTRAINT research_atlas_sync_cursors_watermark_object CHECK (jsonb_typeof(watermark_json) = 'object'),
    CONSTRAINT research_atlas_sync_cursors_unique UNIQUE (space_id, cursor_key)
);

CREATE TABLE public.research_atlas_project_papers (
    id varchar(36) NOT NULL,
    space_id varchar(36) NOT NULL,
    project_id varchar(36) NOT NULL,
    paper_id varchar(36) NOT NULL,
    status varchar(16) NOT NULL DEFAULT 'candidate',
    read_status varchar(16) NOT NULL DEFAULT 'unread',
    rating smallint,
    tags jsonb NOT NULL DEFAULT '[]'::jsonb,
    note text,
    pinned boolean NOT NULL DEFAULT false,
    added_by_user_id varchar(36),
    source varchar(32) NOT NULL DEFAULT 'manual',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT research_atlas_project_papers_pkey PRIMARY KEY (id),
    CONSTRAINT research_atlas_project_papers_space_nonempty CHECK (length(trim(space_id)) > 0),
    CONSTRAINT research_atlas_project_papers_project_nonempty CHECK (length(trim(project_id)) > 0),
    CONSTRAINT research_atlas_project_papers_status_check CHECK (status IN ('candidate', 'shortlist', 'reading', 'done', 'rejected')),
    CONSTRAINT research_atlas_project_papers_read_status_check CHECK (read_status IN ('unread', 'skimmed', 'read')),
    CONSTRAINT research_atlas_project_papers_rating_check CHECK (rating IS NULL OR rating BETWEEN 1 AND 5),
    CONSTRAINT research_atlas_project_papers_source_check CHECK (source IN ('manual', 'intake_sync', 'agent_proposal')),
    CONSTRAINT research_atlas_project_papers_paper_fkey FOREIGN KEY (paper_id)
        REFERENCES public.research_atlas_papers(id) ON DELETE CASCADE,
    CONSTRAINT research_atlas_project_papers_unique UNIQUE (project_id, paper_id)
);

CREATE TABLE public.research_atlas_departments (
    id varchar(36) NOT NULL,
    space_id varchar(36) NOT NULL,
    institution_id varchar(36) NOT NULL,
    name varchar(512) NOT NULL,
    aliases jsonb NOT NULL DEFAULT '[]'::jsonb,
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT research_atlas_departments_pkey PRIMARY KEY (id),
    CONSTRAINT research_atlas_departments_space_nonempty CHECK (length(trim(space_id)) > 0),
    CONSTRAINT research_atlas_departments_name_nonempty CHECK (length(trim(name)) > 0),
    CONSTRAINT research_atlas_departments_institution_fkey FOREIGN KEY (institution_id)
        REFERENCES public.research_atlas_institutions(id) ON DELETE CASCADE
);

CREATE TABLE public.research_atlas_topics (
    id varchar(36) NOT NULL,
    space_id varchar(36) NOT NULL,
    label varchar(256) NOT NULL,
    kind varchar(16) NOT NULL DEFAULT 'topic',
    taxonomy varchar(32) NOT NULL DEFAULT 'manual',
    external_ref varchar(128),
    parent_topic_id varchar(36),
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    merged_into_id varchar(36),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT research_atlas_topics_pkey PRIMARY KEY (id),
    CONSTRAINT research_atlas_topics_space_nonempty CHECK (length(trim(space_id)) > 0),
    CONSTRAINT research_atlas_topics_label_nonempty CHECK (length(trim(label)) > 0),
    CONSTRAINT research_atlas_topics_kind_check CHECK (kind IN ('field', 'subfield', 'topic', 'keyword', 'concept')),
    CONSTRAINT research_atlas_topics_parent_fkey FOREIGN KEY (parent_topic_id)
        REFERENCES public.research_atlas_topics(id) ON DELETE SET NULL,
    CONSTRAINT research_atlas_topics_merged_fkey FOREIGN KEY (merged_into_id)
        REFERENCES public.research_atlas_topics(id) ON DELETE SET NULL
);

CREATE TABLE public.research_atlas_research_groups (
    id varchar(36) NOT NULL,
    space_id varchar(36) NOT NULL,
    name varchar(512) NOT NULL,
    aliases jsonb NOT NULL DEFAULT '[]'::jsonb,
    homepage_url text,
    institution_id varchar(36),
    department_id varchar(36),
    pi_scholar_id varchar(36),
    status varchar(16) NOT NULL DEFAULT 'unknown',
    confidence double precision,
    curation_status varchar(16) NOT NULL DEFAULT 'user_curated',
    notes text,
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    merged_into_id varchar(36),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT research_atlas_research_groups_pkey PRIMARY KEY (id),
    CONSTRAINT research_atlas_research_groups_space_nonempty CHECK (length(trim(space_id)) > 0),
    CONSTRAINT research_atlas_research_groups_name_nonempty CHECK (length(trim(name)) > 0),
    CONSTRAINT research_atlas_research_groups_status_check CHECK (status IN ('active', 'dissolved', 'unknown')),
    CONSTRAINT research_atlas_research_groups_confidence_check CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    CONSTRAINT research_atlas_research_groups_curation_check CHECK (curation_status IN ('auto_inferred', 'user_curated')),
    CONSTRAINT research_atlas_research_groups_institution_fkey FOREIGN KEY (institution_id)
        REFERENCES public.research_atlas_institutions(id) ON DELETE SET NULL,
    CONSTRAINT research_atlas_research_groups_department_fkey FOREIGN KEY (department_id)
        REFERENCES public.research_atlas_departments(id) ON DELETE SET NULL,
    CONSTRAINT research_atlas_research_groups_pi_fkey FOREIGN KEY (pi_scholar_id)
        REFERENCES public.research_atlas_scholars(id) ON DELETE SET NULL,
    CONSTRAINT research_atlas_research_groups_merged_fkey FOREIGN KEY (merged_into_id)
        REFERENCES public.research_atlas_research_groups(id) ON DELETE SET NULL
);

CREATE TABLE public.research_atlas_affiliations (
    id varchar(36) NOT NULL,
    space_id varchar(36) NOT NULL,
    scholar_id varchar(36) NOT NULL,
    institution_id varchar(36) NOT NULL,
    department_id varchar(36),
    role varchar(64),
    start_date date,
    end_date date,
    confidence double precision,
    source varchar(32),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT research_atlas_affiliations_pkey PRIMARY KEY (id),
    CONSTRAINT research_atlas_affiliations_space_nonempty CHECK (length(trim(space_id)) > 0),
    CONSTRAINT research_atlas_affiliations_confidence_check CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    CONSTRAINT research_atlas_affiliations_scholar_fkey FOREIGN KEY (scholar_id)
        REFERENCES public.research_atlas_scholars(id) ON DELETE CASCADE,
    CONSTRAINT research_atlas_affiliations_institution_fkey FOREIGN KEY (institution_id)
        REFERENCES public.research_atlas_institutions(id) ON DELETE CASCADE,
    CONSTRAINT research_atlas_affiliations_department_fkey FOREIGN KEY (department_id)
        REFERENCES public.research_atlas_departments(id) ON DELETE SET NULL
);

CREATE TABLE public.research_atlas_citation_edges (
    id varchar(36) NOT NULL,
    space_id varchar(36) NOT NULL,
    citing_paper_id varchar(36) NOT NULL,
    cited_paper_id varchar(36) NOT NULL,
    source varchar(32) NOT NULL DEFAULT 'manual',
    confidence double precision,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT research_atlas_citation_edges_pkey PRIMARY KEY (id),
    CONSTRAINT research_atlas_citation_edges_space_nonempty CHECK (length(trim(space_id)) > 0),
    CONSTRAINT research_atlas_citation_edges_not_self CHECK (citing_paper_id <> cited_paper_id),
    CONSTRAINT research_atlas_citation_edges_confidence_check CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    CONSTRAINT research_atlas_citation_edges_citing_fkey FOREIGN KEY (citing_paper_id)
        REFERENCES public.research_atlas_papers(id) ON DELETE CASCADE,
    CONSTRAINT research_atlas_citation_edges_cited_fkey FOREIGN KEY (cited_paper_id)
        REFERENCES public.research_atlas_papers(id) ON DELETE CASCADE,
    CONSTRAINT research_atlas_citation_edges_unique UNIQUE (citing_paper_id, cited_paper_id)
);

CREATE TABLE public.research_atlas_group_memberships (
    id varchar(36) NOT NULL,
    space_id varchar(36) NOT NULL,
    group_id varchar(36) NOT NULL,
    scholar_id varchar(36) NOT NULL,
    role varchar(32) NOT NULL DEFAULT 'unknown',
    start_date date,
    end_date date,
    confidence double precision,
    source varchar(32) NOT NULL DEFAULT 'manual',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT research_atlas_group_memberships_pkey PRIMARY KEY (id),
    CONSTRAINT research_atlas_group_memberships_space_nonempty CHECK (length(trim(space_id)) > 0),
    CONSTRAINT research_atlas_group_memberships_role_check CHECK (role IN ('pi', 'faculty', 'postdoc', 'phd_student', 'masters_student', 'engineer', 'alumni', 'unknown')),
    CONSTRAINT research_atlas_group_memberships_confidence_check CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    CONSTRAINT research_atlas_group_memberships_group_fkey FOREIGN KEY (group_id)
        REFERENCES public.research_atlas_research_groups(id) ON DELETE CASCADE,
    CONSTRAINT research_atlas_group_memberships_scholar_fkey FOREIGN KEY (scholar_id)
        REFERENCES public.research_atlas_scholars(id) ON DELETE CASCADE,
    CONSTRAINT research_atlas_group_memberships_unique UNIQUE (group_id, scholar_id, role)
);

CREATE TABLE public.research_atlas_paper_topics (
    id varchar(36) NOT NULL,
    space_id varchar(36) NOT NULL,
    paper_id varchar(36) NOT NULL,
    topic_id varchar(36) NOT NULL,
    score double precision,
    source varchar(32) NOT NULL DEFAULT 'manual',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT research_atlas_paper_topics_pkey PRIMARY KEY (id),
    CONSTRAINT research_atlas_paper_topics_space_nonempty CHECK (length(trim(space_id)) > 0),
    CONSTRAINT research_atlas_paper_topics_score_check CHECK (score IS NULL OR (score >= 0 AND score <= 1)),
    CONSTRAINT research_atlas_paper_topics_paper_fkey FOREIGN KEY (paper_id)
        REFERENCES public.research_atlas_papers(id) ON DELETE CASCADE,
    CONSTRAINT research_atlas_paper_topics_topic_fkey FOREIGN KEY (topic_id)
        REFERENCES public.research_atlas_topics(id) ON DELETE CASCADE,
    CONSTRAINT research_atlas_paper_topics_unique UNIQUE (paper_id, topic_id)
);

CREATE TABLE public.research_atlas_scholar_topics (
    id varchar(36) NOT NULL,
    space_id varchar(36) NOT NULL,
    scholar_id varchar(36) NOT NULL,
    topic_id varchar(36) NOT NULL,
    score double precision,
    source varchar(32) NOT NULL DEFAULT 'manual',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT research_atlas_scholar_topics_pkey PRIMARY KEY (id),
    CONSTRAINT research_atlas_scholar_topics_space_nonempty CHECK (length(trim(space_id)) > 0),
    CONSTRAINT research_atlas_scholar_topics_score_check CHECK (score IS NULL OR (score >= 0 AND score <= 1)),
    CONSTRAINT research_atlas_scholar_topics_scholar_fkey FOREIGN KEY (scholar_id)
        REFERENCES public.research_atlas_scholars(id) ON DELETE CASCADE,
    CONSTRAINT research_atlas_scholar_topics_topic_fkey FOREIGN KEY (topic_id)
        REFERENCES public.research_atlas_topics(id) ON DELETE CASCADE,
    CONSTRAINT research_atlas_scholar_topics_unique UNIQUE (scholar_id, topic_id)
);

CREATE TABLE public.research_atlas_project_scholars (
    id varchar(36) NOT NULL,
    space_id varchar(36) NOT NULL,
    project_id varchar(36) NOT NULL,
    scholar_id varchar(36) NOT NULL,
    status varchar(16) NOT NULL DEFAULT 'candidate',
    tags jsonb NOT NULL DEFAULT '[]'::jsonb,
    note text,
    pinned boolean NOT NULL DEFAULT false,
    added_by_user_id varchar(36),
    source varchar(32) NOT NULL DEFAULT 'manual',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT research_atlas_project_scholars_pkey PRIMARY KEY (id),
    CONSTRAINT research_atlas_project_scholars_space_nonempty CHECK (length(trim(space_id)) > 0),
    CONSTRAINT research_atlas_project_scholars_status_check CHECK (status IN ('candidate', 'shortlist', 'reading', 'done', 'rejected')),
    CONSTRAINT research_atlas_project_scholars_scholar_fkey FOREIGN KEY (scholar_id)
        REFERENCES public.research_atlas_scholars(id) ON DELETE CASCADE,
    CONSTRAINT research_atlas_project_scholars_unique UNIQUE (project_id, scholar_id)
);

CREATE TABLE public.research_atlas_project_groups (
    id varchar(36) NOT NULL,
    space_id varchar(36) NOT NULL,
    project_id varchar(36) NOT NULL,
    group_id varchar(36) NOT NULL,
    status varchar(16) NOT NULL DEFAULT 'candidate',
    tags jsonb NOT NULL DEFAULT '[]'::jsonb,
    note text,
    pinned boolean NOT NULL DEFAULT false,
    added_by_user_id varchar(36),
    source varchar(32) NOT NULL DEFAULT 'manual',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT research_atlas_project_groups_pkey PRIMARY KEY (id),
    CONSTRAINT research_atlas_project_groups_space_nonempty CHECK (length(trim(space_id)) > 0),
    CONSTRAINT research_atlas_project_groups_status_check CHECK (status IN ('candidate', 'shortlist', 'reading', 'done', 'rejected')),
    CONSTRAINT research_atlas_project_groups_group_fkey FOREIGN KEY (group_id)
        REFERENCES public.research_atlas_research_groups(id) ON DELETE CASCADE,
    CONSTRAINT research_atlas_project_groups_unique UNIQUE (project_id, group_id)
);

CREATE TABLE public.research_atlas_saved_views (
    id varchar(36) NOT NULL,
    space_id varchar(36) NOT NULL,
    project_id varchar(36),
    owner_user_id varchar(36),
    name varchar(256) NOT NULL,
    view_type varchar(16) NOT NULL DEFAULT 'list',
    query_json jsonb NOT NULL,
    snapshot_artifact_id varchar(36),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT research_atlas_saved_views_pkey PRIMARY KEY (id),
    CONSTRAINT research_atlas_saved_views_space_nonempty CHECK (length(trim(space_id)) > 0),
    CONSTRAINT research_atlas_saved_views_name_nonempty CHECK (length(trim(name)) > 0),
    CONSTRAINT research_atlas_saved_views_type_check CHECK (view_type IN ('list', 'table', 'graph')),
    CONSTRAINT research_atlas_saved_views_query_object CHECK (jsonb_typeof(query_json) = 'object')
);

CREATE UNIQUE INDEX research_atlas_papers_doi_unique ON public.research_atlas_papers (space_id, lower(doi))
    WHERE doi IS NOT NULL AND merged_into_id IS NULL;
CREATE UNIQUE INDEX research_atlas_papers_arxiv_unique ON public.research_atlas_papers (space_id, lower(arxiv_id))
    WHERE arxiv_id IS NOT NULL AND merged_into_id IS NULL;
CREATE INDEX research_atlas_papers_year_idx ON public.research_atlas_papers (space_id, publication_year);
CREATE INDEX research_atlas_papers_title_idx ON public.research_atlas_papers USING gin (to_tsvector('simple', coalesce(title, '')));

CREATE UNIQUE INDEX research_atlas_scholars_orcid_unique ON public.research_atlas_scholars (space_id, orcid)
    WHERE orcid IS NOT NULL AND merged_into_id IS NULL;
CREATE UNIQUE INDEX research_atlas_institutions_ror_unique ON public.research_atlas_institutions (space_id, ror_id)
    WHERE ror_id IS NOT NULL AND merged_into_id IS NULL;

CREATE INDEX research_atlas_authorships_scholar_idx ON public.research_atlas_authorships (scholar_id);
CREATE INDEX research_atlas_authorships_space_scholar_idx ON public.research_atlas_authorships (space_id, scholar_id);
CREATE INDEX research_atlas_external_ids_entity_idx ON public.research_atlas_external_ids (entity_type, entity_id);
CREATE INDEX research_atlas_source_records_refresh_idx ON public.research_atlas_source_records (space_id, refresh_after);
CREATE INDEX research_atlas_source_records_intake_item_idx ON public.research_atlas_source_records (intake_item_id);
CREATE UNIQUE INDEX research_atlas_source_records_unique ON public.research_atlas_source_records (space_id, connector, external_id, entity_type);
CREATE INDEX research_atlas_curation_events_entity_idx ON public.research_atlas_curation_events (entity_type, entity_id, created_at);
CREATE INDEX research_atlas_curation_events_locked_idx ON public.research_atlas_curation_events (entity_type, entity_id, field)
    WHERE locked;
CREATE INDEX research_atlas_sync_cursors_key_idx ON public.research_atlas_sync_cursors (space_id, cursor_key);
CREATE INDEX research_atlas_project_papers_project_status_idx ON public.research_atlas_project_papers (space_id, project_id, status);
CREATE INDEX research_atlas_project_papers_paper_idx ON public.research_atlas_project_papers (space_id, paper_id);
CREATE UNIQUE INDEX research_atlas_topics_external_unique ON public.research_atlas_topics (space_id, taxonomy, external_ref)
    WHERE external_ref IS NOT NULL;
CREATE INDEX research_atlas_research_groups_institution_idx ON public.research_atlas_research_groups (space_id, institution_id);
CREATE INDEX research_atlas_affiliations_scholar_idx ON public.research_atlas_affiliations (space_id, scholar_id);
CREATE INDEX research_atlas_affiliations_institution_idx ON public.research_atlas_affiliations (space_id, institution_id);
CREATE INDEX research_atlas_citation_edges_cited_idx ON public.research_atlas_citation_edges (space_id, cited_paper_id);
CREATE INDEX research_atlas_group_memberships_group_idx ON public.research_atlas_group_memberships (space_id, group_id);
CREATE INDEX research_atlas_group_memberships_scholar_idx ON public.research_atlas_group_memberships (space_id, scholar_id);
CREATE INDEX research_atlas_saved_views_project_idx ON public.research_atlas_saved_views (space_id, project_id);
