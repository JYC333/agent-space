import type {
  Memory, Session, Message, Task,
  Capability, ContextPackage, Feature, Workspace, WorkspaceCreateBody, WorkspaceUpdateBody, Page,
  CapabilitiesReloadResult, ReflectResult, ApiError,
  RuntimeToolDefinition, RuntimeToolInstallResult, RuntimeToolStatus, RuntimeToolLatest,
  CredentialLoginMethod, CredentialStatus, CliUsageEntry, CliUsageAutoRefreshSettings, LoginEvent,
  CurrentUser, SpaceWithMembership, SpaceMember, SpaceInvitationOut,
  Job, JobEvent, ActivityInboxRecord,
  Board, TaskRunCreateBody, Run, RunStatusOut, TaskRunListItem,
  TaskArtifact, TaskProposal, Artifact, Proposal, ProposalAcceptOut, AgentOut, AgentCreateBody, AgentUpdateBody, RunCreateBody,
  AgentTemplateOut, AgentTemplateVersionOut, CreateAgentFromTemplateBody,
  AgentVersionOut, AgentConfigUpdateBody, ChatTurnOut,
  SpaceAssistantSettingsOut, SpaceAssistantSettingsUpdate,
  ActivityRecord, ActivitySourceType,
  KnowledgeCreateProposalBody, KnowledgeItem, KnowledgeItemSummary, KnowledgeRelation, KnowledgeRelationProposalBody, KnowledgeUpdateProposalBody,
  KnowledgeSummary, KnowledgeSourceSummary,
  Note, NoteSummary, NoteCreateBody, NoteUpdateBody, NoteCollection, NoteCollectionCreateBody, NoteCollectionUpdateBody, EntityLink, NoteLinkCreateBody,
  FileNode, FileContent, GitStatus, RuntimeInfo, ConsoleSession, WorkspaceInfo,
  HomeSummaryOut, MeSummaryOut, MeTimelineEntry, MeTaskItem, MePendingProposalItem,
  PersonalMemoryGrantPreviewRequest, PersonalMemoryGrantPreviewResponse,
  PersonalMemoryGrantCreateRequest, PersonalMemoryGrantResponse,
  PersonalMemoryGrantAuditResponse,
  EgressApprovalRequest, ProposalApprovalResponse,
  EvolutionSummaryOut, EvolutionTarget, EvolutionTargetCreateBody, EvolutionTargetUpdateBody, EvolutionSignal, EvolutionSignalCreateBody,
  EvolutionRunListItem, EvolutionRunResult, EvolutionProposal, EvolutionValidationResult,
  Project, ProjectCreate, ProjectUpdate, ProjectWorkspaceLinkCreate, ProjectWorkspaceLinkOut, ProjectSummary,
  SourceConnector, SourceConnection, SourceConnectionCreate, IntakeItem, ExtractionJob,
  ExtractedEvidence, EvidenceLink, WorkspaceIntakeProfile, WorkspaceSourceBinding,
  SummaryRunRequest, SummaryRunOut,
  DailyCaptureReportSettingOut, DailyCaptureReportSettingUpdate,
  DailyReportRunRequest, DailyReportRunResponse, DailyReportArtifactItem,
  AutomationOut, AutomationCreateBody, AutomationUpdateBody, AutomationFireResult,
} from '../types/api'

const BASE = '/api/v1'

let _spaceId = 'personal'
let _userId  = 'default_user'
let _apiKey: string | null = null

export function setSpaceContext(spaceId: string, userId: string): void {
  _spaceId = spaceId
  _userId  = userId
}

export function setAuth(key: string | null): void {
  _apiKey = key
}

function spaceParams(spaceId = _spaceId, userId = _userId): string {
  return `space_id=${encodeURIComponent(spaceId)}&user_id=${encodeURIComponent(userId)}`
}

function formatApiErrorMessage(err: ApiError, fallback: string): string {
  if (typeof err.detail === 'string') return err.detail
  if (err.detail && typeof err.detail === 'object') return JSON.stringify(err.detail)
  const m = err.message
  if (typeof m === 'string') return m
  if (m && typeof m === 'object') {
    const rec = m as Record<string, unknown>
    const code = rec.code
    if (typeof code === 'string') return code
    return JSON.stringify(m)
  }
  return fallback
}

interface RequestOptions {
  includeSpaceParams?: boolean
  spaceId?: string
}

async function request<T = unknown>(method: string, path: string, body?: unknown, options: RequestOptions = {}): Promise<T> {
  // FormData (file/voice upload) must keep the browser-set multipart boundary, so
  // we do not force a Content-Type for it and pass the body through unserialized.
  const isForm = typeof FormData !== 'undefined' && body instanceof FormData
  const headers: Record<string, string> = isForm ? {} : { 'Content-Type': 'application/json' }
  if (_apiKey) headers['Authorization'] = `Bearer ${_apiKey}`

  const includeSpaceParams = options.includeSpaceParams ?? true
  const url = includeSpaceParams
    ? BASE + path + (path.includes('?') ? '&' : '?') + spaceParams(options.spaceId)
    : BASE + path

  const opts: RequestInit = { method, headers }
  if (body !== undefined) opts.body = isForm ? (body as FormData) : JSON.stringify(body)

  const r = await fetch(url, opts)

  if (r.status === 401) {
    window.dispatchEvent(new CustomEvent('auth:required'))
  }

  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`
    try {
      const err = await r.json() as ApiError
      msg = formatApiErrorMessage(err, msg)
    } catch {
      const text = await r.text().catch(() => '')
      if (text) msg = text
    }
    throw new Error(msg)
  }

  if (r.status === 204) return null as T
  return r.json() as Promise<T>
}

const get   = <T>(path: string, options?: RequestOptions)                => request<T>('GET',    path, undefined, options)
const post  = <T>(path: string, body?: unknown, options?: RequestOptions) => request<T>('POST',   path, body, options)
const put   = <T>(path: string, body?: unknown, options?: RequestOptions) => request<T>('PUT',    path, body, options)
const patch = <T>(path: string, body?: unknown, options?: RequestOptions) => request<T>('PATCH',  path, body, options)
const del   = <T>(path: string, options?: RequestOptions)                => request<T>('DELETE', path, undefined, options)

// ── Memory ────────────────────────────────────────────────────────────────
export const memoryApi = {
  list: (params: {
    scope?: string
    namespace?: string
    type?: string
    status?: string
    workspace_id?: string
    project_id?: string
    limit?: number
    offset?: number
  } = {}) => {
    const q: Record<string, string> = {}
    if (params.scope !== undefined) q.scope = params.scope
    if (params.namespace !== undefined) q.namespace = params.namespace
    if (params.type !== undefined) q.type = params.type
    if (params.status !== undefined) q.status = params.status
    if (params.workspace_id !== undefined) q.workspace_id = params.workspace_id
    if (params.project_id !== undefined) q.project_id = params.project_id
    if (params.limit !== undefined) q.limit = String(params.limit)
    if (params.offset !== undefined) q.offset = String(params.offset)
    return get<Page<Memory>>('/memory?' + new URLSearchParams(q))
  },
  get: (id: string, params: { workspace_id?: string } = {}) => {
    const q: Record<string, string> = {}
    if (params.workspace_id !== undefined) q.workspace_id = params.workspace_id
    const suffix = Object.keys(q).length ? '?' + new URLSearchParams(q) : ''
    return get<Memory>(`/memory/${id}${suffix}`)
  },
  create: (data: Partial<Memory>) =>
    post<Proposal>('/memory', { space_id: _spaceId, owner_user_id: _userId, ...data }),
  update: (id: string, data: Partial<Memory>) =>
    patch<Proposal>(`/memory/${id}`, data),
  delete: (id: string) =>
    del<Proposal>(`/memory/${id}`),
  search: (data: { query: string; scope?: string; namespace?: string; type?: string; workspace_id?: string; limit?: number }) =>
    post<Memory[]>('/memory/search', { space_id: _spaceId, user_id: _userId, ...data }),
}

// ── Knowledge ─────────────────────────────────────────────────────────────
export const knowledgeApi = {
  list: (params: {
    item_type?: string
    status?: string
    visibility?: string
    q?: string
    limit?: number
    offset?: number
  } = {}) => {
    const q: Record<string, string> = {}
    if (params.item_type !== undefined) q.item_type = params.item_type
    if (params.status !== undefined) q.status = params.status
    if (params.visibility !== undefined) q.visibility = params.visibility
    if (params.q !== undefined) q.q = params.q
    if (params.limit !== undefined) q.limit = String(params.limit)
    if (params.offset !== undefined) q.offset = String(params.offset)
    return get<Page<KnowledgeItemSummary>>('/knowledge/items?' + new URLSearchParams(q))
  },
  get: (id: string) => get<KnowledgeItem>(`/knowledge/items/${id}`),
  relations: (id: string) => get<KnowledgeRelation[]>(`/knowledge/items/${id}/relations`),
  backlinks: (id: string) => get<EntityLink[]>(`/knowledge/items/${id}/backlinks`),
  proposeCreate: (body: KnowledgeCreateProposalBody) =>
    post<Proposal>('/knowledge/items/proposals', body),
  proposeUpdate: (id: string, body: KnowledgeUpdateProposalBody) =>
    patch<Proposal>(`/knowledge/items/${id}/proposals`, body),
  proposeArchive: (id: string) =>
    del<Proposal>(`/knowledge/items/${id}`),
  proposeRelation: (body: KnowledgeRelationProposalBody) =>
    post<Proposal>('/knowledge/relations/proposals', body),
  proposeRelationArchive: (id: string) =>
    del<Proposal>(`/knowledge/relations/${id}`),
  summary: () => get<KnowledgeSummary>('/knowledge/summary'),
}

// ── Notes (working knowledge; direct CRUD) ─────────────────────────────────
export const notesCollectionsApi = {
  list: () => get<NoteCollection[]>('/notes/collections'),
  create: (body: NoteCollectionCreateBody) => post<NoteCollection>('/notes/collections', body),
  update: (id: string, body: NoteCollectionUpdateBody) => patch<NoteCollection>(`/notes/collections/${id}`, body),
  delete: (id: string) => del<void>(`/notes/collections/${id}`),
}

export const notesApi = {
  list: (params: { status?: string; project_id?: string; collection_id?: string; q?: string; limit?: number; offset?: number } = {}) => {
    const q: Record<string, string> = {}
    if (params.status !== undefined) q.status = params.status
    if (params.project_id !== undefined) q.project_id = params.project_id
    if (params.collection_id !== undefined) q.collection_id = params.collection_id
    if (params.q !== undefined) q.q = params.q
    if (params.limit !== undefined) q.limit = String(params.limit)
    if (params.offset !== undefined) q.offset = String(params.offset)
    return get<Page<NoteSummary>>('/knowledge/notes?' + new URLSearchParams(q))
  },
  get: (id: string) => get<Note>(`/knowledge/notes/${id}`),
  create: (body: NoteCreateBody) => post<Note>('/knowledge/notes', body),
  update: (id: string, body: NoteUpdateBody) => patch<Note>(`/knowledge/notes/${id}`, body),
  delete: (id: string) => del<Note>(`/knowledge/notes/${id}`),
  purgeDeleted: () => post<{ deleted: number; retention_days: number }>('/knowledge/notes/deleted/purge'),
  links: (id: string) => get<EntityLink[]>(`/knowledge/notes/${id}/links`),
  backlinks: (id: string) => get<EntityLink[]>(`/knowledge/notes/${id}/backlinks`),
  createLink: (id: string, body: NoteLinkCreateBody) =>
    post<EntityLink>(`/knowledge/notes/${id}/links`, body),
  deleteLink: (id: string, linkId: string) =>
    del<void>(`/knowledge/notes/${id}/links/${linkId}`),
}

// ── Sources (provenance / evidence layer) ──────────────────────────────────
export const sourcesApi = {
  list: (params: { source_type?: string; status?: string; q?: string; limit?: number; offset?: number } = {}) => {
    const q: Record<string, string> = {}
    if (params.source_type !== undefined) q.source_type = params.source_type
    if (params.status !== undefined) q.status = params.status
    if (params.q !== undefined) q.q = params.q
    if (params.limit !== undefined) q.limit = String(params.limit)
    if (params.offset !== undefined) q.offset = String(params.offset)
    return get<Page<KnowledgeSourceSummary>>('/knowledge/sources?' + new URLSearchParams(q))
  },
}

// ── Sessions ──────────────────────────────────────────────────────────────
export const sessionsApi = {
  list:       (params: Record<string, string> = {}) =>
    get<Page<Session>>('/sessions?' + new URLSearchParams(params)),
  create:     (data: Partial<Session>)              => post<Session>('/sessions', data),
  get:        (id: string)                          => get<Session>(`/sessions/${id}`),
  messages:   (id: string)                          => get<Message[]>(`/sessions/${id}/messages`),
  addMessage: (id: string, data: { role: string; content: string }) =>
    post<Message>(`/sessions/${id}/messages`, data),
  reflect:    (id: string)                          => post<ReflectResult>(`/sessions/${id}/reflect`),
}

// ── Boards (task surfaces) ────────────────────────────────────────────────
export const boardsApi = {
  list:   (params: Record<string, string> = {}) =>
    get<Page<Board>>('/boards?' + new URLSearchParams(params)),
  create: (body: Partial<Board> & { name: string }) =>
    post<Board>('/boards', body),
  get:    (id: string) => get<Board>(`/boards/${id}`),
  update: (id: string, body: Record<string, unknown>) =>
    patch<Board>(`/boards/${id}`, body),
  tasks:  (boardId: string, params: Record<string, string> = {}) =>
    get<Page<Task>>(`/boards/${boardId}/tasks?` + new URLSearchParams(params)),
}

// ── Tasks (product work items) ─────────────────────────────────────────────
export const tasksApi = {
  list:   (params: Record<string, string> = {}) =>
    get<Page<Task>>('/tasks?' + new URLSearchParams(params)),
  create: (data: Record<string, unknown>, options: { spaceId?: string } = {}) =>
    post<Task>('/tasks', data, { spaceId: options.spaceId }),
  get:    (id: string) => get<Task>(`/tasks/${id}`),
  update: (id: string, data: Record<string, unknown>) =>
    patch<Task>(`/tasks/${id}`, data),
  createRun: (taskId: string, body: TaskRunCreateBody = {}) =>
    post<Run>(`/tasks/${taskId}/runs`, body),
  runs:   (taskId: string, params: Record<string, string> = {}) =>
    get<Page<TaskRunListItem>>(`/tasks/${taskId}/runs?` + new URLSearchParams(params)),
  artifacts: (taskId: string, params: Record<string, string> = {}) =>
    get<Page<TaskArtifact>>(`/tasks/${taskId}/artifacts?` + new URLSearchParams(params)),
  proposals: (taskId: string, params: Record<string, string> = {}) =>
    get<Page<TaskProposal>>(`/tasks/${taskId}/proposals?` + new URLSearchParams(params)),
}

// ── Home (Today Command Center summary) ───────────────────────────────────
export const homeApi = {
  summary: (params: Record<string, string> = {}) =>
    get<HomeSummaryOut>('/home/summary?' + new URLSearchParams(params)),
}

// ── Personal perspective (/me aggregation) ─────────────────────────────────
export const meApi = {
  summary: (params: Record<string, string> = {}) =>
    get<MeSummaryOut>('/me/summary?' + new URLSearchParams(params), { includeSpaceParams: false }),
  timeline: (params: Record<string, string> = {}) =>
    get<MeTimelineEntry[]>('/me/timeline?' + new URLSearchParams(params), { includeSpaceParams: false }),
  tasks: (params: Record<string, string> = {}) =>
    get<MeTaskItem[]>('/me/tasks?' + new URLSearchParams(params), { includeSpaceParams: false }),
  pending: (params: Record<string, string> = {}) =>
    get<MePendingProposalItem[]>('/me/pending?' + new URLSearchParams(params), { includeSpaceParams: false }),
}

// ── Runs (canonical API) ──────────────────────────────────────────────────
export const runsApi = {
  list: (params: {
    status?: string
    mode?: string
    agent_id?: string
    workspace_id?: string
    project_id?: string
    limit?: number
    offset?: number
  } = {}) => {
    const q: Record<string, string> = {}
    if (params.status !== undefined) q.status = params.status
    if (params.mode !== undefined) q.mode = params.mode
    if (params.agent_id !== undefined) q.agent_id = params.agent_id
    if (params.workspace_id !== undefined) q.workspace_id = params.workspace_id
    if (params.project_id !== undefined) q.project_id = params.project_id
    if (params.limit !== undefined) q.limit = String(params.limit)
    if (params.offset !== undefined) q.offset = String(params.offset)
    return get<Run[]>('/runs?' + new URLSearchParams(q))
  },
  get:    (id: string) => get<Run>(`/runs/${id}`),
  status: (id: string) => get<RunStatusOut>(`/runs/${id}/status`),
  stop:   (id: string) => patch<Record<string, unknown>>(`/runs/${id}/stop`),
  executeQueuedRun: (id: string) => post<Run>(`/runs/${id}/execute`),
  activities: (id: string, params: Record<string, string> = {}) =>
    get<Page<ActivityRecord>>(`/runs/${id}/activities?` + new URLSearchParams(params)),
  artifacts: (id: string, params: Record<string, string> = {}) =>
    get<Page<Artifact>>(`/runs/${id}/artifacts?` + new URLSearchParams(params)),
  proposals: (id: string, params: Record<string, string> = {}) =>
    get<Page<Proposal>>(`/runs/${id}/proposals?` + new URLSearchParams(params)),
}

// ── Personal Memory Grants ─────────────────────────────────────────────────
export const personalMemoryGrantsApi = {
  previewPersonalMemoryGrant: (input: PersonalMemoryGrantPreviewRequest) =>
    post<PersonalMemoryGrantPreviewResponse>('/personal-memory-grants/preview', input),
  createPersonalMemoryGrant: (input: PersonalMemoryGrantCreateRequest) =>
    post<PersonalMemoryGrantResponse>('/personal-memory-grants', input),
  listPersonalMemoryGrants: (filters: { status?: string; target_space_id?: string } = {}) => {
    const q: Record<string, string> = {}
    if (filters.status !== undefined) q.status = filters.status
    if (filters.target_space_id !== undefined) q.target_space_id = filters.target_space_id
    return get<PersonalMemoryGrantResponse[]>('/personal-memory-grants?' + new URLSearchParams(q))
  },
  revokePersonalMemoryGrant: (grantId: string) =>
    post<PersonalMemoryGrantResponse>(`/personal-memory-grants/${grantId}/revoke`),
  getPersonalMemoryGrantAudit: (grantId: string) =>
    get<PersonalMemoryGrantAuditResponse>(`/personal-memory-grants/${grantId}/audit`),
}

// ── Artifacts ─────────────────────────────────────────────────────────────
export const artifactsApi = {
  list: (params: {
    artifact_type?: string
    project_id?: string
    limit?: number
    offset?: number
  } = {}) => {
    const q: Record<string, string> = {}
    if (params.artifact_type !== undefined) q.artifact_type = params.artifact_type
    if (params.project_id !== undefined) q.project_id = params.project_id
    if (params.limit !== undefined) q.limit = String(params.limit)
    if (params.offset !== undefined) q.offset = String(params.offset)
    return get<Page<Artifact>>('/artifacts?' + new URLSearchParams(q))
  },
  get: (id: string) => get<Artifact>(`/artifacts/${id}`),
  export: (id: string) => downloadArtifactExport(id),
}

async function downloadArtifactExport(artifactId: string): Promise<void> {
  const headers: Record<string, string> = {}
  if (_apiKey) headers['Authorization'] = `Bearer ${_apiKey}`
  const sep = '/artifacts/' + artifactId + '/export'
  const url = BASE + sep + (sep.includes('?') ? '&' : '?') + spaceParams()
  const r = await fetch(url, { method: 'GET', headers })
  if (r.status === 401) window.dispatchEvent(new CustomEvent('auth:required'))
  if (r.status === 404) throw new Error('Artifact not found or not exportable')
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`
    try {
      const err = await r.json() as ApiError
      msg = formatApiErrorMessage(err, msg)
    } catch {
      const text = await r.text().catch(() => '')
      if (text) msg = text
    }
    throw new Error(msg)
  }
  const cd = r.headers.get('Content-Disposition')
  let filename = 'artifact'
  if (cd) {
    const m = /filename="([^"]+)"/.exec(cd) ?? /filename=([^;]+)/.exec(cd)
    if (m) filename = m[1].trim()
  }
  const blob = await r.blob()
  const href = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = href
  a.download = filename
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(href)
}

// ── Proposals (canonical list) ────────────────────────────────────────────
export const proposalsApi = {
  list: (params: {
    status?: string
    type?: string
    proposal_type?: string
    urgency?: string
    expired?: boolean
    project_id?: string
    limit?: number
    offset?: number
  } = {}) => {
    const q: Record<string, string> = {}
    if (params.status !== undefined) q.status = params.status
    if (params.type !== undefined) q.type = params.type
    if (params.proposal_type !== undefined) q.type = params.proposal_type
    if (params.urgency !== undefined) q.urgency = params.urgency
    if (params.expired !== undefined) q.expired = String(params.expired)
    if (params.project_id !== undefined) q.project_id = params.project_id
    if (params.limit !== undefined) q.limit = String(params.limit)
    if (params.offset !== undefined) q.offset = String(params.offset)
    return get<Page<Proposal>>('/proposals?' + new URLSearchParams(q))
  },
  get: (id: string) => get<Proposal>(`/proposals/${id}`),
  accept: (id: string) => post<ProposalAcceptOut>(`/proposals/${id}/accept`),
  reject: (id: string) => post<Proposal>(`/proposals/${id}/reject`),
  approveEgressGrantingUserProposal: (id: string, input: EgressApprovalRequest = {}) =>
    post<ProposalApprovalResponse>(`/proposals/${id}/approvals/egress-granting-user`, input),
}

// ── Evolution ─────────────────────────────────────────────────────────────
export const evolutionApi = {
  summary: () => get<EvolutionSummaryOut>('/evolution/summary'),
  targets: (params: { status?: string } = {}) => {
    const q: Record<string, string> = {}
    if (params.status !== undefined) q.status = params.status
    const query = new URLSearchParams(q).toString()
    return get<EvolutionTarget[]>(query ? `/evolution/targets?${query}` : '/evolution/targets')
  },
  createTarget: (body: EvolutionTargetCreateBody) =>
    post<EvolutionTarget>('/evolution/targets', body),
  target: (id: string) => get<EvolutionTarget>(`/evolution/targets/${id}`),
  updateTarget: (id: string, body: EvolutionTargetUpdateBody) =>
    patch<EvolutionTarget>(`/evolution/targets/${id}`, body),
  signals: (params: { limit?: number; offset?: number } = {}) => {
    const q: Record<string, string> = {}
    if (params.limit !== undefined) q.limit = String(params.limit)
    if (params.offset !== undefined) q.offset = String(params.offset)
    return get<EvolutionSignal[]>('/evolution/signals?' + new URLSearchParams(q))
  },
  targetSignals: (targetId: string, params: { limit?: number; offset?: number } = {}) => {
    const q: Record<string, string> = {}
    if (params.limit !== undefined) q.limit = String(params.limit)
    if (params.offset !== undefined) q.offset = String(params.offset)
    return get<EvolutionSignal[]>(`/evolution/targets/${targetId}/signals?` + new URLSearchParams(q))
  },
  createSignal: (targetId: string, body: EvolutionSignalCreateBody) =>
    post<EvolutionSignal>(`/evolution/targets/${targetId}/signals`, body),
  runs: (params: { limit?: number; offset?: number } = {}) => {
    const q: Record<string, string> = {}
    if (params.limit !== undefined) q.limit = String(params.limit)
    if (params.offset !== undefined) q.offset = String(params.offset)
    return get<EvolutionRunListItem[]>('/evolution/runs?' + new URLSearchParams(q))
  },
  runTarget: (targetId: string, body: { engine?: string } = {}) =>
    post<EvolutionRunResult>(`/evolution/targets/${targetId}/run`, body),
  proposals: (params: { limit?: number; offset?: number } = {}) => {
    const q: Record<string, string> = {}
    if (params.limit !== undefined) q.limit = String(params.limit)
    if (params.offset !== undefined) q.offset = String(params.offset)
    return get<EvolutionProposal[]>('/evolution/proposals?' + new URLSearchParams(q))
  },
  validation: () => get<EvolutionValidationResult[]>('/evolution/validation'),
}

// ── Agents ────────────────────────────────────────────────────────────────
export const agentsApi = {
  list: (params: Record<string, string> = {}) =>
    get<AgentOut[]>('/agents?' + new URLSearchParams(params)),
  get: (agentId: string) => get<AgentOut>(`/agents/${agentId}`),
  create: (data: AgentCreateBody) => post<AgentOut>('/agents', data),
  update: (agentId: string, data: AgentUpdateBody) => patch<AgentOut>(`/agents/${agentId}`, data),
  // Config edit: appends a new immutable AgentVersion and repoints current_version_id.
  updateConfig: (agentId: string, data: AgentConfigUpdateBody) =>
    post<AgentOut>(`/agents/${agentId}/config`, data),
  currentVersion: (agentId: string) => get<AgentVersionOut>(`/agents/${agentId}/current-version`),
  // Per-space system-managed default Assistant (the Chat identity). ensure is idempotent.
  getDefaultAssistant: () => get<AgentOut>('/agents/default-assistant'),
  ensureDefaultAssistant: () => post<AgentOut>('/agents/default-assistant'),
  // Assistant preferences (soft UI/context layer — never edits prompt or hard policy).
  getAssistantSettings: () => get<SpaceAssistantSettingsOut>('/agents/default-assistant/settings'),
  updateAssistantSettings: (data: SpaceAssistantSettingsUpdate) =>
    patch<SpaceAssistantSettingsOut>('/agents/default-assistant/settings', data),
  listVersions: (agentId: string) => get<AgentVersionOut[]>(`/agents/${agentId}/versions`),
  getVersion: (agentId: string, versionId: string) =>
    get<AgentVersionOut>(`/agents/${agentId}/versions/${versionId}`),
  restoreVersion: (agentId: string, versionId: string) =>
    post<AgentOut>(`/agents/${agentId}/versions/${versionId}/restore`),
  listProposals: (agentId: string, status = 'pending') =>
    get<Proposal[]>(`/agents/${agentId}/proposals?status=${encodeURIComponent(status)}`),
  createRun: (agentId: string, body: RunCreateBody = {}) =>
    post<Run>(`/agents/${agentId}/runs`, body),
  // Synchronous Personal Assistant chat turn. spaceId pins the request to the
  // agent's space (the assistant may live in a space other than the active one).
  chat: (agentId: string, body: { message: string; session_id?: string }, options: { spaceId?: string } = {}) =>
    post<ChatTurnOut>(`/agents/${agentId}/chat`, body, { spaceId: options.spaceId }),
  listRuns:       (limit = 50)        => get<Run[]>(`/agents/runs?limit=${limit}`),
  getRun:         (runId: string)     => get<Run>(`/agents/runs/${runId}`),
  listRunsForAgent:  (agentId: string)   => get<Run[]>(`/agents/${agentId}/runs`),
}

// ── Agent Templates (reusable factories) ────────────────────────────────────
export const agentTemplatesApi = {
  list: (params: Record<string, string> = {}) =>
    get<AgentTemplateOut[]>('/agent-templates?' + new URLSearchParams(params)),
  get: (templateId: string) => get<AgentTemplateOut>(`/agent-templates/${templateId}`),
  listVersions: (templateId: string) =>
    get<AgentTemplateVersionOut[]>(`/agent-templates/${templateId}/versions`),
  getVersion: (templateId: string, versionId: string) =>
    get<AgentTemplateVersionOut>(`/agent-templates/${templateId}/versions/${versionId}`),
  createAgent: (templateId: string, body: CreateAgentFromTemplateBody = {}) =>
    post<AgentOut>(`/agent-templates/${templateId}/agents`, body),
}

// ── Automations ───────────────────────────────────────────────────────────
// Space-scoped paths (/spaces/{space_id}/automations); identity via session/bearer.
export const automationsApi = {
  list:   ()                                  => get<AutomationOut[]>(`/spaces/${_spaceId}/automations`),
  get:    (id: string)                        => get<AutomationOut>(`/spaces/${_spaceId}/automations/${id}`),
  create: (data: AutomationCreateBody)        => post<AutomationOut>(`/spaces/${_spaceId}/automations`, data),
  update: (id: string, data: AutomationUpdateBody) => patch<AutomationOut>(`/spaces/${_spaceId}/automations/${id}`, data),
  fire:   (id: string, body: { prompt?: string; instruction?: string } = {}) =>
    post<AutomationFireResult>(`/spaces/${_spaceId}/automations/${id}/fire`, body),
}

// ── Workspaces ────────────────────────────────────────────────────────────
export const workspacesApi = {
  list:   (params: Record<string, string> = {}) =>
    get<Page<Workspace>>('/workspaces?' + new URLSearchParams(params)),
  create: (data: WorkspaceCreateBody) =>
    post<Workspace>('/workspaces', data),
  get:    (id: string)                          => get<Workspace>(`/workspaces/${id}`),
  update: (id: string, data: WorkspaceUpdateBody) => patch<Workspace>(`/workspaces/${id}`, data),
  archive:(id: string)                          => del<null>(`/workspaces/${id}`),
  scan:   ()                                    => post<{ created: Workspace[]; deleted: string[] }>('/workspaces/scan'),
}

// ── Capabilities ──────────────────────────────────────────────────────────
export const capabilitiesApi = {
  list:   ()            => get<Capability[]>('/capabilities'),
  get:    (id: string)  => get<Capability>(`/capabilities/${id}`),
  reload: ()            => post<CapabilitiesReloadResult>('/capabilities/reload'),
}

// ── Context ───────────────────────────────────────────────────────────────
export const contextApi = {
  build: (data: { workspace_id?: string | null; session_id?: string | null; capability_id?: string | null; query?: string | null }) =>
    post<ContextPackage>('/context/build', data),
}

export const runtimeToolsApi = {
  catalog: () => get<RuntimeToolDefinition[]>('/runtime-tools/catalog'),
  list: () => get<RuntimeToolStatus[]>('/runtime-tools'),
  get: (runtime: string) => get<RuntimeToolStatus>(`/runtime-tools/${encodeURIComponent(runtime)}`),
  latest: (runtime: string) => get<RuntimeToolLatest>(`/runtime-tools/${encodeURIComponent(runtime)}/latest`),
  install: (runtime: string, data: { version?: string | null; activate?: boolean; force?: boolean } = {}) =>
    post<RuntimeToolInstallResult>(`/runtime-tools/${encodeURIComponent(runtime)}/install`, data),
  activate: (runtime: string, version: string) =>
    post<RuntimeToolStatus>(`/runtime-tools/${encodeURIComponent(runtime)}/activate`, { version }),
}

// ── Credentials / Login ───────────────────────────────────────────────────
export const credentialsApi = {
  methods: () => get<CredentialLoginMethod[]>('/credentials/cli/methods'),
  status:  () => get<CredentialStatus[]>('/credentials/cli/status'),
  usage:   () => get<CliUsageEntry[]>('/credentials/cli/usage'),
  usageAutoRefresh: () => get<CliUsageAutoRefreshSettings>('/credentials/cli/usage/auto-refresh'),
  setUsageAutoRefresh: (enabled: boolean) =>
    put<CliUsageAutoRefreshSettings>('/credentials/cli/usage/auto-refresh', { enabled }),
  refreshUsage: (runtime: string) =>
    post<CliUsageEntry>(`/credentials/cli/usage/refresh?runtime=${encodeURIComponent(runtime)}`, {}),

  sendLoginInput: (runtime: string, input: string) =>
    post<{ status: string }>(`/credentials/cli/login/input?runtime=${encodeURIComponent(runtime)}`, { input }),

  async *loginStream(runtime: string): AsyncGenerator<LoginEvent> {
    const url = `${BASE}/credentials/cli/login/stream?runtime=${encodeURIComponent(runtime)}&${spaceParams()}`
    const headers: Record<string, string> = {}
    if (_apiKey) headers['Authorization'] = `Bearer ${_apiKey}`

    const r = await fetch(url, { headers })
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
    if (!r.body) throw new Error('No response body')

    const reader = r.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const parts = buf.split('\n\n')
      buf = parts.pop() ?? ''
      for (const block of parts) {
        const line = block.trim()
        if (line.startsWith('data: ')) {
          try { yield JSON.parse(line.slice(6)) as LoginEvent } catch { /* skip malformed */ }
        }
      }
    }
  },
}

// ── Jobs ──────────────────────────────────────────────────────────────────
export const jobsApi = {
  list:   (params: Record<string, string> = {}) =>
    get<Page<Job>>('/jobs?' + new URLSearchParams(params)),
  get:    (id: string)    => get<Job>(`/jobs/${id}`),
  events: (id: string)    => get<JobEvent[]>(`/jobs/${id}/events`),
  cancel: (id: string)    => post<Job>(`/jobs/${id}/cancel`),
}

// ── Activity ──────────────────────────────────────────────────────────────
export const activityApi = {
  list: (params: {
    status?: string
    source_type?: string
    workspace_id?: string
    project_id?: string
    limit?: number
    offset?: number
  } = {}) => {
    const q: Record<string, string> = {}
    if (params.status !== undefined) q.status = params.status
    if (params.source_type !== undefined) q.source_type = params.source_type
    if (params.workspace_id !== undefined) q.workspace_id = params.workspace_id
    if (params.project_id !== undefined) q.project_id = params.project_id
    if (params.limit !== undefined) q.limit = String(params.limit)
    if (params.offset !== undefined) q.offset = String(params.offset)
    return get<ActivityInboxRecord[]>('/activity?' + new URLSearchParams(q))
  },
  create: (
    data: { source_type: ActivitySourceType; content: string; title?: string; source_url?: string; workspace_id?: string; metadata_json?: Record<string, unknown> },
    options: { spaceId?: string } = {},
  ) =>
    post<ActivityInboxRecord>('/activity', data, { spaceId: options.spaceId }),
  // File / voice capture (store-only). Sends multipart; lands in the Activity Inbox.
  upload: (
    file: File,
    options: { kind?: 'file' | 'voice'; title?: string; note?: string; workspace_id?: string; spaceId?: string } = {},
  ) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('kind', options.kind ?? 'file')
    if (options.title) fd.append('title', options.title)
    if (options.note) fd.append('note', options.note)
    if (options.workspace_id) fd.append('workspace_id', options.workspace_id)
    return post<ActivityInboxRecord>('/activity/upload', fd, { spaceId: options.spaceId })
  },
  get:    (id: string) => get<ActivityInboxRecord>(`/activity/${id}`),
  review: (id: string) => patch<ActivityInboxRecord>(`/activity/${id}/review`),
  archive:(id: string) => patch<ActivityInboxRecord>(`/activity/${id}/archive`),
  consolidate: (id: string) =>
    post<Proposal[]>(`/activity/${id}/consolidate`),
  summarize: (body: SummaryRunRequest) =>
    post<SummaryRunOut>('/activity/summary-runs', body),
}

// ── Intake / Evidence ────────────────────────────────────────────────────
export const intakeApi = {
  connectors: () =>
    get<SourceConnector[]>('/intake/connectors'),

  connections: (params: { status?: string; limit?: number; offset?: number } = {}) => {
    const q: Record<string, string> = {}
    if (params.status !== undefined) q.status = params.status
    if (params.limit !== undefined) q.limit = String(params.limit)
    if (params.offset !== undefined) q.offset = String(params.offset)
    return get<Page<SourceConnection>>('/intake/connections?' + new URLSearchParams(q))
  },
  createConnection: (body: SourceConnectionCreate) =>
    post<SourceConnection>('/intake/connections', body),
  updateConnection: (id: string, body: Partial<SourceConnectionCreate> & { status?: string }) =>
    patch<SourceConnection>(`/intake/connections/${id}`, body),
  scanConnection: (id: string) =>
    post<ExtractionJob>(`/intake/connections/${id}/scan`),

  items: (params: {
    status?: string
    connection_id?: string
    content_state?: string
    limit?: number
    offset?: number
  } = {}) => {
    const q: Record<string, string> = {}
    if (params.status !== undefined) q.status = params.status
    if (params.connection_id !== undefined) q.connection_id = params.connection_id
    if (params.content_state !== undefined) q.content_state = params.content_state
    if (params.limit !== undefined) q.limit = String(params.limit)
    if (params.offset !== undefined) q.offset = String(params.offset)
    return get<Page<IntakeItem>>('/intake/items?' + new URLSearchParams(q))
  },
  createManualUrl: (body: { url: string; title?: string; connection_id?: string | null; queue_content?: boolean }) =>
    post<IntakeItem>('/intake/items/manual-url', body),
  itemAction: (id: string, action: string) =>
    post<IntakeItem>(`/intake/items/${id}/actions`, { action }),
  jobs: (params: {
    status?: string
    intake_item_id?: string
    connection_id?: string
    job_type?: string
    limit?: number
    offset?: number
  } = {}) => {
    const q: Record<string, string> = {}
    if (params.status !== undefined) q.status = params.status
    if (params.intake_item_id !== undefined) q.intake_item_id = params.intake_item_id
    if (params.connection_id !== undefined) q.connection_id = params.connection_id
    if (params.job_type !== undefined) q.job_type = params.job_type
    if (params.limit !== undefined) q.limit = String(params.limit)
    if (params.offset !== undefined) q.offset = String(params.offset)
    return get<Page<ExtractionJob>>('/intake/jobs?' + new URLSearchParams(q))
  },
  runJob: (id: string) =>
    post<ExtractionJob>(`/intake/jobs/${id}/run`),

  evidence: (params: { status?: string; evidence_type?: string; intake_item_id?: string; limit?: number; offset?: number } = {}) => {
    const q: Record<string, string> = {}
    if (params.status !== undefined) q.status = params.status
    if (params.evidence_type !== undefined) q.evidence_type = params.evidence_type
    if (params.intake_item_id !== undefined) q.intake_item_id = params.intake_item_id
    if (params.limit !== undefined) q.limit = String(params.limit)
    if (params.offset !== undefined) q.offset = String(params.offset)
    return get<Page<ExtractedEvidence>>('/intake/evidence?' + new URLSearchParams(q))
  },
  updateEvidence: (id: string, body: { status?: string; confidence?: number; metadata?: Record<string, unknown> }) =>
    patch<ExtractedEvidence>(`/intake/evidence/${id}`, body),
  createEvidenceLink: (body: {
    evidence_id: string
    target_type: string
    target_id?: string | null
    link_type?: string
    status?: string
    confidence?: number
    reason?: string
  }) => post<EvidenceLink>('/intake/evidence-links', body),
  evidenceLinks: (params: { evidence_id?: string; target_type?: string; target_id?: string; status?: string } = {}) => {
    const q: Record<string, string> = {}
    if (params.evidence_id !== undefined) q.evidence_id = params.evidence_id
    if (params.target_type !== undefined) q.target_type = params.target_type
    if (params.target_id !== undefined) q.target_id = params.target_id
    if (params.status !== undefined) q.status = params.status
    return get<Page<EvidenceLink>>('/intake/evidence-links?' + new URLSearchParams(q))
  },

  workspaceProfiles: (params: { workspace_id?: string } = {}) => {
    const q: Record<string, string> = {}
    if (params.workspace_id !== undefined) q.workspace_id = params.workspace_id
    return get<WorkspaceIntakeProfile[]>('/intake/workspace-profiles?' + new URLSearchParams(q))
  },
  createWorkspaceProfile: (body: {
    workspace_id: string
    name?: string
    observation_policy?: string
    routing_policy?: Record<string, unknown>
    filters?: Record<string, unknown>
    extraction_policy?: Record<string, unknown>
    context_policy?: Record<string, unknown>
  }) => post<WorkspaceIntakeProfile>('/intake/workspace-profiles', body),
  workspaceBindings: (params: { workspace_id?: string; source_connection_id?: string } = {}) => {
    const q: Record<string, string> = {}
    if (params.workspace_id !== undefined) q.workspace_id = params.workspace_id
    if (params.source_connection_id !== undefined) q.source_connection_id = params.source_connection_id
    return get<WorkspaceSourceBinding[]>('/intake/workspace-source-bindings?' + new URLSearchParams(q))
  },
  createWorkspaceBinding: (body: {
    workspace_id: string
    source_connection_id: string
    binding_key?: string
    project_id?: string | null
    priority?: number
    filters?: Record<string, unknown>
    routing_policy?: Record<string, unknown>
    extraction_policy?: Record<string, unknown>
  }) => post<WorkspaceSourceBinding>('/intake/workspace-source-bindings', body),
  summarize: (body: SummaryRunRequest) =>
    post<SummaryRunOut>('/intake/summary-runs', body),
}

// ── Workspace Console ─────────────────────────────────────────────────────
export const workspaceConsoleApi = {
  listWorkspaces: () =>
    get<{ items: WorkspaceInfo[] }>('/workspace-console/workspaces'),

  fileTree: (workspaceId: string) =>
    get<FileNode>(`/workspace-console/workspaces/${workspaceId}/tree`),

  fileContent: (workspaceId: string, path: string) =>
    get<FileContent>(`/workspace-console/workspaces/${workspaceId}/file?path=${encodeURIComponent(path)}`),

  gitStatus: (workspaceId: string) =>
    get<GitStatus>(`/workspace-console/workspaces/${workspaceId}/git/status`),

  gitDiff: (workspaceId: string, path?: string) =>
    get<{ diff: string; path: string | null }>(
      `/workspace-console/workspaces/${workspaceId}/git/diff` + (path ? `?path=${encodeURIComponent(path)}` : ''),
    ),

  runtimes: () =>
    get<{ runtimes: RuntimeInfo[] }>('/workspace-console/runtimes'),

  listSessions: (workspaceId?: string) =>
    get<{ items: ConsoleSession[] }>(
      '/workspace-console/sessions' + (workspaceId ? `?workspace_id=${workspaceId}` : ''),
    ),

  createSession: (data: { workspace_id?: string; runtime: string; model?: string; prompt: string }) =>
    post<ConsoleSession>('/workspace-console/sessions', data),

  runTurn: (id: string, prompt: string) =>
    post<ConsoleSession>(`/workspace-console/sessions/${id}/run`, { prompt }),

  getSession: (id: string) =>
    get<ConsoleSession>(`/workspace-console/sessions/${id}`),

  stopSession: (id: string) =>
    post<ConsoleSession>(`/workspace-console/sessions/${id}/stop`),
}

// ── Projects ──────────────────────────────────────────────────────────────
export const projectsApi = {
  list: (params: { status?: string; limit?: number; offset?: number } = {}) => {
    const q: Record<string, string> = {}
    if (params.status !== undefined) q.status = params.status
    if (params.limit !== undefined) q.limit = String(params.limit)
    if (params.offset !== undefined) q.offset = String(params.offset)
    return get<Page<Project>>('/projects?' + new URLSearchParams(q))
  },
  create: (data: ProjectCreate) => post<Project>('/projects', data),
  get: (id: string) => get<Project>(`/projects/${id}`),
  update: (id: string, data: ProjectUpdate) => patch<Project>(`/projects/${id}`, data),
  archive: (id: string) => post<Project>(`/projects/${id}/archive`),
  getSummary: (id: string) => get<ProjectSummary>(`/projects/${id}/summary`),
  listWorkspaces: (id: string) => get<ProjectWorkspaceLinkOut[]>(`/projects/${id}/workspaces`),
  linkWorkspace: (id: string, data: ProjectWorkspaceLinkCreate) =>
    post<ProjectWorkspaceLinkOut>(`/projects/${id}/workspaces`, data),
  unlinkWorkspace: (id: string, workspaceId: string, role?: string) => {
    const q = role ? `?role=${encodeURIComponent(role)}` : ''
    return del<null>(`/projects/${id}/workspaces/${workspaceId}${q}`)
  },
}

// ── Features ──────────────────────────────────────────────────────────────
export const featuresApi = {
  list: () => get<Feature[]>('/features'),
}

// ── Auth / Identity ───────────────────────────────────────────────────────
export const authApi = {
  me:          ()                  => get<CurrentUser>('/me'),
  mySpaces:    ()                  => get<SpaceWithMembership[]>('/me/spaces'),
  googleConfigured: ()            => get<{google_auth_available: boolean}>('/auth/google-configured'),
  logout:      ()                  => post<null>('/auth/logout'),
  googleLogin: (next?: string)     => {
    const url = next
      ? `/api/v1/auth/google?next=${encodeURIComponent(next)}`
      : '/api/v1/auth/google'
    window.location.href = url
  },
}

// ── Spaces ────────────────────────────────────────────────────────────────
export const spacesApi = {
  create:         (data: { name: string; type: Exclude<SpaceWithMembership['type'], 'personal'> }) => post<SpaceWithMembership>('/spaces', data),
  get:            (spaceId: string)                              => get<SpaceWithMembership>(`/spaces/${spaceId}`),
  members:        (spaceId: string)                              => get<SpaceMember[]>(`/spaces/${spaceId}/members`),
  invite:         (spaceId: string, data: { email: string; role: string }) =>
    post<SpaceInvitationOut>(`/spaces/${spaceId}/invitations`, data),
  acceptInvite:   (token: string)                                => post<{ space_id: string; role: string; space_name: string }>(`/invitations/${token}/accept`),
}

// ── Providers ─────────────────────────────────────────────────────────────
export type ProviderType =
  | 'openai'
  | 'anthropic'
  | 'openrouter'
  | 'ollama'
  | 'custom_openai_compatible'
  | 'other'

export interface ModelProviderOut {
  id: string
  space_id: string
  name: string
  provider_type: ProviderType | string
  base_url: string | null
  default_model: string | null
  available_models: string[]
  enabled: boolean
  is_default: boolean
  has_api_key: boolean
  created_at: string
  updated_at: string
}

export interface ModelProviderModelsOut {
  models: string[]
  source: 'configured' | 'live'
}

export interface CatalogInfo {
  id: string
  name: string
  description: string
  model_hint: string
}

export interface TestConnectionOut {
  success: boolean
  message: string
  model?: string
}

export interface ChatRequest {
  provider_id?: string
  model?: string
  messages: { role: string; content: string }[]
  system?: string
  temperature?: number
  max_tokens?: number
}

export interface ChatResponse {
  content: string
  provider: string
  model: string
  usage: { input_tokens: number; output_tokens: number; total_tokens: number }
}

export const providersApi = {
  list: () => get<ModelProviderOut[]>('/providers'),

  litellmProviders: () => get<string[]>('/providers/litellm-providers'),

  create: (data: {
    name: string
    provider_type: ProviderType | string
    api_key?: string
    default_model?: string
    available_models?: string[]
    base_url?: string
    enabled?: boolean
    is_default?: boolean
  }) => post<ModelProviderOut>('/providers', data),

  patch: (id: string, data: Partial<{
    name: string
    provider_type: ProviderType | string
    api_key: string
    default_model: string
    available_models: string[]
    base_url: string
    enabled: boolean
    is_default: boolean
  }>) => patch<ModelProviderOut>(`/providers/${id}`, data),

  delete: (id: string) => del<void>(`/providers/${id}`),

  models: (id: string) => get<ModelProviderModelsOut>(`/providers/${id}/models`),

  test: (id: string) => post<TestConnectionOut>(`/providers/${id}/test`, {}),

  catalog: () => get<CatalogInfo>('/providers/catalog'),

  chat: (data: ChatRequest) => post<ChatResponse>('/providers/chat', data),
}

export const dailyReportApi = {
  getSettings: () =>
    get<DailyCaptureReportSettingOut>('/daily-capture-report/settings'),

  updateSettings: (data: DailyCaptureReportSettingUpdate) =>
    patch<DailyCaptureReportSettingOut>('/daily-capture-report/settings', data),

  run: (data: DailyReportRunRequest) =>
    post<DailyReportRunResponse>('/daily-capture-report/run', data),

  listReports: (limit = 10) =>
    get<DailyReportArtifactItem[]>(`/daily-capture-report/reports?limit=${limit}`),
}
