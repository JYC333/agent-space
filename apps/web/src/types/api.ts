// API response shapes shared with the server HTTP contracts.

export type SpaceType      = 'personal' | 'household' | 'team'
export type MemberRole     = 'owner' | 'admin' | 'member' | 'viewer'
export type InviteStatus   = 'pending' | 'accepted' | 'revoked' | 'expired'

export interface CurrentUser {
  id: string
  email: string
  display_name: string
  avatar_url: string | null
  is_instance_admin?: boolean
  default_space_id: string | null
  created_at: string
  last_login_at: string | null
}

export interface SpaceWithMembership {
  id: string
  name: string
  type: SpaceType
  role: MemberRole
  created_at: string
  updated_at: string
}

export interface SpaceMember {
  user_id: string
  email: string
  display_name: string
  avatar_url: string | null
  role: MemberRole
  joined_at: string
}

export interface SpaceInvitationOut {
  id: string
  space_id: string
  invited_email: string
  role: MemberRole
  token: string
  status: InviteStatus
  expires_at: string
}

export type MemoryType       = 'preference' | 'semantic' | 'episodic' | 'procedural' | 'project'
export type MemoryScope      = 'user' | 'workspace' | 'capability' | 'agent' | 'system' | 'space'
export type MemoryStatus     = 'active' | 'archived' | 'proposed' | 'rejected' | 'superseded'
export type MemoryVisibility = 'private' | 'space_shared' | 'workspace_shared' | 'selected_users' | 'summary_only' | 'restricted' | 'public_template'
export type ObjectVisibility = 'private' | 'space_shared' | 'restricted' | string
export type ProposalStatus   = 'pending' | 'accepted' | 'rejected'
export type KnowledgeItemType =
  | 'concept'
  | 'claim'
  | 'lesson'
  | 'procedure'
  | 'decision'
  | 'question'
  | 'answer'
  | 'summary'
export type KnowledgeContentFormat = 'markdown' | 'plain' | 'prosemirror_json'
export type KnowledgeItemStatus = 'draft' | 'active' | 'superseded' | 'archived'
export type KnowledgeVisibility = 'private' | 'space_shared' | 'workspace_shared' | 'restricted'
export type KnowledgeVerificationStatus = 'unverified' | 'needs_review' | 'verified'
export type KnowledgeReflectionStatus = 'unreviewed' | 'reviewed' | 'distilled'
export type KnowledgeRelationType =
  | 'related_to'
  | 'explains'
  | 'depends_on'
  | 'prerequisite_of'
  | 'part_of'
  | 'example_of'
  | 'applies_to'
  | 'supports'
  | 'contradicts'
  | 'derived_from'
  | 'summarizes'
  | 'updates'
export type KnowledgeRelationStatus = 'candidate' | 'active' | 'rejected' | 'archived'
export type ActivityStatus     = 'raw' | 'processed' | 'proposals_generated' | 'archived'
export type ActivitySourceType =
  | 'user_capture'
  | 'chat_message'
  | 'external_chat'
  | 'file_import'
  | 'web_capture'
  | 'run_event'
  | 'workspace_event'
  | 'system_event'
  | 'external_source'
  | 'intake'
export type SessionStatus    = 'active' | 'closed'
/** Canonical run lifecycle (Run API). */
export type RunLifecycleStatus =
  | 'queued'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'cancelled'
  | 'degraded'
  | 'waiting_for_review'

export type MessageRole      = 'user' | 'assistant' | 'system' | 'tool'
export type WorkspaceStatus  = 'active' | 'archived'
export type WorkspaceType    = 'project' | 'repo' | 'knowledge_base' | 'personal' | 'team' | 'system_core'
export type WorkspaceCreateType = Exclude<WorkspaceType, 'system_core'>

export type ModelSelectionMode = 'cli_default' | 'cli_model_override' | 'agent_space_provider'

export interface RuntimeToolManifest {
  schema_version: 1
  runtime: string
  source: 'npm'
  package_name: string
  requested_version: string
  version: string
  bin_name: string
  bin_relative_path: string
  installed_at: string
}

export interface RuntimeToolDefinition {
  runtime: string
  label: string
  source: 'npm'
  package_name: string
  bin_name: string
  bin_relative_path: string
  package_json_relative_path: string
  default_version: string
}

export interface RuntimeToolStatus {
  runtime: string
  label: string
  source: 'npm'
  package_name: string
  bin_name: string
  installed: boolean
  active_version: string | null
  executable_path: string | null
  executable_exists: boolean
  manifest: RuntimeToolManifest | null
  installed_versions: RuntimeToolInstalledVersion[]
  warnings: string[]
}

export interface RuntimeToolInstalledVersion {
  version: string
  installed: boolean
  executable_path: string | null
  executable_exists: boolean
  manifest: RuntimeToolManifest | null
  warnings: string[]
}

export interface RuntimeToolInstallResult extends RuntimeToolStatus {
  installed_version: string
  activated: boolean
}

export interface RuntimeToolLatest {
  runtime: string
  package_name: string
  latest_version: string | null
}

export interface SpaceRuntimeToolPolicyOut {
  runtime: string
  label: string
  enabled: boolean
  default_version: string | null
  allowed_versions: string[]
  policy_id: string | null
  active_version: string | null
  installed_versions: RuntimeToolInstalledVersion[]
  warnings: string[]
  updated_by_user_id: string | null
  updated_at: string | null
}

// CLI Credentials / Login

export type LoginMethod = 'cli'

export interface CredentialLoginMethod {
  runtime: string
  method: LoginMethod
  label: string
  hint_cli: string
  supports_cli: boolean
}

export interface CredentialStatus {
  runtime: string
  label: string
  method: LoginMethod
  profile_id: string | null
  network_profile_id: string | null
  logged_in: boolean
  file_count: number
}

export type NetworkProfileMode = 'direct' | 'http_proxy'

export interface NetworkProfileOut {
  id: string
  space_id: string
  name: string
  mode: NetworkProfileMode
  proxy_url: string | null
  no_proxy: string | null
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface NetworkProfileCreateBody {
  name: string
  mode: NetworkProfileMode
  proxy_url?: string | null
  no_proxy?: string | null
  enabled?: boolean
}

export type NetworkProfileUpdateBody = Partial<NetworkProfileCreateBody>

export interface CliCredentialProfileOut {
  id: string
  owner_user_id?: string | null
  runtime: string
  name: string
  source_path: string
  target_path: string
  readonly: boolean
  notes: string
  network_profile_id: string | null
  source_exists: boolean
  logged_in: boolean
  file_count: number
  manageable?: boolean
  grant_id?: string | null
  grant_enabled?: boolean
  is_default?: boolean
}

export interface CliCredentialAvailableProfileOut {
  id: string
  owner_user_id?: string | null
  runtime: string
  name: string
  target_path: string
  readonly: boolean
  notes: string
  network_profile_id: string | null
  source_exists: boolean
  logged_in: boolean
  file_count: number
  manageable: boolean
  grant_id: string
  is_default: boolean
}

export interface TokenUsage {
  available: boolean
  source: 'transcripts' | 'codex_sessions' | 'unsupported'
  input_tokens: number
  output_tokens: number
  cache_creation_input_tokens: number
  cache_read_input_tokens: number
  cost_usd: number
  message_count: number
  session_count: number
}

export interface QuotaUsage {
  available: boolean
  session_pct: number | null
  session_resets: string | null
  week_pct: number | null
  week_resets: string | null
  checked_at: string | null
  error: string | null
}

export interface CliUsageEntry {
  runtime: string
  label: string
  tokens: TokenUsage
  quota: QuotaUsage | null
}

export interface CliUsageAutoRefreshSettings {
  enabled: boolean
  interval_ms: number
  updated_at: string | null
}

export type LoginEventType = 'output' | 'error' | 'warning' | 'hint' | 'profile' | 'synced' | 'done' | 'needs_input' | 'device_auth'

export interface LoginEvent {
  type: LoginEventType
  text?: string
  exit_code?: number
  profile_id?: string
  prompt?: string
  step?: string
  url?: string
  code?: string
  expires_in_minutes?: number
}

export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface SourceConnector {
  id: string
  connector_key: string
  display_name: string
  connector_type: string
  ingestion_mode: string
  status: string
  capabilities_json: Record<string, unknown>
  config_schema_json: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export interface SourceConnection {
  id: string
  space_id: string
  connector_id: string
  owner_user_id: string
  credential_id: string | null
  name: string
  endpoint_url: string | null
  status: 'active' | 'paused' | 'archived'
  fetch_frequency: 'manual' | 'hourly' | 'daily' | 'weekly'
  capture_policy: string
  trust_level: 'trusted' | 'normal' | 'untrusted'
  topic_hints_json: string[] | null
  consent_json: Record<string, unknown>
  policy_json: Record<string, unknown>
  config_json: Record<string, unknown>
  last_checked_at: string | null
  next_check_at: string | null
  created_at: string
  updated_at: string
}

export interface SourceConnectionCreate {
  connector_key: string
  name: string
  endpoint_url?: string | null
  credential_id?: string | null
  fetch_frequency?: 'manual' | 'hourly' | 'daily' | 'weekly'
  capture_policy?: string
  trust_level?: 'trusted' | 'normal' | 'untrusted'
  topic_hints?: string[] | null
  consent?: Record<string, unknown>
  policy?: Record<string, unknown>
  config?: Record<string, unknown>
}

export interface IntakeItem {
  id: string
  space_id: string
  connection_id: string | null
  item_type: string
  source_object_type: string | null
  source_object_id: string | null
  title: string
  source_uri: string | null
  canonical_uri: string | null
  source_domain: string | null
  source_external_id: string | null
  author: string | null
  occurred_at: string | null
  first_seen_at: string
  last_seen_at: string
  content_hash: string | null
  excerpt: string | null
  status: 'new' | 'triaged' | 'selected' | 'ignored' | 'archived'
  read_status: 'unread' | 'skimmed' | 'read' | 'discussed'
  content_state: string
  retention_policy: string
  relevance_score: number | null
  novelty_score: number | null
  raw_artifact_id: string | null
  extracted_artifact_id: string | null
  summary_artifact_id: string | null
  search_index_ref: string | null
  embedding_index_ref: string | null
  metadata_json: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export interface ExtractionJob {
  id: string
  space_id: string
  connection_id: string | null
  intake_item_id: string | null
  source_snapshot_id: string | null
  source_object_type: string | null
  source_object_id: string | null
  job_type: string
  status: string
  started_at: string | null
  completed_at: string | null
  items_seen: number | null
  items_created: number | null
  items_updated: number | null
  error_code: string | null
  error_message: string | null
  metadata_json: Record<string, unknown> | null
  created_at: string
}

export interface ExtractedEvidence {
  id: string
  space_id: string
  intake_item_id: string | null
  extraction_job_id: string | null
  source_snapshot_id: string | null
  source_object_type: string | null
  source_object_id: string | null
  evidence_type: string
  title: string
  content_excerpt: string | null
  content_hash: string | null
  artifact_id: string | null
  source_uri: string | null
  source_title: string | null
  source_author: string | null
  occurred_at: string | null
  trust_level: 'trusted' | 'normal' | 'untrusted'
  extraction_method: string
  confidence: number | null
  status: 'candidate' | 'active' | 'rejected' | 'archived'
  metadata_json: Record<string, unknown> | null
  created_by_user_id: string | null
  created_by_agent_id: string | null
  created_by_run_id: string | null
  created_at: string
  updated_at: string
}

export interface EvidenceLink {
  id: string
  space_id: string
  evidence_id: string
  target_type: string
  target_id: string | null
  link_type: string
  status: 'candidate' | 'active' | 'rejected' | 'archived'
  confidence: number | null
  reason: string | null
  created_by_user_id: string | null
  created_by_agent_id: string | null
  created_by_run_id: string | null
  created_at: string
  updated_at: string
}

export interface WorkspaceIntakeProfile {
  id: string
  space_id: string
  workspace_id: string
  name: string
  status: string
  observation_policy: string
  routing_policy_json: Record<string, unknown>
  filters_json: Record<string, unknown>
  extraction_policy_json: Record<string, unknown>
  context_policy_json: Record<string, unknown>
  created_by_user_id: string | null
  created_at: string
  updated_at: string
}

export interface WorkspaceSourceBinding {
  id: string
  space_id: string
  workspace_id: string
  project_id: string | null
  source_connection_id: string
  binding_key: string
  status: string
  priority: number
  filters_json: Record<string, unknown>
  routing_policy_json: Record<string, unknown>
  extraction_policy_json: Record<string, unknown>
  created_by_user_id: string | null
  created_at: string
  updated_at: string
}

export type JobStatus    = 'pending' | 'claimed' | 'running' | 'completed' | 'failed' | 'cancelled'
export type JobEventType = 'log' | 'status_change' | 'artifact' | 'error'

export interface Job {
  id: string
  space_id: string
  user_id: string
  workspace_id: string | null
  agent_id: string | null
  job_type: string
  status: JobStatus
  priority: number
  payload: Record<string, unknown> | null
  result: Record<string, unknown> | null
  error: string | null
  attempts: number
  max_attempts: number
  claimed_by: string | null
  claimed_at: string | null
  scheduled_at: string
  started_at: string | null
  completed_at: string | null
  created_at: string
  updated_at: string
}

export interface JobEvent {
  id: string
  job_id: string
  event_type: JobEventType
  message: string
  data: Record<string, unknown> | null
  created_at: string
}

export interface Memory {
  id: string
  space_id: string
  subject_user_id?: string | null
  owner_user_id: string | null
  workspace_id: string | null
  title: string | null
  content: string | null
  type: MemoryType
  scope: MemoryScope
  namespace: string | null
  status: MemoryStatus
  visibility: MemoryVisibility
  sensitivity_level?: string
  selected_user_ids?: string[] | null
  last_confirmed_at?: string | null
  confidence: number
  importance: number
  source_id: string | null
  created_by: string | null
  version: number
  access_count?: number
  last_accessed_at?: string | null
  tags: string[] | null
  created_at: string
  updated_at: string
  deleted_at: string | null
  agent_id?: string | null
  capability_id?: string | null
  source_activity_id?: string | null
  source_artifact_id?: string | null
  approved_by?: string | null
  memory_layer?: string | null
  memory_kind?: string | null
  source_trust?: string | null
  created_from_proposal_id?: string | null
  root_memory_id?: string | null
  supersedes_memory_id?: string | null
  project_id?: string | null
}

export interface KnowledgeItemSummary {
  id: string
  space_id: string
  project_id: string | null
  workspace_id: string | null
  item_type: KnowledgeItemType
  slug: string | null
  title: string
  content_preview: string
  excerpt: string | null
  status: KnowledgeItemStatus
  visibility: KnowledgeVisibility
  verification_status: KnowledgeVerificationStatus
  reflection_status: KnowledgeReflectionStatus
  tags: string[]
  confidence: number | null
  version: number
  updated_at: string
}

export interface KnowledgeItem extends KnowledgeItemSummary {
  root_item_id: string | null
  supersedes_item_id: string | null
  redirect_to_item_id: string | null
  aliases: string[]
  content: string
  content_json: Record<string, unknown> | null
  content_format: KnowledgeContentFormat
  content_schema_version: number
  plain_text: string | null
  source_url: string | null
  source_refs: Record<string, unknown>[]
  owner_user_id: string | null
  created_by_user_id: string | null
  created_by_agent_id: string | null
  created_by_run_id: string | null
  source_activity_id: string | null
  source_artifact_id: string | null
  created_from_proposal_id: string | null
  approved_by_user_id: string | null
  created_at: string
  archived_at: string | null
  deprecated_at: string | null
}

export interface KnowledgeRelation {
  id: string
  space_id: string
  from_item_id: string
  to_item_id: string
  relation_type: KnowledgeRelationType
  status: KnowledgeRelationStatus
  confidence: number | null
  evidence_summary: string | null
  source_proposal_id: string | null
  created_by_user_id: string | null
  created_by_agent_id: string | null
  created_from_assessment_id: string | null
  created_at: string
  updated_at: string
}

export interface KnowledgeCreateProposalBody {
  item_type: KnowledgeItemType
  title: string
  slug?: string | null
  aliases?: string[]
  content: string
  content_json?: Record<string, unknown> | null
  content_format: KnowledgeContentFormat
  content_schema_version?: number
  visibility: KnowledgeVisibility
  project_id?: string | null
  workspace_id?: string | null
  tags: string[]
  confidence?: number | null
  source_url?: string | null
  source_refs?: Record<string, unknown>[]
  source_activity_id?: string | null
  source_run_id?: string | null
  source_artifact_id?: string | null
  rationale?: string | null
}

export interface KnowledgeUpdateProposalBody {
  title: string
  slug?: string | null
  aliases?: string[]
  content: string
  content_json?: Record<string, unknown> | null
  content_format: KnowledgeContentFormat
  content_schema_version?: number
  tags: string[]
  confidence?: number | null
  rationale?: string | null
  verification_status?: KnowledgeVerificationStatus
  reflection_status?: KnowledgeReflectionStatus
}

export interface KnowledgeRelationProposalBody {
  from_item_id: string
  to_item_id: string
  relation_type: KnowledgeRelationType
  status: Extract<KnowledgeRelationStatus, 'candidate' | 'active'>
  confidence?: number | null
  evidence_summary?: string | null
  rationale?: string | null
}

// ── Notes (working knowledge; direct CRUD) ─────────────────────────────────
export type NoteStatus = 'active' | 'archived' | 'deleted'
export type NoteContentFormat = 'markdown' | 'plain' | 'prosemirror_json'
export type NoteCollectionSystemRole = 'normal' | 'inbox' | 'archive'

export interface NoteCollection {
  id: string
  space_id: string
  parent_id: string | null
  name: string
  system_role: NoteCollectionSystemRole
  sort_order: number
  is_system: boolean
  is_hidden: boolean
  created_at: string
  updated_at: string
  deleted_at?: string | null
}

export interface NoteCollectionCreateBody {
  name: string
  parent_id?: string | null
  sort_order?: number | null
}

export interface NoteCollectionUpdateBody {
  name?: string
  parent_id?: string | null
  sort_order?: number | null
  is_hidden?: boolean
}

export interface NoteSummary {
  id: string
  space_id: string
  title: string
  excerpt: string | null
  status: NoteStatus
  content_format: NoteContentFormat
  primary_project_id: string | null
  /** Folder this note belongs to (first membership); null/absent if uncategorized. */
  collection_id?: string | null
  created_at: string
  updated_at: string
}

export interface Note extends NoteSummary {
  content_json: Record<string, unknown> | null
  content_schema_version: number
  plain_text: string | null
  created_from_activity_id: string | null
  created_by_user_id: string | null
  archived_at: string | null
  deleted_at: string | null
}

export interface NoteCreateBody {
  title: string
  plain_text?: string | null
  content_json?: Record<string, unknown> | null
  content_format?: NoteContentFormat
  content_schema_version?: number
  status?: 'active'
  primary_project_id?: string | null
  created_from_activity_id?: string | null
  collection_id?: string | null
}

export interface NoteUpdateBody {
  title?: string
  plain_text?: string | null
  content_json?: Record<string, unknown> | null
  content_format?: NoteContentFormat
  content_schema_version?: number
  status?: NoteStatus
  primary_project_id?: string | null
}

// ── Entity links (generic cross-object relation layer) ─────────────────────
export type EntityType =
  | 'note' | 'knowledge_item' | 'source' | 'project'
  | 'workspace' | 'activity' | 'run' | 'proposal'
export type EntityLinkType =
  | 'references' | 'related_to' | 'belongs_to'
  | 'captured_from' | 'source_for' | 'derived_from'
export type EntityLinkStatus = 'suggested' | 'accepted' | 'rejected'

export interface EntityLink {
  id: string
  space_id: string
  source_type: EntityType
  source_id: string
  target_type: EntityType
  target_id: string
  link_type: EntityLinkType
  confidence: number | null
  status: EntityLinkStatus
  created_by_user_id: string | null
  created_at: string
}

export interface NoteLinkCreateBody {
  target_type: EntityType
  target_id: string
  link_type?: EntityLinkType
  confidence?: number | null
  direction?: 'outgoing' | 'incoming'
}

export interface KnowledgeSummary {
  notes: { active: number; archived: number; deleted: number; total: number }
  wiki: { active: number }
  sources: { total: number }
}

// ── Sources (provenance / evidence layer) ──────────────────────────────────
export interface KnowledgeSourceSummary {
  id: string
  space_id: string
  source_type: string
  title: string
  uri: string | null
  status: string
  source_activity_id: string | null
  created_at: string
  updated_at: string
}

/** Activity inbox (`GET /activity`) — distinct from run-scoped activity records. */
export interface ActivityInboxRecord {
  id: string
  space_id: string
  user_id: string | null
  workspace_id: string | null
  agent_id: string | null
  source_type: ActivitySourceType
  title: string | null
  content: string
  source_run_id: string | null
  source_task_id: string | null
  source_session_id: string | null
  source_url: string | null
  status: ActivityStatus
  metadata_json: Record<string, unknown> | null
  visibility?: ObjectVisibility
  created_at: string
  updated_at: string
}

/** Run timeline row (`GET /runs/{id}/activities`). */
export interface ActivityRecord {
  id: string
  space_id: string
  source_run_id: string | null
  session_id: string | null
  user_id: string | null
  activity_type: string
  title: string | null
  content: string | null
  payload_json: Record<string, unknown>
  visibility?: ObjectVisibility
  occurred_at: string
  created_at: string
}

export interface Session {
  id: string
  space_id: string
  user_id: string
  title: string | null
  status: SessionStatus
  workspace_id: string | null
  created_at: string
  updated_at: string
}

export interface Message {
  id: string
  session_id: string
  space_id: string
  user_id: string
  role: MessageRole
  content: string
  metadata_json: Record<string, unknown> | null
  created_at: string
}

/** One synchronous Personal Assistant chat turn result (`ChatTurnOut`). */
export interface ChatTurnOut {
  session_id: string
  run_id: string
  ok: boolean
  reply?: string | null
  error?: string | null
  error_code?: string | null
}

/** Product task board item (`TaskOut`). */
export interface Task {
  id: string
  space_id: string
  workspace_id: string | null
  board_id: string | null
  column_id: string | null
  parent_task_id: string | null
  title: string
  description: string | null
  task_type: string
  status: string
  priority: string
  risk_level: string
  visibility: ObjectVisibility
  created_by_user_id: string | null
  created_by_agent_id: string | null
  assigned_user_id: string | null
  assigned_agent_id: string | null
  claimed_by_user_id: string | null
  claimed_by_agent_id: string | null
  source_activity_id: string | null
  source_run_id: string | null
  source_proposal_id: string | null
  source_artifact_id: string | null
  due_at: string | null
  start_after: string | null
  completed_at: string | null
  cancelled_at: string | null
  blocked_reason: string | null
  created_at: string
  updated_at: string
  deleted_at: string | null
  /** Present when API expands TaskOut; optional on wire today. */
  acceptance_criteria_json?: Record<string, unknown> | null
  definition_of_done?: string | null
  required_outputs_json?: unknown[] | null
  tags?: string[] | null
  metadata_json?: Record<string, unknown> | null
}

export interface BoardColumn {
  id: string
  space_id: string
  board_id: string
  name: string
  description: string | null
  status_key: string
  position: number
  wip_limit: number | null
  is_done_column: boolean
  is_default_column: boolean
  metadata_json: Record<string, unknown> | null
  created_at: string
  updated_at: string
  deleted_at: string | null
}

export interface Board {
  id: string
  space_id: string
  workspace_id: string | null
  name: string
  description: string | null
  board_type: string
  status: string
  default_view: string | null
  sort_order: number | null
  metadata_json: Record<string, unknown> | null
  created_by_user_id: string | null
  created_by_agent_id: string | null
  created_at: string
  updated_at: string
  deleted_at: string | null
}

export interface TaskRunCreateBody {
  agent_id?: string | null
  mode?: string
  run_type?: string
  trigger_origin?: string
  session_id?: string | null
  workspace_id?: string | null
  prompt?: string | null
  instruction?: string | null
  set_task_in_progress?: boolean
}

export interface TaskRunOut {
  id: string
  space_id: string
  task_id: string
  run_id: string
  role: string
  created_at: string
}

export interface RunResolvedModel {
  provider_id: string | null
  provider_name: string | null
  provider_type: string | null
  model: string | null
  source: 'request' | 'agent_default' | 'space_default' | 'none'
  used_by_adapter: boolean
  adapter_model_support: 'uses_model' | 'not_applicable' | 'unsupported' | 'unknown'
  disclosure_note?: string | null
}

export interface Run {
  id: string
  space_id: string
  agent_id: string
  agent_version_id: string
  context_snapshot_id: string | null
  workspace_id: string | null
  session_id: string | null
  parent_run_id: string | null
  instructed_by_user_id?: string | null
  instructed_by_agent_id?: string | null
  run_type: string
  trigger_origin: string
  status: string
  mode: string
  prompt: string | null
  instruction: string | null
  scheduled_at: string | null
  started_at: string | null
  ended_at: string | null
  created_at: string
  updated_at: string
  error_message: string | null
  error_json: Record<string, unknown> | null
  output_json: Record<string, unknown> | null
  usage_json: Record<string, unknown> | null
  adapter_type?: string | null
  capability_id?: string | null
  model_provider_id?: string | null
  resolved_model?: RunResolvedModel | null
  visibility?: ObjectVisibility
  task_id?: string | null
}

export interface RunStatusOut {
  id: string
  status: string
  mode: string
  run_type: string
  trigger_origin: string
  started_at: string | null
  ended_at: string | null
  error_message: string | null
}

export interface ArtifactSummary {
  id: string
  space_id: string
  run_id: string | null
  proposal_id: string | null
  artifact_type: string
  title: string
  mime_type: string | null
  visibility?: ObjectVisibility
  created_at: string
}

export interface ProposalSummary {
  id: string
  space_id: string
  proposal_type: string
  status: string
  title: string
  visibility?: ObjectVisibility
  created_at: string
}

export interface TaskRunListItem {
  link: TaskRunOut
  run: Run
}

export interface TaskArtifact {
  id: string
  space_id: string
  task_id: string
  artifact_id: string
  role: string
  created_at: string
  artifact: ArtifactSummary & { preview?: boolean }
}

export interface TaskProposal {
  id: string
  space_id: string
  task_id: string
  proposal_id: string
  role: string
  created_at: string
  proposal: ProposalSummary & {
    preview?: boolean
    urgency?: string
    expired?: boolean
  }
}

export interface Artifact {
  id: string
  space_id: string
  run_id: string | null
  proposal_id: string | null
  artifact_type: string
  title: string
  mime_type: string | null
  exportable: boolean
  preview: boolean
  storage_ref: string | null
  storage_path: string | null
  has_inline_content: boolean
  visibility?: ObjectVisibility
  owner_user_id?: string | null
  content?: string | null
  created_at: string
  updated_at: string
}

/** Canonical proposal (`GET /proposals`, `ProposalOut`). */
export interface Proposal {
  id: string
  space_id: string
  user_id: string
  workspace_id: string | null
  source_session_id: string | null
  source_task_id: string | null
  source_run_id: string | null
  created_by_run_id: string | null
  proposal_type: string
  target_scope: string
  target_namespace: string
  memory_type: string
  proposed_title: string
  proposed_content: string
  rationale: string
  status: string
  risk_level: string
  urgency: string
  visibility?: ObjectVisibility
  preview: boolean
  review_deadline: string | null
  expires_at: string | null
  expired: boolean
  created_at: string
  decided_at: string | null
  resulting_memory_id: string | null
  owner_user_id?: string | null
  subject_user_id?: string | null
  sensitivity_level?: string | null
  selected_user_ids?: string[] | null
  grant_id?: string | null
  required_approver_user_id?: string | null
  requires_approval_type?: string | null
  egress_approval_status?: string | null
  egress_approval_id?: string | null
  incomplete_patch?: boolean
  skipped_changes?: Array<Record<string, unknown>>
  skipped_count?: number
}

/** `POST /proposals/{id}/accept` — result depends on `proposal_type`. */
export type ProposalAcceptOut = {
  proposal: Proposal
  result_type: 'memory_entry'
  result: { memory: Memory }
} | {
  proposal: Proposal
  result_type: 'code_patch_apply'
  result: { updated_paths: string[] }
} | {
  proposal: Proposal
  result_type: 'policy_version'
  result: { policy_id: string; policy_version: number }
} | {
  proposal: Proposal
  result_type: 'egress_review'
  result: { approved_egress_review: boolean }
} | {
  proposal: Proposal
  result_type: 'follow_up_task'
  result: { task_id: string; title: string }
} | {
  proposal: Proposal
  result_type: 'agent_version'
  result: { agent_id: string; agent_version_id: string }
} | {
  proposal: Proposal
  result_type: 'knowledge_item'
  result: { knowledge_item: KnowledgeItem }
} | {
  proposal: Proposal
  result_type: 'knowledge_relation'
  result: { knowledge_relation: KnowledgeRelation }
}

export interface PersonalMemoryGrantSafeMemoryFilter {
  max_items?: number
}

export interface PersonalMemoryGrantPreviewRequest {
  target_space_id: string
  target_run_id: string
  access_mode: 'summary_only'
  read_expires_in_seconds?: number
  memory_filter?: PersonalMemoryGrantSafeMemoryFilter | null
}

export interface PersonalMemoryGrantPreviewResponse {
  eligible: boolean
  target_space_id: string
  target_run_id: string
  access_mode: 'summary_only'
  proposed_read_expires_at: string | null
  warnings: string[]
  excluded_sensitivity_levels: string[]
  max_items: number | null
}

export interface PersonalMemoryGrantCreateRequest {
  target_space_id: string
  target_run_id: string
  access_mode: 'summary_only'
  read_expires_in_seconds: number
  memory_filter?: PersonalMemoryGrantSafeMemoryFilter | null
}

export type PersonalMemoryGrantStatus =
  | 'active'
  | 'consuming'
  | 'used'
  | 'revoked'
  | 'expired'
  | 'failed'

export interface PersonalMemoryGrantResponse {
  id: string
  granting_user_id: string
  personal_space_id: string
  target_space_id: string
  target_run_id: string
  target_agent_id: string | null
  grant_scope: 'run' | string
  access_mode: 'summary_only' | string
  status: PersonalMemoryGrantStatus | string
  memory_filter_json: PersonalMemoryGrantSafeMemoryFilter | Record<string, unknown> | null
  read_expires_at: string
  revoked_at: string | null
  used_at: string | null
  created_at: string
  updated_at: string
}

export interface PersonalMemoryGrantEvent {
  id: string
  grant_id: string
  event_type: string
  actor_user_id: string | null
  run_id: string | null
  metadata_json: Record<string, unknown> | null
  created_at: string
}

export interface PersonalMemoryGrantAuditResponse {
  grant: PersonalMemoryGrantResponse
  events: PersonalMemoryGrantEvent[]
}

export interface EgressApprovalRequest {
  grant_id?: string | null
}

export interface ProposalApprovalResponse {
  id: string
  proposal_id: string
  approval_type: 'egress_granting_user' | string
  approver_user_id: string
  grant_id: string | null
  target_space_id: string | null
  status: 'approved' | 'revoked' | string
  metadata_json: Record<string, unknown> | null
  created_at: string
  revoked_at: string | null
}

export interface EvolutionSummaryOut {
  active_targets: number
  signals_collected: number
  pending_proposals: number
  recent_runs: number
}

export interface EvolutionTarget {
  id: string
  space_id: string | null
  target_name: string | null
  target_type: string
  target_ref_type: string | null
  target_ref_id: string | null
  capability_key: string | null
  current_version_id: string | null
  current_version: string | null
  scope: string | null
  purpose: string | null
  risk_level: string
  status: string
  enabled: boolean
  recent_signal_count: number
  last_run_at: string | null
  engine_policy_json: Record<string, unknown>
  metadata_json: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface EvolutionTargetCreateBody {
  target_type: string
  target_ref_type?: string | null
  target_ref_id?: string | null
  capability_key?: string | null
  current_version_id?: string | null
  risk_level?: string
  enabled?: boolean
  status?: string
  target_name?: string | null
  purpose?: string | null
  engine_policy_json?: Record<string, unknown>
  metadata_json?: Record<string, unknown>
}

export interface EvolutionTargetUpdateBody {
  target_type?: string | null
  target_ref_type?: string | null
  target_ref_id?: string | null
  capability_key?: string | null
  current_version_id?: string | null
  risk_level?: string | null
  enabled?: boolean | null
  status?: string | null
  target_name?: string | null
  purpose?: string | null
  engine_policy_json?: Record<string, unknown> | null
  metadata_json?: Record<string, unknown> | null
}

export interface EvolutionSignal {
  id: string
  space_id: string | null
  target_id: string
  target_name: string | null
  target_type: string | null
  capability_key: string | null
  signal_type: string
  source_type: string
  source_id: string | null
  severity: string
  summary: string | null
  payload_json: Record<string, unknown>
  created_at: string
}

export interface EvolutionSignalCreateBody {
  signal_type: string
  source_type: string
  source_id?: string | null
  severity?: string
  summary?: string | null
  payload_json?: Record<string, unknown>
}

export interface EvolutionRunListItem {
  run_id: string
  target_id: string | null
  target_name: string | null
  target_type: string | null
  capability_key: string | null
  engine: string | null
  status: string
  created_at: string
  started_at: string | null
  artifact_count: number
  proposal_id: string | null
}

export interface EvolutionRunResult {
  run_id: string
  target_id: string
  context_artifact_id: string
  report_artifact_id: string
  revision_artifact_id: string
  proposal_id: string
  proposal_type: string
  run_status: string
}

export interface EvolutionProposal {
  id: string
  proposal_type: string
  target_id: string | null
  target_name: string | null
  target_type: string | null
  capability_key: string | null
  status: string
  summary: string | null
  created_at: string
  created_by_run_id: string | null
}

export interface EvolutionValidationResult {
  metric_id: string
  label: string
  evaluator: string
  target_id: string
  target_name: string | null
  value: unknown | null
  status: string
  window: string | null
  goal: Record<string, unknown>
  sample_size: number
  numerator_count: number | null
  denominator_count: number | null
  updated_at: string | null
  metadata_json: Record<string, unknown>
}

export interface AgentModelSummary {
  provider_id: string | null
  provider_name: string | null
  provider_type: string | null
  model: string | null
}

export interface AgentOut {
  id: string
  space_id: string
  created_by_user_id: string
  name: string
  description: string | null
  visibility: string
  role_instruction: string | null
  status: string
  // 'standard' | 'system_assistant' (the space's system-managed default Assistant)
  agent_kind: string
  current_version_id: string | null
  // Provenance only — never used to assemble runtime config.
  source_template_id: string | null
  source_template_version_id: string | null
  model: AgentModelSummary | null
  // Effective runtime adapter and whether it needs a space model provider.
  // CLI runtimes manage their own model/login and require no provider.
  adapter_type: string | null
  requires_model_provider: boolean
  system_prompt: string | null
  created_at: string
  updated_at: string
}

export interface AgentVersionOut {
  id: string
  agent_id: string
  space_id: string
  version_label: string
  model_provider_id: string | null
  model_name: string | null
  system_prompt: string | null
  model_config_json: Record<string, unknown>
  runtime_config_json: Record<string, unknown>
  context_policy_json: Record<string, unknown>
  memory_policy_json: Record<string, unknown>
  capabilities_json: unknown[]
  tool_permissions_json: Record<string, unknown>
  runtime_policy_json: Record<string, unknown>
  tool_policy_json: Record<string, unknown>
  output_policy_json: Record<string, unknown>
  schedule_config_json: Record<string, unknown>
  output_schema_json: Record<string, unknown>
  source_proposal_id: string | null
  source_activity_id: string | null
  created_at: string
  published_at: string | null
  archived_at: string | null
}

export interface AgentTemplateOut {
  id: string
  key: string
  name: string
  description: string | null
  category: string | null
  scope: 'system' | 'space' | 'user'
  space_id: string | null
  owner_user_id: string | null
  visibility: 'private' | 'space_shared' | 'system_public' | 'system_internal'
  status: 'draft' | 'published' | 'archived'
  current_version_id: string | null
  created_at: string
  updated_at: string
}

export type AssistantResponseStyle = 'neutral' | 'friendly' | 'direct' | 'formal'
export type AssistantVerbosity = 'concise' | 'balanced' | 'detailed'
export type AssistantProposalStyle = 'proactive' | 'balanced' | 'conservative'

export interface SpaceAssistantSettingsOut {
  id: string
  space_id: string
  assistant_agent_id: string | null
  response_style: AssistantResponseStyle | null
  verbosity: AssistantVerbosity | null
  default_context_toggles_json: Record<string, boolean>
  default_project_id: string | null
  proposal_style: AssistantProposalStyle | null
  model_preferences_json: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface SpaceAssistantSettingsUpdate {
  response_style?: AssistantResponseStyle | null
  verbosity?: AssistantVerbosity | null
  default_context_toggles_json?: Record<string, boolean>
  default_project_id?: string | null
  proposal_style?: AssistantProposalStyle | null
  model_preferences_json?: Record<string, unknown>
}

export interface AgentTemplateVersionOut {
  id: string
  template_id: string
  version: string
  system_prompt: string | null
  model_config_json: Record<string, unknown>
  context_policy_json: Record<string, unknown>
  memory_policy_json: Record<string, unknown>
  tool_policy_json: Record<string, unknown>
  runtime_policy_json: Record<string, unknown>
  output_policy_json: Record<string, unknown>
  schedule_defaults_json: Record<string, unknown>
  output_schema_json: Record<string, unknown>
  created_by_user_id: string | null
  created_at: string
  published_at: string | null
}

/** Editable areas for the agent config UI (`POST /agents/{id}/config`). */
export interface AgentConfigUpdateBody {
  name?: string | null
  description?: string | null
  system_prompt?: string | null
  model_provider_id?: string | null
  model_name?: string | null
  model_config_json?: Record<string, unknown> | null
  runtime_config_json?: Record<string, unknown> | null
  context_policy_json?: Record<string, unknown> | null
  memory_policy_json?: Record<string, unknown> | null
  output_policy_json?: Record<string, unknown> | null
  schedule_config_json?: Record<string, unknown> | null
  output_schema_json?: Record<string, unknown> | null
}

export interface CreateAgentFromTemplateBody {
  template_version_id?: string | null
  space_id?: string | null
  name?: string | null
  description?: string | null
  model_config_json?: Record<string, unknown> | null
  schedule_config_json?: Record<string, unknown> | null
  system_prompt?: string | null
  context_policy_json?: Record<string, unknown> | null
  memory_policy_json?: Record<string, unknown> | null
  output_policy_json?: Record<string, unknown> | null
  output_schema_json?: Record<string, unknown> | null
}

export interface AgentCreateBody {
  name: string
  description?: string | null
  visibility?: string
  role_instruction?: string | null
  system_prompt?: string | null
  default_model_provider_id?: string | null
  default_model?: string | null
  adapter_type?: string | null
  runtime_config_json?: Record<string, unknown> | null
}

export interface AgentUpdateBody {
  name?: string
  description?: string | null
  visibility?: string
  role_instruction?: string | null
  status?: string
  system_prompt?: string | null
  default_model_provider_id?: string | null
  default_model?: string | null
}

export interface RunCreateBody {
  mode?: string
  run_type?: string
  trigger_origin?: string
  session_id?: string | null
  workspace_id?: string | null
  prompt?: string | null
  instruction?: string | null
  scheduled_at?: string | null
}

export interface Workspace {
  id: string
  owner_space_id: string
  created_by_user_id: string
  name: string
  slug: string | null
  description: string | null
  workspace_type: WorkspaceType
  kind: string
  repo_url: string | null
  root_path: string | null
  default_branch: string | null
  visibility: string
  status: WorkspaceStatus
  protected: boolean
  system_managed: boolean
  registered_from: string | null
  metadata_json: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export interface WorkspaceCreateBody {
  name: string
  description?: string
  workspace_type?: WorkspaceCreateType
  kind?: string
  repo_url?: string | null
  root_path?: string | null
  default_branch?: string | null
  metadata_json?: Record<string, unknown> | null
}

export type WorkspaceUpdateBody = Partial<Omit<WorkspaceCreateBody, 'workspace_type'>> & {
  status?: WorkspaceStatus
  visibility?: string
}

export interface Capability {
  id: string
  name: string
  version: string
  description: string | null
  enabled: boolean
  manifest_json: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface ContextPackage {
  user_memory: Memory[]
  workspace_memory: Memory[]
  capability_memory: Memory[]
  agent_memory: Memory[]
  system_policy: Memory[]
  relevant_episodes: Memory[]
  recent_session_summary: Record<string, unknown>[]
  attachments: Record<string, unknown>[]
}

export interface Feature {
  id: string
  name: string
  always_on: boolean
  enabled: boolean
}

export interface CapabilitiesReloadResult {
  loaded: number
  failed: number
  details: Record<string, unknown>[]
}

export interface ReflectResult {
  session_id: string
  proposals_created: number
  proposals: Proposal[]
}

export interface ApiError {
  error: string
  message?: string | Record<string, unknown>
  detail?: unknown
}

// ── Workspace Console ──────────────────────────────────────────────────────

export interface FileNode {
  name: string
  path: string          // relative to workspace root; "." for root
  type: 'file' | 'dir'
  size?: number
  children?: FileNode[]
}

export interface FileContent {
  path: string
  content: string
  size: number
  line_count: number
}

export interface GitChangedFile {
  path: string
  status: 'modified' | 'added' | 'deleted' | 'untracked' | 'renamed'
}

export interface GitStatus {
  is_repo: boolean
  branch: string | null
  files: GitChangedFile[]
}

export interface RuntimeInfo {
  id: string
  name: string
  available: boolean
  models: string[]
}

export type RuntimeEventType =
  | 'user_turn'
  | 'text_delta'
  | 'file_read'
  | 'grep'
  | 'command_start'
  | 'command_output'
  | 'file_changed'
  | 'patch_created'
  | 'run_completed'
  | 'run_failed'

export type RuntimeEvent =
  | { type: 'user_turn';     prompt: string }
  | { type: 'text_delta';    content: string }
  | { type: 'file_read';     path: string }
  | { type: 'grep';          query: string; path?: string }
  | { type: 'command_start'; command: string }
  | { type: 'command_output';stdout?: string; stderr?: string }
  | { type: 'file_changed';  path: string }
  | { type: 'patch_created'; files: string[] }
  | { type: 'run_completed' }
  | { type: 'run_failed';    error: string }

export type ConsoleSessionStatus = 'pending' | 'running' | 'completed' | 'failed' | 'stopped'

export interface ConsoleSession {
  id: string
  space_id: string
  workspace_id: string | null
  user_id: string
  runtime: string
  model: string | null
  prompt: string
  status: ConsoleSessionStatus
  notes: string | null
  events: RuntimeEvent[]
  created_at: string
  updated_at: string
}

export interface WorkspaceInfo {
  id: string
  name: string
  path: string | null
  type: string
  description: string | null
}

// ── Home summary (`GET /api/v1/home/summary`) ──────────────────────────────

export type HomeSuggestedActionPriority = 'high' | 'normal' | 'low'

export interface HomeRunSummaryItem {
  id: string
  status: string
  mode: string
  run_type: string
  agent_id: string
  task_id: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
  error_text: string | null
  visibility?: ObjectVisibility
}

export interface HomePendingProposalItem {
  id: string
  title: string
  proposal_type: string
  status: string
  risk_level: string
  urgency: string
  review_deadline: string | null
  expires_at: string | null
  expired: boolean
  preview: boolean
  created_by_run_id: string | null
  visibility?: ObjectVisibility
}

export interface HomePendingProposalsSection {
  count: number
  items: HomePendingProposalItem[]
}

export interface HomeArtifactSummaryItem {
  id: string
  title: string
  artifact_type: string
  preview: boolean
  run_id: string | null
  created_at: string
  visibility?: ObjectVisibility
}

export interface HomeTaskSummarySection {
  by_status: Record<string, number>
  total_open: number
  needs_review_count: number
  blocked_count: number
  done_count: number
}

export interface HomeActiveTaskItem {
  id: string
  title: string
  status: string
  priority: string
  risk_level: string
  task_type: string
  assigned_user_id: string | null
  assigned_agent_id: string | null
  due_at: string | null
  updated_at: string
  visibility?: ObjectVisibility
}

export interface HomeActivitySummarySection {
  recent_count: number
  raw_count: number
  today_count: number
}

export interface HomeRunStatsTodaySection {
  created: number
  queued: number
  running: number
  succeeded: number
  failed: number
  cancelled: number
  dry_run_count: number
}

export interface HomeJobQueueStatusSection {
  queued: number
  running: number
  failed: number
  retryable: number
  recent_error_preview: string | null
}

export interface HomeRuntimeStatusSection {
  real_adapters_configured_count: number
  configured_adapter_types: string[]
  message: string
}

export interface HomeModelProviderStatusSection {
  model_providers_count: number
  enabled_model_providers_count: number
  missing_model_provider_config: boolean
  message: string
}

export interface HomeSuggestedActionItem {
  id: string
  label: string
  reason: string
  target_path: string
  priority: HomeSuggestedActionPriority
}

export interface HomeIntakeSummarySection {
  open_items: number
  new_items_today: number
  pending_extraction_jobs: number
  failed_extraction_jobs: number
  candidate_evidence: number
  active_evidence: number
  due_connections: number
}

export interface HomeSummaryOut {
  recent_runs: HomeRunSummaryItem[]
  active_runs: HomeRunSummaryItem[]
  pending_proposals: HomePendingProposalsSection
  recent_artifacts: HomeArtifactSummaryItem[]
  task_summary: HomeTaskSummarySection
  active_tasks: HomeActiveTaskItem[]
  activity_summary: HomeActivitySummarySection
  run_stats_today: HomeRunStatsTodaySection
  job_queue_status: HomeJobQueueStatusSection
  runtime_status: HomeRuntimeStatusSection
  model_provider_status: HomeModelProviderStatusSection
  suggested_actions: HomeSuggestedActionItem[]
  intake_summary: HomeIntakeSummarySection
}

// ── Daily Capture Report ──────────────────────────────────────────────────

export interface DailyCaptureReportSettingOut {
  id: string
  space_id: string
  user_id: string
  enabled: boolean
  local_time: string
  timezone: string
  include_source_types: string[]
  create_experience_proposals: boolean
  create_memory_proposals: boolean
  experience_confidence_threshold: number
  memory_confidence_threshold: number
  max_experience_proposals_per_day: number
  max_memory_proposals_per_day: number
  last_report_date: string | null
  next_run_at: string | null
  created_at: string
  updated_at: string
}

export interface DailyCaptureReportSettingUpdate {
  enabled?: boolean | null
  local_time?: string | null
  timezone?: string | null
  include_source_types?: string[] | null
  create_experience_proposals?: boolean | null
  create_memory_proposals?: boolean | null
  experience_confidence_threshold?: number | null
  memory_confidence_threshold?: number | null
  max_experience_proposals_per_day?: number | null
  max_memory_proposals_per_day?: number | null
}

export interface DailyReportRunRequest {
  local_date?: string | null
  force?: boolean
  create_experience_proposals?: boolean | null
  create_memory_proposals?: boolean | null
}

export interface DailyReportRunResponse {
  run_id: string
  artifact_id: string | null
  proposal_ids: string[]
  experience_proposal_ids: string[]
  memory_proposal_ids: string[]
  capture_count: number
  status: string
  summary_preview: string
}

export interface DailyReportArtifactItem {
  id: string
  title: string
  artifact_type: string
  run_id: string | null
  created_at: string
  report_date: string | null
  capture_count: number
}

// ── Input Summary (POST /activity/summary-runs, POST /intake/summary-runs) ──

export interface SummaryRunRequest {
  activity_ids?: string[]
  evidence_ids?: string[]
  intake_item_ids?: string[]
  summary_goal?: string | null
  create_memory_proposal?: boolean
  create_knowledge_proposal?: boolean
}

export interface SummaryRunOut {
  run_id: string
  artifact_id: string
  proposal_ids: string[]
  status: string
  summary_preview: string
}

// ── Personal perspective (`GET /api/v1/me/*`) ─────────────────────────────

export interface MeRecentRunItem {
  id: string
  space_id: string
  agent_id: string
  status: string
  mode: string
  run_type: string
  created_at: string
  updated_at: string
}

export interface MeRecentParticipationItem {
  id: string
  user_id: string
  personal_space_id: string
  source_space_id: string
  source_object_type: string
  source_object_id: string
  role: string
  occurred_at: string
  created_at: string
}

export interface MeSpaceRollup {
  space_id: string
  name: string
  type: string
  pending_proposals_count: number
  assigned_tasks_count: number
  recent_failed_runs_count: number
}

export interface MeSummaryOut {
  pending_proposals_count: number
  assigned_tasks_count: number
  recent_runs: MeRecentRunItem[]
  recent_participation: MeRecentParticipationItem[]
  accessible_spaces_count: number
  spaces: MeSpaceRollup[]
}

export interface MeTimelineEntry {
  id: string
  entry_type: 'participation' | string
  source_space_id: string | null
  source_object_type: string | null
  source_object_id: string | null
  role: string | null
  occurred_at: string
  created_at: string
}

export interface MeTaskItem {
  id: string
  space_id: string
  title: string
  status: string
  priority: string
  visibility: ObjectVisibility
  created_by_user_id: string | null
  assigned_user_id: string | null
  created_at: string
  updated_at: string
}

export interface MePendingProposalItem {
  id: string
  space_id: string
  proposal_type: string
  status: string
  urgency: string
  title: string
  visibility: ObjectVisibility
  created_by_user_id: string | null
  created_at: string
  updated_at: string
}

// ── Projects ───────────────────────────────────────────────────────────────

export type ProjectStatus = 'active' | 'archived'

export interface Project {
  id: string
  space_id: string
  owner_user_id: string | null
  name: string
  description: string | null
  status: ProjectStatus
  current_focus: string | null
  settings_json: Record<string, unknown> | null
  created_at: string
  updated_at: string
  archived_at: string | null
}

export interface ProjectCreate {
  name: string
  description?: string | null
  current_focus?: string | null
  settings_json?: Record<string, unknown> | null
}

export interface ProjectUpdate {
  name?: string | null
  description?: string | null
  current_focus?: string | null
  status?: ProjectStatus | null
  settings_json?: Record<string, unknown> | null
}

export interface ProjectWorkspaceLinkCreate {
  workspace_id: string
  role?: string
}

export interface ProjectWorkspaceLinkOut {
  id: string
  project_id: string
  workspace_id: string
  role: string
  created_at: string
  updated_at: string
}

export interface ProjectSummary {
  project_id: string
  activity_count: number
  artifact_count: number
  pending_proposal_count: number
  workspace_count: number
  active_run_count: number
  memory_entry_count: number
}

// ── Automations ─────────────────────────────────────────────────────────────
export type AutomationTriggerType = 'manual' | 'schedule'

export interface AutomationOut {
  id: string
  space_id: string
  owner_user_id: string
  agent_id: string
  workspace_id: string | null
  name: string
  description: string | null
  trigger_type: string
  status: string
  preflight_snapshot_json: Record<string, unknown> | null
  config_json: Record<string, unknown> | null
  next_run_at: string | null
  last_fired_at: string | null
  created_at: string
  updated_at: string
}

export interface AutomationCreateBody {
  name: string
  agent_id: string
  workspace_id?: string | null
  description?: string | null
  trigger_type?: AutomationTriggerType
  config_json?: Record<string, unknown> | null
}

export interface AutomationUpdateBody {
  name?: string | null
  description?: string | null
  status?: string | null
  config_json?: Record<string, unknown> | null
}

export interface AutomationFireResult {
  run_id: string
  automation_run_id: string
  trigger_origin: string
  preflight_executable: boolean
}
