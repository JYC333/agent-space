export interface KnowledgeItemRow {
  id: string;
  space_id: string;
  project_id: string | null;
  workspace_id: string | null;
  root_item_id: string | null;
  supersedes_item_id: string | null;
  redirect_to_item_id: string | null;
  item_type: string;
  slug: string | null;
  aliases_json: unknown;
  title: string;
  content: string;
  content_json: unknown;
  content_format: string;
  content_schema_version: unknown;
  plain_text: string | null;
  excerpt: string | null;
  status: string;
  visibility: string;
  verification_status: string;
  reflection_status: string;
  tags_json: unknown;
  confidence: number | null;
  source_url: string | null;
  owner_user_id: string | null;
  created_by_user_id: string | null;
  created_by_agent_id: string | null;
  created_by_run_id: string | null;
  source_activity_id: string | null;
  source_artifact_id: string | null;
  created_from_proposal_id: string | null;
  approved_by_user_id: string | null;
  version: unknown;
  created_at: unknown;
  updated_at: unknown;
  archived_at: unknown;
  deprecated_at: unknown;
}

export interface KnowledgeRelationRow {
  id: string;
  space_id: string;
  from_item_id: string;
  to_item_id: string;
  relation_type: string;
  status: string;
  confidence: number | null;
  evidence_summary: string | null;
  source_proposal_id: string | null;
  created_by_user_id: string | null;
  created_by_agent_id: string | null;
  created_from_assessment_id: string | null;
  created_at: unknown;
  updated_at: unknown;
}

export interface SourceRow {
  id: string;
  space_id: string;
  source_type: string;
  title: string;
  uri: string | null;
  content_ref: string | null;
  raw_text: string | null;
  summary: string | null;
  metadata_json: unknown;
  status: string;
  source_activity_id: string | null;
  created_by_user_id: string | null;
  created_at: unknown;
  updated_at: unknown;
}

export interface NoteRow {
  id: string;
  space_id: string;
  title: string;
  content_json: unknown;
  content_format: string;
  content_schema_version: unknown;
  plain_text: string | null;
  excerpt: string | null;
  status: string;
  primary_project_id: string | null;
  collection_id: string | null;
  created_from_activity_id: string | null;
  created_by_user_id: string | null;
  created_at: unknown;
  updated_at: unknown;
  archived_at: unknown;
  deleted_at: unknown;
}

export interface NoteCollectionRow {
  id: string;
  space_id: string;
  parent_id: string | null;
  name: string;
  system_role: string;
  sort_order: number | string;
  is_system: boolean;
  is_hidden: boolean;
  created_at: unknown;
  updated_at: unknown;
}

export interface EntityLinkRow {
  id: string;
  space_id: string;
  source_type: string;
  source_id: string;
  target_type: string;
  target_id: string;
  link_type: string;
  confidence: number | null;
  status: string;
  created_by_user_id: string | null;
  created_at: unknown;
}

export interface ProvenanceLinkRow {
  source_type: string;
  source_id: string;
  source_trust: string | null;
  evidence_json: unknown;
  created_at: unknown;
}

export const KNOWLEDGE_ITEM_COLUMNS = `
  id, space_id, project_id, workspace_id, root_item_id, supersedes_item_id,
  redirect_to_item_id, item_type, slug, aliases_json, title, content, content_json,
  content_format, content_schema_version, plain_text, excerpt, status, visibility,
  verification_status, reflection_status, tags_json, confidence, source_url,
  owner_user_id, created_by_user_id, created_by_agent_id, created_by_run_id,
  source_activity_id, source_artifact_id, created_from_proposal_id,
  approved_by_user_id, version, created_at, updated_at, archived_at, deprecated_at
`;

export const KNOWLEDGE_RELATION_COLUMNS = `
  id, space_id, from_item_id, to_item_id, relation_type, status, confidence,
  evidence_summary, source_proposal_id, created_by_user_id, created_by_agent_id,
  created_from_assessment_id, created_at, updated_at
`;

export const SOURCE_COLUMNS = `
  id, space_id, source_type, title, uri, content_ref, raw_text, summary,
  metadata_json, status, source_activity_id, created_by_user_id, created_at, updated_at
`;

export const NOTE_COLUMNS = `
  n.id, n.space_id, n.title, n.content_json, n.content_format,
  n.content_schema_version, n.plain_text, n.excerpt, n.status,
  n.primary_project_id, n.created_from_activity_id, n.created_by_user_id,
  n.created_at, n.updated_at, n.archived_at, n.deleted_at,
  first_collection.collection_id
`;

export const NOTE_COLLECTION_COLUMNS = `
  id, space_id, parent_id, name, system_role, sort_order, is_system,
  is_hidden, created_at, updated_at
`;

export const ENTITY_LINK_COLUMNS = `
  id, space_id, source_type, source_id, target_type, target_id, link_type,
  confidence, status, created_by_user_id, created_at
`;

export const ITEM_TYPES = new Set(["concept", "claim", "lesson", "procedure", "decision", "question", "answer", "summary"]);
export const CONTENT_FORMATS = new Set(["markdown", "plain", "prosemirror_json"]);
export const KNOWLEDGE_VISIBILITIES = new Set(["private", "space_shared", "workspace_shared", "restricted"]);
export const RELATION_TYPES = new Set([
  "related_to",
  "explains",
  "depends_on",
  "prerequisite_of",
  "part_of",
  "example_of",
  "applies_to",
  "supports",
  "contradicts",
  "derived_from",
  "summarizes",
  "updates",
]);
export const SOURCE_TYPES = new Set(["activity_record", "chat_capture", "webpage", "article", "paper", "pdf", "file", "email", "manual_reference", "external_note"]);
export const SOURCE_STATUSES = new Set(["raw", "processing", "processed", "archived", "error"]);
