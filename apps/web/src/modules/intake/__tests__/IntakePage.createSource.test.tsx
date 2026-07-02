import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import IntakePage from '../IntakePage'
import { intakeApi, workspacesApi } from '../../../api/client'
import type { ExtractionJob, IntakeItem, SourceConnection, SourceRecipeDefinition, SourceRecipeVersion } from '../../../types/api'

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
  intakeApi: {
    connectors: vi.fn(),
    connections: vi.fn(),
    items: vi.fn(),
    jobs: vi.fn(),
    evidence: vi.fn(),
    evidenceLinks: vi.fn(),
    workspaceProfiles: vi.fn(),
    workspaceBindings: vi.fn(),
    createConnection: vi.fn(),
    createManualUrl: vi.fn(),
    createCustomSourceDraft: vi.fn(),
    planSourceRecipe: vi.fn(),
    createSourceRecipe: vi.fn(),
    dryRunSourceRecipe: vi.fn(),
    activateSourceRecipe: vi.fn(),
    scanConnection: vi.fn(),
    updateConnection: vi.fn(),
    createWorkspaceProfile: vi.fn(),
    createWorkspaceBinding: vi.fn(),
    itemAction: vi.fn(),
    runJob: vi.fn(),
    summarize: vi.fn(),
    updateEvidence: vi.fn(),
    createEvidenceLink: vi.fn(),
  },
  workspacesApi: {
    list: vi.fn(),
  },
}))

const recipe: SourceRecipeDefinition = {
  recipe_version: 'source.recipe.v1' as const,
  steps: [
    { type: 'fetch_page' as const, url: '$source.endpoint_url', bind: 'page' },
    { type: 'parse_rss' as const, input: 'page', bind: 'items' },
  ],
  output: { items_var: 'items' },
}

const recipeVersion: SourceRecipeVersion = {
  id: 'recipe-version-1',
  space_id: 'space-1',
  source_connection_id: 'recipe-conn-1',
  version_number: 1,
  recipe_json: recipe,
  policy_envelope_json: {
    allowed_network_origins: ['https://example.test'],
    capture_policy: 'auto_extract_relevant',
    retention_policy: 'full_text',
    credential_ref: null,
    log_redaction_enabled: true,
    limits: { timeout_ms: 1000, max_download_bytes: 1024, max_output_bytes: 2048, max_files: 2, max_items: 20, max_evidence_items: 20, log_max_bytes: 512 },
  },
  primitive_versions_json: { fetch_page: 1, parse_rss: 1 },
  status: 'draft',
  created_by_user_id: 'user-1',
  proposal_id: null,
  test_result_json: null,
  created_at: '2026-07-01T00:00:00.000Z',
  activated_at: null,
  superseded_at: null,
}

function emptyPage<T>(limit = 20) {
  return { items: [] as T[], total: 0, limit, offset: 0 }
}

function extractionJob(overrides: Partial<ExtractionJob> = {}): ExtractionJob {
  return {
    id: 'scan-job-1',
    space_id: 'space-1',
    connection_id: 'recipe-conn-1',
    intake_item_id: null,
    source_snapshot_id: null,
    source_object_type: null,
    source_object_id: null,
    job_type: 'connection_scan',
    status: 'pending',
    started_at: null,
    completed_at: null,
    items_seen: null,
    items_created: null,
    items_updated: null,
    error_code: null,
    error_message: null,
    metadata_json: { implementation: 'recipe' },
    created_at: '2026-07-01T00:00:00.000Z',
    ...overrides,
  }
}

function recipeSourceConnection(): SourceConnection {
  return {
    id: 'recipe-conn-1',
    space_id: 'space-1',
    connector_id: 'connector-custom',
    owner_user_id: 'user-1',
    credential_id: null,
    name: 'Engineering feed',
    endpoint_url: 'https://example.test/feed.xml',
    status: 'active',
    fetch_frequency: 'daily',
    capture_policy: 'auto_extract_relevant',
    trust_level: 'normal',
    topic_hints_json: null,
    consent_json: {},
    policy_json: {},
    config_json: { source_type: 'rss' },
    last_checked_at: null,
    next_check_at: null,
    handler_kind: 'recipe',
    active_handler_version_id: null,
    active_recipe_version_id: 'recipe-version-1',
    repair_status: 'ok',
    last_handler_run_id: null,
    created_at: '2026-07-01T00:00:00.000Z',
    updated_at: '2026-07-01T00:00:00.000Z',
  }
}

function intakeItem(overrides: Partial<IntakeItem> = {}): IntakeItem {
  return {
    id: 'item-1',
    space_id: 'space-1',
    connection_id: 'recipe-conn-1',
    item_type: 'feed_entry',
    source_object_type: null,
    source_object_id: null,
    title: 'Feed item',
    source_uri: 'https://example.test/item-1',
    canonical_uri: 'https://example.test/item-1',
    source_domain: 'example.test',
    source_external_id: 'guid-1',
    author: null,
    occurred_at: null,
    first_seen_at: '2026-07-01T00:00:00.000Z',
    last_seen_at: '2026-07-01T00:00:00.000Z',
    content_hash: null,
    excerpt: 'RSS summary',
    status: 'new',
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
    created_at: '2026-07-01T00:00:00.000Z',
    updated_at: '2026-07-01T00:00:00.000Z',
    ...overrides,
  }
}

function renderPage() {
  return render(
    <MemoryRouter
      initialEntries={['/spaces/space-1/intake']}
      future={{ v7_relativeSplatPath: true, v7_startTransition: true }}
    >
      <Routes>
        <Route path="/spaces/:spaceId/intake" element={<IntakePage />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(intakeApi.connectors).mockResolvedValue([
    {
      id: 'connector-rss',
      connector_key: 'rss',
      display_name: 'RSS',
      connector_type: 'external_url',
      ingestion_mode: 'pull',
      status: 'active',
      capabilities_json: {},
      config_schema_json: null,
      created_at: '2026-07-01T00:00:00.000Z',
      updated_at: '2026-07-01T00:00:00.000Z',
    },
    {
      id: 'connector-custom',
      connector_key: 'custom_source',
      display_name: 'Custom Source',
      connector_type: 'external_url',
      ingestion_mode: 'pull',
      status: 'active',
      capabilities_json: {},
      config_schema_json: null,
      created_at: '2026-07-01T00:00:00.000Z',
      updated_at: '2026-07-01T00:00:00.000Z',
    },
  ])
  vi.mocked(intakeApi.connections).mockResolvedValue(emptyPage(100))
  vi.mocked(intakeApi.items).mockResolvedValue(emptyPage(80))
  vi.mocked(intakeApi.jobs).mockResolvedValue(emptyPage(60))
  vi.mocked(intakeApi.evidence).mockResolvedValue(emptyPage(80))
  vi.mocked(intakeApi.evidenceLinks).mockResolvedValue(emptyPage(20))
  vi.mocked(intakeApi.workspaceProfiles).mockResolvedValue([])
  vi.mocked(intakeApi.workspaceBindings).mockResolvedValue([])
  vi.mocked(intakeApi.planSourceRecipe).mockResolvedValue({
    source_type: 'rss',
    recipe,
    policy_envelope: recipeVersion.policy_envelope_json,
    analysis: {
      primitives: ['fetch_page', 'parse_rss'],
      primitive_versions: { fetch_page: 1, parse_rss: 1 },
      network_access: 'primary_endpoint',
      writes_files: false,
      live_fetch_urls: [],
    },
    preview: {
      status: 'succeeded',
      item_count: 1,
      sample_items: [{ external_id: 'item-1', title: 'Planned item', source_uri: 'https://example.test/item', excerpt: 'Preview excerpt' }],
      warnings: [],
      step_traces: [],
      error: null,
    },
    defaults: {
      fetch_frequency: 'daily',
      capture_policy: 'auto_extract_relevant',
      retention_policy: 'full_text',
    },
  })
  vi.mocked(intakeApi.createSourceRecipe).mockResolvedValue({
    connection: {
      id: 'recipe-conn-1',
      space_id: 'space-1',
      connector_id: 'connector-custom',
      owner_user_id: 'user-1',
      credential_id: null,
      name: 'Engineering feed',
      endpoint_url: 'https://example.test/feed.xml',
      status: 'paused',
      fetch_frequency: 'daily',
      capture_policy: 'auto_extract_relevant',
      trust_level: 'normal',
      topic_hints_json: null,
      consent_json: {},
      policy_json: {},
      config_json: {},
      last_checked_at: null,
      next_check_at: null,
      handler_kind: 'recipe',
      active_handler_version_id: null,
      active_recipe_version_id: null,
      repair_status: 'ok',
      last_handler_run_id: null,
      created_at: '2026-07-01T00:00:00.000Z',
      updated_at: '2026-07-01T00:00:00.000Z',
    },
    recipe_version: recipeVersion,
  })
  vi.mocked(intakeApi.dryRunSourceRecipe).mockResolvedValue({
    recipe_version: recipeVersion,
    dry_run: {
      status: 'succeeded',
      item_count: 1,
      sample_items: [{ external_id: 'item-1', title: 'Planned item', source_uri: 'https://example.test/item', excerpt: 'Preview excerpt' }],
      followed_urls: [],
      skipped_urls: [],
      warnings: [],
      errors: [],
      step_traces: [],
      policy_envelope: recipeVersion.policy_envelope_json,
      started_at: '2026-07-01T00:00:00.000Z',
      completed_at: '2026-07-01T00:00:01.000Z',
    },
  })
  vi.mocked(intakeApi.activateSourceRecipe).mockResolvedValue({
    status: 'active',
    deltas: [],
    proposal_id: null,
    recipe_version: { ...recipeVersion, status: 'active', activated_at: '2026-07-01T00:01:00.000Z' },
  })
  vi.mocked(workspacesApi.list).mockResolvedValue(emptyPage(100))
})

describe('IntakePage Create Source', () => {
  it('plans, creates, dry-runs, and activates through the recipe API path', async () => {
    renderPage()

    expect(await screen.findByText('Create Source')).toBeInTheDocument()
    expect(screen.queryByText('Connector Source')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Connector')).not.toBeInTheDocument()

    const urlInput = (await screen.findAllByPlaceholderText('https://example.com/feed.xml'))[0]
    fireEvent.change(urlInput, { target: { value: 'https://example.test/feed.xml' } })
    fireEvent.change(screen.getAllByPlaceholderText('Source name')[0], { target: { value: 'Engineering feed' } })
    fireEvent.click(screen.getByRole('button', { name: /preview/i }))

    expect(await screen.findByText('Planned item')).toBeInTheDocument()
    expect(screen.getByText('Feed source')).toBeInTheDocument()
    expect(screen.getByText('Level 1')).toBeInTheDocument()
    expect(screen.getByText('RSS parser')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /create and activate/i }))

    await waitFor(() => {
      expect(intakeApi.planSourceRecipe).toHaveBeenCalledWith(expect.objectContaining({
        name: 'Engineering feed',
        endpoint_url: 'https://example.test/feed.xml',
        fetch_frequency: 'daily',
        capture_policy: 'auto_extract_relevant',
      }))
      expect(intakeApi.createSourceRecipe).toHaveBeenCalledWith(expect.objectContaining({
        name: 'Engineering feed',
        endpoint_url: 'https://example.test/feed.xml',
        source_type: 'rss',
        recipe,
      }))
      expect(intakeApi.dryRunSourceRecipe).toHaveBeenCalledWith('recipe-conn-1', {
        recipe_version_id: 'recipe-version-1',
      })
      expect(intakeApi.activateSourceRecipe).toHaveBeenCalledWith('recipe-conn-1', {
        recipe_version_id: 'recipe-version-1',
      })
    })
    expect(intakeApi.createCustomSourceDraft).not.toHaveBeenCalled()
    expect(intakeApi.createConnection).not.toHaveBeenCalled()
  }, 10_000)

  it('runs a manually queued source scan without waiting for the scheduler', async () => {
    vi.mocked(intakeApi.connections).mockResolvedValue({
      items: [recipeSourceConnection()],
      total: 1,
      limit: 100,
      offset: 0,
    })
    vi.mocked(intakeApi.scanConnection).mockResolvedValue(extractionJob())
    vi.mocked(intakeApi.runJob).mockResolvedValue(extractionJob({
      status: 'succeeded',
      completed_at: '2026-07-01T00:00:03.000Z',
      items_created: 2,
    }))

    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /scan/i }))

    await waitFor(() => {
      expect(intakeApi.scanConnection).toHaveBeenCalledWith('recipe-conn-1')
      expect(intakeApi.runJob).toHaveBeenCalledWith('scan-job-1')
    })
  })

  it('runs manually queued text extraction without waiting for the jobs panel', async () => {
    vi.mocked(intakeApi.items).mockResolvedValue({
      items: [intakeItem()],
      total: 1,
      limit: 80,
      offset: 0,
    })
    vi.mocked(intakeApi.itemAction).mockResolvedValue(intakeItem({
      content_state: 'content_queued',
      retention_policy: 'full_text',
    }))
    vi.mocked(intakeApi.jobs).mockImplementation(async (params = {}) => {
      if (params.intake_item_id === 'item-1' && params.job_type === 'extract_text' && params.status === 'pending') {
        return { items: [extractionJob({ id: 'extract-job-1', intake_item_id: 'item-1', job_type: 'extract_text' })], total: 1, limit: 1, offset: 0 }
      }
      return emptyPage(60)
    })
    vi.mocked(intakeApi.runJob).mockResolvedValue(extractionJob({
      id: 'extract-job-1',
      intake_item_id: 'item-1',
      job_type: 'extract_text',
      status: 'succeeded',
      completed_at: '2026-07-01T00:00:03.000Z',
    }))

    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /extract text/i }))

    await waitFor(() => {
      expect(intakeApi.itemAction).toHaveBeenCalledWith('item-1', 'queue_content')
      expect(intakeApi.jobs).toHaveBeenCalledWith({
        intake_item_id: 'item-1',
        job_type: 'extract_text',
        status: 'pending',
        limit: 1,
      })
      expect(intakeApi.runJob).toHaveBeenCalledWith('extract-job-1')
    })
  })

  it('allows content-saved items to be re-extracted from the items list', async () => {
    vi.mocked(intakeApi.items).mockResolvedValue({
      items: [intakeItem({
        content_state: 'content_saved',
        retention_policy: 'full_text',
        extracted_artifact_id: 'artifact-1',
      })],
      total: 1,
      limit: 80,
      offset: 0,
    })
    vi.mocked(intakeApi.itemAction).mockResolvedValue(intakeItem({
      content_state: 'content_queued',
      retention_policy: 'full_text',
    }))
    vi.mocked(intakeApi.jobs).mockImplementation(async (params = {}) => {
      if (params.intake_item_id === 'item-1' && params.job_type === 'extract_text' && params.status === 'pending') {
        return { items: [extractionJob({ id: 'extract-job-1', intake_item_id: 'item-1', job_type: 'extract_text' })], total: 1, limit: 1, offset: 0 }
      }
      return emptyPage(60)
    })
    vi.mocked(intakeApi.runJob).mockResolvedValue(extractionJob({
      id: 'extract-job-1',
      intake_item_id: 'item-1',
      job_type: 'extract_text',
      status: 'succeeded',
      completed_at: '2026-07-01T00:00:03.000Z',
    }))

    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /re-extract/i }))

    await waitFor(() => {
      expect(intakeApi.itemAction).toHaveBeenCalledWith('item-1', 'queue_content')
      expect(intakeApi.runJob).toHaveBeenCalledWith('extract-job-1')
    })
  })
})
