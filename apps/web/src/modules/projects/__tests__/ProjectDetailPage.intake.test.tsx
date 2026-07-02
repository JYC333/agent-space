import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import ProjectDetailPage from '../ProjectDetailPage'
import { intakeApi, intakeReaderApi } from '../../../api/client'

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

vi.mock('../../../contexts/SpaceContext', () => ({
  useSpace: () => ({ activeSpaceId: 'space-1', activeSpaceName: 'Space One' }),
}))

vi.mock('../../../core/spaceNav', () => ({
  useSpaceNavigate: () => vi.fn(),
  SpaceLink: ({ to, children, ...props }: { to: string; children: ReactNode }) => (
    <a href={to} {...props}>{children}</a>
  ),
}))

vi.mock('../../capabilities/ResearchWorkflowPanel', () => ({
  ResearchWorkflowPanel: () => <div>Research workflow panel</div>,
}))

vi.mock('../../../api/client', () => ({
  projectsApi: {
    get: vi.fn().mockResolvedValue({
      id: 'project-1',
      space_id: 'space-1',
      owner_user_id: 'user-1',
      name: 'Project One',
      description: null,
      status: 'active',
      current_focus: null,
      settings_json: null,
      created_at: '2026-06-30T00:00:00.000Z',
      updated_at: '2026-06-30T00:00:00.000Z',
      archived_at: null,
    }),
    getSummary: vi.fn().mockResolvedValue({
      project_id: 'project-1',
      activity_count: 0,
      artifact_count: 0,
      pending_proposal_count: 0,
      workspace_count: 0,
      active_run_count: 0,
      memory_entry_count: 0,
    }),
    listWorkspaces: vi.fn().mockResolvedValue([]),
    update: vi.fn(),
    archive: vi.fn(),
    linkWorkspace: vi.fn(),
    unlinkWorkspace: vi.fn(),
  },
  workspacesApi: {
    list: vi.fn().mockResolvedValue({ items: [], total: 0, limit: 200, offset: 0 }),
  },
  activityApi: {
    list: vi.fn().mockResolvedValue([]),
  },
  artifactsApi: {
    list: vi.fn().mockResolvedValue({ items: [], total: 0, limit: 5, offset: 0 }),
  },
  proposalsApi: {
    list: vi.fn().mockResolvedValue({ items: [], total: 0, limit: 5, offset: 0 }),
  },
  runsApi: {
    list: vi.fn().mockResolvedValue([]),
  },
  memoryApi: {
    list: vi.fn().mockResolvedValue({ items: [], total: 0, limit: 5, offset: 0 }),
  },
  intakeApi: {
    createConnection: vi.fn(),
    createSourceRecipe: vi.fn(),
    createCustomSourceDraft: vi.fn(),
    connections: vi.fn().mockResolvedValue({
      items: [{
        id: 'conn-1',
        space_id: 'space-1',
        connector_id: 'connector-1',
        owner_user_id: 'user-1',
        credential_id: null,
        name: 'Engineering feed',
        endpoint_url: 'https://example.test/feed.xml',
        status: 'active',
        fetch_frequency: 'daily',
        capture_policy: 'metadata_only',
        trust_level: 'normal',
        topic_hints_json: null,
        consent_json: {},
        policy_json: {},
        config_json: {},
        last_checked_at: null,
        next_check_at: null,
        created_at: '2026-06-30T00:00:00.000Z',
        updated_at: '2026-06-30T00:00:00.000Z',
      }],
      total: 1,
      limit: 100,
      offset: 0,
    }),
    workspaceBindings: vi.fn().mockResolvedValue([{
      id: 'binding-1',
      space_id: 'space-1',
      workspace_id: 'workspace-1',
      project_id: 'project-1',
      source_connection_id: 'conn-1',
      binding_key: 'engineering',
      status: 'active',
      priority: 0,
      filters_json: {},
      routing_policy_json: {},
      extraction_policy_json: {},
      created_by_user_id: 'user-1',
      created_at: '2026-06-30T00:00:00.000Z',
      updated_at: '2026-06-30T00:00:00.000Z',
    }]),
    items: vi.fn().mockResolvedValue({
      items: [{
        id: 'item-1',
        space_id: 'space-1',
        connection_id: 'conn-1',
        item_type: 'feed_entry',
        source_object_type: null,
        source_object_id: null,
        title: 'Release item',
        source_uri: 'https://example.test/item',
        canonical_uri: 'https://example.test/item',
        source_domain: 'example.test',
        source_external_id: 'guid-1',
        author: null,
        occurred_at: null,
        first_seen_at: '2026-06-30T00:00:00.000Z',
        last_seen_at: '2026-06-30T00:00:00.000Z',
        content_hash: null,
        excerpt: null,
        status: 'new',
        read_status: 'unread',
        content_state: 'metadata_only',
        retention_policy: 'metadata_only',
        relevance_score: null,
        novelty_score: null,
        raw_artifact_id: null,
        extracted_artifact_id: null,
        summary_artifact_id: null,
        search_index_ref: null,
        embedding_index_ref: null,
        metadata_json: null,
        created_at: '2026-06-30T00:00:00.000Z',
        updated_at: '2026-06-30T00:00:00.000Z',
      }],
      total: 1,
      limit: 5,
      offset: 0,
    }),
    evidence: vi.fn().mockResolvedValue({
      items: [{
        id: 'evidence-1',
        space_id: 'space-1',
        intake_item_id: 'item-1',
        extraction_job_id: null,
        source_snapshot_id: null,
        source_object_type: null,
        source_object_id: null,
        evidence_type: 'excerpt',
        title: 'Useful evidence',
        content_excerpt: 'Project-relevant excerpt.',
        content_hash: null,
        artifact_id: null,
        source_uri: 'https://example.test/item',
        source_title: 'Release item',
        source_author: null,
        occurred_at: null,
        trust_level: 'normal',
        extraction_method: 'connection_scan',
        confidence: 0.7,
        status: 'active',
        metadata_json: null,
        created_by_user_id: null,
        created_by_agent_id: null,
        created_by_run_id: null,
        created_at: '2026-06-30T00:00:00.000Z',
        updated_at: '2026-06-30T00:00:00.000Z',
      }],
      total: 1,
      limit: 5,
      offset: 0,
    }),
  },
  intakeReaderApi: {
    listByProject: vi.fn().mockResolvedValue({ items: [] }),
  },
}))

function renderPage() {
  return render(
    <MemoryRouter
      initialEntries={['/spaces/space-1/projects/project-1']}
      future={{ v7_relativeSplatPath: true, v7_startTransition: true }}
    >
      <Routes>
        <Route path="/spaces/:spaceId/projects/:projectId" element={<ProjectDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('ProjectDetailPage Intake consumption', () => {
  it('shows read-only Intake summaries and links management back to Intake', async () => {
    renderPage()

    expect(await screen.findByText('Project One')).toBeInTheDocument()
    expect(screen.getByText('Engineering feed')).toBeInTheDocument()
    expect(screen.getByText('Release item')).toBeInTheDocument()
    expect(screen.getByText('Useful evidence')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /manage in intake/i })).toHaveAttribute('href', '/intake?project_id=project-1')
    expect(screen.queryByText(/create connection/i)).toBeNull()

    await waitFor(() => {
      expect(intakeApi.workspaceBindings).toHaveBeenCalledWith({ project_id: 'project-1' })
      expect(intakeApi.items).toHaveBeenCalledWith({ project_id: 'project-1', limit: 5 })
      expect(intakeApi.evidence).toHaveBeenCalledWith({ project_id: 'project-1', status: 'active', limit: 5 })
      expect(intakeApi.createConnection).not.toHaveBeenCalled()
      expect(intakeApi.createSourceRecipe).not.toHaveBeenCalled()
      expect(intakeApi.createCustomSourceDraft).not.toHaveBeenCalled()
    })
  })

  it('shows reader annotation quote linked to Intake reader, with no annotation controls', async () => {
    vi.mocked(intakeReaderApi.listByProject).mockResolvedValueOnce({
      items: [{
        id: 'ann-1',
        space_id: 'space-1',
        intake_item_id: 'item-1',
        artifact_id: null,
        source_snapshot_id: null,
        annotation_type: 'excerpt',
        quote_text: 'Highlighted content from the article.',
        anchor_json: { schema_version: 1, normalizer: 'plain_text_v1', quote_text: 'Highlighted content from the article.', text_range: { start: 0, end: 38, unit: 'utf16' as const }, before_context: '', after_context: '' },
        color: null,
        label: null,
        visibility: 'space_shared',
        status: 'active',
        anchor_state: 'unverified' as const,
        created_by_user_id: 'user-1',
        created_at: '2026-06-30T00:00:00.000Z',
        updated_at: '2026-06-30T00:00:00.000Z',
      }],
    })

    renderPage()

    // Quote text renders in the reader annotations card
    expect(await screen.findByText('Highlighted content from the article.')).toBeInTheDocument()

    // The card links back to the Intake reader — never owns the reader itself
    const link = screen.getByRole('link', { name: /highlighted content from the article/i })
    expect(link).toHaveAttribute('href', '/intake/items/item-1/read')

    // Project page has no annotation creation or deletion controls
    expect(screen.queryByRole('button', { name: /save annotation/i })).toBeNull()
    expect(screen.queryByRole('button', { name: /delete annotation/i })).toBeNull()

    await waitFor(() => {
      expect(intakeReaderApi.listByProject).toHaveBeenCalledWith('project-1', 5)
    })
  })
})
