import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import ProjectDetailPage from '../ProjectDetailPage'
import { intakeApi, intakeReaderApi, projectsApi, workspacesApi } from '../../../api/client'

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
        capture_policy: 'reference_only',
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
    createWorkspaceBinding: vi.fn().mockResolvedValue({
      id: 'binding-new',
      space_id: 'space-1',
      workspace_id: 'workspace-1',
      project_id: 'project-1',
      source_connection_id: 'conn-1',
      binding_key: 'default',
      status: 'active',
      priority: 0,
      filters_json: {},
      routing_policy_json: {},
      extraction_policy_json: {},
      created_by_user_id: 'user-1',
      created_at: '2026-06-30T00:00:00.000Z',
      updated_at: '2026-06-30T00:00:00.000Z',
    }),
    backfillWorkspaceBinding: vi.fn().mockResolvedValue({
      binding_id: 'binding-1',
      workspace_id: 'workspace-1',
      project_id: 'project-1',
      source_connection_id: 'conn-1',
      created_links: 2,
    }),
    createManualUrl: vi.fn().mockResolvedValue({
      id: 'item-new',
      space_id: 'space-1',
      connection_id: 'conn-1',
      item_type: 'external_url',
      source_object_type: null,
      source_object_id: null,
      title: 'Saved URL',
      source_uri: 'https://example.test/saved',
      canonical_uri: 'https://example.test/saved',
      source_domain: 'example.test',
      source_external_id: null,
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
      metadata_json: { created_by: 'manual_url' },
      created_at: '2026-06-30T00:00:00.000Z',
      updated_at: '2026-06-30T00:00:00.000Z',
    }),
    updateItem: vi.fn().mockResolvedValue({
      id: 'item-1',
      space_id: 'space-1',
      connection_id: 'conn-1',
      item_type: 'external_url',
      source_object_type: null,
      source_object_id: null,
      title: 'Release item',
      source_uri: 'https://example.test/item',
      canonical_uri: 'https://example.test/item',
      source_domain: 'example.test',
      source_external_id: null,
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
      metadata_json: { created_by: 'manual_url' },
      created_at: '2026-06-30T00:00:00.000Z',
      updated_at: '2026-06-30T00:00:00.000Z',
    }),
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
    postProcessingDecisions: vi.fn().mockResolvedValue({
      items: [],
      total: 0,
      limit: 5,
      offset: 0,
    }),
  },
  intakeReaderApi: {
    listByProject: vi.fn().mockResolvedValue({ items: [] }),
  },
  automationsApi: {
    list: vi.fn().mockResolvedValue([]),
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
  it('shows Intake summaries and links management back to Intake', async () => {
    renderPage()

    expect(await screen.findByText('Project One')).toBeInTheDocument()
    expect(screen.getByText('Engineering feed')).toBeInTheDocument()
    expect(screen.getByText('Release item')).toBeInTheDocument()
    expect(screen.getByText('Useful evidence')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^link source$/i })).toBeInTheDocument()
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

  it('backfills historical evidence for an existing linked source', async () => {
    renderPage()

    const button = await screen.findByRole('button', { name: /backfill history/i })
    fireEvent.click(button)

    await waitFor(() => {
      expect(intakeApi.backfillWorkspaceBinding).toHaveBeenCalledWith('binding-1')
    })
  })

  it('links an Intake source directly from the Project page', async () => {
    vi.mocked(projectsApi.listWorkspaces).mockResolvedValue([
      {
        id: 'project-workspace-1',
        project_id: 'project-1',
        workspace_id: 'workspace-1',
        role: 'reference',
        created_at: '2026-06-30T00:00:00.000Z',
        updated_at: '2026-06-30T00:00:00.000Z',
      },
    ])
    vi.mocked(workspacesApi.list).mockResolvedValue({
      items: [{
        id: 'workspace-1',
        owner_space_id: 'space-1',
        created_by_user_id: 'user-1',
        name: 'Project workspace',
        slug: 'project-workspace',
        description: null,
        workspace_type: 'project',
        kind: 'standard',
        repo_url: null,
        root_path: null,
        default_branch: null,
        visibility: 'space_shared',
        status: 'active',
        protected: false,
        system_managed: false,
        registered_from: null,
        metadata_json: null,
        snapshot_retention_days: null,
        snapshot_max_count: null,
        created_at: '2026-06-30T00:00:00.000Z',
        updated_at: '2026-06-30T00:00:00.000Z',
      }],
      total: 1,
      limit: 200,
      offset: 0,
    })
    vi.mocked(intakeApi.workspaceBindings).mockResolvedValue([])

    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /^link source$/i }))
    expect(await screen.findByRole('dialog', { name: /^link source$/i })).toBeInTheDocument()
    expect(screen.getByText('Project workspace · reference')).toBeInTheDocument()
    expect(screen.getByText('Engineering feed')).toBeInTheDocument()

    const buttons = screen.getAllByRole('button', { name: /^link source$/i })
    fireEvent.click(buttons[buttons.length - 1]!)

    await waitFor(() => {
      expect(intakeApi.createWorkspaceBinding).toHaveBeenCalledWith({
        project_id: 'project-1',
        workspace_id: 'workspace-1',
        source_connection_id: 'conn-1',
        backfill_history: true,
      })
    })
  })

  it('saves a URL directly to a project-linked Intake source', async () => {
    vi.mocked(intakeApi.workspaceBindings).mockResolvedValue([{
      id: 'binding-1',
      space_id: 'space-1',
      workspace_id: 'workspace-1',
      project_id: 'project-1',
      source_connection_id: 'conn-1',
      binding_key: 'default',
      status: 'active',
      priority: 0,
      filters_json: {},
      routing_policy_json: {},
      extraction_policy_json: {},
      created_by_user_id: 'user-1',
      created_at: '2026-06-30T00:00:00.000Z',
      updated_at: '2026-06-30T00:00:00.000Z',
    }])

    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /^save url$/i }))
    expect(await screen.findByRole('dialog', { name: /^save url$/i })).toBeInTheDocument()

    fireEvent.change(screen.getByPlaceholderText('https://example.com/post'), { target: { value: 'https://example.test/saved' } })
    fireEvent.change(screen.getByPlaceholderText('Optional'), { target: { value: 'Saved article' } })

    const buttons = screen.getAllByRole('button', { name: /^save url$/i })
    fireEvent.click(buttons[buttons.length - 1]!)

    await waitFor(() => {
      expect(intakeApi.createManualUrl).toHaveBeenCalledWith({
        url: 'https://example.test/saved',
        title: 'Saved article',
        connection_id: 'conn-1',
        queue_content: false,
      })
    })
  })

  it('attaches an already saved URL to the selected project source', async () => {
    vi.mocked(intakeApi.workspaceBindings).mockResolvedValue([{
      id: 'binding-1',
      space_id: 'space-1',
      workspace_id: 'workspace-1',
      project_id: 'project-1',
      source_connection_id: 'conn-1',
      binding_key: 'default',
      status: 'active',
      priority: 0,
      filters_json: {},
      routing_policy_json: {},
      extraction_policy_json: {},
      created_by_user_id: 'user-1',
      created_at: '2026-06-30T00:00:00.000Z',
      updated_at: '2026-06-30T00:00:00.000Z',
    }])
    vi.mocked(intakeApi.createManualUrl).mockResolvedValueOnce({
      id: 'item-existing',
      space_id: 'space-1',
      connection_id: null,
      item_type: 'external_url',
      source_object_type: null,
      source_object_id: null,
      title: 'Existing URL',
      source_uri: 'https://example.test/existing',
      canonical_uri: 'https://example.test/existing',
      source_domain: 'example.test',
      source_external_id: null,
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
      metadata_json: { created_by: 'manual_url' },
      created_at: '2026-06-30T00:00:00.000Z',
      updated_at: '2026-06-30T00:00:00.000Z',
    })
    vi.mocked(intakeApi.updateItem).mockClear()

    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /^save url$/i }))
    fireEvent.change(await screen.findByPlaceholderText('https://example.com/post'), { target: { value: 'https://example.test/existing' } })

    const buttons = screen.getAllByRole('button', { name: /^save url$/i })
    fireEvent.click(buttons[buttons.length - 1]!)

    await waitFor(() => {
      expect(intakeApi.updateItem).toHaveBeenCalledWith('item-existing', { connection_id: 'conn-1' })
    })
  })

  it('changes the source for a manually saved URL item from the Project page', async () => {
    vi.mocked(intakeApi.connections).mockResolvedValue({
      items: [
        {
          id: 'conn-1',
          space_id: 'space-1',
          connector_id: 'connector-1',
          owner_user_id: 'user-1',
          credential_id: null,
          name: 'Engineering feed',
          endpoint_url: 'https://example.test/feed.xml',
          status: 'active',
          fetch_frequency: 'daily',
          capture_policy: 'reference_only',
          trust_level: 'normal',
          topic_hints_json: null,
          consent_json: {},
          policy_json: {},
          config_json: {},
          last_checked_at: null,
          next_check_at: null,
          created_at: '2026-06-30T00:00:00.000Z',
          updated_at: '2026-06-30T00:00:00.000Z',
        },
        {
          id: 'conn-2',
          space_id: 'space-1',
          connector_id: 'connector-1',
          owner_user_id: 'user-1',
          credential_id: null,
          name: 'Research feed',
          endpoint_url: 'https://example.test/research.xml',
          status: 'active',
          fetch_frequency: 'daily',
          capture_policy: 'reference_only',
          trust_level: 'normal',
          topic_hints_json: null,
          consent_json: {},
          policy_json: {},
          config_json: {},
          last_checked_at: null,
          next_check_at: null,
          created_at: '2026-06-30T00:00:00.000Z',
          updated_at: '2026-06-30T00:00:00.000Z',
        },
      ],
      total: 2,
      limit: 100,
      offset: 0,
    })
    vi.mocked(intakeApi.workspaceBindings).mockResolvedValue([
      {
        id: 'binding-1',
        space_id: 'space-1',
        workspace_id: 'workspace-1',
        project_id: 'project-1',
        source_connection_id: 'conn-1',
        binding_key: 'default',
        status: 'active',
        priority: 0,
        filters_json: {},
        routing_policy_json: {},
        extraction_policy_json: {},
        created_by_user_id: 'user-1',
        created_at: '2026-06-30T00:00:00.000Z',
        updated_at: '2026-06-30T00:00:00.000Z',
      },
      {
        id: 'binding-2',
        space_id: 'space-1',
        workspace_id: 'workspace-1',
        project_id: 'project-1',
        source_connection_id: 'conn-2',
        binding_key: 'default',
        status: 'active',
        priority: 0,
        filters_json: {},
        routing_policy_json: {},
        extraction_policy_json: {},
        created_by_user_id: 'user-1',
        created_at: '2026-06-30T00:00:00.000Z',
        updated_at: '2026-06-30T00:00:00.000Z',
      },
    ])
    vi.mocked(intakeApi.items).mockResolvedValue({
      items: [{
        id: 'item-1',
        space_id: 'space-1',
        connection_id: 'conn-1',
        item_type: 'external_url',
        source_object_type: null,
        source_object_id: null,
        title: 'Saved URL',
        source_uri: 'https://example.test/item',
        canonical_uri: 'https://example.test/item',
        source_domain: 'example.test',
        source_external_id: null,
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
        metadata_json: { created_by: 'manual_url' },
        created_at: '2026-06-30T00:00:00.000Z',
        updated_at: '2026-06-30T00:00:00.000Z',
      }],
      total: 1,
      limit: 5,
      offset: 0,
    })

    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /^engineering feed$/i }))
    fireEvent.click(screen.getByRole('option', { name: /^research feed$/i }))

    await waitFor(() => {
      expect(intakeApi.updateItem).toHaveBeenCalledWith('item-1', { connection_id: 'conn-2' })
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
