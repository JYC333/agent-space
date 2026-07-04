import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import SourceConnectionDetailPage from '../SourceConnectionDetailPage'
import { intakeApi } from '../../../api/client'
import type { CustomSourceHandlerVersion, ExtractionJob, SourceConnection, SourceRecipeVersion } from '../../../types/api'
import { scheduleRuleFromForm } from '../intakePageModel'

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
    getConnection: vi.fn(),
    items: vi.fn(),
    jobs: vi.fn(),
    evidence: vi.fn(),
    sourceRuns: vi.fn(),
    sourceRecipeVersions: vi.fn(),
    customSourceSummary: vi.fn(),
    customSourceVersions: vi.fn(),
    customSourceRuns: vi.fn(),
    generateCustomSourceHandler: vi.fn(),
    testCustomSourceHandler: vi.fn(),
    activateCustomSourceHandler: vi.fn(),
    updateConnection: vi.fn(),
    scanConnection: vi.fn(),
    runJob: vi.fn(),
  },
}))

const baseConnection = {
  id: 'conn-1',
  space_id: 'space-1',
  connector_id: 'connector-1',
  owner_user_id: 'user-1',
  credential_id: null,
  name: 'Recipe Feed',
  endpoint_url: 'https://example.test/feed.xml',
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
  repair_status: 'ok',
  last_handler_run_id: null,
  created_at: '2026-07-01T00:00:00.000Z',
  updated_at: '2026-07-01T00:00:00.000Z',
}

const recipeVersion = {
  id: 'recipe-version-1',
  space_id: 'space-1',
  source_connection_id: 'conn-1',
  version_number: 1,
  recipe_json: {
    recipe_version: 'source.recipe.v1',
    steps: [
      { type: 'fetch_page', bind: 'page' },
      { type: 'parse_rss', input: 'page', bind: 'items' },
      { type: 'dedupe', input: 'items', bind: 'items' },
    ],
    output: { items_var: 'items' },
  },
  policy_envelope_json: {
    allowed_network_origins: ['https://example.test'],
    capture_policy: 'extract_text',
    retention_policy: 'full_text',
    credential_ref: null,
    log_redaction_enabled: true,
    limits: { timeout_ms: 1000, max_download_bytes: 1024, max_output_bytes: 2048, max_files: 2, max_items: 20, max_evidence_items: 20, log_max_bytes: 512 },
  },
  primitive_versions_json: { fetch_page: 1, parse_rss: 1, dedupe: 1 },
  status: 'active',
  created_by_user_id: 'user-1',
  proposal_id: null,
  test_result_json: {
    status: 'succeeded',
    item_count: 1,
    sample_items: [{ external_id: 'guid-1', title: 'Release item', source_uri: 'https://example.test/item', excerpt: 'Summary' }],
    followed_urls: [],
    skipped_urls: [],
    warnings: [],
    errors: [],
    step_traces: [],
    policy_envelope: {},
    started_at: '2026-07-01T00:00:00.000Z',
    completed_at: '2026-07-01T00:00:01.000Z',
  },
  created_at: '2026-07-01T00:00:00.000Z',
  activated_at: '2026-07-01T00:01:00.000Z',
  superseded_at: null,
}

function page<T>(items: T[]) {
  return { items, total: items.length, limit: 20, offset: 0 }
}

function setupCommonMocks() {
  vi.mocked(intakeApi.items).mockResolvedValue(page([{
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
    first_seen_at: '2026-07-01T00:00:00.000Z',
    last_seen_at: '2026-07-01T00:00:00.000Z',
    content_hash: null,
    excerpt: 'Summary',
    status: 'new',
    read_status: 'unread',
    content_state: 'content_saved',
    retention_policy: 'full_text',
    relevance_score: null,
    novelty_score: null,
    raw_artifact_id: null,
    extracted_artifact_id: null,
    summary_artifact_id: null,
    search_index_ref: null,
    embedding_index_ref: null,
    metadata_json: null,
    created_at: '2026-07-01T00:00:00.000Z',
    updated_at: '2026-07-01T00:00:00.000Z',
  }]))
  vi.mocked(intakeApi.jobs).mockResolvedValue(page([]))
  vi.mocked(intakeApi.evidence).mockResolvedValue(page([{
    id: 'evidence-1',
    space_id: 'space-1',
    intake_item_id: 'item-1',
    extraction_job_id: null,
    source_snapshot_id: null,
    source_object_type: null,
    source_object_id: null,
    evidence_type: 'excerpt',
    title: 'Recipe evidence',
    content_excerpt: 'Evidence from recipe source.',
    content_hash: null,
    artifact_id: null,
    source_uri: 'https://example.test/item',
    source_title: 'Release item',
    source_author: null,
    occurred_at: null,
    trust_level: 'normal',
    extraction_method: 'source_recipe',
    confidence: 0.8,
    status: 'candidate',
    metadata_json: null,
    created_by_user_id: null,
    created_by_agent_id: null,
    created_by_run_id: null,
    created_at: '2026-07-01T00:00:00.000Z',
    updated_at: '2026-07-01T00:00:00.000Z',
  }]))
}

function renderPage() {
  return render(
    <MemoryRouter
      initialEntries={['/spaces/space-1/intake/connections/conn-1']}
      future={{ v7_relativeSplatPath: true, v7_startTransition: true }}
    >
      <Routes>
        <Route path="/spaces/:spaceId/intake/connections/:connectionId" element={<SourceConnectionDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

function chooseSelect(currentLabel: string, nextLabel: string, index = 0) {
  fireEvent.click(screen.getAllByRole('button', { name: currentLabel })[index])
  fireEvent.click(screen.getByRole('button', { name: nextLabel }))
}

function typeScheduleNumber(label: string, value: string, index = 0) {
  fireEvent.change(screen.getAllByLabelText(label)[index], { target: { value } })
}

beforeEach(() => {
  vi.clearAllMocks()
  setupCommonMocks()
})

describe('SourceConnectionDetailPage', () => {
  it('shows recipe source detail as product tabs with Advanced separated', async () => {
    const user = userEvent.setup()
    vi.mocked(intakeApi.getConnection).mockResolvedValue({
      ...baseConnection,
      handler_kind: 'recipe',
      active_handler_version_id: null,
      active_recipe_version_id: 'recipe-version-1',
    } as SourceConnection)
    vi.mocked(intakeApi.sourceRuns).mockResolvedValue(page([
      {
        id: 'recipe_dry_run:recipe-version-1',
        space_id: 'space-1',
        source_connection_id: 'conn-1',
        run_kind: 'dry_run',
        implementation: 'recipe',
        status: 'succeeded',
        items_created: 1,
        error: null,
        extraction_job_id: null,
        handler_run_id: null,
        recipe_version_id: 'recipe-version-1',
        created_at: '2026-07-01T00:00:00.000Z',
        started_at: '2026-07-01T00:00:00.000Z',
        completed_at: '2026-07-01T00:00:01.000Z',
      },
    ]))
    vi.mocked(intakeApi.sourceRecipeVersions).mockResolvedValue(page([recipeVersion as SourceRecipeVersion]))

    renderPage()

    expect(await screen.findByText('Recipe Feed')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Plan' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Preview' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Evidence' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Advanced' })).toBeInTheDocument()
    expect(screen.queryByText('Recipe Versions')).toBeNull()

    await user.click(screen.getByRole('tab', { name: 'Plan' }))
    expect(screen.getByText('Feed Parser')).toBeInTheDocument()
    expect(screen.getAllByText(/RSS parser/).length).toBeGreaterThan(0)

    await user.click(screen.getByRole('tab', { name: 'Preview' }))
    expect(screen.getByText('Sample Output')).toBeInTheDocument()
    expect(screen.getByText('Release item')).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Evidence' }))
    expect(screen.getByText('Recipe evidence')).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Runs' }))
    expect(screen.getByText('preview')).toBeInTheDocument()
    expect(screen.getByText('source recipe')).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Advanced' }))
    expect(screen.getByText('Recipe Versions')).toBeInTheDocument()

    await waitFor(() => {
      expect(intakeApi.evidence).toHaveBeenCalledWith({ connection_id: 'conn-1', limit: 20 })
      expect(intakeApi.sourceRuns).toHaveBeenCalledWith('conn-1', { limit: 30 })
    })
  })

  it('keeps generated handler internals behind Advanced while normal Runs use source_runs', async () => {
    const user = userEvent.setup()
    vi.mocked(intakeApi.getConnection).mockResolvedValue({
      ...baseConnection,
      name: 'Advanced Source',
      handler_kind: 'generated_custom',
      active_handler_version_id: 'handler-version-1',
      active_recipe_version_id: null,
    } as SourceConnection)
    const handlerVersion = {
      id: 'handler-version-1',
      space_id: 'space-1',
      source_connection_id: 'conn-1',
      version_number: 1,
      language: 'typescript_node',
      entrypoint: 'handler.cjs',
      handler_artifact_id: null,
      manifest_json: {},
      input_schema_json: null,
      output_schema_json: null,
      policy_envelope_json: {
        allowed_network_origins: ['https://example.test'],
        capture_policy: 'extract_text',
        retention_policy: 'full_text',
        credential_ref: null,
        language: 'typescript_node',
        browser_automation_enabled: false,
        shell_enabled: false,
        dependency_installation_enabled: false,
        log_redaction_enabled: true,
        limits: { timeout_ms: 1000, max_download_bytes: 1024, max_output_bytes: 2048, max_files: 2, max_items: 20, max_evidence_items: 20, log_max_bytes: 512 },
      },
      requested_capabilities_json: null,
      checksum: 'checksum',
      status: 'active',
      created_by_user_id: 'user-1',
      created_by_run_id: null,
      proposal_id: null,
      test_result_json: { status: 'succeeded', item_count: 1 },
      created_at: '2026-07-01T00:00:00.000Z',
      activated_at: '2026-07-01T00:01:00.000Z',
      superseded_at: null,
    } as CustomSourceHandlerVersion
    vi.mocked(intakeApi.sourceRuns).mockResolvedValue(page([
      {
        id: 'handler_run:handler-run-1',
        space_id: 'space-1',
        source_connection_id: 'conn-1',
        run_kind: 'test',
        implementation: 'generated_handler',
        status: 'succeeded',
        items_created: null,
        error: null,
        extraction_job_id: null,
        handler_run_id: 'handler-run-1',
        recipe_version_id: null,
        created_at: '2026-07-01T00:00:00.000Z',
        started_at: '2026-07-01T00:00:00.000Z',
        completed_at: '2026-07-01T00:00:01.000Z',
      },
    ]))
    vi.mocked(intakeApi.customSourceSummary).mockResolvedValue({
      active_handler_version: handlerVersion,
      latest_handler_run: null,
      repair_status: 'ok',
      recent_run_status_counts: {},
      pending_proposals: [],
    })
    vi.mocked(intakeApi.customSourceVersions).mockResolvedValue(page([handlerVersion]))
    vi.mocked(intakeApi.customSourceRuns).mockResolvedValue(page([]))

    renderPage()

    expect(await screen.findByText('Advanced Source')).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'Handler' })).toBeNull()
    expect(screen.queryByText('Handler Versions')).toBeNull()

    await user.click(screen.getByRole('tab', { name: 'Runs' }))
    expect(screen.getByText('advanced handler')).toBeInTheDocument()
    expect(screen.getByText('test')).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Advanced' }))
    expect(screen.getByText('Handler Versions')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /generate/i })).toBeInTheDocument()
  })

  it('updates frequency and schedule rule, and can run the source immediately', async () => {
    const user = userEvent.setup()
    vi.mocked(intakeApi.getConnection).mockResolvedValue({
      ...baseConnection,
      next_check_at: '2026-07-04T08:00:00.000Z',
      handler_kind: 'recipe',
      active_handler_version_id: null,
      active_recipe_version_id: 'recipe-version-1',
    } as SourceConnection)
    vi.mocked(intakeApi.sourceRuns).mockResolvedValue(page([]))
    vi.mocked(intakeApi.sourceRecipeVersions).mockResolvedValue(page([recipeVersion as SourceRecipeVersion]))
    vi.mocked(intakeApi.updateConnection).mockResolvedValue({
      ...baseConnection,
      fetch_frequency: 'weekly',
      next_check_at: '2026-07-06T09:30:00.000Z',
      schedule_rule_json: { frequency: 'weekly', weekday: 1, hour: 9, minute: 30 },
      handler_kind: 'recipe',
      active_handler_version_id: null,
      active_recipe_version_id: 'recipe-version-1',
    } as SourceConnection)
    vi.mocked(intakeApi.scanConnection).mockResolvedValue({ id: 'scan-job-1', items_created: null } as ExtractionJob)
    vi.mocked(intakeApi.runJob).mockResolvedValue({ id: 'scan-job-1', status: 'succeeded', items_created: 2 } as ExtractionJob)

    renderPage()

    await screen.findByText('Recipe Feed')
    chooseSelect('Daily', 'Weekly')
    chooseSelect('Weekday', 'Monday')
    typeScheduleNumber('Hour', '10')
    typeScheduleNumber('Minute', '30')
    const scheduleRule = scheduleRuleFromForm('weekly', { weekday: '1', hour: '10', minute: '30' })
    await user.click(screen.getByRole('button', { name: /save schedule/i }))

    await waitFor(() => {
      expect(intakeApi.updateConnection).toHaveBeenCalledWith('conn-1', {
        fetch_frequency: 'weekly',
        schedule_rule: scheduleRule,
      })
    })

    await user.click(screen.getByRole('button', { name: /run now/i }))

    await waitFor(() => {
      expect(intakeApi.scanConnection).toHaveBeenCalledWith('conn-1')
      expect(intakeApi.runJob).toHaveBeenCalledWith('scan-job-1')
    })
  })
})
