import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import LibraryDetailPage from '../LibraryDetailPage'
import { sourcesApi } from '../../../api/client'
import type { SourcePostProcessingBriefingDetail } from '../../../types/api'

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

vi.mock('../../../core/spaceNav', () => ({
  SpaceLink: ({ to, children, ...props }: { to: string; children: ReactNode }) => (
    <a href={to} {...props}>{children}</a>
  ),
}))

vi.mock('../../../api/client', () => ({
  sourcesApi: {
    briefing: vi.fn(),
  },
}))

function renderAt(connectionId: string, date: string) {
  return render(
    <MemoryRouter initialEntries={[`/library/digests/${connectionId}/${date}`]}>
      <Routes>
        <Route path="/library/digests/:connectionId/:date" element={<LibraryDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

type BriefingDecision = SourcePostProcessingBriefingDetail['item_decisions'][number]

function makeDecision(overrides: Partial<BriefingDecision> & Pick<BriefingDecision, 'id' | 'source_item_id' | 'relevance'>): BriefingDecision {
  return {
    space_id: 'space-1',
    source_connection_id: 'conn-1',
    rule_id: 'rule-1',
    run_id: 'run-1',
    project_id: null,
    confidence: null,
    reason: null,
    matched_context_refs: [],
    review_status: 'pending',
    action_json: {},
    item: {
      title: overrides.source_item_id,
      source_uri: null,
      source_domain: null,
      author: null,
      library_status: 'new',
      read_status: 'unread',
      content_state: 'excerpt_saved',
    },
    rule_name: 'Screening',
    run_status: 'succeeded',
    run_created_at: '2026-07-07T02:31:31.179Z',
    created_at: '2026-07-07T02:31:31.179Z',
    updated_at: '2026-07-07T02:31:31.179Z',
    ...overrides,
  }
}

describe('LibraryDetailPage', () => {
  it('renders the digest markdown and item decisions grouped by relevance', async () => {
    vi.mocked(sourcesApi.briefing).mockResolvedValue({
      source_connection_id: 'conn-1',
      connection_name: 'arXiv: 3dgs',
      project_id: null,
      date: '2026-07-07',
      runs: [{ run_id: 'run-1', status: 'succeeded', created_at: '2026-07-07T02:31:31.179Z', summary: null }],
      digests: [{ run_id: 'run-1', artifact_id: 'artifact-1', title: 'arXiv: 3dgs digest', content: '# Digest\n\nScreened 5 items.\n' }],
      item_summaries: [
        { source_item_id: 'item-1', artifact_id: 'artifact-2', title: 'Summary: FastBridge', content: 'Concise per-item summary.' },
      ],
      item_decisions: [
        {
          id: 'decision-1',
          space_id: 'space-1',
          source_connection_id: 'conn-1',
          rule_id: 'rule-1',
          run_id: 'run-1',
          project_id: null,
          source_item_id: 'item-1',
          relevance: 'relevant',
          confidence: 0.9,
          reason: 'Strong match.',
          matched_context_refs: [],
          review_status: 'pending',
          action_json: {},
          item: {
            title: 'FastBridge',
            source_uri: 'https://arxiv.org/abs/1',
            source_domain: 'arxiv.org',
            author: null,
            library_status: 'new',
            read_status: 'unread',
            content_state: 'excerpt_saved',
          },
          rule_name: 'Screening',
          run_status: 'succeeded',
          run_created_at: '2026-07-07T02:31:31.179Z',
          created_at: '2026-07-07T02:31:31.179Z',
          updated_at: '2026-07-07T02:31:31.179Z',
        },
        {
          id: 'decision-2',
          space_id: 'space-1',
          source_connection_id: 'conn-1',
          rule_id: 'rule-1',
          run_id: 'run-1',
          project_id: null,
          source_item_id: 'item-2',
          relevance: 'maybe',
          confidence: 0.5,
          reason: 'Unclear match.',
          matched_context_refs: [],
          review_status: 'pending',
          action_json: {},
          item: {
            title: 'DL-SLAM',
            source_uri: null,
            source_domain: null,
            author: null,
            library_status: 'new',
            read_status: 'unread',
            content_state: 'excerpt_saved',
          },
          rule_name: 'Screening',
          run_status: 'succeeded',
          run_created_at: '2026-07-07T02:31:31.179Z',
          created_at: '2026-07-07T02:31:31.179Z',
          updated_at: '2026-07-07T02:31:31.179Z',
        },
      ],
    })

    renderAt('conn-1', '2026-07-07')

    expect(await screen.findByRole('heading', { name: 'Digest' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Library' })).toHaveAttribute('href', '/library/digests')
    expect(screen.getByText('arXiv: 3dgs')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'FastBridge' })).toHaveAttribute('href', '/library/digests/conn-1/2026-07-07/items/item-1')
    expect(screen.getByText('Strong match.')).toBeInTheDocument()
    expect(screen.getByText('Summary: FastBridge')).toBeInTheDocument()
    expect(screen.getByText('Concise per-item summary.')).toBeInTheDocument()
    // Reads into the day-scoped reader even without a source_uri — the reader
    // itself degrades gracefully when there is nothing to read.
    expect(screen.getByRole('link', { name: 'DL-SLAM' })).toHaveAttribute('href', '/library/digests/conn-1/2026-07-07/items/item-2')
  })

  it('shows an empty state for a 404', async () => {
    vi.mocked(sourcesApi.briefing).mockRejectedValue(new Error('404 Not Found'))

    renderAt('conn-1', '2026-07-07')

    expect(await screen.findByText('Digest not found')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Library' })).toHaveAttribute('href', '/library/digests')
  })

  it('deduplicates repeated item decisions in the same order used by reader next and previous links', async () => {
    vi.mocked(sourcesApi.briefing).mockResolvedValue({
      source_connection_id: 'conn-1',
      connection_name: 'arXiv: 3dgs',
      project_id: null,
      date: '2026-07-07',
      runs: [],
      digests: [],
      item_summaries: [],
      item_decisions: [
        makeDecision({
          id: 'decision-older',
          source_item_id: 'item-1',
          relevance: 'not_relevant',
          reason: 'Older not relevant decision.',
          item: {
            title: 'FastBridge',
            source_uri: null,
            source_domain: null,
            author: null,
            library_status: 'new',
            read_status: 'unread',
            content_state: 'excerpt_saved',
          },
        }),
        makeDecision({
          id: 'decision-current',
          source_item_id: 'item-1',
          relevance: 'relevant',
          reason: 'Current relevant decision.',
          item: {
            title: 'FastBridge',
            source_uri: null,
            source_domain: null,
            author: null,
            library_status: 'new',
            read_status: 'unread',
            content_state: 'excerpt_saved',
          },
        }),
        makeDecision({
          id: 'decision-2',
          source_item_id: 'item-2',
          relevance: 'maybe',
          reason: 'Maybe decision.',
          item: {
            title: 'DL-SLAM',
            source_uri: null,
            source_domain: null,
            author: null,
            library_status: 'new',
            read_status: 'unread',
            content_state: 'excerpt_saved',
          },
        }),
      ],
    })

    renderAt('conn-1', '2026-07-07')

    expect(await screen.findByText('Current relevant decision.')).toBeInTheDocument()
    expect(screen.queryByText('Older not relevant decision.')).not.toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: 'FastBridge' })).toHaveLength(1)
    expect(screen.getByRole('link', { name: 'DL-SLAM' })).toHaveAttribute('href', '/library/digests/conn-1/2026-07-07/items/item-2')
  })
})
