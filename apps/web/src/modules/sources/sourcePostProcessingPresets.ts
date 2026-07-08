import type {
  SourceConnection,
  SourcePostProcessingCandidatePrefilterConfig,
  SourcePostProcessingContentSource,
  SourcePostProcessingDeepAnalysisConfig,
  SourcePostProcessingRetrievalDomain,
  SourcePostProcessingRuleCreate,
  SourcePostProcessingStrategy,
} from '../../types/api'

export type SourcePostProcessingPreset =
  | 'batch_digest'
  | 'per_item_summary'
  | 'extract_evidence'
  | 'screen_relevant_papers'
export type SourcePostProcessingContentProfile = 'generic' | 'arxiv_new_papers'

export const SOURCE_POST_PROCESSING_PRESET_OPTIONS: Array<{ value: SourcePostProcessingPreset; label: string }> = [
  { value: 'batch_digest', label: 'Digest new items' },
  { value: 'per_item_summary', label: 'Per-item summaries' },
  { value: 'extract_evidence', label: 'Extract evidence' },
  { value: 'screen_relevant_papers', label: 'Screen for relevance' },
]

export interface SourcePostProcessingPresetConfig {
  enabled: boolean
  preset: SourcePostProcessingPreset
  createProposals: boolean
  contentProfile?: SourcePostProcessingContentProfile
  processingStrategy?: SourcePostProcessingStrategy
  contentSource?: SourcePostProcessingContentSource
  maxBatchesPerEvent?: number
  candidatePrefilter?: Partial<SourcePostProcessingCandidatePrefilterConfig>
  deepAnalysis?: Partial<SourcePostProcessingDeepAnalysisConfig>
  summaryGoal?: string
  outputInstructions?: string
  screeningObjective?: string
}

const DEFAULT_ITEM_LIMIT = 10
const DEFAULT_RETRIEVAL_CONTEXT = {
  enabled: false,
  domains: ['project'] as SourcePostProcessingRetrievalDomain[],
  max_results_per_domain: 6,
  mode: 'hybrid' as const,
}

export function sourcePostProcessingRuleForConnection(
  connection: SourceConnection,
  config: SourcePostProcessingPresetConfig,
): SourcePostProcessingRuleCreate | null {
  if (!config.enabled) return null
  const isScreening = config.preset === 'screen_relevant_papers'
  const summaryGoal = config.summaryGoal?.trim()
  const outputInstructions = config.outputInstructions?.trim()
  const screeningObjective = config.screeningObjective?.trim() || `Screen new items from ${connection.name} for relevance to this source stream.`
  return {
    name: `${connection.name} post-processing`,
    trigger_type: 'items_materialized',
    trigger_config_json: {
      min_new_items: 1,
      cooldown_seconds: 900,
      skip_when_no_new_items: true,
    },
    input_config_json: {
      window: 'new_since_last_success',
      item_limit: DEFAULT_ITEM_LIMIT,
      max_batches_per_event: config.maxBatchesPerEvent ?? 10,
      processing_strategy: config.processingStrategy ?? (isScreening ? 'screen_then_digest' : 'batch_digest'),
      content_source: config.contentSource ?? 'excerpt_only',
      include_excerpts: true,
      include_evidence: true,
      ...(config.contentProfile ? { content_profile: config.contentProfile } : {}),
      ...(summaryGoal ? { summary_goal: summaryGoal } : {}),
      ...(outputInstructions ? { output_instructions: outputInstructions } : {}),
      retrieval_context: DEFAULT_RETRIEVAL_CONTEXT,
      candidate_prefilter: {
        enabled: config.candidatePrefilter?.enabled ?? false,
        mode: config.candidatePrefilter?.mode ?? 'hybrid',
        max_candidates: config.candidatePrefilter?.max_candidates ?? 20,
        ...(config.candidatePrefilter?.min_score !== undefined ? { min_score: config.candidatePrefilter.min_score } : {}),
      },
      deep_analysis: {
        enabled: config.deepAnalysis?.enabled ?? false,
        trigger_relevance: config.deepAnalysis?.trigger_relevance ?? ['relevant'],
        min_confidence: config.deepAnalysis?.min_confidence ?? 0.7,
        max_candidates_per_run: config.deepAnalysis?.max_candidates_per_run ?? 5,
        content_source: config.deepAnalysis?.content_source ?? 'prefer_extracted_text',
        output: config.deepAnalysis?.output ?? 'deep_report',
      },
      ...(isScreening
        ? {
            relevance_profile: {
              enabled: true,
              objective: screeningObjective,
              include_criteria: [],
              exclude_criteria: [],
              must_have: [],
              nice_to_have: [],
            },
          }
        : {}),
    },
    actions_json: {
      batch_digest: config.preset === 'batch_digest' || isScreening,
      per_item_summary: config.preset === 'per_item_summary',
      extract_evidence: config.preset === 'extract_evidence',
      create_proposals: config.createProposals,
      mark_items: isScreening,
    },
  }
}
