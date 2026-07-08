import { describe, expect, it } from 'vitest'
import { arxivPostProcessingPresetConfig } from '../sourcePresets/academic/arxivPostProcessing'

describe('arxivPostProcessingPresetConfig', () => {
  it('does not set a screening objective for non-screening presets', () => {
    const config = arxivPostProcessingPresetConfig({
      enabled: true,
      preset: 'batch_digest',
      createProposals: false,
      mode: 'search',
      categories: [],
      searchQuery: 'cat:cs.AI',
    })
    expect(config.screeningObjective).toBeUndefined()
    expect(config.outputInstructions).toContain('research digest')
  })

  it('prefers the user-entered screening objective when provided', () => {
    const config = arxivPostProcessingPresetConfig({
      enabled: true,
      preset: 'screen_relevant_papers',
      createProposals: false,
      mode: 'search',
      categories: [],
      searchQuery: 'cat:cs.AI',
      screeningObjective: '  Papers on agent memory  ',
    })
    expect(config.screeningObjective).toBe('Papers on agent memory')
  })

  it('derives a screening objective from the search query when none is provided', () => {
    const config = arxivPostProcessingPresetConfig({
      enabled: true,
      preset: 'screen_relevant_papers',
      createProposals: false,
      mode: 'search',
      categories: [],
      searchQuery: 'cat:cs.AI AND all:"agent memory"',
    })
    expect(config.screeningObjective).toContain('cat:cs.AI AND all:"agent memory"')
    expect(config.summaryGoal).toContain('Screen newly captured arXiv papers')
    expect(config.outputInstructions).toContain('Must read')
    expect(config.processingStrategy).toBe('screen_then_digest')
    expect(config.contentSource).toBe('prefer_extracted_text_for_candidates')
    expect(config.candidatePrefilter).toEqual({
      enabled: true,
      mode: 'hybrid',
      max_candidates: 20,
    })
    expect(config.deepAnalysis).toEqual({
      enabled: false,
      trigger_relevance: ['relevant'],
      min_confidence: 0.7,
      max_candidates_per_run: 5,
      content_source: 'prefer_extracted_text',
      output: 'deep_report',
    })
  })

  it('derives a screening objective from selected categories in category mode', () => {
    const config = arxivPostProcessingPresetConfig({
      enabled: true,
      preset: 'screen_relevant_papers',
      createProposals: false,
      mode: 'recent_by_category',
      categories: ['cs.AI', 'cs.CL'],
      searchQuery: '',
    })
    expect(config.screeningObjective).toContain('cs.AI, cs.CL')
  })

  it('enables optional deep analysis only when explicitly requested', () => {
    const config = arxivPostProcessingPresetConfig({
      enabled: true,
      preset: 'screen_relevant_papers',
      createProposals: false,
      mode: 'search',
      categories: [],
      searchQuery: 'cat:cs.AI',
      deepAnalysis: true,
    })
    expect(config.deepAnalysis).toEqual({
      enabled: true,
      trigger_relevance: ['relevant'],
      min_confidence: 0.7,
      max_candidates_per_run: 5,
      content_source: 'prefer_extracted_text',
      output: 'deep_report',
    })
  })
})
