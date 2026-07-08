import type {
  Memory, Session, Message, Task, CondenserPresetPromptOut,
  ContextPackage, Feature, Workspace, WorkspaceCreateBody, WorkspaceUpdateBody, Page,
  ReflectResult, ApiError,
  RuntimeToolDefinition, RuntimeToolInstallResult, RuntimeToolStatus, RuntimeToolLatest, SpaceRuntimeToolPolicyOut,
  CredentialLoginMethod, CredentialStatus, CliUsageEntry, CliUsageAutoRefreshSettings, LoginEvent,
  NetworkProfileOut, NetworkProfileCreateBody, NetworkProfileUpdateBody, CliCredentialProfileOut,
  CliCredentialAvailableProfileOut,
  CurrentUser, SpaceWithMembership, SpaceMember, SpaceInvitationOut, SpaceSnapshotDefaults,
  RetrievalPromptTask, SpaceRetrievalPrompt, SpaceRetrievalPromptUpdate,
  SpaceRetrievalSettings, SpaceRetrievalSettingsUpdate,
  Job, JobEvent, ActivityInboxRecord,
  Board, TaskRunCreateBody, Run, RunStatusOut, TaskRunListItem,
  AgentRunGroup, AgentRunGroupTimeline, AgentRunGroupTrace,
  CreateAgentRunGroupRequest, CreateAgentRunGroupResponse,
  UpdateAgentRunGroupRequest, UpdateAgentRunGroupResponse,
  SendAgentRunGroupMessageRequest, SendAgentRunGroupMessageResponse,
  TaskArtifact, TaskProposal, Artifact, Proposal, ProposalAcceptOut, AgentOut, AgentCreateBody, AgentUpdateBody, RunCreateBody,
  AgentRuntimeProfileCreateBody, AgentRuntimeProfileOut, AgentRuntimeProfileUpdateBody,
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
  EvolutionStrategy, EvolutionSelectorDecision, EvolutionExperience,
  Project, ProjectCreate, ProjectUpdate, ProjectWorkspaceLinkCreate, ProjectWorkspaceLinkOut, ProjectSummary,
  CapabilityDefinition, CapabilityPackDescriptor, WorkflowTemplate, ProjectWorkflowProfile, WorkflowRunDraftRequest, WorkflowRunDraftResponse,
  SkillImportPreviewResponse, SkillPackage, SkillImportApprovalProposalResponse, SkillConvertToCapabilityResponse,
  SkillLibraryIndexResponse, SkillLocalOverlay, SkillLocalOverlayUpsertRequest,
  SourceConnector, SourceConnection, SourceConnectionCreate, SourceCapturePolicy, SourceScheduleRule, SourceItem, ExtractionJob,
  SourcePresetListResponse, ArxivPresetPreviewRequest, ArxivPresetPreviewResponse, ArxivPresetCreateRequest,
  ExtractedEvidence, EvidenceLink, WorkspaceSourceBinding, WorkspaceSourceBindingBackfillResult,
  CustomSourceActivationResult, CustomSourceCreateDraftRequest, CustomSourceHandlerRun,
  CustomSourceHandlerSummary, CustomSourceHandlerVersion, CustomSourceInstanceRunnerSettings,
  CustomSourceInstanceRunnerSettingsUpdate,
  CustomSourceSpacePolicy, CustomSourceSpacePolicyUpdate, CustomSourceTestOutcome,
  SourceRecipeActivationResult, SourceRecipeCreateRequest, SourceRecipeCreateResponse,
  SourceRecipeDryRunResponse, SourceRecipePlanRequest, SourceRecipePlanResponse,
  SourceRecipePipelineBridgeRequest, SourceRecipePipelineBridgeResponse,
  SourceRecipeVersion, SourceRunSummary,
  SourcePostProcessingBacklog, SourcePostProcessingBriefingDaySummary,
  SourcePostProcessingBriefingDetail, SourcePostProcessingDecisionActionResult,
  SourcePostProcessingDecisionReviewStatus, SourcePostProcessingDrainResult,
  SourcePostProcessingItemDecision, SourcePostProcessingItemRelevance,
  SourcePostProcessingRule, SourcePostProcessingRun,
  SourcePostProcessingRuleCreate, SourcePostProcessingRuleUpdate,
  SummaryRunRequest, SummaryRunOut,
  DailyCaptureReportSettingOut, DailyCaptureReportSettingUpdate,
  DailyReportRunRequest, DailyReportRunResponse, DailyReportArtifactItem,
  AutomationOut, AutomationCreateBody, AutomationUpdateBody, AutomationFireResult,
  RetrievalFeedbackRequest, RetrievalFeedbackResponse, RetrievalSearchRequest, RetrievalSearchResponse,
  RetrievalBriefRequest, RetrievalBriefResponse, RetrievalDiagnosticsReportRequest, RetrievalDiagnosticsReportResponse,
  RetrievalCalibrationDecisionRequest, RetrievalCalibrationDecisionResponse,
  RetrievalExplainRequest, RetrievalExplainResponse,
  RetrievalMaintenanceScanRequest, RetrievalMaintenanceScanResponse,
  RetrievalObjectType, SpaceObjectKindCreateProposalRequest, SpaceObjectKindPage,
  SpaceObjectKindStatus, SpaceObjectKindUpdateProposalRequest,
  ObjectSchemaExportManifest, ObjectSchemaImportRequest, ObjectSchemaImportResponse,
  ObjectSchemaSuggestionScanRequest, ObjectSchemaSuggestionScanResponse,
  ContextOpsSummary, ContextOpsDrilldown, ContextOpsDrilldownSection,
  ContextReviewCycleRequest, ContextReviewCycleResponse,
  AskSpaceRequest, AskSpaceResponse,
  ClaimCandidatePacketCreateRequest, ClaimCandidatePacketCreateResponse,
  ClaimContradictionScanRequest, ClaimContradictionScanResponse,
  RelationDiscoveryScanRequest, RelationDiscoveryScanResponse,
  ContextArtifactRevocation, ContextArtifactRevocationCreateRequest, ContextArtifactRevocationListResponse,
  ContextEffectiveRoutingResponse, ContextProfile, ContextProfileListResponse, ContextProfileUpsertRequest, ContextRoutingUpdateRequest,
  MemoryAccessLogListResponse, MemoryMaintenanceJob, MemoryMaintenanceJobRunResponse, MemoryMaintenanceReport, MemoryMaintenanceScanRequest,
  ContextOpsContextObservationScanRequest, ContextOpsContextObservationScanResponse,
  ReaderDocumentPayload, ReaderAnnotation, ReaderAnnotationsResponse,
  ReaderAnnotationCreate, ReaderAnnotationUpdate,
  ReaderCommentThread, ReaderComment, ReaderCommentCreate, ReaderCommentUpdate, ReaderThreadUpdate,
  ReaderCreateEvidenceRequest, ReaderCreatedEvidence,
  ReaderCreateProposalRequest, ReaderCreatedProposal,
} from '../types/api'
import type { GraphProjection, GraphProjectionViewMode } from '@agent-space/protocol'

const BASE = '/api/v1'

let _spaceId = 'personal'
let _apiKey: string | null = null

export function setSpaceContext(spaceId: string): void {
  _spaceId = spaceId
}

export function setAuth(key: string | null): void {
  _apiKey = key
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
  includeSpaceContext?: boolean
  spaceId?: string
}

async function request<T = unknown>(method: string, path: string, body?: unknown, options: RequestOptions = {}): Promise<T> {
  // FormData (file/voice upload) must keep the browser-set multipart boundary, so
  // we do not force a Content-Type for it and pass the body through unserialized.
  const isForm = typeof FormData !== 'undefined' && body instanceof FormData
  const headers: Record<string, string> = isForm ? {} : { 'Content-Type': 'application/json' }
  if (_apiKey) headers['Authorization'] = `Bearer ${_apiKey}`
  if (options.includeSpaceContext ?? true) headers['X-Agent-Space-Id'] = options.spaceId ?? _spaceId

  const url = BASE + path

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

async function requestText(method: string, path: string, options: RequestOptions = {}): Promise<string> {
  const headers: Record<string, string> = {}
  if (_apiKey) headers['Authorization'] = `Bearer ${_apiKey}`
  if (options.includeSpaceContext ?? true) headers['X-Agent-Space-Id'] = options.spaceId ?? _spaceId

  const r = await fetch(BASE + path, { method, headers })

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

  return r.text()
}

const get   = <T>(path: string, options?: RequestOptions)                => request<T>('GET',    path, undefined, options)
const post  = <T>(path: string, body?: unknown, options?: RequestOptions) => request<T>('POST',   path, body, options)
const put   = <T>(path: string, body?: unknown, options?: RequestOptions) => request<T>('PUT',    path, body, options)
const patch = <T>(path: string, body?: unknown, options?: RequestOptions) => request<T>('PATCH',  path, body, options)
const del   = <T>(path: string, options?: RequestOptions)                => request<T>('DELETE', path, undefined, options)
const getText = (path: string, options?: RequestOptions) => requestText('GET', path, options)

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
    post<Proposal>('/memory', data),
  update: (id: string, data: Partial<Memory>) =>
    patch<Proposal>(`/memory/${id}`, data),
  delete: (id: string) =>
    del<Proposal>(`/memory/${id}`),
  search: (data: { query: string; scope?: string; namespace?: string; type?: string; workspace_id?: string; limit?: number }) =>
    // Memory search is identity-scoped server-side; do not send space_id/user_id.
    post<Memory[]>('/memory/search', data),
  retrievalSearch: (data: RetrievalSearchRequest) =>
    post<RetrievalSearchResponse>('/memory/retrieval/search', data),
  retrievalBrief: (data: RetrievalBriefRequest) =>
    post<RetrievalBriefResponse>('/memory/retrieval/brief', data),
  feedback: (data: RetrievalFeedbackRequest) =>
    post<RetrievalFeedbackResponse>('/memory/retrieval/feedback', data),
  maintenanceScan: (data: MemoryMaintenanceScanRequest = {}) =>
    post<MemoryMaintenanceReport>('/memory/maintenance/scan', data),
  createMaintenanceJob: (data: MemoryMaintenanceScanRequest = {}) =>
    post<MemoryMaintenanceJob>('/memory/maintenance/jobs', data),
  getMaintenanceJob: (jobId: string) =>
    get<MemoryMaintenanceJob>(`/memory/maintenance/jobs/${jobId}`),
  runMaintenanceJob: (jobId: string) =>
    post<MemoryMaintenanceJobRunResponse>(`/memory/maintenance/jobs/${jobId}/run`, {}),
  accessLogs: (params: { limit?: number; offset?: number; memory_id?: string; access_type?: string; workspace_id?: string; project_id?: string } = {}) => {
    const q: Record<string, string> = {}
    if (params.limit !== undefined) q.limit = String(params.limit)
    if (params.offset !== undefined) q.offset = String(params.offset)
    if (params.memory_id !== undefined) q.memory_id = params.memory_id
    if (params.access_type !== undefined) q.access_type = params.access_type
    if (params.workspace_id !== undefined) q.workspace_id = params.workspace_id
    if (params.project_id !== undefined) q.project_id = params.project_id
    return get<MemoryAccessLogListResponse>('/memory/access-logs?' + new URLSearchParams(q))
  },
}

// ── Knowledge ─────────────────────────────────────────────────────────────
export const knowledgeApi = {
  list: (params: {
    knowledge_kind?: string
    status?: string
    visibility?: string
    q?: string
    limit?: number
    offset?: number
  } = {}) => {
    const q: Record<string, string> = {}
    if (params.knowledge_kind !== undefined) q.knowledge_kind = params.knowledge_kind
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
    post<Proposal>('/knowledge/object-relations/proposals', {
      from_object_id: body.from_object_id,
      to_object_id: body.to_object_id,
      relation_type: body.relation_type,
      status: body.status,
      confidence: body.confidence,
      evidence_summary: body.evidence_summary,
      rationale: body.rationale,
      metadata: { endpoint_type: 'knowledge_item', requested_relation_type: body.relation_type },
    }),
  proposeRelationArchive: (id: string) =>
    del<Proposal>(`/knowledge/object-relations/${id}`),
  summary: () => get<KnowledgeSummary>('/knowledge/summary'),
  search: (data: RetrievalSearchRequest) =>
    post<RetrievalSearchResponse>('/knowledge/search', data),
  brief: (data: RetrievalBriefRequest) =>
    post<RetrievalBriefResponse>('/knowledge/retrieval/brief', data),
  diagnosticsReport: (data: RetrievalDiagnosticsReportRequest) =>
    post<RetrievalDiagnosticsReportResponse>('/knowledge/retrieval/eval/diagnostics/report', data),
  calibrationDecision: (data: RetrievalCalibrationDecisionRequest) =>
    post<RetrievalCalibrationDecisionResponse>('/knowledge/retrieval/eval/calibration-decisions', data),
  maintenanceScan: (data: RetrievalMaintenanceScanRequest = {}) =>
    post<RetrievalMaintenanceScanResponse>('/knowledge/retrieval/maintenance/scan', data),
  claimCandidatePacket: (data: ClaimCandidatePacketCreateRequest) =>
    post<ClaimCandidatePacketCreateResponse>('/knowledge/claims/candidate-packets', data),
  contradictionScan: (data: ClaimContradictionScanRequest = {}) =>
    post<ClaimContradictionScanResponse>('/knowledge/claims/contradiction-scan', data),
  relationDiscoveryScan: (data: RelationDiscoveryScanRequest = {}) =>
    post<RelationDiscoveryScanResponse>('/knowledge/relations/discovery-scan', data),
  explain: (data: RetrievalExplainRequest) =>
    post<RetrievalExplainResponse>('/knowledge/retrieval/explain', data),
  feedback: (data: RetrievalFeedbackRequest) =>
    post<RetrievalFeedbackResponse>('/knowledge/retrieval/feedback', data),
}

export interface GraphProjectionQuery {
  mode?: Exclude<GraphProjectionViewMode, 'debug'>
  root_id?: string
  depth?: number
  node_kinds?: string[]
  edge_kinds?: string[]
  q?: string
  limit?: number
  include_clusters?: boolean
}

export interface GraphViewStateRecord {
  scope_key: string
  state_json: Record<string, unknown>
  updated_at: string | null
}

export const graphApi = {
  projection: (params: GraphProjectionQuery = {}) => {
    const q = new URLSearchParams()
    if (params.mode) q.set('mode', params.mode)
    if (params.root_id) q.set('root_id', params.root_id)
    if (params.depth !== undefined) q.set('depth', String(params.depth))
    if (params.node_kinds?.length) q.set('node_kinds', params.node_kinds.join(','))
    if (params.edge_kinds?.length) q.set('edge_kinds', params.edge_kinds.join(','))
    if (params.q) q.set('q', params.q)
    if (params.limit !== undefined) q.set('limit', String(params.limit))
    if (params.include_clusters !== undefined) q.set('include_clusters', String(params.include_clusters))
    return get<GraphProjection>(`/graph/projection${q.size ? '?' + q : ''}`)
  },
  getViewState: (scopeKey: string) =>
    get<GraphViewStateRecord>(`/graph/view-state?scope_key=${encodeURIComponent(scopeKey)}`),
  saveViewState: (scopeKey: string, stateJson: Record<string, unknown>) =>
    put<GraphViewStateRecord>('/graph/view-state', {
      scope_key: scopeKey,
      state_json: stateJson,
    }),
}

export const objectSchemaApi = {
  exportSchema: () =>
    get<ObjectSchemaExportManifest>('/knowledge/object-schema/export'),
  importSchema: (body: ObjectSchemaImportRequest) =>
    post<ObjectSchemaImportResponse>('/knowledge/object-schema/imports/proposals', body),
  suggestionScan: (body: ObjectSchemaSuggestionScanRequest = {}) =>
    post<ObjectSchemaSuggestionScanResponse>('/knowledge/object-schema/suggestions/scan', body),
  listKinds: (params: {
    base_object_type?: RetrievalObjectType
    status?: SpaceObjectKindStatus
    limit?: number
    offset?: number
  } = {}) => {
    const q: Record<string, string> = {}
    if (params.base_object_type !== undefined) q.base_object_type = params.base_object_type
    if (params.status !== undefined) q.status = params.status
    if (params.limit !== undefined) q.limit = String(params.limit)
    if (params.offset !== undefined) q.offset = String(params.offset)
    return get<SpaceObjectKindPage>('/knowledge/object-schema/kinds?' + new URLSearchParams(q))
  },
  proposeCreateKind: (body: SpaceObjectKindCreateProposalRequest) =>
    post<Proposal>('/knowledge/object-schema/kinds/proposals', body),
  proposeUpdateKind: (id: string, body: SpaceObjectKindUpdateProposalRequest) =>
    patch<Proposal>(`/knowledge/object-schema/kinds/${encodeURIComponent(id)}/proposals`, body),
  proposeDeprecateKind: (id: string, body: { rationale?: string } = {}) =>
    post<Proposal>(`/knowledge/object-schema/kinds/${encodeURIComponent(id)}/deprecate-proposals`, body),
  proposeArchiveKind: (id: string) =>
    del<Proposal>(`/knowledge/object-schema/kinds/${encodeURIComponent(id)}`),
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
export const knowledgeSourcesApi = {
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
  condenserPresetPrompts: () =>
    get<CondenserPresetPromptOut[]>('/sessions/condenser-preset-prompts'),
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
    get<MeSummaryOut>('/me/summary?' + new URLSearchParams(params), { includeSpaceContext: false }),
  timeline: (params: Record<string, string> = {}) =>
    get<MeTimelineEntry[]>('/me/timeline?' + new URLSearchParams(params), { includeSpaceContext: false }),
  tasks: (params: Record<string, string> = {}) =>
    get<Page<MeTaskItem>>('/me/tasks?' + new URLSearchParams(params), { includeSpaceContext: false }),
  pending: (params: Record<string, string> = {}) =>
    get<MePendingProposalItem[]>('/me/pending?' + new URLSearchParams(params), { includeSpaceContext: false }),
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

// ── Agent Rooms / group runs ──────────────────────────────────────────────
export const agentGroupsApi = {
  list: (params: { status?: string; limit?: number; offset?: number } = {}) => {
    const q: Record<string, string> = {}
    if (params.status !== undefined) q.status = params.status
    if (params.limit !== undefined) q.limit = String(params.limit)
    if (params.offset !== undefined) q.offset = String(params.offset)
    return get<Page<AgentRunGroup>>('/agent-groups?' + new URLSearchParams(q))
  },
  create: (body: CreateAgentRunGroupRequest) =>
    post<CreateAgentRunGroupResponse>('/agent-groups', body),
  update: (groupId: string, body: UpdateAgentRunGroupRequest) =>
    patch<UpdateAgentRunGroupResponse>(`/agent-groups/${groupId}`, body),
  timeline: (groupId: string, params: { limit?: number; offset?: number } = {}) => {
    const q: Record<string, string> = {}
    if (params.limit !== undefined) q.limit = String(params.limit)
    if (params.offset !== undefined) q.offset = String(params.offset)
    return get<AgentRunGroupTimeline>(`/agent-groups/${groupId}/timeline?` + new URLSearchParams(q))
  },
  trace: (groupId: string) =>
    get<AgentRunGroupTrace>(`/agent-groups/${groupId}/trace`),
  sendMessage: (groupId: string, body: SendAgentRunGroupMessageRequest) =>
    post<SendAgentRunGroupMessageResponse>(`/agent-groups/${groupId}/messages`, body),
  pause: (groupId: string) => post<AgentRunGroup>(`/agent-groups/${groupId}/pause`, {}),
  resume: (groupId: string) => post<AgentRunGroup>(`/agent-groups/${groupId}/resume`, {}),
  cancel: (groupId: string) => post<AgentRunGroup>(`/agent-groups/${groupId}/cancel`, {}),
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
    workspace_id?: string
    limit?: number
    offset?: number
  } = {}) => {
    const q: Record<string, string> = {}
    if (params.artifact_type !== undefined) q.artifact_type = params.artifact_type
    if (params.project_id !== undefined) q.project_id = params.project_id
    if (params.workspace_id !== undefined) q.workspace_id = params.workspace_id
    if (params.limit !== undefined) q.limit = String(params.limit)
    if (params.offset !== undefined) q.offset = String(params.offset)
    return get<Page<Artifact>>('/artifacts?' + new URLSearchParams(q))
  },
  get: (id: string, params: { workspace_id?: string } = {}) => {
    const q: Record<string, string> = {}
    if (params.workspace_id !== undefined) q.workspace_id = params.workspace_id
    const suffix = new URLSearchParams(q).toString()
    return get<Artifact>(`/artifacts/${id}${suffix ? `?${suffix}` : ''}`)
  },
  export: (id: string, params: { workspace_id?: string } = {}) => downloadArtifactExport(id, params),
}

async function downloadArtifactExport(
  artifactId: string,
  params: { workspace_id?: string } = {},
): Promise<void> {
  const headers: Record<string, string> = {}
  if (_apiKey) headers['Authorization'] = `Bearer ${_apiKey}`
  headers['X-Agent-Space-Id'] = _spaceId
  const sep = '/artifacts/' + artifactId + '/export'
  const query = new URLSearchParams()
  if (params.workspace_id !== undefined) query.set('workspace_id', params.workspace_id)
  const artifactParams = query.toString()
  const url = BASE + sep + (artifactParams ? `?${artifactParams}` : '')
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
  accept: (id: string, options: { confirmIncompletePatch?: boolean } = {}) => {
    const suffix = options.confirmIncompletePatch ? '?confirm_incomplete_patch=true' : ''
    return post<ProposalAcceptOut>(`/proposals/${id}/accept${suffix}`)
  },
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
  runTarget: (targetId: string, body: {
    agent_id?: string
    mode?: 'dry_run'
    runtime_profile_id?: string | null
    workspace_id?: string | null
    project_id?: string | null
    context_artifact_ids?: string[]
  } = {}) =>
    post<EvolutionRunResult>(`/evolution/targets/${targetId}/run`, body),
  strategies: (params: { status?: string; target_type?: string; limit?: number; offset?: number } = {}) => {
    const q: Record<string, string> = {}
    if (params.status !== undefined) q.status = params.status
    if (params.target_type !== undefined) q.target_type = params.target_type
    if (params.limit !== undefined) q.limit = String(params.limit)
    if (params.offset !== undefined) q.offset = String(params.offset)
    return get<EvolutionStrategy[]>('/evolution/strategies?' + new URLSearchParams(q))
  },
  selectorDecisions: (params: { limit?: number; offset?: number } = {}) => {
    const q: Record<string, string> = {}
    if (params.limit !== undefined) q.limit = String(params.limit)
    if (params.offset !== undefined) q.offset = String(params.offset)
    return get<EvolutionSelectorDecision[]>('/evolution/selector-decisions?' + new URLSearchParams(q))
  },
  experiences: (params: { limit?: number; offset?: number } = {}) => {
    const q: Record<string, string> = {}
    if (params.limit !== undefined) q.limit = String(params.limit)
    if (params.offset !== undefined) q.offset = String(params.offset)
    return get<EvolutionExperience[]>('/evolution/experiences?' + new URLSearchParams(q))
  },
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
  listRuntimeProfiles: (agentId: string) =>
    get<AgentRuntimeProfileOut[]>(`/agents/${agentId}/runtime-profiles`),
  createRuntimeProfile: (agentId: string, data: AgentRuntimeProfileCreateBody) =>
    post<AgentRuntimeProfileOut>(`/agents/${agentId}/runtime-profiles`, data),
  updateRuntimeProfile: (agentId: string, profileId: string, data: AgentRuntimeProfileUpdateBody) =>
    patch<AgentRuntimeProfileOut>(`/agents/${agentId}/runtime-profiles/${profileId}`, data),
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
  scan:   ()                                    => post<{ created: Workspace[]; marked_stale: string[] }>('/workspaces/scan'),
}

export const capabilitiesFrameworkApi = {
  listCapabilityDefinitions: () =>
    get<CapabilityDefinition[]>('/capability-definitions'),
  getCapabilityDefinition: (id: string) =>
    get<CapabilityDefinition>(`/capability-definitions/${encodeURIComponent(id)}`),
  listCapabilityPacks: () =>
    get<CapabilityPackDescriptor[]>('/capability-packs'),
  getCapabilityPack: (id: string) =>
    get<CapabilityPackDescriptor>(`/capability-packs/${encodeURIComponent(id)}`),
  listWorkflowTemplates: () =>
    get<WorkflowTemplate[]>('/workflow-templates'),
  getWorkflowTemplate: (id: string) =>
    get<WorkflowTemplate>(`/workflow-templates/${encodeURIComponent(id)}`),
  previewSkillImport: (data: { url: string }) =>
    post<SkillImportPreviewResponse>('/skill-sources/import-preview', data),
  importSkill: (data: { url: string }) =>
    post<SkillPackage>('/skill-sources/import', data),
  listSkillPackages: () =>
    get<Page<SkillPackage>>('/skill-packages'),
  getSkillPackage: (id: string) =>
    get<SkillPackage>(`/skill-packages/${encodeURIComponent(id)}`),
  listSkillLibraryIndex: () =>
    get<SkillLibraryIndexResponse>('/capabilities/skills/index'),
  getSkillLocalOverlay: (skillPackageId: string, params: { scope_type?: string; scope_id?: string | null } = {}) => {
    const q: Record<string, string> = {}
    if (params.scope_type !== undefined) q.scope_type = params.scope_type
    if (params.scope_id !== undefined && params.scope_id !== null) q.scope_id = params.scope_id
    const suffix = new URLSearchParams(q).toString()
    return get<SkillLocalOverlay>(`/capabilities/skills/${encodeURIComponent(skillPackageId)}/local-overlay${suffix ? `?${suffix}` : ''}`)
  },
  updateSkillLocalOverlay: (skillPackageId: string, data: SkillLocalOverlayUpsertRequest) =>
    put<SkillLocalOverlay>(`/capabilities/skills/${encodeURIComponent(skillPackageId)}/local-overlay`, data),
  createSkillReviewProposal: (skillPackageId: string) =>
    post<SkillImportApprovalProposalResponse>(`/skill-packages/${encodeURIComponent(skillPackageId)}/review-proposal`),
  convertSkillToCapability: (skillPackageId: string, data: { capability_id?: string; namespace?: string; enable_for_project_id?: string | null; create_runtime_bindings?: boolean } = {}) =>
    post<SkillConvertToCapabilityResponse>(`/skill-packages/${encodeURIComponent(skillPackageId)}/convert-to-capability`, data),
  createCapabilityEnableProposal: (capabilityId: string, data: { capability_version_id?: string; project_id?: string; agent_id?: string; user_id?: string; config_json?: Record<string, unknown> } = {}) =>
    post<Proposal>(`/capability-definitions/${encodeURIComponent(capabilityId)}/enable-proposal`, data),
  createCapabilityDisableProposal: (capabilityId: string, data: { capability_version_id?: string; project_id?: string; agent_id?: string; user_id?: string } = {}) =>
    post<Proposal>(`/capability-definitions/${encodeURIComponent(capabilityId)}/disable-proposal`, data),
}

export const projectWorkflowProfilesApi = {
  list: (projectId: string) =>
    get<ProjectWorkflowProfile[]>(`/projects/${encodeURIComponent(projectId)}/workflow-profiles`),
  create: (projectId: string, data: { workflow_template_id: string; name: string; enabled?: boolean; config_json?: Record<string, unknown> }) =>
    post<ProjectWorkflowProfile>(`/projects/${encodeURIComponent(projectId)}/workflow-profiles`, data),
  update: (projectId: string, profileId: string, data: { name?: string; enabled?: boolean; config_json?: Record<string, unknown> }) =>
    patch<ProjectWorkflowProfile>(`/projects/${encodeURIComponent(projectId)}/workflow-profiles/${encodeURIComponent(profileId)}`, data),
  disable: (projectId: string, profileId: string) =>
    del<ProjectWorkflowProfile>(`/projects/${encodeURIComponent(projectId)}/workflow-profiles/${encodeURIComponent(profileId)}`),
  buildTemplateRunDraft: (projectId: string, workflowTemplateId: string, data: WorkflowRunDraftRequest = {}) =>
    post<WorkflowRunDraftResponse>(`/projects/${encodeURIComponent(projectId)}/workflow-templates/${encodeURIComponent(workflowTemplateId)}/run-draft`, data),
  buildRunDraft: (projectId: string, profileId: string, data: WorkflowRunDraftRequest = {}) =>
    post<WorkflowRunDraftResponse>(`/projects/${encodeURIComponent(projectId)}/workflow-profiles/${encodeURIComponent(profileId)}/run-draft`, data),
}

// ── Context ───────────────────────────────────────────────────────────────
export const contextApi = {
  build: (data: { workspace_id?: string | null; project_id?: string | null; session_id?: string | null; capability_id?: string | null; query?: string | null; context_artifact_ids?: string[] }) =>
    post<ContextPackage>('/context/build', data),
  listProfiles: (params: { scope_type?: string; scope_id?: string; status?: string } = {}) => {
    const q: Record<string, string> = {}
    if (params.scope_type !== undefined) q.scope_type = params.scope_type
    if (params.scope_id !== undefined) q.scope_id = params.scope_id
    if (params.status !== undefined) q.status = params.status
    const suffix = new URLSearchParams(q).toString()
    return get<ContextProfileListResponse>(`/context/profiles${suffix ? `?${suffix}` : ''}`)
  },
  updateProfile: (data: ContextProfileUpsertRequest) =>
    put<ContextProfile>('/context/profiles', data),
  getWorkspaceRouting: (workspaceId: string) =>
    get<ContextEffectiveRoutingResponse>(`/context/workspaces/${encodeURIComponent(workspaceId)}/routing`),
  updateWorkspaceRouting: (workspaceId: string, data: ContextRoutingUpdateRequest) =>
    put<ContextEffectiveRoutingResponse>(`/context/workspaces/${encodeURIComponent(workspaceId)}/routing`, data),
  listArtifactRevocations: (params: { workspace_id?: string | null; project_id?: string | null; artifact_ids?: string[] } = {}) => {
    const q: Record<string, string> = {}
    if (params.workspace_id) q.workspace_id = params.workspace_id
    if (params.project_id) q.project_id = params.project_id
    if (params.artifact_ids?.length) q.artifact_ids = params.artifact_ids.join(',')
    return get<ContextArtifactRevocationListResponse>(`/context/artifact-revocations?${new URLSearchParams(q).toString()}`)
  },
  revokeArtifact: (data: ContextArtifactRevocationCreateRequest) =>
    post<ContextArtifactRevocation>('/context/artifact-revocations', data),
  unrevokeArtifact: (artifactId: string, params: { scope_type: 'workspace' | 'project'; scope_id: string }) => {
    const q = new URLSearchParams({ scope_type: params.scope_type, scope_id: params.scope_id })
    return del<null>(`/context/artifact-revocations/${encodeURIComponent(artifactId)}?${q.toString()}`)
  },
}

export const contextOpsApi = {
  summary: (params: { window_days?: number; limit?: number } = {}) => {
    const q: Record<string, string> = {}
    if (params.window_days !== undefined) q.window_days = String(params.window_days)
    if (params.limit !== undefined) q.limit = String(params.limit)
    const suffix = new URLSearchParams(q).toString()
    return get<ContextOpsSummary>(`/context-ops/summary${suffix ? `?${suffix}` : ''}`)
  },
  drilldown: (section: ContextOpsDrilldownSection, params: { limit?: number } = {}) => {
    const q: Record<string, string> = { section }
    if (params.limit !== undefined) q.limit = String(params.limit)
    return get<ContextOpsDrilldown>(`/context-ops/drilldown?${new URLSearchParams(q).toString()}`)
  },
  reviewCycleRun: (data: ContextReviewCycleRequest = {}) =>
    post<ContextReviewCycleResponse>('/context-ops/review-cycle/run', data),
  contextObservationScan: (data: ContextOpsContextObservationScanRequest = {}) =>
    post<ContextOpsContextObservationScanResponse>('/context-ops/context-observations/scan', data),
}

export const askSpaceApi = {
  think: (data: AskSpaceRequest) => post<AskSpaceResponse>('/ask-space/think', data),
}

export const runtimeToolsApi = {
  catalog: () => get<RuntimeToolDefinition[]>('/runtime-tools/catalog'),
  list: () => get<RuntimeToolStatus[]>('/runtime-tools'),
  get: (runtime: string) => get<RuntimeToolStatus>(`/runtime-tools/${encodeURIComponent(runtime)}`),
  latest: (runtime: string) => get<RuntimeToolLatest>(`/runtime-tools/${encodeURIComponent(runtime)}/latest`),
  spacePolicies: () => get<SpaceRuntimeToolPolicyOut[]>('/runtime-tools/space-policy'),
  spacePolicy: (runtime: string) =>
    get<SpaceRuntimeToolPolicyOut>(`/runtime-tools/space-policy/${encodeURIComponent(runtime)}`),
  updateSpacePolicy: (runtime: string, data: { enabled?: boolean; default_version?: string | null; allowed_versions?: string[] }) =>
    put<SpaceRuntimeToolPolicyOut>(`/runtime-tools/space-policy/${encodeURIComponent(runtime)}`, data),
  install: (runtime: string, data: { version?: string | null; activate?: boolean; force?: boolean } = {}) =>
    post<RuntimeToolInstallResult>(`/runtime-tools/${encodeURIComponent(runtime)}/install`, data),
  activate: (runtime: string, version: string) =>
    post<RuntimeToolStatus>(`/runtime-tools/${encodeURIComponent(runtime)}/activate`, { version }),
}

// ── Credentials / Login ───────────────────────────────────────────────────
export const credentialsApi = {
  profiles: (runtime?: string, spaceId?: string | null) =>
    get<CliCredentialProfileOut[]>(
      '/credentials/cli/profiles' + (runtime ? `?runtime=${encodeURIComponent(runtime)}` : ''),
      spaceId ? { spaceId } : undefined,
    ),
  available: (runtime?: string, spaceId?: string | null) =>
    get<CliCredentialAvailableProfileOut[]>(
      '/credentials/cli/available' + (runtime ? `?runtime=${encodeURIComponent(runtime)}` : ''),
      spaceId ? { spaceId } : undefined,
    ),
  createProfile: (body: {
    runtime: string
    name: string
    readonly?: boolean
    notes?: string
    network_profile_id?: string | null
    is_default?: boolean
  }, spaceId?: string | null) => post<CliCredentialProfileOut>(
    '/credentials/cli/profiles',
    body,
    spaceId ? { spaceId } : undefined,
  ),
  grantProfile: (profileId: string, body: {
    space_id: string
    enabled?: boolean
    is_default?: boolean
    network_profile_id?: string | null
  }, spaceId?: string | null) => put(
    `/credentials/cli/profiles/${encodeURIComponent(profileId)}/grants`,
    body,
    spaceId ? { spaceId } : undefined,
  ),
  updateProfile: (profileId: string, body: { network_profile_id?: string | null }, spaceId?: string | null) =>
    patch<CliCredentialProfileOut>(
      `/credentials/cli/profiles/${encodeURIComponent(profileId)}`,
      body,
      spaceId ? { spaceId } : undefined,
    ),
  methods: (spaceId?: string | null) =>
    get<CredentialLoginMethod[]>('/credentials/cli/methods', spaceId ? { spaceId } : undefined),
  status: (spaceId?: string | null) =>
    get<CredentialStatus[]>('/credentials/cli/status', spaceId ? { spaceId } : undefined),
  usage: (spaceId?: string | null) =>
    get<CliUsageEntry[]>('/credentials/cli/usage', spaceId ? { spaceId } : undefined),
  usageAutoRefresh: (spaceId?: string | null) =>
    get<CliUsageAutoRefreshSettings>('/credentials/cli/usage/auto-refresh', spaceId ? { spaceId } : undefined),
  setUsageAutoRefresh: (enabled: boolean, spaceId?: string | null) =>
    put<CliUsageAutoRefreshSettings>(
      '/credentials/cli/usage/auto-refresh',
      { enabled },
      spaceId ? { spaceId } : undefined,
    ),
  refreshUsage: (runtime: string, profileId?: string | null, spaceId?: string | null) =>
    post<CliUsageEntry>(
      `/credentials/cli/usage/refresh?runtime=${encodeURIComponent(runtime)}${profileId ? `&profile_id=${encodeURIComponent(profileId)}` : ''}`,
      {},
      spaceId ? { spaceId } : undefined,
    ),

  sendLoginInput: (runtime: string, input: string, profileId?: string | null, spaceId?: string | null) =>
    post<{ status: string }>(
      `/credentials/cli/login/input?runtime=${encodeURIComponent(runtime)}`,
      profileId ? { input, profile_id: profileId } : { input },
      spaceId ? { spaceId } : undefined,
    ),

  async *loginStream(runtime: string, profileId?: string | null, spaceId?: string | null): AsyncGenerator<LoginEvent> {
    const profileParam = profileId ? `&profile_id=${encodeURIComponent(profileId)}` : ''
    const url = `${BASE}/credentials/cli/login/stream?runtime=${encodeURIComponent(runtime)}${profileParam}`
    const headers: Record<string, string> = {}
    if (_apiKey) headers['Authorization'] = `Bearer ${_apiKey}`
    headers['X-Agent-Space-Id'] = spaceId ?? _spaceId

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

export const networkProfilesApi = {
  list: () => get<NetworkProfileOut[]>('/network-profiles'),
  get: (id: string) => get<NetworkProfileOut>(`/network-profiles/${encodeURIComponent(id)}`),
  create: (body: NetworkProfileCreateBody) => post<NetworkProfileOut>('/network-profiles', body),
  patch: (id: string, body: NetworkProfileUpdateBody) =>
    patch<NetworkProfileOut>(`/network-profiles/${encodeURIComponent(id)}`, body),
  delete: (id: string) => del<void>(`/network-profiles/${encodeURIComponent(id)}`),
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

// ── Source / Evidence ────────────────────────────────────────────────────
export const sourcesApi = {
  connectors: () =>
    get<SourceConnector[]>('/sources/connectors'),

  connections: (params: { view?: 'subscribed' | 'pending' | 'owned' | 'available' | 'manageable'; status?: string; limit?: number; offset?: number } = {}) => {
    const q: Record<string, string> = {}
    if (params.view !== undefined) q.view = params.view
    if (params.status !== undefined) q.status = params.status
    if (params.limit !== undefined) q.limit = String(params.limit)
    if (params.offset !== undefined) q.offset = String(params.offset)
    return get<Page<SourceConnection>>('/sources/connections?' + new URLSearchParams(q))
  },
  createConnection: (body: SourceConnectionCreate) =>
    post<SourceConnection>('/sources/connections', body),
  sourcePresets: () =>
    get<SourcePresetListResponse>('/sources/source-presets'),
  previewArxivSourcePreset: (body: ArxivPresetPreviewRequest) =>
    post<ArxivPresetPreviewResponse>('/sources/source-presets/arxiv/preview', body),
  createArxivSourcePreset: (body: ArxivPresetCreateRequest) =>
    post<SourceConnection>('/sources/source-presets/arxiv', body),
  getConnection: (id: string) =>
    get<SourceConnection>(`/sources/connections/${id}`),
  updateConnection: (id: string, body: Partial<SourceConnectionCreate> & { status?: string }) =>
    patch<SourceConnection>(`/sources/connections/${id}`, body),
  recommendConnection: (id: string, body: { target_user_ids?: string[]; all_space?: boolean; message?: string | null }) =>
    post<{ source_connection_id: string; recommended: number }>(`/sources/connections/${id}/recommendations`, body),
  updateConnectionSubscription: (id: string, body: {
    action: 'subscribe' | 'dismiss' | 'mute' | 'unsubscribe'
    library_enabled?: boolean
    digest_enabled?: boolean
  }) =>
    post<SourceConnection>(`/sources/connections/${id}/subscription`, body),
  scanConnection: (id: string) =>
    post<ExtractionJob>(`/sources/connections/${id}/scan`),
  sourceRuns: (connectionId: string, params: { limit?: number; offset?: number } = {}) => {
    const q: Record<string, string> = {}
    if (params.limit !== undefined) q.limit = String(params.limit)
    if (params.offset !== undefined) q.offset = String(params.offset)
    return get<Page<SourceRunSummary>>(`/sources/connections/${connectionId}/source-runs?` + new URLSearchParams(q))
  },

  createCustomSourceDraft: (body: CustomSourceCreateDraftRequest) =>
    post<SourceConnection>('/sources/custom-sources/drafts', body),
  customSourceSummary: (connectionId: string) =>
    get<CustomSourceHandlerSummary>(`/sources/connections/${connectionId}/custom-source`),
  customSourceVersions: (connectionId: string, params: { limit?: number; offset?: number } = {}) => {
    const q: Record<string, string> = {}
    if (params.limit !== undefined) q.limit = String(params.limit)
    if (params.offset !== undefined) q.offset = String(params.offset)
    return get<Page<CustomSourceHandlerVersion>>(`/sources/connections/${connectionId}/handler-versions?` + new URLSearchParams(q))
  },
  customSourceRuns: (connectionId: string, params: { limit?: number; offset?: number } = {}) => {
    const q: Record<string, string> = {}
    if (params.limit !== undefined) q.limit = String(params.limit)
    if (params.offset !== undefined) q.offset = String(params.offset)
    return get<Page<CustomSourceHandlerRun>>(`/sources/connections/${connectionId}/handler-runs?` + new URLSearchParams(q))
  },
  generateCustomSourceHandler: (connectionId: string, body: { capture_policy?: SourceCapturePolicy; retention_policy?: string } = {}) =>
    post<CustomSourceHandlerVersion>(`/sources/custom-sources/${connectionId}/generate-handler`, body),
  testCustomSourceHandler: (connectionId: string, body: { handler_version_id: string; fixture_html?: string }) =>
    post<CustomSourceTestOutcome>(`/sources/custom-sources/${connectionId}/test-handler`, body),
  activateCustomSourceHandler: (connectionId: string, body: { handler_version_id: string; next_check_at?: string | null; schedule_rule?: SourceScheduleRule | null }) =>
    post<CustomSourceActivationResult>(`/sources/custom-sources/${connectionId}/activate`, body),
  customSourceSpacePolicy: () =>
    get<CustomSourceSpacePolicy>('/sources/custom-source-settings/space'),
  customSourceInstanceRunnerSettings: () =>
    get<CustomSourceInstanceRunnerSettings>('/sources/custom-source-settings/instance'),
  updateCustomSourceInstanceRunnerSettings: (body: CustomSourceInstanceRunnerSettingsUpdate) =>
    put<CustomSourceInstanceRunnerSettings>('/sources/custom-source-settings/instance', body),
  updateCustomSourceSpacePolicy: (body: CustomSourceSpacePolicyUpdate) =>
    put<CustomSourceSpacePolicy>('/sources/custom-source-settings/space', body),
  planSourceRecipe: (body: SourceRecipePlanRequest) =>
    post<SourceRecipePlanResponse>('/sources/source-recipes/plan', body),
  createSourceRecipe: (body: SourceRecipeCreateRequest) =>
    post<SourceRecipeCreateResponse>('/sources/source-recipes', body),
  dryRunSourceRecipe: (connectionId: string, body: { recipe_version_id: string; fixture_content?: string }) =>
    post<SourceRecipeDryRunResponse>(`/sources/source-recipes/${connectionId}/dry-run`, body),
  activateSourceRecipe: (connectionId: string, body: { recipe_version_id: string; next_check_at?: string | null; schedule_rule?: SourceScheduleRule | null }) =>
    post<SourceRecipeActivationResult>(`/sources/source-recipes/${connectionId}/activate`, body),
  bridgePipelineSourceRecipe: (connectionId: string, body: SourceRecipePipelineBridgeRequest = {}) =>
    post<SourceRecipePipelineBridgeResponse>(`/sources/custom-sources/${connectionId}/bridge-pipeline`, body),
  sourceRecipeVersions: (connectionId: string, params: { limit?: number; offset?: number } = {}) => {
    const q: Record<string, string> = {}
    if (params.limit !== undefined) q.limit = String(params.limit)
    if (params.offset !== undefined) q.offset = String(params.offset)
    return get<Page<SourceRecipeVersion>>(`/sources/connections/${connectionId}/recipe-versions?` + new URLSearchParams(q))
  },

  items: (params: {
    library_status?: string
    read_status?: string
    connection_id?: string
    project_id?: string
    content_state?: string
    q?: string
    library_type?: string
    created_after?: string
    limit?: number
    offset?: number
  } = {}) => {
    const q: Record<string, string> = {}
    if (params.library_status !== undefined) q.library_status = params.library_status
    if (params.read_status !== undefined) q.read_status = params.read_status
    if (params.connection_id !== undefined) q.connection_id = params.connection_id
    if (params.project_id !== undefined) q.project_id = params.project_id
    if (params.content_state !== undefined) q.content_state = params.content_state
    if (params.q !== undefined) q.q = params.q
    if (params.library_type !== undefined) q.library_type = params.library_type
    if (params.created_after !== undefined) q.created_after = params.created_after
    if (params.limit !== undefined) q.limit = String(params.limit)
    if (params.offset !== undefined) q.offset = String(params.offset)
    return get<Page<SourceItem>>('/sources/items?' + new URLSearchParams(q))
  },
  getItem: (id: string) =>
    get<SourceItem>(`/sources/items/${id}`),
  updateItem: (id: string, body: { connection_id?: string | null }) =>
    patch<SourceItem>(`/sources/items/${id}`, body),
  createManualUrl: (body: { url: string; title?: string; connection_id?: string | null; queue_content?: boolean }) =>
    post<SourceItem>('/sources/items/manual-url', body),
  itemAction: (id: string, action: string) =>
    post<SourceItem>(`/sources/items/${id}/actions`, { action }),
  jobs: (params: {
    status?: string
    source_item_id?: string
    connection_id?: string
    job_type?: string
    limit?: number
    offset?: number
  } = {}) => {
    const q: Record<string, string> = {}
    if (params.status !== undefined) q.status = params.status
    if (params.source_item_id !== undefined) q.source_item_id = params.source_item_id
    if (params.connection_id !== undefined) q.connection_id = params.connection_id
    if (params.job_type !== undefined) q.job_type = params.job_type
    if (params.limit !== undefined) q.limit = String(params.limit)
    if (params.offset !== undefined) q.offset = String(params.offset)
    return get<Page<ExtractionJob>>('/sources/jobs?' + new URLSearchParams(q))
  },
  runJob: (id: string) =>
    post<ExtractionJob>(`/sources/jobs/${id}/run`),

  evidence: (params: { status?: string; evidence_type?: string; source_item_id?: string; project_id?: string; connection_id?: string; limit?: number; offset?: number } = {}) => {
    const q: Record<string, string> = {}
    if (params.status !== undefined) q.status = params.status
    if (params.evidence_type !== undefined) q.evidence_type = params.evidence_type
    if (params.source_item_id !== undefined) q.source_item_id = params.source_item_id
    if (params.project_id !== undefined) q.project_id = params.project_id
    if (params.connection_id !== undefined) q.connection_id = params.connection_id
    if (params.limit !== undefined) q.limit = String(params.limit)
    if (params.offset !== undefined) q.offset = String(params.offset)
    return get<Page<ExtractedEvidence>>('/sources/evidence?' + new URLSearchParams(q))
  },
  updateEvidence: (id: string, body: { status?: string; confidence?: number; metadata?: Record<string, unknown> }) =>
    patch<ExtractedEvidence>(`/sources/evidence/${id}`, body),
  createEvidenceLink: (body: {
    evidence_id: string
    target_type: string
    target_id?: string | null
    link_type?: string
    status?: string
    confidence?: number
    reason?: string
  }) => post<EvidenceLink>('/sources/evidence-links', body),
  evidenceLinks: (params: { evidence_id?: string; target_type?: string; target_id?: string; status?: string } = {}) => {
    const q: Record<string, string> = {}
    if (params.evidence_id !== undefined) q.evidence_id = params.evidence_id
    if (params.target_type !== undefined) q.target_type = params.target_type
    if (params.target_id !== undefined) q.target_id = params.target_id
    if (params.status !== undefined) q.status = params.status
    return get<Page<EvidenceLink>>('/sources/evidence-links?' + new URLSearchParams(q))
  },

  workspaceBindings: (params: { workspace_id?: string; source_connection_id?: string; project_id?: string } = {}) => {
    const q: Record<string, string> = {}
    if (params.workspace_id !== undefined) q.workspace_id = params.workspace_id
    if (params.source_connection_id !== undefined) q.source_connection_id = params.source_connection_id
    if (params.project_id !== undefined) q.project_id = params.project_id
    return get<WorkspaceSourceBinding[]>('/sources/workspace-source-bindings?' + new URLSearchParams(q))
  },
  createWorkspaceBinding: (body: {
    workspace_id: string
    source_connection_id: string
    project_id: string
    backfill_history?: boolean
    binding_key?: string
    priority?: number
    filters?: Record<string, unknown>
    routing_policy?: Record<string, unknown>
    extraction_policy?: Record<string, unknown>
  }) => post<WorkspaceSourceBinding>('/sources/workspace-source-bindings', body),
  backfillWorkspaceBinding: (bindingId: string) =>
    post<WorkspaceSourceBindingBackfillResult>(`/sources/workspace-source-bindings/${bindingId}/backfill`),
  summarize: (body: SummaryRunRequest) =>
    post<SummaryRunOut>('/sources/post-processing/run-once', body),
  postProcessingRules: (connectionId: string) =>
    get<SourcePostProcessingRule[]>(`/sources/connections/${connectionId}/post-processing/rules`),
  createPostProcessingRule: (connectionId: string, body: SourcePostProcessingRuleCreate) =>
    post<SourcePostProcessingRule>(`/sources/connections/${connectionId}/post-processing/rules`, body),
  updatePostProcessingRule: (connectionId: string, ruleId: string, body: SourcePostProcessingRuleUpdate) =>
    patch<SourcePostProcessingRule>(`/sources/connections/${connectionId}/post-processing/rules/${ruleId}`, body),
  runPostProcessingRule: (connectionId: string, ruleId: string) =>
    post<SourcePostProcessingRun>(`/sources/connections/${connectionId}/post-processing/rules/${ruleId}/run`),
  drainPostProcessingRule: (connectionId: string, ruleId: string) =>
    post<SourcePostProcessingDrainResult>(`/sources/connections/${connectionId}/post-processing/rules/${ruleId}/drain`),
  postProcessingRuns: (connectionId: string, params: { limit?: number; offset?: number } = {}) => {
    const q: Record<string, string> = {}
    if (params.limit !== undefined) q.limit = String(params.limit)
    if (params.offset !== undefined) q.offset = String(params.offset)
    return get<Page<SourcePostProcessingRun>>(`/sources/connections/${connectionId}/post-processing/runs?` + new URLSearchParams(q))
  },
  postProcessingBacklog: (connectionId: string) =>
    get<SourcePostProcessingBacklog>(`/sources/connections/${connectionId}/post-processing/backlog`),
  postProcessingDecisions: (params: {
    connection_id?: string
    project_id?: string
    rule_id?: string
    relevance?: SourcePostProcessingItemRelevance
    review_status?: SourcePostProcessingDecisionReviewStatus
    limit?: number
    offset?: number
  } = {}) => {
    const q: Record<string, string> = {}
    if (params.connection_id !== undefined) q.connection_id = params.connection_id
    if (params.project_id !== undefined) q.project_id = params.project_id
    if (params.rule_id !== undefined) q.rule_id = params.rule_id
    if (params.relevance !== undefined) q.relevance = params.relevance
    if (params.review_status !== undefined) q.review_status = params.review_status
    if (params.limit !== undefined) q.limit = String(params.limit)
    if (params.offset !== undefined) q.offset = String(params.offset)
    return get<Page<SourcePostProcessingItemDecision>>('/sources/post-processing/decisions?' + new URLSearchParams(q))
  },
  postProcessingConnectionDecisions: (connectionId: string, params: {
    rule_id?: string
    relevance?: SourcePostProcessingItemRelevance
    review_status?: SourcePostProcessingDecisionReviewStatus
    limit?: number
    offset?: number
  } = {}) => {
    const q: Record<string, string> = {}
    if (params.rule_id !== undefined) q.rule_id = params.rule_id
    if (params.relevance !== undefined) q.relevance = params.relevance
    if (params.review_status !== undefined) q.review_status = params.review_status
    if (params.limit !== undefined) q.limit = String(params.limit)
    if (params.offset !== undefined) q.offset = String(params.offset)
    return get<Page<SourcePostProcessingItemDecision>>(`/sources/connections/${connectionId}/post-processing/decisions?` + new URLSearchParams(q))
  },
  postProcessingDecisionAction: (decisionId: string, action: string) =>
    post<SourcePostProcessingDecisionActionResult>(`/sources/post-processing/decisions/${decisionId}/actions`, { action }),
  briefings: (params: {
    connection_id?: string
    project_id?: string
    limit?: number
    offset?: number
  } = {}) => {
    const q: Record<string, string> = {}
    if (params.connection_id !== undefined) q.connection_id = params.connection_id
    if (params.project_id !== undefined) q.project_id = params.project_id
    if (params.limit !== undefined) q.limit = String(params.limit)
    if (params.offset !== undefined) q.offset = String(params.offset)
    return get<Page<SourcePostProcessingBriefingDaySummary>>('/sources/briefings?' + new URLSearchParams(q))
  },
  briefing: (connectionId: string, date: string) =>
    get<SourcePostProcessingBriefingDetail>(`/sources/briefings/${connectionId}/${date}`),
}

// ── Source Reader ─────────────────────────────────────────────────────────
export const sourceReaderApi = {
  getDocument: (documentType: string, documentId: string) =>
    get<ReaderDocumentPayload>(`/sources/reader/documents/${documentType}/${documentId}`),

  listAnnotations: (documentType: string, documentId: string) =>
    get<ReaderAnnotationsResponse>(`/sources/reader/documents/${documentType}/${documentId}/annotations`),

  createAnnotation: (body: ReaderAnnotationCreate) =>
    post<ReaderAnnotation>('/sources/reader/annotations', body),

  updateAnnotation: (annotationId: string, body: ReaderAnnotationUpdate) =>
    patch<ReaderAnnotation>(`/sources/reader/annotations/${annotationId}`, body),

  deleteAnnotation: (annotationId: string) =>
    del(`/sources/reader/annotations/${annotationId}`),

  listThreads: (annotationId: string) =>
    get<{ items: ReaderCommentThread[] }>(`/sources/reader/annotations/${annotationId}/threads`),

  createComment: (annotationId: string, body: ReaderCommentCreate) =>
    post<{ thread: ReaderCommentThread }>(`/sources/reader/annotations/${annotationId}/comments`, body),

  updateComment: (commentId: string, body: ReaderCommentUpdate) =>
    patch<ReaderComment>(`/sources/reader/comments/${commentId}`, body),

  updateThread: (threadId: string, body: ReaderThreadUpdate) =>
    patch<ReaderCommentThread>(`/sources/reader/comment-threads/${threadId}`, body),

  createEvidence: (annotationId: string, body: ReaderCreateEvidenceRequest) =>
    post<ReaderCreatedEvidence>(`/sources/reader/annotations/${annotationId}/evidence`, body),

  createProposal: (annotationId: string, body: ReaderCreateProposalRequest) =>
    post<ReaderCreatedProposal>(`/sources/reader/annotations/${annotationId}/proposals`, body),

  listByProject: (projectId: string, limit?: number) =>
    get<{ items: ReaderAnnotation[] }>(
      `/sources/reader/annotations?project_id=${encodeURIComponent(projectId)}${limit != null ? `&limit=${limit}` : ''}`,
    ),
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
  publicSummaryFeedback: (data: RetrievalFeedbackRequest) =>
    post<RetrievalFeedbackResponse>('/projects/public-summaries/feedback', data),
  publicSummaryBrief: (data: RetrievalBriefRequest) =>
    post<RetrievalBriefResponse>('/projects/retrieval/brief', data),
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
  create:               (data: { name: string; type: Exclude<SpaceWithMembership['type'], 'personal'> }) => post<SpaceWithMembership>('/spaces', data),
  get:                  (spaceId: string)                              => get<SpaceWithMembership>(`/spaces/${spaceId}`),
  members:              (spaceId: string)                              => get<SpaceMember[]>(`/spaces/${spaceId}/members`),
  invite:               (spaceId: string, data: { email: string; role: string }) =>
    post<SpaceInvitationOut>(`/spaces/${spaceId}/invitations`, data),
  acceptInvite:         (token: string)                                => post<{ space_id: string; role: string; space_name: string }>(`/invitations/${token}/accept`),
  getSnapshotDefaults:  (spaceId: string)                              => get<SpaceSnapshotDefaults>(`/spaces/${spaceId}/snapshot-defaults`),
  updateSnapshotDefaults: (spaceId: string, data: SpaceSnapshotDefaults) => patch<SpaceSnapshotDefaults>(`/spaces/${spaceId}/snapshot-defaults`, data),
  getRetrievalSettings: (spaceId: string) =>
    get<SpaceRetrievalSettings>(`/spaces/${spaceId}/retrieval-settings`),
  updateRetrievalSettings: (spaceId: string, data: SpaceRetrievalSettingsUpdate) =>
    patch<SpaceRetrievalSettings>(`/spaces/${spaceId}/retrieval-settings`, data),
  getRetrievalPrompt: (spaceId: string, task: RetrievalPromptTask) =>
    get<SpaceRetrievalPrompt>(`/spaces/${spaceId}/retrieval-prompts/${task}`),
  updateRetrievalPrompt: (spaceId: string, task: RetrievalPromptTask, data: SpaceRetrievalPromptUpdate) =>
    patch<SpaceRetrievalPrompt>(`/spaces/${spaceId}/retrieval-prompts/${task}`, data),
}

// ── Providers ─────────────────────────────────────────────────────────────
export type ProviderType =
  | 'openai'
  | 'anthropic'
  | 'openrouter'
  | 'ollama'
  | 'zeroentropy'
  | 'cohere'
  | 'other'

export interface ModelProviderOut {
  id: string
  space_id: string
  home_space_id?: string
  owner_user_id?: string | null
  grant_id?: string | null
  name: string
  provider_type: ProviderType | string
  base_url: string
  network_profile_id: string | null
  claude_compatible_base_url: string | null
  openai_compatible_base_url: string | null
  default_model: string | null
  available_models: string[]
  enabled: boolean
  is_default: boolean
  has_api_key: boolean
  manageable?: boolean
  grant_enabled?: boolean
  created_at: string
  updated_at: string
}

export interface ModelProviderModelsOut {
  models: string[]
  source: 'configured' | 'live'
}

export type ProviderPresetMode = 'chat' | 'embedding' | 'rerank'

export interface ProviderPresetOut {
  id: string
  mode: ProviderPresetMode
  label: string
  description?: string | null
  name: string
  provider_type: ProviderType
  base_url: string
  claude_compatible_base_url?: string | null
  openai_compatible_base_url?: string | null
  default_model?: string | null
  available_models: string[]
  embedding_dimensions?: number | null
  embedding_dimension_options?: number[]
  api_key_required: boolean
  task?: string | null
}

export interface ProviderFromPresetCreateRequest {
  preset_id: string
  api_key?: string | null
  name?: string
  network_profile_id?: string | null
  default_model?: string | null
  available_models?: string[]
  embedding_dimensions?: number
  is_default?: boolean
}

export interface ProviderFromPresetCreateResponse {
  provider: ModelProviderOut
}

export interface ProviderTaskChainEntry {
  provider_id: string
  model?: string | null
}

export interface ProviderTaskPolicyOut {
  task: string
  chain: ProviderTaskChainEntry[]
  enabled: boolean
  updated_at: string
}

export interface ProviderTaskPolicyPutRequest {
  chain: ProviderTaskChainEntry[]
  enabled?: boolean
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

  presets: () => get<ProviderPresetOut[]>('/providers/presets'),

  litellmProviders: () => get<string[]>('/providers/litellm-providers'),

  create: (data: {
    name: string
    provider_type: ProviderType | string
    api_key?: string
    default_model?: string
    available_models?: string[]
    base_url: string
    network_profile_id?: string | null
    claude_compatible_base_url?: string
    openai_compatible_base_url?: string
    enabled?: boolean
    is_default?: boolean
  }) => post<ModelProviderOut>('/providers', data),

  createFromPreset: (data: ProviderFromPresetCreateRequest) =>
    post<ProviderFromPresetCreateResponse>('/providers/from-preset', data),

  patch: (id: string, data: Partial<{
    name: string
    provider_type: ProviderType | string
    api_key: string
    default_model: string
    available_models: string[]
    base_url: string
    network_profile_id: string | null
    claude_compatible_base_url: string | null
    openai_compatible_base_url: string | null
    enabled: boolean
    is_default: boolean
  }>) => patch<ModelProviderOut>(`/providers/${id}`, data),

  delete: (id: string) => del<void>(`/providers/${id}`),

  models: (id: string) => get<ModelProviderModelsOut>(`/providers/${id}/models`),

  test: (id: string) => post<TestConnectionOut>(`/providers/${id}/test`, {}),

  taskPolicies: () => get<ProviderTaskPolicyOut[]>('/providers/task-policies'),

  putTaskPolicy: (task: string, data: ProviderTaskPolicyPutRequest) =>
    put<ProviderTaskPolicyOut>(`/providers/task-policies/${encodeURIComponent(task)}`, data),

  deleteTaskPolicy: (task: string) =>
    del<void>(`/providers/task-policies/${encodeURIComponent(task)}`),

  grant: (id: string, data: {
    space_id: string
    enabled?: boolean
    is_default?: boolean
    network_profile_id?: string | null
  }) => put(`/providers/${encodeURIComponent(id)}/grants`, data),

  catalog: () => get<CatalogInfo>('/providers/catalog'),

  chat: (data: ChatRequest) => post<ChatResponse>('/providers/chat', data),
}

// ── Official Optional Modules (plugins) ───────────────────────────────────
// GET /api/v1/plugins       — list all descriptors + effective state
// GET /api/v1/plugins/effective — effective map for frontend overlay
// GET /api/v1/plugins/:id   — single plugin
// POST /api/v1/plugins/:id/install  — install package + migrations
// POST /api/v1/plugins/:id/enable   — enable
// POST /api/v1/plugins/:id/disable  — disable
// PATCH /api/v1/plugins/:id/settings — patch settings
export const pluginsApi = {
  list: () => get<{ items: unknown[] }>('/plugins'),
  effective: () => get<{ plugins: Record<string, unknown> }>('/plugins/effective'),
  get: (pluginId: string) => get<unknown>(`/plugins/${encodeURIComponent(pluginId)}`),
  install: (pluginId: string) =>
    post<unknown>(`/plugins/${encodeURIComponent(pluginId)}/install`, {}),
  enable: (pluginId: string, body: { settings?: Record<string, unknown> } = {}) =>
    post<unknown>(`/plugins/${encodeURIComponent(pluginId)}/enable`, body),
  disable: (pluginId: string, body: Record<string, never> = {}) =>
    post<unknown>(`/plugins/${encodeURIComponent(pluginId)}/disable`, body),
  patchSettings: (pluginId: string, settings: Record<string, unknown>) =>
    patch<unknown>(`/plugins/${encodeURIComponent(pluginId)}/settings`, { settings }),
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

// ── diary ─────────────────────────────────────────────────────────────────
export interface DiaryEntry {
  id: string
  user_id: string
  entry_date: string
  content: string
  created_at: string
  updated_at: string
}

export interface DiaryReflection {
  id: string
  entry_id: string
  reflection_date: string
  content: string
  ai_model: string | null
  created_at: string
}

// ── finance ledger ────────────────────────────────────────────────────────
export interface FinanceBook {
  id: string
  space_id: string
  name: string
  base_currency: string
  operating_currency: string
  status: string
  created_at: string
  updated_at: string
}

export interface FinanceAccount {
  id: string
  name: string
  display_name: string | null
  root_type: string
  parent_account_id: string | null
  commodity_constraints: string[] | null
  opened_at: string
  closed_at: string | null
  booking_method: string | null
  default_commodity: string | null
  owner_user_id: string | null
  visibility: 'space' | 'private'
}

export type FinanceBalanceScope = 'all' | 'shared' | 'personal'

export interface CreateFinanceAccountInput {
  root_type: string
  group: string
  leaf: string
  display_name?: string
  opened_at: string
  currencies?: string[]
  default_currency?: string
  owner?: 'shared' | 'personal'
  visible_to_space?: boolean
}

export interface FinanceCommodity {
  id: string
  symbol: string
  commodity_type: string
  name: string | null
}

export interface FinanceDirective {
  id: string
  directive_type: string
  date: string
  sequence: number
  status: string
}

export interface FinanceTransaction {
  directive_id: string
  flag: string
  payee: string | null
  narration: string | null
  tags: string[]
  links: string[]
  directive: FinanceDirective
}

export interface FinancePosting {
  id: string
  transaction_directive_id: string
  account_id: string
  account_name: string
  amount_text: string | null
  commodity_symbol: string | null
  price_number_text: string | null
  price_commodity_symbol: string | null
  price_is_total: boolean
  flag: string | null
  sort_order: number
}

export interface FinanceBalancePosition {
  accountId: string
  accountName: string
  positions: string[]
}

export interface FinanceValidationError {
  code: string
  message: string
  directiveId?: string
}

export interface FinanceLedgerError {
  code: string
  message: string
  source?: { filename: string; lineno: number }
}

export interface FinanceTransactionInput {
  date: string
  payee?: string | null
  narration?: string | null
  post?: boolean
  postings: Array<{
    account_id: string
    amount?: { number: string; commodity: string } | null
  }>
}

export interface FinanceImportResult {
  import_source_id: string | null
  deduplicated: boolean
  created_directives: number
  errors: FinanceLedgerError[]
}

export interface FinanceExportResult {
  export_id: string
  content: string
  content_hash: string
  errors: FinanceLedgerError[]
}

export const financeApi = {
  listBooks: () => get<{ books: FinanceBook[] }>('/finance/books'),
  createBook: (input: { name: string; base_currency: string; operating_currency?: string }) =>
    post<{ book: FinanceBook }>('/finance/books', input),
  listAccounts: (bookId: string) =>
    get<{ accounts: FinanceAccount[] }>(`/finance/books/${encodeURIComponent(bookId)}/accounts`),
  createAccount: (bookId: string, input: CreateFinanceAccountInput) =>
    post<{ account: FinanceAccount }>(`/finance/books/${encodeURIComponent(bookId)}/accounts`, input),
  closeAccount: (bookId: string, accountId: string, date: string) =>
    post<{ account: FinanceAccount }>(
      `/finance/books/${encodeURIComponent(bookId)}/accounts/${encodeURIComponent(accountId)}/close`,
      { date },
    ),
  setAccountVisibility: (bookId: string, accountId: string, visibility: 'space' | 'private') =>
    post<{ account: FinanceAccount }>(
      `/finance/books/${encodeURIComponent(bookId)}/accounts/${encodeURIComponent(accountId)}/visibility`,
      { visibility },
    ),
  listCommodities: (bookId: string) =>
    get<{ commodities: FinanceCommodity[] }>(`/finance/books/${encodeURIComponent(bookId)}/commodities`),
  createCommodity: (bookId: string, input: { symbol: string; commodity_type?: string }) =>
    post<{ commodity: FinanceCommodity }>(`/finance/books/${encodeURIComponent(bookId)}/commodities`, input),
  listTransactions: (bookId: string) =>
    get<{ transactions: FinanceTransaction[] }>(`/finance/books/${encodeURIComponent(bookId)}/transactions`),
  createTransaction: (bookId: string, input: FinanceTransactionInput) =>
    post<{ directive: FinanceDirective }>(`/finance/books/${encodeURIComponent(bookId)}/transactions`, input),
  getAccountLedger: (bookId: string, accountId: string) =>
    get<{ postings: FinancePosting[] }>(
      `/finance/books/${encodeURIComponent(bookId)}/accounts/${encodeURIComponent(accountId)}/ledger`,
    ),
  getBalances: (bookId: string, scope: FinanceBalanceScope = 'all') =>
    get<{ balances: FinanceBalancePosition[] }>(
      `/finance/books/${encodeURIComponent(bookId)}/balances?scope=${scope}`,
    ),
  validateBook: (bookId: string) =>
    post<{ errors: FinanceValidationError[] }>(`/finance/books/${encodeURIComponent(bookId)}/validate`),
  importBeancount: (bookId: string, input: { text: string; filename?: string; post_directly?: boolean }) =>
    post<FinanceImportResult>(`/finance/books/${encodeURIComponent(bookId)}/import/beancount`, input),
  exportBeancount: (bookId: string) =>
    post<FinanceExportResult>(`/finance/books/${encodeURIComponent(bookId)}/export/beancount`),
}

export const diaryApi = {
  today: () => get<{ date: string; entry: DiaryEntry | null }>('/diary/today'),
  listEntries: (params: { limit?: number; before?: string } = {}) => {
    const q = new URLSearchParams()
    if (params.limit) q.set('limit', String(params.limit))
    if (params.before) q.set('before', params.before)
    return get<{ entries: DiaryEntry[] }>(`/diary/entries${q.size ? '?' + q : ''}`)
  },
  saveEntry: (date: string, content: string) =>
    put<{ entry: DiaryEntry }>(`/diary/entries/${encodeURIComponent(date)}`, { content }),
  deleteEntry: (date: string) =>
    del<{ deleted: boolean }>(`/diary/entries/${encodeURIComponent(date)}`),
  onThisDay: (date: string) =>
    get<{ date: string; entries: DiaryEntry[] }>(`/diary/on-this-day?date=${encodeURIComponent(date)}`),
  reflections: (date: string) =>
    get<{ entry_date: string; reflections: DiaryReflection[] }>(`/diary/entries/${encodeURIComponent(date)}/reflections`),
}

export interface ResearchAtlasStatus {
  ok: boolean
  plugin_id: string
  version: string
  scope: 'space'
  space_id: string
}

export interface ResearchAtlasPaper {
  id: string
  space_id: string
  title: string
  abstract: string | null
  publication_date: string | null
  publication_year: number | null
  paper_type: string
  venue_id: string | null
  doi: string | null
  arxiv_id: string | null
  oa_status: string
  best_oa_url: string | null
  raw_author_names: string[]
  merged_into_id: string | null
  created_at: string
  updated_at: string
}

export interface ResearchAtlasAuthorship {
  id: string
  paper_id: string
  scholar_id: string | null
  author_position: number
  raw_author_name: string
  raw_affiliation_text: string | null
  confidence: number | null
}

export interface ResearchAtlasExternalId {
  id_type: string
  id_value: string
  is_primary: boolean
}

export interface ResearchAtlasPaperDetail {
  paper: ResearchAtlasPaper
  authorships: ResearchAtlasAuthorship[]
  external_ids: ResearchAtlasExternalId[]
  provenance: Array<{ connector: string; fetched_at: string; fetch_status: string }>
}

export interface ResearchAtlasScholar {
  id: string
  display_name: string
  orcid: string | null
  h_index: number | null
  works_count: number | null
}

export interface ResearchAtlasScholarDetail {
  scholar: ResearchAtlasScholar
  papers: ResearchAtlasPaper[]
  external_ids: ResearchAtlasExternalId[]
  coauthors: Array<{ id: string; display_name: string; shared_paper_count: number }>
  affiliations: Array<{
    id: string
    role: string | null
    institution: { id: string; name: string } | null
    department: { id: string; name: string } | null
  }>
}

export interface ResearchAtlasSearchResult {
  entity_type: string
  id: string
  label: string
  detail: string | null
}

export interface ResearchAtlasSyncStatus {
  cursors: Array<{
    cursor_key: string
    watermark_json: Record<string, unknown>
    last_run_at: string | null
    last_error: string | null
    updated_at: string
  }>
  due_refresh_count: number
}

export interface ResearchAtlasProjectPaper {
  id: string
  project_id: string
  paper_id: string
  status: 'candidate' | 'shortlist' | 'reading' | 'done' | 'rejected'
  read_status: 'unread' | 'skimmed' | 'read'
  rating: number | null
  tags: string[]
  note: string | null
  pinned: boolean
  source: string
  source_item_id: string | null
  paper: ResearchAtlasPaper
}

export interface ResearchAtlasTopic {
  id: string
  label: string
  kind: string
  taxonomy: string
}

export interface ResearchAtlasGroup {
  id: string
  name: string
  aliases: string[]
  pi_scholar_id: string | null
  confidence: number | null
  member_count?: number
}

export interface ResearchAtlasGroupMembership {
  id: string
  group_id: string
  scholar_id: string
  role: string
  source: string
  confidence: number | null
  scholar?: ResearchAtlasScholar
}

export interface ResearchAtlasPaperRelated {
  references: ResearchAtlasPaper[]
  citations: ResearchAtlasPaper[]
  coauthors: Array<{ id: string; display_name: string }>
}

export const researchAtlasApi = {
  status: () => get<ResearchAtlasStatus>('/atlas/status'),
  listPapers: (params: { q?: string; year?: number; cursor?: string; limit?: number } = {}) => {
    const q = new URLSearchParams()
    if (params.q) q.set('q', params.q)
    if (params.year) q.set('year', String(params.year))
    if (params.cursor) q.set('cursor', params.cursor)
    if (params.limit) q.set('limit', String(params.limit))
    return get<{ papers: ResearchAtlasPaper[]; next_cursor: string | null }>(`/atlas/papers${q.size ? '?' + q : ''}`)
  },
  importPaper: (input: { doi?: string; arxiv_id?: string }) =>
    post<{ paper: ResearchAtlasPaper; status: 'created' | 'matched'; job_id: string | null }>('/atlas/papers/import', input),
  importFile: (input: { format: 'bibtex' | 'ris' | 'csl_json'; content: string | unknown }) =>
    post<{ imported: Array<{ paper: ResearchAtlasPaper; status: 'created' | 'matched'; job_id: string | null }>; count: number }>('/atlas/papers/import-file', input),
  getPaper: (paperId: string) =>
    get<ResearchAtlasPaperDetail>(`/atlas/papers/${encodeURIComponent(paperId)}`),
  patchPaper: (paperId: string, input: Partial<Pick<ResearchAtlasPaper, 'title' | 'abstract' | 'publication_year' | 'paper_type' | 'doi' | 'arxiv_id'>>) =>
    patch<{ paper: ResearchAtlasPaper }>(`/atlas/papers/${encodeURIComponent(paperId)}`, input),
  search: (query: string) =>
    get<{ results: ResearchAtlasSearchResult[] }>(`/atlas/search?q=${encodeURIComponent(query)}`),
  getScholar: (scholarId: string) =>
    get<ResearchAtlasScholarDetail>(`/atlas/scholars/${encodeURIComponent(scholarId)}`),
  getPaperReferences: (paperId: string) =>
    get<{ papers: ResearchAtlasPaper[] }>(`/atlas/papers/${encodeURIComponent(paperId)}/references`),
  getPaperCitations: (paperId: string) =>
    get<{ papers: ResearchAtlasPaper[] }>(`/atlas/papers/${encodeURIComponent(paperId)}/citations`),
  getPaperRelated: (paperId: string) =>
    get<ResearchAtlasPaperRelated>(`/atlas/papers/${encodeURIComponent(paperId)}/related`),
  getGraph: (params: { mode?: 'global' | 'library'; paper_id?: string }) => {
    const q = new URLSearchParams()
    if (params.mode) q.set('mode', params.mode)
    if (params.paper_id) q.set('paper_id', params.paper_id)
    return get<GraphProjection>(`/atlas/graph?${q}`)
  },
  listTopics: () => get<{ topics: ResearchAtlasTopic[] }>('/atlas/topics'),
  listGroups: () => get<{ groups: ResearchAtlasGroup[] }>('/atlas/groups'),
  createGroup: (input: { name: string; aliases?: string[]; pi_scholar_id?: string | null; confidence?: number | null }) =>
    post<{ group: ResearchAtlasGroup }>('/atlas/groups', input),
  addGroupMembership: (groupId: string, input: { scholar_id: string; role?: string; confidence?: number | null }) =>
    post<{ membership: ResearchAtlasGroupMembership }>(`/atlas/groups/${encodeURIComponent(groupId)}/members`, input),
  exportEntities: (params: { type: string; since?: string; cursor?: string; limit?: number; include_merged?: boolean; active_only?: boolean }) => {
    const q = new URLSearchParams()
    q.set('type', params.type)
    if (params.since) q.set('since', params.since)
    if (params.cursor) q.set('cursor', params.cursor)
    if (params.limit) q.set('limit', String(params.limit))
    if (params.include_merged !== undefined) q.set('include_merged', String(params.include_merged))
    if (params.active_only) q.set('active_only', 'true')
    return getText(`/atlas/export/entities?${q}`)
  },
  settings: () => get<ResearchAtlasSyncStatus>('/atlas/settings'),
  syncSource: () => post<{ imported: number; scanned: number; last_error: string | null }>('/atlas/sync/sources'),
  listProjectPapers: (projectId: string) =>
    get<{ project_id: string; papers: ResearchAtlasProjectPaper[] }>(`/atlas/projects/${encodeURIComponent(projectId)}/papers`),
  addProjectPaper: (projectId: string, input: { paper_id: string; status?: ResearchAtlasProjectPaper['status'] }) =>
    post<{ project_paper: ResearchAtlasProjectPaper }>(`/atlas/projects/${encodeURIComponent(projectId)}/papers`, input),
  updateProjectPaper: (projectId: string, paperId: string, input: Partial<Pick<ResearchAtlasProjectPaper, 'status' | 'read_status' | 'rating' | 'tags' | 'note' | 'pinned'>>) =>
    patch<{ project_paper: ResearchAtlasProjectPaper }>(`/atlas/projects/${encodeURIComponent(projectId)}/papers/${encodeURIComponent(paperId)}`, input),
  removeProjectPaper: (projectId: string, paperId: string) =>
    del<{ deleted: boolean }>(`/atlas/projects/${encodeURIComponent(projectId)}/papers/${encodeURIComponent(paperId)}`),
  getPluginSettings: async () => {
    const item = await pluginsApi.get('research_atlas') as { effective?: { settings?: Record<string, unknown> } }
    return item.effective?.settings ?? {}
  },
  patchPluginSettings: (settings: Record<string, unknown>) =>
    pluginsApi.patchSettings('research_atlas', settings),
}
