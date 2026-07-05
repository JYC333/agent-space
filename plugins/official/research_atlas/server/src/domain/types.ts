export type AtlasEntityType = "paper" | "scholar" | "institution" | "venue" | "group" | "topic";
export type PaperType = "article" | "preprint" | "book_chapter" | "thesis" | "dataset" | "other";
export type OaStatus = "gold" | "green" | "hybrid" | "bronze" | "closed" | "unknown";

export interface PaperRow {
  id: string;
  space_id: string;
  title: string;
  abstract: string | null;
  publication_date: string | null;
  publication_year: number | null;
  paper_type: PaperType;
  venue_id: string | null;
  language: string | null;
  doi: string | null;
  arxiv_id: string | null;
  oa_status: OaStatus;
  best_oa_url: string | null;
  pdf_artifact_id: string | null;
  cited_by_count: number | null;
  reference_count: number | null;
  raw_author_names: string[];
  metadata_json: Record<string, unknown>;
  merged_into_id: string | null;
  created_at: Date;
  updated_at: Date;
}

export interface ScholarRow {
  id: string;
  space_id: string;
  display_name: string;
  orcid: string | null;
  alternate_names: string[];
  homepage_url: string | null;
  h_index: number | null;
  works_count: number | null;
  last_known_institution_id: string | null;
  metadata_json: Record<string, unknown>;
  merged_into_id: string | null;
  created_at: Date;
  updated_at: Date;
}

export interface InstitutionRow {
  id: string;
  space_id: string;
  name: string;
  ror_id: string | null;
  country_code: string | null;
  institution_type: string | null;
  homepage_url: string | null;
  aliases: string[];
  metadata_json: Record<string, unknown>;
  merged_into_id: string | null;
  created_at: Date;
  updated_at: Date;
}

export interface VenueRow {
  id: string;
  space_id: string;
  name: string;
  venue_type: string;
  issns: string[];
  abbreviations: string[];
  metadata_json: Record<string, unknown>;
  merged_into_id: string | null;
  created_at: Date;
  updated_at: Date;
}

export interface AuthorshipRow {
  id: string;
  space_id: string;
  paper_id: string;
  scholar_id: string | null;
  author_position: number;
  raw_author_name: string;
  is_corresponding: boolean;
  raw_affiliation_text: string | null;
  institution_id: string | null;
  confidence: number | null;
  source: string | null;
  metadata_json: Record<string, unknown>;
  created_at: Date;
  updated_at: Date;
}

export interface ExternalIdRow {
  id: string;
  space_id: string;
  entity_type: AtlasEntityType;
  entity_id: string;
  id_type: string;
  id_value: string;
  is_primary: boolean;
  confidence: number | null;
  source_record_id: string | null;
  created_at: Date;
  updated_at: Date;
}

export interface SourceRecordRow {
  id: string;
  space_id: string;
  connector: string;
  external_id: string;
  entity_type: AtlasEntityType;
  payload_json: Record<string, unknown>;
  payload_artifact_id: string | null;
  content_hash: string | null;
  fetched_at: Date;
  fetch_status: string;
  intake_item_id: string | null;
  refresh_after: Date | null;
  created_at: Date;
  updated_at: Date;
}

export interface SyncCursorRow {
  id: string;
  space_id: string;
  cursor_key: string;
  watermark_json: Record<string, unknown>;
  last_run_at: Date | null;
  last_error: string | null;
  created_at: Date;
  updated_at: Date;
}

export interface PaperMetadataInput {
  title?: string;
  abstract?: string | null;
  publication_date?: string | null;
  publication_year?: number | null;
  paper_type?: PaperType;
  venue_name?: string | null;
  venue_type?: string | null;
  doi?: string | null;
  arxiv_id?: string | null;
  oa_status?: OaStatus;
  best_oa_url?: string | null;
  cited_by_count?: number | null;
  reference_count?: number | null;
  raw_author_names?: string[];
  authors?: Array<{ name: string; orcid?: string | null; affiliation?: string | null }>;
  metadata_json?: Record<string, unknown>;
}

export interface ImportFilePaperInput extends PaperMetadataInput {
  doi?: string | null;
  arxiv_id?: string | null;
}

export interface PaperListFilters {
  q?: string | null;
  year?: number | null;
  venueId?: string | null;
  scholarId?: string | null;
  limit: number;
  offset: number;
}
