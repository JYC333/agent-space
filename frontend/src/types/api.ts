// API response shapes — mirroring the backend Pydantic schemas

export type SpaceType      = 'personal' | 'family' | 'team'
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
export type ProposalStatus   = 'pending' | 'accepted' | 'rejected' | 'needs_changes'
export type ActivityStatus     = 'raw' | 'processed' | 'proposals_generated' | 'archived'
export type ActivitySourceType = 'user_input' | 'imported_chat' | 'web_capture' | 'file_import' | 'agent_run' | 'task_log' | 'manual'
export type SessionStatus    = 'active' | 'closed'
export type RunStatus        = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
export type MessageRole      = 'user' | 'assistant' | 'system' | 'tool'
export type WorkspaceStatus  = 'active' | 'archived'
export type WorkspaceType    = 'project' | 'repo' | 'knowledge_base' | 'personal' | 'team'

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

export interface MemoryProposal {
  id: string
  space_id: string
  user_id: string
  workspace_id: string | null
  proposed_title: string
  proposed_content: string
  memory_type: string
  target_scope: string
  target_namespace: string
  target_visibility: string
  rationale: string
  source_evidence: string | null
  risk_level: 'low' | 'medium' | 'high' | 'critical'
  review_metadata: Record<string, unknown> | null
  approved_by: string | null
  status: ProposalStatus
  source_session_id: string | null
  source_task_id: string | null
  source_run_id: string | null
  source_activity_id: string | null
  resulting_memory_id: string | null
  created_at: string
  decided_at: string | null
}

export interface ActivityRecord {
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
  created_at: string
  updated_at: string
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

export interface Task {
  id: string
  space_id: string
  user_id: string
  workspace_id: string | null
  session_id: string | null
  title: string
  description: string | null
  capability_id: string | null
  status: string
  result: string | null
  error: string | null
  created_at: string
  updated_at: string
}

export interface AgentRun {
  id: string
  task_id: string | null
  space_id: string
  user_id: string
  agent_id: string | null
  cli_adapter_config_id: string | null
  adapter_type: string
  capability_id: string | null
  model_selection_mode: ModelSelectionMode
  model_override_json: Record<string, unknown> | null
  prompt: string
  status: RunStatus
  output: string | null
  error: string | null
  exit_code: number | null
  sandbox_level: string | null
  sandbox_path: string | null
  executor_type: string | null
  delegation_depth: number
  runtime_seconds: number | null
  usage_accuracy: 'precise' | 'estimated' | 'unknown'
  estimated_input_tokens: number | null
  estimated_output_tokens: number | null
  estimated_cost: number | null
  started_at: string | null
  completed_at: string | null
  created_at: string
}

export interface Workspace {
  id: string
  space_id: string
  created_by: string
  name: string
  description: string | null
  type: WorkspaceType
  status: WorkspaceStatus
  path: string | null
  metadata_json: Record<string, unknown> | null
  created_at: string
  updated_at: string
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
  proposals: MemoryProposal[]
}

export interface ApiError {
  error: string
  message: string
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
