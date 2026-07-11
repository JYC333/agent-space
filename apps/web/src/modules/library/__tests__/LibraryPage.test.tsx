import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import LibraryModule from '../LibraryModule'
import { sourcesApi } from '../../../api/client'
import type { ExtractionJob, SourceConnection, SourceItem } from '../../../types/api'

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

vi.mock('../../../contexts/SpaceContext', () => ({
  useSpace: () => ({ activeSpaceId: 'space-1', activeSpaceName: 'Space One' }),
}))

vi.mock('../../../core/spaceNav', () => ({
  SpaceLink: ({ to, children, ...props }: { to: string; children: ReactNode }) => (
    <a href={to} {...props}>{children}</a>
  ),
}))

vi.mock('../../../api/client', () => ({
  sourcesApi: {
    connections: vi.fn(),
    items: vi.fn(),
    briefings: vi.fn(),
    itemAction: vi.fn(),
    jobs: vi.fn(),
    runJob: vi.fn(),
  },
}))

function page<T>(items: T[], limit = 20) {
  return { items, total: items.length, limit, offset: 0 }
}

function connection(): SourceConnection {
  return {
    id: 'conn-1',
    space_id: 'space-1',
    connector_id: 'connector-1',
    owner_user_id: 'user-1',
    credential_id: null,
    visibility: 'space_shared',
    access_level: 'full',
    name: 'arXiv: 3dgs',
    endpoint_url: 'https://export.arxiv.org/api/query',
    status: 'active',
    fetch_frequency: 'daily',
    capture_policy: 'extract_text',
    trust_level: 'normal',
    topic_hints_json: null,
    consent_json: {},
    policy_json: {},
    config_json: {},
    last_checked_at: null,
    next_check_at: null,
    created_at: '2026-07-01T00:00:00.000Z',
    updated_at: '2026-07-01T00:00:00.000Z',
  }
}

function sourceItem(overrides: Partial<SourceItem> = {}): SourceItem {
  return {
    id: 'item-1',
    space_id: 'space-1',
    connection_id: 'conn-1',
    item_type: 'feed_entry',
    source_object_type: null,
    source_object_id: null,
    created_by_user_id: null,
    title: 'Gaussian Splatting Paper',
    source_uri: 'https://arxiv.org/abs/2607.00001',
    canonical_uri: 'https://arxiv.org/abs/2607.00001',
    source_domain: 'arxiv.org',
    source_external_id: '2607.00001',
    author: 'Researcher',
    occurred_at: null,
    first_seen_at: '2026-07-07T00:00:00.000Z',
    last_seen_at: '2026-07-07T00:00:00.000Z',
    content_hash: null,
    excerpt: 'A new paper summary.',
    library_status: 'new',
    read_status: 'unread',
    content_state: 'excerpt_saved',
    retention_policy: 'summary_only',
    relevance_score: null,
    novelty_score: null,
    raw_artifact_id: null,
    extracted_artifact_id: null,
    summary_artifact_id: null,
    search_index_ref: null,
    embedding_index_ref: null,
    metadata_json: {},
    created_at: '2026-07-07T00:00:00.000Z',
    updated_at: '2026-07-07T00:00:00.000Z',
    ...overrides,
  }
}

function extractionJob(overrides: Partial<ExtractionJob> = {}): ExtractionJob {
  return {
    id: 'extract-job-1',
    space_id: 'space-1',
    connection_id: 'conn-1',
    source_item_id: 'item-1',
    source_snapshot_id: null,
    source_object_type: null,
    source_object_id: null,
    job_type: 'extract_text',
    status: 'pending',
    started_at: null,
    completed_at: null,
    items_seen: null,
    items_created: null,
    items_updated: null,
    error_code: null,
    error_message: null,
    metadata_json: null,
    created_at: '2026-07-07T00:00:00.000Z',
    ...overrides,
  }
}

function renderLibrary(path = '/library/items') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/library/*" element={<LibraryModule />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('LibraryPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(sourcesApi.connections).mockResolvedValue(page([connection()], 100))
    vi.mocked(sourcesApi.items).mockResolvedValue(page([sourceItem()], 30))
    vi.mocked(sourcesApi.briefings).mockResolvedValue({ items: [], total: 0, limit: 10, offset: 0 })
  })

  it('defaults the Library shell to the all items route', async () => {
    renderLibrary('/library')

    expect(await screen.findByText('Gaussian Splatting Paper')).toBeInTheDocument()
    expect(sourcesApi.items).toHaveBeenCalledWith(expect.objectContaining({ limit: 30, offset: 0 }))
    expect(sourcesApi.briefings).not.toHaveBeenCalled()
  })

  it('renders source items as the primary reading stream', async () => {
    renderLibrary('/library/items')

    expect(await screen.findByText('Gaussian Splatting Paper')).toBeInTheDocument()
    expect(screen.getByText('A new paper summary.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Gaussian Splatting Paper' })).toHaveAttribute('href', '/library/items/item-1')
    expect(sourcesApi.items).toHaveBeenCalledWith(expect.objectContaining({ limit: 30, offset: 0 }))
    expect(sourcesApi.briefings).not.toHaveBeenCalled()
  })

  it('uses item type routes as soft library-type filters', async () => {
    renderLibrary('/library/items/pdfs')

    expect(await screen.findByRole('heading', { name: 'PDFs' })).toBeInTheDocument()
    await waitFor(() => {
      expect(sourcesApi.items).toHaveBeenCalledWith(expect.objectContaining({
        library_type: 'pdf',
        limit: 30,
        offset: 0,
      }))
    })
    expect(sourcesApi.briefings).not.toHaveBeenCalled()
  })

  it('uses the podcasts route as the podcast library-type filter', async () => {
    renderLibrary('/library/items/podcasts')

    expect(await screen.findByRole('heading', { name: 'Podcasts' })).toBeInTheDocument()
    await waitFor(() => {
      expect(sourcesApi.items).toHaveBeenCalledWith(expect.objectContaining({
        library_type: 'podcast',
        limit: 30,
        offset: 0,
      }))
    })
  })

  it('renders the digest stream with decision counts and a link into the day detail', async () => {
    vi.mocked(sourcesApi.briefings).mockResolvedValue({
      items: [
        {
          source_connection_id: 'conn-1',
          connection_name: 'arXiv: 3dgs',
          project_id: null,
          date: '2026-07-07',
          run_ids: ['run-1'],
          run_count: 1,
          item_decision_counts: { relevant: 1, maybe: 2, not_relevant: 2 },
          digest_artifact_id: 'artifact-1',
          digest_preview: 'Screened 5 new items from arXiv.',
          latest_run_created_at: '2026-07-07T02:31:31.179Z',
        },
      ],
      total: 1,
      limit: 10,
      offset: 0,
    })

    renderLibrary('/library/digests')

    expect(await screen.findByText('arXiv: 3dgs')).toBeInTheDocument()
    expect(screen.getByText('Screened 5 new items from arXiv.')).toBeInTheDocument()
    expect(screen.getByText('1 relevant')).toBeInTheDocument()
    expect(screen.getByText('2 maybe')).toBeInTheDocument()
    expect(screen.getByText('2 not relevant')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /arXiv: 3dgs/ })).toHaveAttribute('href', '/library/digests/conn-1/2026-07-07')
    expect(sourcesApi.items).not.toHaveBeenCalled()
  })

  it('runs text extraction from the source item reading stream', async () => {
    vi.mocked(sourcesApi.itemAction).mockResolvedValue(sourceItem({
      content_state: 'content_queued',
      retention_policy: 'full_text',
    }))
    vi.mocked(sourcesApi.jobs).mockResolvedValue(page([extractionJob()], 1))
    vi.mocked(sourcesApi.runJob).mockResolvedValue(extractionJob({ status: 'succeeded' }))

    renderLibrary('/library/items')

    fireEvent.click(await screen.findByRole('button', { name: /extract text gaussian splatting paper/i }))

    await waitFor(() => {
      expect(sourcesApi.itemAction).toHaveBeenCalledWith('item-1', 'queue_content')
      expect(sourcesApi.jobs).toHaveBeenCalledWith({
        source_item_id: 'item-1',
        job_type: 'extract_text',
        status: 'pending',
        limit: 1,
      })
      expect(sourcesApi.runJob).toHaveBeenCalledWith('extract-job-1')
      expect(screen.getByText('succeeded')).toBeInTheDocument()
    })
  })

  it('allows content-saved items to be re-extracted from Library', async () => {
    vi.mocked(sourcesApi.items).mockResolvedValue(page([sourceItem({
      content_state: 'content_saved',
      retention_policy: 'full_text',
      extracted_artifact_id: 'artifact-1',
    })], 30))
    vi.mocked(sourcesApi.itemAction).mockResolvedValue(sourceItem({
      content_state: 'content_queued',
      retention_policy: 'full_text',
    }))
    vi.mocked(sourcesApi.jobs).mockResolvedValue(page([extractionJob()], 1))
    vi.mocked(sourcesApi.runJob).mockResolvedValue(extractionJob({ status: 'succeeded' }))

    renderLibrary('/library/items')

    fireEvent.click(await screen.findByRole('button', { name: /re-extract gaussian splatting paper/i }))

    await waitFor(() => {
      expect(sourcesApi.itemAction).toHaveBeenCalledWith('item-1', 'queue_content')
      expect(sourcesApi.runJob).toHaveBeenCalledWith('extract-job-1')
    })
  })

  it('shows an empty state when no library items exist yet', async () => {
    vi.mocked(sourcesApi.items).mockResolvedValue({ items: [], total: 0, limit: 30, offset: 0 })
    renderLibrary('/library/items')
    expect(await screen.findByText('No library items')).toBeInTheDocument()
  })

  it('shows an empty state when no digests exist yet', async () => {
    vi.mocked(sourcesApi.briefings).mockResolvedValue({ items: [], total: 0, limit: 10, offset: 0 })
    renderLibrary('/library/digests')
    expect(await screen.findByText('No digests')).toBeInTheDocument()
    expect(sourcesApi.items).not.toHaveBeenCalled()
  })
})
