import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import type { Artifact } from '../../../types/api'
import { ArtifactInlineRenderer } from '../ArtifactRendererRegistry'

vi.mock('../../../core/spaceNav', () => ({
  SpaceLink: ({ to, children, ...props }: { to: string; children: ReactNode }) => (
    <a href={to} {...props}>{children}</a>
  ),
}))

function artifact(overrides: Partial<Artifact>): Artifact {
  return {
    id: 'artifact-1',
    space_id: 'space-1',
    run_id: null,
    proposal_id: null,
    artifact_type: 'research_brief.v1',
    title: 'Research artifact',
    mime_type: 'application/json',
    exportable: true,
    preview: false,
    storage_ref: null,
    storage_path: null,
    has_inline_content: true,
    content: '',
    created_at: '2026-06-20T00:00:00.000Z',
    updated_at: '2026-06-20T00:00:00.000Z',
    ...overrides,
  }
}

describe('ArtifactInlineRenderer', () => {
  it('renders structured research briefs', () => {
    render(
      <ArtifactInlineRenderer
        artifact={artifact({
          content: JSON.stringify({
            title: 'Storage strategy',
            summary: 'Use project-scoped evidence before broader synthesis.',
            findings: [
              { finding: 'Source metadata should be preserved.', confidence: 'high' },
            ],
            citations: [
              { title: 'Architecture note', url: 'https://example.com/arch' },
            ],
          }),
        })}
      />,
    )

    expect(screen.getByText('Storage strategy')).toBeInTheDocument()
    expect(screen.getByText('Source metadata should be preserved.')).toBeInTheDocument()
    expect(screen.getByText('Architecture note')).toBeInTheDocument()
  })

  it('renders source tables from JSON rows', () => {
    render(
      <ArtifactInlineRenderer
        artifact={artifact({
          artifact_type: 'research_source_table.v1',
          content: JSON.stringify({
            sources: [
              {
                title: 'Primary source',
                publisher: 'Example Org',
                date: '2026-06-20',
                relevance: 'core',
                summary: 'Contains the source claim.',
              },
            ],
          }),
        })}
      />,
    )

    expect(screen.getByText('Primary source')).toBeInTheDocument()
    expect(screen.getByText('Example Org')).toBeInTheDocument()
    expect(screen.getByText('Contains the source claim.')).toBeInTheDocument()
  })

  it('falls back to inline text for unstructured content', () => {
    render(
      <ArtifactInlineRenderer
        artifact={artifact({
          artifact_type: 'research_idea_candidates.v1',
          mime_type: 'text/plain',
          content: 'Plain candidate notes',
        })}
      />,
    )

    expect(screen.getByText('Plain candidate notes')).toBeInTheDocument()
  })

  it('renders retrieval eval reports without candidate content', () => {
    render(
      <ArtifactInlineRenderer
        artifact={artifact({
          artifact_type: 'retrieval_eval_report',
          content: JSON.stringify({
            report_label: 'Nightly retrieval eval',
            metrics: { recall: 1, mrr: 0.95, 'trend.low_coverage_rate_delta': 0.2 },
            counts: { cases: 2, misses: 0, 'trend.brief_sample_sufficient': 1 },
            diagnostic_codes: ['all_cases_passed'],
            cases: [
              {
                case_label: 'named-entity',
                mode: 'lexical',
                metrics: { recall: 1 },
                first_relevant_rank: 1,
                diagnostic_codes: ['top_ranked'],
              },
            ],
            rank_attribution: {
              evidence_kind_counts: { lexical_match: 2 },
              matched_field_counts: { title: 1 },
            },
          }),
        })}
      />,
    )

    expect(screen.getByText('Nightly retrieval eval')).toBeInTheDocument()
    expect(screen.getByText('named-entity')).toBeInTheDocument()
    expect(screen.getByText('all_cases_passed')).toBeInTheDocument()
    expect(screen.getByText('lexical_match')).toBeInTheDocument()
    expect(screen.getByText('Trend deltas')).toBeInTheDocument()
    expect(screen.getByText('trend.low_coverage_rate_delta')).toBeInTheDocument()
    expect(screen.getByText('Trend sample')).toBeInTheDocument()
  })

  it('renders retrieval brief artifacts', () => {
    render(
      <ArtifactInlineRenderer
        artifact={artifact({
          artifact_type: 'retrieval_brief',
          content: JSON.stringify({
            query: 'relation recall',
            surface: 'knowledge_brief',
            answer: 'Use the cited relation sources.',
            synthesized: true,
            citations: [
              { object_type: 'knowledge_item', object_id: 'ki-1', title: 'Relation source' },
            ],
            gap_analysis: {
              low_coverage: true,
              stale: [],
              thin: [{ title: 'Thin item', reason: 'short body' }],
              uncited_claims: [],
              contradictions: [],
              missing_topics: [],
            },
            item_refs: [
              { object_type: 'knowledge_item', title: 'Relation source', score: 0.9, matched_fields: ['relation_weight:supports'] },
            ],
            source_count: 1,
          }),
        })}
      />,
    )

    expect(screen.getByText('relation recall')).toBeInTheDocument()
    expect(screen.getByText('Use the cited relation sources.')).toBeInTheDocument()
    expect(screen.getAllByText('Relation source').length).toBeGreaterThan(0)
    expect(screen.getByText('Low coverage')).toBeInTheDocument()
  })

  it('renders retrieval maintenance reports', () => {
    render(
      <ArtifactInlineRenderer
        artifact={artifact({
          artifact_type: 'retrieval_maintenance_report',
          content: JSON.stringify({
            source: 'automation_knowledge_retrieval_maintenance',
            counts: { stale: 1, relation_suggestion: 1 },
            scanned: 12,
            truncated: false,
            findings: [
              {
                kind: 'relation_suggestion',
                reason: 'A supports B',
                objects: [
                  { object_type: 'knowledge_item', title: 'A' },
                  { object_type: 'knowledge_item', title: 'B' },
                ],
                proposed_action: { proposal_type: 'object_relation_create' },
              },
            ],
          }),
        })}
      />,
    )

    expect(screen.getByText('automation_knowledge_retrieval_maintenance')).toBeInTheDocument()
    expect(screen.getAllByText('relation_suggestion').length).toBeGreaterThan(0)
    expect(screen.getByText('A supports B')).toBeInTheDocument()
    expect(screen.getByText('object_relation_create')).toBeInTheDocument()
  })

  it('renders memory maintenance reports with the shared maintenance renderer', () => {
    render(
      <ArtifactInlineRenderer
        artifact={artifact({
          artifact_type: 'memory_maintenance_report',
          content: JSON.stringify({
            source: 'memory_maintenance',
            counts: { duplicate: 1 },
            scanned: 3,
            truncated: false,
            findings: [
              {
                kind: 'duplicate',
                reason: 'same title',
              },
            ],
          }),
        })}
      />,
    )

    expect(screen.getByText('memory_maintenance')).toBeInTheDocument()
    expect(screen.getAllByText('duplicate').length).toBeGreaterThan(0)
    expect(screen.getByText('same title')).toBeInTheDocument()
  })

  it('renders claim candidate packets', () => {
    render(
      <ArtifactInlineRenderer
        artifact={artifact({
          artifact_type: 'claim_candidate_packet',
          content: JSON.stringify({
            kind: 'claim_candidate_packet',
            review_scope: 'private',
            visibility: 'private',
            candidate_count: 2,
            access_safety: {
              canonical_write_performed: false,
            },
            source_artifacts: [
              {
                artifact_id: 'brief-1',
                artifact_type: 'retrieval_brief',
                title: 'Brief source',
              },
            ],
            candidates: [
              {
                kind: 'claim_candidate',
                title: 'Review uncited claim',
                reason: 'Needs source evidence.',
                confidence: 0.35,
                origin: { source_section: 'gap_analysis.uncited_claims' },
                markers: { needs_source: true },
                proposed_action: { proposal_type: 'claim_create' },
              },
              {
                kind: 'review_note',
                title: 'Review stale object',
                reason: 'Object may need refresh.',
                origin: { source_section: 'gap_analysis.stale' },
                markers: { stale: true, object_id: 'item-1' },
                proposed_action: null,
              },
            ],
          }),
        })}
      />,
    )

    expect(screen.getByText('Claim Candidate Packet')).toBeInTheDocument()
    expect(screen.getByText('canonical write: no')).toBeInTheDocument()
    expect(screen.getByText('Brief source')).toBeInTheDocument()
    expect(screen.getByText('claim_create')).toBeInTheDocument()
    expect(screen.getAllByText('review_note').length).toBeGreaterThan(0)
    expect(screen.getByText('Review stale object')).toBeInTheDocument()
  })

  it('renders relation discovery review-only candidates distinctly', () => {
    render(
      <ArtifactInlineRenderer
        artifact={artifact({
          artifact_type: 'relation_discovery_report',
          content: JSON.stringify({
            kind: 'relation_discovery_report',
            proposal_candidate_count: 1,
            review_only_candidate_count: 1,
            counts: {
              proposal_candidate: 1,
              review_only_candidate: 1,
              relation_review_candidate: 1,
              object_relation_candidate: 1,
            },
            sources_scanned: 2,
            links_extracted: 2,
            candidates: [
              {
                kind: 'object_relation_candidate',
                title: 'Relate Alpha to Beta',
                reason: 'Alpha links to Beta.',
                confidence_tier: 'high',
                proposed_action: { proposal_type: 'object_relation_create' },
              },
              {
                kind: 'relation_review_candidate',
                title: 'Review relation evidence',
                reason: 'Artifact text mentions Beta.',
                confidence_tier: 'medium',
                proposed_action: null,
              },
            ],
          }),
        })}
      />,
    )

    expect(screen.getByText('Relation Discovery Report')).toBeInTheDocument()
    expect(screen.getByText('1 proposal-ready')).toBeInTheDocument()
    expect(screen.getAllByText('1 review-only').length).toBeGreaterThan(0)
    expect(screen.getByText('object_relation_create')).toBeInTheDocument()
    expect(screen.getByText('Review-only evidence; accepting the packet will not generate a child proposal for this candidate.')).toBeInTheDocument()
  })

  it('renders retrieval explain reports', () => {
    render(
      <ArtifactInlineRenderer
        artifact={artifact({
          artifact_type: 'retrieval_explain_report',
          content: JSON.stringify({
            kind: 'retrieval_explain_report',
            mode: 'exact',
            target: {
              object_type: 'knowledge_item',
              object_id: 'item-1',
              title: 'Alpha',
              visible: true,
              returned: false,
            },
            match: {
              matched_fields: ['title'],
              evidence_kind: 'exact_title_match',
            },
            trace: {
              arms: { exact: 1 },
              dropped: 0,
              dropped_reasons: {},
              mode: 'exact',
            },
            diagnostic_codes: ['target_not_returned'],
            access_safety: {
              target_revalidated: true,
              content_included: false,
            },
          }),
        })}
      />,
    )

    expect(screen.getByText('Alpha')).toBeInTheDocument()
    expect(screen.getByText('missed')).toBeInTheDocument()
    expect(screen.getByText('Trace arms')).toBeInTheDocument()
    expect(screen.getByText('target_not_returned')).toBeInTheDocument()
    expect(screen.getByText('Access safety')).toBeInTheDocument()
  })

  it('renders post-processing summary artifacts as markdown through the shared reading core', async () => {
    render(
      <ArtifactInlineRenderer
        artifact={artifact({
          artifact_type: 'summary',
          title: 'arXiv digest',
          content: '# Digest\n\n- [Paper one](https://arxiv.org/abs/1)\n- Paper two\n',
        })}
      />,
    )

    expect(await screen.findByRole('heading', { name: 'Digest' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Paper one' })).toHaveAttribute('href', 'https://arxiv.org/abs/1')
    expect(screen.getByText('Paper two')).toBeInTheDocument()
    expect(document.querySelector('pre')).not.toBeInTheDocument()
  })

  it('falls back to an empty-state message for a summary artifact with no inline content', () => {
    render(
      <ArtifactInlineRenderer
        artifact={artifact({ artifact_type: 'summary', has_inline_content: false, content: '' })}
      />,
    )
    expect(screen.getByText('No inline preview. Use Export to download.')).toBeInTheDocument()
  })
})
