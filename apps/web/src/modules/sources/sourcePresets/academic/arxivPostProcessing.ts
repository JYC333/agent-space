import type { ArxivPresetMode } from '../../../../types/api'
import type {
  SourcePostProcessingPreset,
  SourcePostProcessingPresetConfig,
} from '../../sourcePostProcessingPresets'

const ARXIV_OUTPUT_INSTRUCTIONS =
  'Create a compact research digest with notable papers, shared themes, and concrete follow-up candidates. Include arXiv ids and categories when available.'

const ARXIV_SCREENING_OUTPUT_INSTRUCTIONS =
  'First classify every paper as relevant, maybe, or not relevant. Then write a compact reading digest for relevant and maybe papers only. Use sections: Must read, Maybe, Ignored count. For must-read papers include title, authors, arXiv id, categories, research question, method, contribution, why relevant, matched context refs, and next action. Do not write long summaries for ignored papers.'

export interface ArxivPostProcessingPresetInput {
  enabled: boolean
  preset: SourcePostProcessingPreset
  createProposals: boolean
  mode: ArxivPresetMode
  categories: string[]
  searchQuery: string
  screeningObjective?: string
  deepAnalysis?: boolean
}

export function arxivPostProcessingPresetConfig(input: ArxivPostProcessingPresetInput): SourcePostProcessingPresetConfig {
  const isScreening = input.preset === 'screen_relevant_papers'
  return {
    enabled: input.enabled,
    preset: input.preset,
    createProposals: input.createProposals,
    contentProfile: 'arxiv_new_papers',
    processingStrategy: isScreening ? 'screen_then_digest' : 'batch_digest',
    contentSource: isScreening ? 'prefer_extracted_text_for_candidates' : 'excerpt_only',
    maxBatchesPerEvent: 10,
    candidatePrefilter: {
      enabled: isScreening,
      mode: 'hybrid',
      max_candidates: 20,
    },
    deepAnalysis: {
      enabled: isScreening && input.deepAnalysis === true,
      trigger_relevance: ['relevant'],
      min_confidence: 0.7,
      max_candidates_per_run: 5,
      content_source: 'prefer_extracted_text',
      output: 'deep_report',
    },
    summaryGoal: isScreening ? arxivScreeningGoal(input) : arxivPostProcessingGoal(input),
    outputInstructions: isScreening ? ARXIV_SCREENING_OUTPUT_INSTRUCTIONS : ARXIV_OUTPUT_INSTRUCTIONS,
    ...(isScreening ? { screeningObjective: arxivScreeningObjective(input) } : {}),
  }
}

function arxivPostProcessingGoal(input: Pick<ArxivPostProcessingPresetInput, 'mode' | 'categories' | 'searchQuery'>): string {
  if (input.mode === 'recent_by_category') {
    const categories = input.categories.length > 0 ? input.categories.join(', ') : 'the selected categories'
    return `Summarize newly captured arXiv papers for categories: ${categories}. Highlight notable papers, topic clusters, and follow-up-worthy research signals.`
  }
  const query = input.searchQuery.trim() || 'the configured query'
  return `Summarize newly captured arXiv papers matching query: ${query}. Highlight notable papers, topic clusters, and follow-up-worthy research signals.`
}

function arxivScreeningObjective(
  input: Pick<ArxivPostProcessingPresetInput, 'mode' | 'categories' | 'searchQuery' | 'screeningObjective'>,
): string {
  const objective = input.screeningObjective?.trim()
  if (objective) return objective
  if (input.mode === 'recent_by_category') {
    const categories = input.categories.length > 0 ? input.categories.join(', ') : 'the selected categories'
    return `Screen new arXiv papers in categories: ${categories} for papers worth reading against this stream.`
  }
  const query = input.searchQuery.trim() || 'the configured query'
  return `Screen new arXiv papers matching query: ${query} for papers worth reading against this stream.`
}

function arxivScreeningGoal(input: Pick<ArxivPostProcessingPresetInput, 'mode' | 'categories' | 'searchQuery'>): string {
  if (input.mode === 'recent_by_category') {
    const categories = input.categories.length > 0 ? input.categories.join(', ') : 'the selected categories'
    return `Screen newly captured arXiv papers for categories: ${categories}. Mark relevant papers, identify maybe-useful papers, and produce a compact reading digest.`
  }
  const query = input.searchQuery.trim() || 'the configured query'
  return `Screen newly captured arXiv papers matching query: ${query}. Mark relevant papers, identify maybe-useful papers, and produce a compact reading digest.`
}
