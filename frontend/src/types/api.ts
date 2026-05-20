// API response shapes — mirroring the backend Pydantic schemas

export type SpaceType      = 'personal' | 'household' | 'team'
export type MemberRole     = 'owner' | 'admin' | 'member' | 'viewer'
export type InviteStatus   = 'pending' | 'accepted' | 'revoked' | 'expired'

export interface CurrentUser {
  id: string
  email: string
  display_name: string
  avatar_url: string | null
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
export type MemoryVisibility = 'private' | 'space_shared' | 'workspace_shared' | 'restricted' | 'public_template'
export type ObjectVisibility = 'private' | 'space_shared' | 'restricted' | string
export type ProposalStatus   = 'pending' | 'accepted' | 'rejected'
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

// CLI Adapters
export type CLIAdapterId =
  | 'claude_code'
  | 'codex_cli'
  | 'opencode'
  | 'gemini_cli'
  | 'custom'
  | 'echo'

export type QuotaStatus = 'enough' | 'medium' | 'low' | 'exhausted' | 'unknown'

export type ModelSelectionMode = 'cli_default' | 'cli_model_override' | 'agent_space_provider'

export interface CLIAdapterCapabilities {
  supportsHeadlessRun: boolean
  supportsInteractiveRun: boolean
  supportsStreamingLogs: boolean
  supportsModelOverride: boolean
  supportsUsageOutput: boolean
  supportsPatchOutput: boolean
  contextFileType: 'CLAUDE.md' | 'AGENTS.md' | 'prompt.md' | 'custom'
  usageAccuracy: 'precise' | 'estimated' | 'unknown'
}

export interface CLIStatus {
  adapter_id: string
  available: boolean
  version: string | null
  executable_path: string | null
  login_detected: boolean | null
  status_message: string | null
  capabilities: CLIAdapterCapabilities | null
}

export interface CLIAdapterConfig {
  id: string
  space_id: string
  adapter_id: CLIAdapterId
  display_name: string
  enabled: boolean
  executable_path: string | null
  default_mode: 'interactive' | 'headless'
  quota_status: QuotaStatus
  notes: string | null
  created_at: string
  updated_at: string
}

export interface BuiltinAdapter {
  id: string
  display_name: string
}

// CLI Credentials / Login

export type LoginMethod = 'cli' | 'api_key'

export interface CredentialLoginMethod {
  runtime: string
  method: LoginMethod
  label: string
  hint_cli: string
  hint_api_key: string
  env_var: string | null
  supports_api_key: boolean
  supports_cli: boolean
}

export interface CredentialStatus {
  runtime: string
  label: string
  method: LoginMethod
  profile_id: string | null
  logged_in: boolean
  file_count: number
}

export type LoginEventType = 'output' | 'error' | 'warning' | 'hint' | 'synced' | 'done' | 'needs_input'

export interface LoginEvent {
  type: LoginEventType
  text?: string
  exit_code?: number
  profile_id?: string
  prompt?: string
  step?: string
}

export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
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
  owner_user_id: string
  workspace_id: string | null
  agent_id: string | null
  capability_id: string | null
  source_activity_id: string | null
  source_artifact_id: string | null
  approved_by: string | null
  title: string
  content: string
  type: MemoryType
  scope: MemoryScope
  namespace: string
  status: MemoryStatus
  visibility: MemoryVisibility
  confidence: number
  importance: number
  source_id: string | null
  created_by: string
  version: number
  access_count: number
  tags: string[] | null
  created_at: string
  updated_at: string
  deleted_at: string | null
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
  current_version_id: string | null
  model: AgentModelSummary | null
  created_at: string
  updated_at: string
}

export interface AgentCreateBody {
  name: string
  description?: string | null
  visibility?: string
  role_instruction?: string | null
  default_model_provider_id?: string | null
  default_model?: string | null
}

export interface AgentUpdateBody {
  name?: string
  description?: string | null
  visibility?: string
  role_instruction?: string | null
  status?: string
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
  message: string | Record<string, unknown>
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

export interface MeSummaryOut {
  pending_proposals_count: number
  assigned_tasks_count: number
  recent_runs: MeRecentRunItem[]
  recent_participation: MeRecentParticipationItem[]
  accessible_spaces_count: number
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
