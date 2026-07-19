import type {
  ProjectResearchInitialIntakeInput,
  ProjectResearchQuestionRefinement,
  ProjectResearchWorkflow,
} from '../../types/api'

export interface ResearchSetupDraft {
  research_question: string
  source_channel_ids: string[]
  history_mode: 'bounded_range' | 'all_available'
  from: string
  to: string
  max_items: string
  monitoring_field: 'submittedDate' | 'lastUpdatedDate'
  report_depth: 'quick' | 'full'
  question_refine_skipped: boolean
  search_strategy_id?: string
  /** Latest refinement assessment; persisted with the server-side draft so it survives devices and sessions. */
  question_refinement?: ProjectResearchQuestionRefinement | null
  execution: {
    model_provider_id: string
    model_name: string
  }
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function stringValue(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? [...new Set(value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0).map(item => item.trim()))]
    : []
}

export function researchSetupDraftFromWorkflow(
  workflow: ProjectResearchWorkflow | null,
  researchQuestion: string,
  defaultChannelIds: string[] = [],
  corpusItemCount = 0,
): ResearchSetupDraft {
  const state = objectValue(workflow?.state_json)
  const initialIntake = objectValue(state.initial_intake)
  const execution = objectValue(state.execution)
  const persistedChannelIds = stringArray(state.source_channel_ids ?? state.channel_ids)

  return {
    research_question: stringValue(state.research_question) ?? researchQuestion,
    source_channel_ids: persistedChannelIds.length > 0 ? persistedChannelIds : stringArray(defaultChannelIds),
    history_mode: initialIntake.history_mode === 'all_available' ? 'all_available' : 'bounded_range',
    from: stringValue(initialIntake.from)?.slice(0, 10) ?? '',
    to: stringValue(initialIntake.to)?.slice(0, 10) ?? '',
    max_items: initialIntake.max_items === undefined || initialIntake.max_items === null
      ? '10000'
      : String(initialIntake.max_items),
    monitoring_field: initialIntake.monitoring_field === 'lastUpdatedDate' ? 'lastUpdatedDate' : 'submittedDate',
    report_depth: initialIntake.report_depth === 'quick' ? 'quick' : initialIntake.report_depth === 'full' ? 'full' : corpusItemCount < 15 ? 'quick' : 'full',
    question_refine_skipped: state.question_refine_skipped !== false,
    search_strategy_id: stringValue(state.search_strategy_id) ?? '',
    question_refinement: state.question_refinement && typeof state.question_refinement === 'object' && !Array.isArray(state.question_refinement)
      ? state.question_refinement as ProjectResearchQuestionRefinement
      : null,
    execution: {
      model_provider_id: stringValue(execution.model_provider_id) ?? '',
      model_name: stringValue(execution.model_name) ?? '',
    },
  }
}

/**
 * The refine conversation is client-held by design (the server endpoint is
 * stateless), so closing the setup dialog must not lose it. The in-progress
 * dialog state is kept per project in localStorage and restored on reopen as
 * long as the server-side draft it was based on has not changed underneath.
 */
export interface ResearchClarifyingAnswer {
  selected: string[]
  other: string
}

export interface ResearchSetupSession {
  base_fingerprint: string
  draft: ResearchSetupDraft
  refinement: ProjectResearchQuestionRefinement | null
  refinement_history: Array<{ role: 'user' | 'assistant'; content: string }>
  clarifying_answers: Record<number, ResearchClarifyingAnswer>
  step?: number
}

function sessionKey(projectId: string): string {
  return `agent-space:research-setup-session:${projectId}`
}

export function loadResearchSetupSession(projectId: string): ResearchSetupSession | null {
  try {
    const raw = window.localStorage.getItem(sessionKey(projectId))
    if (!raw) return null
    const value = objectValue(JSON.parse(raw))
    const draft = objectValue(value.draft)
    if (typeof value.base_fingerprint !== 'string' || typeof draft.research_question !== 'string') return null
    return value as unknown as ResearchSetupSession
  } catch {
    return null
  }
}

export function saveResearchSetupSession(projectId: string, session: ResearchSetupSession): void {
  try {
    window.localStorage.setItem(sessionKey(projectId), JSON.stringify(session))
  } catch {
    // Storage may be unavailable (private mode, quota); the dialog still works, it just will not restore.
  }
}

export function clearResearchSetupSession(projectId: string): void {
  try {
    window.localStorage.removeItem(sessionKey(projectId))
  } catch {
    // Ignore storage failures on cleanup.
  }
}

export function serializeResearchSetupDraft(draft: ResearchSetupDraft): ProjectResearchInitialIntakeInput {
  return {
    research_question: draft.research_question.trim(),
    source_channel_ids: [...new Set(draft.source_channel_ids)],
    history_mode: draft.history_mode,
    ...(draft.history_mode === 'bounded_range' ? { from: draft.from, to: draft.to } : {}),
    max_items: Math.max(1, Math.min(10000, Number(draft.max_items) || 10000)),
    monitoring_field: draft.monitoring_field,
    report_depth: draft.report_depth,
    question_refine_skipped: draft.question_refine_skipped,
    ...(draft.search_strategy_id ? { search_strategy_id: draft.search_strategy_id } : {}),
    question_refinement: draft.question_refinement ?? null,
    execution: {
      ...(draft.execution.model_provider_id ? { model_provider_id: draft.execution.model_provider_id } : {}),
      ...(draft.execution.model_name.trim() ? { model_name: draft.execution.model_name.trim() } : {}),
    },
  }
}
