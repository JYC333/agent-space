export interface SourceConnectorRow {
  id: string;
  connector_key: string;
  display_name: string;
  connector_type: string;
  ingestion_mode: string;
  status: string;
  capabilities_json: unknown;
  config_schema_json: unknown;
  created_at: unknown;
  updated_at: unknown;
}

export interface SourceConnectionRow {
  id: string;
  space_id: string;
  connector_id: string;
  owner_user_id: string;
  credential_id: string | null;
  name: string;
  endpoint_url: string | null;
  status: string;
  fetch_frequency: string;
  capture_policy: string;
  trust_level: string;
  topic_hints_json: unknown;
  consent_json: unknown;
  policy_json: unknown;
  config_json: unknown;
  last_checked_at: unknown;
  next_check_at: unknown;
  handler_kind: string;
  active_handler_version_id: string | null;
  active_recipe_version_id: string | null;
  repair_status: string;
  last_handler_run_id: string | null;
  created_at: unknown;
  updated_at: unknown;
}

export interface IntakeItemRow {
  id: string;
  space_id: string;
  connection_id: string | null;
  item_type: string;
  source_object_type: string | null;
  source_object_id: string | null;
  title: string;
  source_uri: string | null;
  canonical_uri: string | null;
  source_domain: string | null;
  source_external_id: string | null;
  author: string | null;
  occurred_at: unknown;
  first_seen_at: unknown;
  last_seen_at: unknown;
  content_hash: string | null;
  excerpt: string | null;
  status: string;
  read_status: string;
  content_state: string;
  retention_policy: string;
  relevance_score: number | null;
  novelty_score: number | null;
  raw_artifact_id: string | null;
  extracted_artifact_id: string | null;
  summary_artifact_id: string | null;
  search_index_ref: string | null;
  embedding_index_ref: string | null;
  metadata_json: unknown;
  created_at: unknown;
  updated_at: unknown;
}

export interface ExtractionJobRow {
  id: string;
  space_id: string;
  connection_id: string | null;
  intake_item_id: string | null;
  source_snapshot_id: string | null;
  source_object_type: string | null;
  source_object_id: string | null;
  job_type: string;
  status: string;
  started_at: unknown;
  completed_at: unknown;
  items_seen: number | null;
  items_created: number | null;
  items_updated: number | null;
  error_code: string | null;
  error_message: string | null;
  metadata_json: unknown;
  created_at: unknown;
}

export interface EvidenceRow {
  id: string;
  space_id: string;
  intake_item_id: string | null;
  extraction_job_id: string | null;
  source_snapshot_id: string | null;
  source_object_type: string | null;
  source_object_id: string | null;
  evidence_type: string;
  title: string;
  content_excerpt: string | null;
  content_hash: string | null;
  artifact_id: string | null;
  source_uri: string | null;
  source_title: string | null;
  source_author: string | null;
  occurred_at: unknown;
  trust_level: string;
  extraction_method: string;
  confidence: number | null;
  status: string;
  metadata_json: unknown;
  created_by_user_id: string | null;
  created_by_agent_id: string | null;
  created_by_run_id: string | null;
  created_at: unknown;
  updated_at: unknown;
}

export interface EvidenceLinkRow {
  id: string;
  space_id: string;
  evidence_id: string;
  target_type: string;
  target_id: string | null;
  link_type: string;
  status: string;
  confidence: number | null;
  reason: string | null;
  created_by_user_id: string | null;
  created_by_agent_id: string | null;
  created_by_run_id: string | null;
  created_at: unknown;
  updated_at: unknown;
}

export interface WorkspaceProfileRow {
  id: string;
  space_id: string;
  workspace_id: string;
  name: string;
  status: string;
  observation_policy: string;
  routing_policy_json: unknown;
  filters_json: unknown;
  extraction_policy_json: unknown;
  context_policy_json: unknown;
  created_by_user_id: string | null;
  created_at: unknown;
  updated_at: unknown;
}

export interface WorkspaceBindingRow {
  id: string;
  space_id: string;
  workspace_id: string;
  project_id: string | null;
  source_connection_id: string;
  binding_key: string;
  status: string;
  priority: number;
  filters_json: unknown;
  routing_policy_json: unknown;
  extraction_policy_json: unknown;
  created_by_user_id: string | null;
  created_at: unknown;
  updated_at: unknown;
}

const CONNECTION_TABLE_COLUMNS = [
  "id",
  "space_id",
  "connector_id",
  "owner_user_id",
  "credential_id",
  "name",
  "endpoint_url",
  "status",
  "fetch_frequency",
  "capture_policy",
  "trust_level",
  "topic_hints_json",
  "consent_json",
  "policy_json",
  "config_json",
  "handler_kind",
  "active_handler_version_id",
  "active_recipe_version_id",
  "repair_status",
  "last_handler_run_id",
  "created_at",
  "updated_at",
];

const CONNECTION_SCHEDULE_SELECT_COLUMNS = [
  "NULL::timestamptz AS last_checked_at",
  "NULL::timestamptz AS next_check_at",
];

export const CONNECTOR_COLUMNS = `id, connector_key, display_name, connector_type, ingestion_mode, status, capabilities_json, config_schema_json, created_at, updated_at`;
export const CONNECTION_COLUMNS = [
  ...CONNECTION_TABLE_COLUMNS,
  ...CONNECTION_SCHEDULE_SELECT_COLUMNS,
].join(", ");
export function connectionColumnsForAlias(alias: string): string {
  return [
    ...CONNECTION_TABLE_COLUMNS.map((column) => `${alias}.${column}`),
    ...CONNECTION_SCHEDULE_SELECT_COLUMNS,
  ].join(", ");
}
export const ITEM_COLUMNS = `id, space_id, connection_id, item_type, source_object_type, source_object_id, title, source_uri, canonical_uri, source_domain, source_external_id, author, occurred_at, first_seen_at, last_seen_at, content_hash, excerpt, status, read_status, content_state, retention_policy, relevance_score, novelty_score, raw_artifact_id, extracted_artifact_id, summary_artifact_id, search_index_ref, embedding_index_ref, metadata_json, created_at, updated_at`;
export const JOB_COLUMNS = `id, space_id, connection_id, intake_item_id, source_snapshot_id, source_object_type, source_object_id, job_type, status, started_at, completed_at, items_seen, items_created, items_updated, error_code, error_message, metadata_json, created_at`;
export const EVIDENCE_COLUMNS = `id, space_id, intake_item_id, extraction_job_id, source_snapshot_id, source_object_type, source_object_id, evidence_type, title, content_excerpt, content_hash, artifact_id, source_uri, source_title, source_author, occurred_at, trust_level, extraction_method, confidence, status, metadata_json, created_by_user_id, created_by_agent_id, created_by_run_id, created_at, updated_at`;
export const EVIDENCE_LINK_COLUMNS = `id, space_id, evidence_id, target_type, target_id, link_type, status, confidence, reason, created_by_user_id, created_by_agent_id, created_by_run_id, created_at, updated_at`;
export const PROFILE_COLUMNS = `id, space_id, workspace_id, name, status, observation_policy, routing_policy_json, filters_json, extraction_policy_json, context_policy_json, created_by_user_id, created_at, updated_at`;
export const BINDING_COLUMNS = `id, space_id, workspace_id, project_id, source_connection_id, binding_key, status, priority, filters_json, routing_policy_json, extraction_policy_json, created_by_user_id, created_at, updated_at`;
