import { describe, expect, it } from 'vitest'
import { sourcePostProcessingRuleForConnection } from '../sourcePostProcessingPresets'
import type { SourceConnection } from '../../../types/api'

function makeConnection(overrides: Partial<SourceConnection> = {}): SourceConnection {
  return {
    id: 'conn-1',
    space_id: 'space-1',
    connector_id: 'connector-1',
    owner_user_id: 'user-1',
    credential_id: null,
    visibility: 'space_shared',
    access_level: 'full',
    name: 'arXiv: cs.AI',
    endpoint_url: null,
    status: 'active',
    fetch_frequency: 'daily',
    capture_policy: 'extract_text',
    trust_level: 'trusted',
    topic_hints_json: null,
    consent_json: {},
    policy_json: {},
    config_json: {},
    last_checked_at: null,
    next_check_at: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  }
}

describe('sourcePostProcessingRuleForConnection', () => {
  it('returns null when disabled', () => {
    const rule = sourcePostProcessingRuleForConnection(makeConnection(), {
      enabled: false,
      preset: 'batch_digest',
      createProposals: false,
    })
    expect(rule).toBeNull()
  })

  it('builds a plain digest rule without screening fields', () => {
    const rule = sourcePostProcessingRuleForConnection(makeConnection(), {
      enabled: true,
      preset: 'batch_digest',
      createProposals: false,
    })
    expect(rule?.actions_json).toEqual({
      batch_digest: true,
      per_item_summary: false,
      extract_evidence: false,
      create_proposals: false,
      mark_items: false,
    })
    expect(rule?.input_config_json?.item_limit).toBe(10)
    expect(rule?.input_config_json?.max_batches_per_event).toBe(10)
    expect(rule?.input_config_json?.processing_strategy).toBe('batch_digest')
    expect(rule?.input_config_json?.content_source).toBe('excerpt_only')
    expect(rule?.input_config_json?.relevance_profile).toBeUndefined()
    expect(rule?.input_config_json?.retrieval_context).toEqual({
      enabled: false,
      domains: ['project'],
      max_results_per_domain: 6,
      mode: 'hybrid',
    })
    expect(rule?.input_config_json?.candidate_prefilter).toEqual({
      enabled: false,
      mode: 'hybrid',
      max_candidates: 20,
    })
    expect(rule?.input_config_json?.deep_analysis).toEqual({
      enabled: false,
      trigger_relevance: ['relevant'],
      min_confidence: 0.7,
      max_candidates_per_run: 5,
      content_source: 'prefer_extracted_text',
      output: 'deep_report',
    })
  })

  it('builds a screening rule with mark_items, retrieval context, prefilter, and relevance profile', () => {
    const rule = sourcePostProcessingRuleForConnection(makeConnection(), {
      enabled: true,
      preset: 'screen_relevant_papers',
      createProposals: false,
      contentProfile: 'arxiv_new_papers',
      screeningObjective: 'Screen new arXiv papers on agent memory',
      candidatePrefilter: {
        enabled: true,
        mode: 'hybrid',
        max_candidates: 20,
      },
      deepAnalysis: {
        enabled: true,
        trigger_relevance: ['relevant', 'maybe'],
        min_confidence: 0.65,
        max_candidates_per_run: 4,
        content_source: 'require_extracted_text',
        output: 'per_item_deep_summary',
      },
    })
    expect(rule?.actions_json).toEqual({
      batch_digest: true,
      per_item_summary: false,
      extract_evidence: false,
      create_proposals: false,
      mark_items: true,
    })
    expect(rule?.input_config_json?.item_limit).toBe(10)
    expect(rule?.input_config_json?.max_batches_per_event).toBe(10)
    expect(rule?.input_config_json?.processing_strategy).toBe('screen_then_digest')
    expect(rule?.input_config_json?.content_source).toBe('excerpt_only')
    expect(rule?.input_config_json?.content_profile).toBe('arxiv_new_papers')
    expect(rule?.input_config_json?.retrieval_context).toEqual({
      enabled: false,
      domains: ['project'],
      max_results_per_domain: 6,
      mode: 'hybrid',
    })
    expect(rule?.input_config_json?.candidate_prefilter).toEqual({
      enabled: true,
      mode: 'hybrid',
      max_candidates: 20,
    })
    expect(rule?.input_config_json?.deep_analysis).toEqual({
      enabled: true,
      trigger_relevance: ['relevant', 'maybe'],
      min_confidence: 0.65,
      max_candidates_per_run: 4,
      content_source: 'require_extracted_text',
      output: 'per_item_deep_summary',
    })
    expect(rule?.input_config_json?.relevance_profile).toEqual({
      enabled: true,
      objective: 'Screen new arXiv papers on agent memory',
      include_criteria: [],
      exclude_criteria: [],
      must_have: [],
      nice_to_have: [],
    })
  })

  it('derives a stream objective when no screening objective is provided', () => {
    const rule = sourcePostProcessingRuleForConnection(makeConnection(), {
      enabled: true,
      preset: 'screen_relevant_papers',
      createProposals: false,
    })
    expect(rule?.input_config_json?.relevance_profile).toEqual({
      enabled: true,
      objective: 'Screen new items from arXiv: cs.AI for relevance to this source stream.',
      include_criteria: [],
      exclude_criteria: [],
      must_have: [],
      nice_to_have: [],
    })
  })
})
