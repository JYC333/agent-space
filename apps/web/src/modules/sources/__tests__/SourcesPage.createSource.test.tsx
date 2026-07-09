import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import SourcesPage from '../SourcesPage'
import SourcePresetsPage from '../sourcePresets/SourcePresetsPage'
import { scheduleRuleFromForm } from '../sourcePageModel'
import { sourcesApi } from '../../../api/client'
import type { ExtractionJob, SourceConnection, SourceRecipeDefinition, SourceRecipeVersion } from '../../../types/api'

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
    connectors: vi.fn(),
    connections: vi.fn(),
    sourceHealth: vi.fn(),
    items: vi.fn(),
    jobs: vi.fn(),
    evidence: vi.fn(),
    evidenceLinks: vi.fn(),
    createConnection: vi.fn(),
    sourcePresets: vi.fn(),
    previewArxivSourcePreset: vi.fn(),
    createArxivSourcePreset: vi.fn(),
    createPostProcessingRule: vi.fn(),
    createProjectSourceBinding: vi.fn(),
    createManualUrl: vi.fn(),
    updateItem: vi.fn(),
    createCustomSourceDraft: vi.fn(),
    planSourceRecipe: vi.fn(),
    createSourceRecipe: vi.fn(),
    dryRunSourceRecipe: vi.fn(),
    activateSourceRecipe: vi.fn(),
    scanConnection: vi.fn(),
    updateConnection: vi.fn(),
    itemAction: vi.fn(),
    runJob: vi.fn(),
    summarize: vi.fn(),
    updateEvidence: vi.fn(),
    createEvidenceLink: vi.fn(),
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
    capture_policy: 'extract_text',
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
    source_item_id: null,
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
    visibility: 'space_discoverable',
    name: 'Engineering feed',
    endpoint_url: 'https://example.test/feed.xml',
    status: 'active',
    fetch_frequency: 'daily',
    capture_policy: 'extract_text',
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

function renderPage(initialEntry = '/spaces/space-1/sources') {
  return render(
    <MemoryRouter
      initialEntries={[initialEntry]}
      future={{ v7_relativeSplatPath: true, v7_startTransition: true }}
    >
      <Routes>
        <Route path="/spaces/:spaceId/sources" element={<SourcesPage />} />
        <Route path="/spaces/:spaceId/sources/source-presets" element={<SourcePresetsPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

function typeScheduleNumber(label: string, value: string, index = 0) {
  fireEvent.change(screen.getAllByLabelText(label)[index], { target: { value } })
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(sourcesApi.connectors).mockResolvedValue([
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
  vi.mocked(sourcesApi.connections).mockResolvedValue(emptyPage(100))
  vi.mocked(sourcesApi.sourceHealth).mockResolvedValue([])
  vi.mocked(sourcesApi.sourcePresets).mockResolvedValue({
    items: [{
      id: 'arxiv',
      category: 'academic',
      display_name: 'arXiv',
      description: 'Monitor arXiv papers by API query.',
      connector_key: 'arxiv',
      fields: ['name', 'mode', 'search_query', 'categories', 'max_results', 'sort_by', 'sort_order', 'fetch_frequency', 'capture_policy'],
      category_options: [{
        group: 'Computer Science',
        options: [{ value: 'cs.AI', label: 'Artificial Intelligence' }],
      }],
    }],
  })
  vi.mocked(sourcesApi.items).mockResolvedValue(emptyPage(80))
  vi.mocked(sourcesApi.jobs).mockResolvedValue(emptyPage(60))
  vi.mocked(sourcesApi.evidence).mockResolvedValue(emptyPage(80))
  vi.mocked(sourcesApi.evidenceLinks).mockResolvedValue(emptyPage(20))
  vi.mocked(sourcesApi.planSourceRecipe).mockResolvedValue({
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
      capture_policy: 'extract_text',
      retention_policy: 'full_text',
    },
  })
  vi.mocked(sourcesApi.createSourceRecipe).mockResolvedValue({
    connection: {
      id: 'recipe-conn-1',
      space_id: 'space-1',
      connector_id: 'connector-custom',
      owner_user_id: 'user-1',
      credential_id: null,
      visibility: 'space_discoverable',
      name: 'Engineering feed',
      endpoint_url: 'https://example.test/feed.xml',
      status: 'paused',
      fetch_frequency: 'daily',
      capture_policy: 'extract_text',
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
  vi.mocked(sourcesApi.dryRunSourceRecipe).mockResolvedValue({
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
  vi.mocked(sourcesApi.activateSourceRecipe).mockResolvedValue({
    status: 'active',
    deltas: [],
    proposal_id: null,
    recipe_version: { ...recipeVersion, status: 'active', activated_at: '2026-07-01T00:01:00.000Z' },
  })
})

describe('SourcesPage Create Source', () => {
  it('plans, creates, dry-runs, and activates through the recipe API path', async () => {
    renderPage()

    expect(await screen.findByText('Create Source')).toBeInTheDocument()
    expect(screen.getByText('Preset Sources')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /open presets/i })).toHaveAttribute('href', '/sources/source-presets')
    expect(screen.queryByRole('tab', { name: 'Academic' })).not.toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'Web / Feed' })).not.toBeInTheDocument()
    expect(screen.queryByText('Connector Source')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Connector')).not.toBeInTheDocument()

    const urlInput = (await screen.findAllByPlaceholderText('https://example.com/feed.xml'))[0]
    fireEvent.change(urlInput, { target: { value: 'https://example.test/feed.xml' } })
    fireEvent.change(screen.getAllByPlaceholderText('Source name')[0], { target: { value: 'Engineering feed' } })
    typeScheduleNumber('Hour', '9')
    typeScheduleNumber('Minute', '0')
    const scheduleRule = scheduleRuleFromForm('daily', { hour: '9', minute: '0', weekday: '' })
    fireEvent.click(screen.getByRole('button', { name: /preview/i }))

    expect(await screen.findByText('Planned item')).toBeInTheDocument()
    expect(screen.getByText('Feed source')).toBeInTheDocument()
    expect(screen.getByText('Level 1')).toBeInTheDocument()
    expect(screen.getByText('RSS parser')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /create and activate/i }))

    await waitFor(() => {
      expect(sourcesApi.planSourceRecipe).toHaveBeenCalledWith(expect.objectContaining({
        name: 'Engineering feed',
        endpoint_url: 'https://example.test/feed.xml',
        fetch_frequency: 'daily',
        schedule_rule: scheduleRule,
        capture_policy: 'extract_text',
      }))
      expect(sourcesApi.createSourceRecipe).toHaveBeenCalledWith(expect.objectContaining({
        name: 'Engineering feed',
        endpoint_url: 'https://example.test/feed.xml',
        schedule_rule: scheduleRule,
        source_type: 'rss',
        recipe,
      }))
      expect(sourcesApi.dryRunSourceRecipe).toHaveBeenCalledWith('recipe-conn-1', {
        recipe_version_id: 'recipe-version-1',
      })
      expect(sourcesApi.activateSourceRecipe).toHaveBeenCalledWith('recipe-conn-1', {
        recipe_version_id: 'recipe-version-1',
        schedule_rule: scheduleRule,
      })
    })
    expect(sourcesApi.createCustomSourceDraft).not.toHaveBeenCalled()
    expect(sourcesApi.createConnection).not.toHaveBeenCalled()
  }, 10_000)

  it('previews and creates a recent arXiv category source without a keyword', async () => {
    vi.mocked(sourcesApi.previewArxivSourcePreset).mockResolvedValue({
      preset_id: 'arxiv',
      query_url: 'https://export.arxiv.org/api/query?search_query=cat%3Acs.AI',
      items: [{
        arxiv_id: '2402.08954',
        arxiv_version: 'v1',
        title: 'Agent paper title',
        authors: ['Author One', 'Author Two'],
        summary: 'Abstract text for the agent paper.',
        published_at: '2024-02-14T00:00:00.000Z',
        updated_at: '2024-02-14T00:00:00.000Z',
        categories: ['cs.AI'],
        primary_category: 'cs.AI',
        doi: null,
        journal_ref: null,
        comment: null,
        abs_url: 'https://arxiv.org/abs/2402.08954',
        html_url: 'https://arxiv.org/html/2402.08954',
        pdf_url: 'https://arxiv.org/pdf/2402.08954',
      }],
      warnings: [],
    })
    vi.mocked(sourcesApi.createArxivSourcePreset).mockResolvedValue({
      ...recipeSourceConnection(),
      id: 'arxiv-conn-1',
      name: 'AI agent papers',
      handler_kind: 'built_in',
    })

    renderPage('/spaces/space-1/sources/source-presets')

    expect(await screen.findByRole('heading', { name: 'Academic' })).toBeInTheDocument()
    expect(screen.getByText('Preset Sources')).toBeInTheDocument()
    expect(screen.getByText('Monitor arXiv papers by API query.')).toBeInTheDocument()
    expect((await screen.findAllByText('cs.AI')).length).toBeGreaterThan(0)
    fireEvent.change(screen.getByPlaceholderText('arXiv source name'), {
      target: { value: 'AI agent papers' },
    })
    typeScheduleNumber('Hour', '10')
    typeScheduleNumber('Minute', '30')
    const arxivScheduleRule = scheduleRuleFromForm('daily', { hour: '10', minute: '30', weekday: '' })
    fireEvent.click(screen.getByRole('button', { name: /preview/i }))

    expect(await screen.findByText('Agent paper title')).toBeInTheDocument()
    expect(screen.getByText('Author One, Author Two')).toBeInTheDocument()
    expect(screen.getAllByText('cs.AI').length).toBeGreaterThan(0)
    fireEvent.click(screen.getByText('Advanced'))
    fireEvent.click(screen.getByLabelText('Enable post-processing after source'))
    fireEvent.click(screen.getByRole('button', { name: 'Digest new items' }))
    fireEvent.click(await screen.findByRole('option', { name: 'Extract evidence' }))
    fireEvent.click(screen.getByLabelText('Create proposals'))
    expect(sourcesApi.previewArxivSourcePreset).toHaveBeenCalledWith({
      mode: 'recent_by_category',
      categories: ['cs.AI'],
      max_results: 10,
    })

    fireEvent.click(screen.getByRole('button', { name: /create source/i }))

    await waitFor(() => {
      expect(sourcesApi.createArxivSourcePreset).toHaveBeenCalledWith({
        mode: 'recent_by_category',
        categories: ['cs.AI'],
        max_results: 50,
        name: 'AI agent papers',
        fetch_frequency: 'daily',
        schedule_rule: arxivScheduleRule,
        capture_policy: 'extract_text',
      })
      expect(sourcesApi.createPostProcessingRule).toHaveBeenCalledWith('arxiv-conn-1', expect.objectContaining({
        trigger_type: 'items_materialized',
        input_config_json: expect.objectContaining({
          content_profile: 'arxiv_new_papers',
          summary_goal: expect.stringContaining('cs.AI'),
          output_instructions: expect.stringContaining('arXiv ids'),
        }),
        actions_json: expect.objectContaining({
          batch_digest: false,
          extract_evidence: true,
          create_proposals: true,
        }),
      }))
    })
    expect(sourcesApi.createConnection).not.toHaveBeenCalled()
    expect(sourcesApi.createSourceRecipe).not.toHaveBeenCalled()
  }, 10_000)

  it('creates an arXiv source and binds it when opened from a project preset workflow', async () => {
    vi.mocked(sourcesApi.createArxivSourcePreset).mockResolvedValue({
      ...recipeSourceConnection(),
      id: 'arxiv-conn-1',
      name: 'AI agent papers',
      handler_kind: 'built_in',
    })
    vi.mocked(sourcesApi.createProjectSourceBinding).mockResolvedValue({
      id: 'binding-1',
      space_id: 'space-1',
      project_id: 'project-1',
      source_connection_id: 'arxiv-conn-1',
      binding_key: 'default',
      status: 'active',
      priority: 0,
      delivery_scope: 'project_members',
      collection_notifications_enabled: true,
      filters_json: {},
      routing_policy_json: {},
      extraction_policy_json: { profile_key: 'academic_paper_v1' },
      created_by_user_id: 'user-1',
      created_at: '2026-07-01T00:00:00.000Z',
      updated_at: '2026-07-01T00:00:00.000Z',
    })

    renderPage('/spaces/space-1/sources/source-presets?project_id=project-1&preset=arxiv')

    expect(await screen.findByText('Add preset source to project')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /project sources/i })).toHaveAttribute('href', '/projects/project-1/sources')

    fireEvent.change(screen.getByPlaceholderText('arXiv source name'), {
      target: { value: 'AI agent papers' },
    })
    fireEvent.click(screen.getByRole('button', { name: /create source/i }))

    await waitFor(() => {
      expect(sourcesApi.createArxivSourcePreset).toHaveBeenCalledWith(expect.objectContaining({
        mode: 'recent_by_category',
        categories: ['cs.AI'],
        name: 'AI agent papers',
      }))
      expect(sourcesApi.createProjectSourceBinding).toHaveBeenCalledWith({
        project_id: 'project-1',
        source_connection_id: 'arxiv-conn-1',
        binding_key: 'default',
        backfill_history: true,
        extraction_policy: { profile_key: 'academic_paper_v1' },
      })
    })
  }, 10_000)

  it('runs a manually queued source scan without waiting for the scheduler', async () => {
    vi.mocked(sourcesApi.connections).mockResolvedValue({
      items: [recipeSourceConnection()],
      total: 1,
      limit: 100,
      offset: 0,
    })
    vi.mocked(sourcesApi.scanConnection).mockResolvedValue(extractionJob())
    vi.mocked(sourcesApi.runJob).mockResolvedValue(extractionJob({
      status: 'succeeded',
      completed_at: '2026-07-01T00:00:03.000Z',
      items_created: 2,
    }))

    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /scan/i }))

    await waitFor(() => {
      expect(sourcesApi.scanConnection).toHaveBeenCalledWith('recipe-conn-1')
      expect(sourcesApi.runJob).toHaveBeenCalledWith('scan-job-1')
    })
  })

})
