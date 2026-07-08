import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import SourceConnectionDetailPage from '../SourceConnectionDetailPage'
import { agentsApi, sourcesApi, projectsApi } from '../../../api/client'
import type {
  CustomSourceHandlerVersion,
  ExtractionJob,
  SourceConnection,
  SourcePostProcessingRule,
  SourcePostProcessingRun,
  SourceRecipeVersion,
} from '../../../types/api'
import { scheduleRuleFromForm } from '../sourcePageModel'

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
    getConnection: vi.fn(),
    items: vi.fn(),
    jobs: vi.fn(),
    evidence: vi.fn(),
    sourceRuns: vi.fn(),
    sourceRecipeVersions: vi.fn(),
    customSourceSummary: vi.fn(),
    customSourceVersions: vi.fn(),
    generateCustomSourceHandler: vi.fn(),
    testCustomSourceHandler: vi.fn(),
    activateCustomSourceHandler: vi.fn(),
    updateConnection: vi.fn(),
    scanConnection: vi.fn(),
    runJob: vi.fn(),
    postProcessingRules: vi.fn(),
    postProcessingRuns: vi.fn(),
    postProcessingBacklog: vi.fn(),
    postProcessingConnectionDecisions: vi.fn(),
    createPostProcessingRule: vi.fn(),
    updatePostProcessingRule: vi.fn(),
    runPostProcessingRule: vi.fn(),
    drainPostProcessingRule: vi.fn(),
    postProcessingDecisionAction: vi.fn(),
  },
  agentsApi: {
    list: vi.fn(),
  },
  projectsApi: {
    list: vi.fn(),
  },
}))

const baseConnection = {
  id: 'conn-1',
  space_id: 'space-1',
  connector_id: 'connector-1',
  owner_user_id: 'user-1',
  credential_id: null,
  visibility: 'space_discoverable',
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
  vi.mocked(sourcesApi.items).mockResolvedValue(page([{
    id: 'item-1',
    space_id: 'space-1',
    connection_id: 'conn-1',
    item_type: 'feed_entry',
    source_object_type: null,
    source_object_id: null,
    created_by_user_id: 'user-1',
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
    library_status: 'new',
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
  vi.mocked(sourcesApi.jobs).mockResolvedValue(page([]))
  vi.mocked(sourcesApi.postProcessingRules).mockResolvedValue([])
  vi.mocked(sourcesApi.postProcessingRuns).mockResolvedValue(page([]))
  vi.mocked(sourcesApi.postProcessingBacklog).mockResolvedValue({ source_connection_id: 'conn-1', rules: [] })
  vi.mocked(sourcesApi.postProcessingConnectionDecisions).mockResolvedValue(page([]))
  vi.mocked(agentsApi.list).mockResolvedValue([])
  vi.mocked(projectsApi.list).mockResolvedValue(page([]))
  vi.mocked(sourcesApi.createPostProcessingRule).mockResolvedValue({
    id: 'rule-1',
    space_id: 'space-1',
    source_connection_id: 'conn-1',
    agent_id: 'agent-1',
    project_id: null,
    name: 'Recipe Feed post-processing',
    status: 'active',
    trigger_type: 'items_materialized',
    trigger_config_json: { min_new_items: 1, cooldown_seconds: 900, timezone: 'UTC', skip_when_no_new_items: true },
    input_config_json: {
      window: 'new_since_last_success',
      item_limit: 10,
      max_batches_per_event: 10,
      processing_strategy: 'batch_digest',
      content_source: 'excerpt_only',
      include_excerpts: true,
      include_evidence: true,
      timezone: 'UTC',
      retrieval_context: { enabled: false, domains: ['project'], max_results_per_domain: 6, mode: 'hybrid' },
      candidate_prefilter: { enabled: false, mode: 'hybrid', max_candidates: 20 },
      deep_analysis: { enabled: false, trigger_relevance: ['relevant'], min_confidence: 0.7, max_candidates_per_run: 5, content_source: 'prefer_extracted_text', output: 'deep_report' },
    },
    actions_json: { batch_digest: true, per_item_summary: false, extract_evidence: false, create_proposals: false, mark_items: false },
    cursor_json: null,
    last_fired_at: null,
    next_run_at: null,
    created_by_user_id: 'user-1',
    created_at: '2026-07-01T00:00:00.000Z',
    updated_at: '2026-07-01T00:00:00.000Z',
  })
  vi.mocked(sourcesApi.updatePostProcessingRule).mockImplementation(async (_connectionId, _ruleId, body) => ({
    id: 'rule-1',
    space_id: 'space-1',
    source_connection_id: 'conn-1',
    agent_id: 'agent-1',
    project_id: null,
    name: 'Recipe Feed post-processing',
    status: body.status ?? 'active',
    trigger_type: 'items_materialized',
    trigger_config_json: { min_new_items: 1, cooldown_seconds: 900, timezone: 'UTC', skip_when_no_new_items: true },
    input_config_json: {
      window: 'new_since_last_success',
      item_limit: 10,
      max_batches_per_event: 10,
      processing_strategy: 'batch_digest',
      content_source: 'excerpt_only',
      include_excerpts: true,
      include_evidence: true,
      timezone: 'UTC',
      retrieval_context: { enabled: false, domains: ['project'], max_results_per_domain: 6, mode: 'hybrid' },
      candidate_prefilter: { enabled: false, mode: 'hybrid', max_candidates: 20 },
      deep_analysis: { enabled: false, trigger_relevance: ['relevant'], min_confidence: 0.7, max_candidates_per_run: 5, content_source: 'prefer_extracted_text', output: 'deep_report' },
    },
    actions_json: { batch_digest: true, per_item_summary: false, extract_evidence: false, create_proposals: false, mark_items: false },
    cursor_json: null,
    last_fired_at: null,
    next_run_at: null,
    created_by_user_id: 'user-1',
    created_at: '2026-07-01T00:00:00.000Z',
    updated_at: '2026-07-01T00:01:00.000Z',
  }))
  vi.mocked(sourcesApi.runPostProcessingRule).mockResolvedValue({
    id: 'post-run-1',
    space_id: 'space-1',
    rule_id: 'rule-1',
    source_connection_id: 'conn-1',
    agent_id: 'agent-1',
    project_id: null,
    agent_run_id: 'agent-run-1',
    triggered_by_user_id: 'user-1',
    trigger_type: 'manual',
    status: 'succeeded',
    input_item_ids: ['item-1'],
    input_evidence_ids: [],
    output_artifact_ids: ['artifact-1'],
    output_proposal_ids: [],
    output_job_ids: [],
    cursor_before_json: null,
    cursor_after_json: null,
    retrieval_context_json: {},
    item_decisions_json: [],
    summary: 'Done',
    error_json: null,
    started_at: '2026-07-01T00:00:00.000Z',
    completed_at: '2026-07-01T00:00:01.000Z',
    created_at: '2026-07-01T00:00:00.000Z',
  })
  vi.mocked(sourcesApi.evidence).mockResolvedValue(page([{
    id: 'evidence-1',
    space_id: 'space-1',
    source_item_id: 'item-1',
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
      initialEntries={['/spaces/space-1/sources/connections/conn-1']}
      future={{ v7_relativeSplatPath: true, v7_startTransition: true }}
    >
      <Routes>
        <Route path="/spaces/:spaceId/sources/connections/:connectionId" element={<SourceConnectionDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

function chooseSelect(currentLabel: string, nextLabel: string, index = 0) {
  fireEvent.click(screen.getAllByRole('button', { name: currentLabel })[index])
  fireEvent.click(screen.getByRole('option', { name: nextLabel }))
}

function typeScheduleNumber(label: string, value: string, index = 0) {
  fireEvent.change(screen.getAllByLabelText(label)[index], { target: { value } })
}

function postProcessingRule(overrides: Partial<SourcePostProcessingRule> = {}): SourcePostProcessingRule {
  return {
    id: 'rule-1',
    space_id: 'space-1',
    source_connection_id: 'conn-1',
    agent_id: 'agent-1',
    project_id: null,
    name: 'Recipe Feed post-processing',
    status: 'active',
    trigger_type: 'items_materialized',
    trigger_config_json: { min_new_items: 1, cooldown_seconds: 900, timezone: 'UTC', skip_when_no_new_items: true },
    input_config_json: {
      window: 'new_since_last_success',
      item_limit: 10,
      max_batches_per_event: 10,
      processing_strategy: 'batch_digest',
      content_source: 'excerpt_only',
      include_excerpts: true,
      include_evidence: true,
      timezone: 'UTC',
      retrieval_context: { enabled: false, domains: ['project'], max_results_per_domain: 6, mode: 'hybrid' },
      candidate_prefilter: { enabled: false, mode: 'hybrid', max_candidates: 20 },
      deep_analysis: { enabled: false, trigger_relevance: ['relevant'], min_confidence: 0.7, max_candidates_per_run: 5, content_source: 'prefer_extracted_text', output: 'deep_report' },
    },
    actions_json: { batch_digest: true, per_item_summary: false, extract_evidence: false, create_proposals: false, mark_items: false },
    cursor_json: null,
    last_fired_at: null,
    next_run_at: null,
    created_by_user_id: 'user-1',
    created_at: '2026-07-01T00:00:00.000Z',
    updated_at: '2026-07-01T00:00:00.000Z',
    ...overrides,
  }
}

function postProcessingRun(overrides: Partial<SourcePostProcessingRun> = {}): SourcePostProcessingRun {
  return {
    id: 'post-run-1',
    space_id: 'space-1',
    rule_id: 'rule-1',
    source_connection_id: 'conn-1',
    agent_id: 'agent-1',
    project_id: null,
    agent_run_id: 'agent-run-1',
    triggered_by_user_id: 'user-1',
    trigger_type: 'manual',
    status: 'succeeded',
    input_item_ids: ['item-1'],
    input_evidence_ids: [],
    output_artifact_ids: ['artifact-1'],
    output_proposal_ids: [],
    output_job_ids: [],
    cursor_before_json: null,
    cursor_after_json: null,
    retrieval_context_json: {},
    item_decisions_json: [],
    summary: 'Done',
    error_json: null,
    started_at: '2026-07-01T00:00:00.000Z',
    completed_at: '2026-07-01T00:00:01.000Z',
    created_at: '2026-07-01T00:00:00.000Z',
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  setupCommonMocks()
})

describe('SourceConnectionDetailPage', () => {
  it('shows recipe source detail as configuration tabs with Advanced separated', async () => {
    const user = userEvent.setup()
    vi.mocked(sourcesApi.getConnection).mockResolvedValue({
      ...baseConnection,
      handler_kind: 'recipe',
      active_handler_version_id: null,
      active_recipe_version_id: 'recipe-version-1',
    } as SourceConnection)
    vi.mocked(sourcesApi.sourceRecipeVersions).mockResolvedValue(page([recipeVersion as SourceRecipeVersion]))

    renderPage()

    expect(await screen.findByText('Recipe Feed')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Plan' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Preview' })).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'Items' })).not.toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'Evidence' })).not.toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'Runs' })).not.toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Advanced' })).toBeInTheDocument()
    expect(screen.queryByText('Recipe Versions')).toBeNull()

    await user.click(screen.getByRole('tab', { name: 'Plan' }))
    expect(screen.getByText('Feed Parser')).toBeInTheDocument()
    expect(screen.getAllByText(/RSS parser/).length).toBeGreaterThan(0)

    await user.click(screen.getByRole('tab', { name: 'Preview' }))
    expect(screen.getByText('Sample Output')).toBeInTheDocument()
    expect(screen.getByText('Release item')).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Advanced' }))
    expect(screen.getByText('Recipe Versions')).toBeInTheDocument()

    await waitFor(() => {
      expect(sourcesApi.items).not.toHaveBeenCalled()
      expect(sourcesApi.evidence).not.toHaveBeenCalled()
      expect(sourcesApi.jobs).not.toHaveBeenCalled()
      expect(sourcesApi.sourceRuns).not.toHaveBeenCalled()
      expect(sourcesApi.postProcessingRuns).not.toHaveBeenCalled()
    })
  })

  it('keeps generated handler internals behind Advanced', async () => {
    const user = userEvent.setup()
    vi.mocked(sourcesApi.getConnection).mockResolvedValue({
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
    vi.mocked(sourcesApi.customSourceSummary).mockResolvedValue({
      active_handler_version: handlerVersion,
      latest_handler_run: null,
      repair_status: 'ok',
      recent_run_status_counts: {},
      pending_proposals: [],
    })
    vi.mocked(sourcesApi.customSourceVersions).mockResolvedValue(page([handlerVersion]))

    renderPage()

    expect(await screen.findByText('Advanced Source')).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'Handler' })).toBeNull()
    expect(screen.queryByRole('tab', { name: 'Runs' })).toBeNull()
    expect(screen.queryByText('Handler Versions')).toBeNull()

    await user.click(screen.getByRole('tab', { name: 'Advanced' }))
    expect(screen.getByText('Handler Versions')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /generate/i })).toBeInTheDocument()
  })

  it('updates frequency and schedule rule, and can run the source immediately', async () => {
    const user = userEvent.setup()
    vi.mocked(sourcesApi.getConnection).mockResolvedValue({
      ...baseConnection,
      next_check_at: '2026-07-04T08:00:00.000Z',
      handler_kind: 'recipe',
      active_handler_version_id: null,
      active_recipe_version_id: 'recipe-version-1',
    } as SourceConnection)
    vi.mocked(sourcesApi.sourceRuns).mockResolvedValue(page([]))
    vi.mocked(sourcesApi.sourceRecipeVersions).mockResolvedValue(page([recipeVersion as SourceRecipeVersion]))
    vi.mocked(sourcesApi.updateConnection).mockResolvedValue({
      ...baseConnection,
      fetch_frequency: 'weekly',
      next_check_at: '2026-07-06T09:30:00.000Z',
      schedule_rule_json: { frequency: 'weekly', weekday: 1, hour: 9, minute: 30 },
      handler_kind: 'recipe',
      active_handler_version_id: null,
      active_recipe_version_id: 'recipe-version-1',
    } as SourceConnection)
    vi.mocked(sourcesApi.scanConnection).mockResolvedValue({ id: 'scan-job-1', items_created: null } as ExtractionJob)
    vi.mocked(sourcesApi.runJob).mockResolvedValue({ id: 'scan-job-1', status: 'succeeded', items_created: 2 } as ExtractionJob)

    renderPage()

    await screen.findByText('Recipe Feed')
    chooseSelect('Daily', 'Weekly')
    chooseSelect('Weekday', 'Monday')
    typeScheduleNumber('Hour', '10')
    typeScheduleNumber('Minute', '30')
    const scheduleRule = scheduleRuleFromForm('weekly', { weekday: '1', hour: '10', minute: '30' })
    await user.click(screen.getByRole('button', { name: /save schedule/i }))

    await waitFor(() => {
      expect(sourcesApi.updateConnection).toHaveBeenCalledWith('conn-1', {
        fetch_frequency: 'weekly',
        schedule_rule: scheduleRule,
      })
    })

    await user.click(screen.getByRole('button', { name: /run now/i }))

    await waitFor(() => {
      expect(sourcesApi.scanConnection).toHaveBeenCalledWith('conn-1')
      expect(sourcesApi.runJob).toHaveBeenCalledWith('scan-job-1')
    })
  })

  it('creates a post-processing rule with a relevance screening profile', async () => {
    const user = userEvent.setup()
    vi.mocked(sourcesApi.getConnection).mockResolvedValue({
      ...baseConnection,
      handler_kind: 'recipe',
      active_handler_version_id: null,
      active_recipe_version_id: 'recipe-version-1',
    } as SourceConnection)
    vi.mocked(sourcesApi.sourceRuns).mockResolvedValue(page([]))
    vi.mocked(sourcesApi.sourceRecipeVersions).mockResolvedValue(page([recipeVersion as SourceRecipeVersion]))

    renderPage()

    await screen.findByText('Recipe Feed')
    await user.click(screen.getByRole('tab', { name: 'Post-processing' }))

    await user.click(screen.getByLabelText('Screen for relevance'))
    await user.type(screen.getByLabelText('Objective'), 'Papers on agent memory')
    await user.type(screen.getByLabelText('Include criteria (one per line)'), 'agent memory{enter}retrieval evaluation')
    await user.type(screen.getByLabelText('Exclude criteria (one per line)'), 'pure hardware optimization')

    await user.click(screen.getByRole('button', { name: 'Create rule' }))

    await waitFor(() => {
      expect(sourcesApi.createPostProcessingRule).toHaveBeenCalledWith('conn-1', expect.objectContaining({
        input_config_json: expect.objectContaining({
          relevance_profile: {
            enabled: true,
            objective: 'Papers on agent memory',
            include_criteria: ['agent memory', 'retrieval evaluation'],
            exclude_criteria: ['pure hardware optimization'],
            must_have: [],
            nice_to_have: [],
          },
        }),
      }))
    })
    expect(screen.getByRole('tab', { name: 'Post-processing' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByText('Recipe Feed post-processing')).toBeInTheDocument()
    expect(sourcesApi.getConnection).toHaveBeenCalledTimes(1)
  })

  it('saves project context and knowledge base comparison as separate judging context options', async () => {
    const user = userEvent.setup()
    vi.mocked(projectsApi.list).mockResolvedValue(page([{
      id: 'project-1',
      space_id: 'space-1',
      owner_user_id: 'user-1',
      name: 'Agent Memory Research',
      description: null,
      status: 'active',
      current_focus: 'Screen papers for agent memory work',
      settings_json: null,
      created_at: '2026-07-01T00:00:00.000Z',
      updated_at: '2026-07-01T00:00:00.000Z',
      archived_at: null,
    }]))
    vi.mocked(sourcesApi.getConnection).mockResolvedValue({
      ...baseConnection,
      handler_kind: 'recipe',
      active_handler_version_id: null,
      active_recipe_version_id: 'recipe-version-1',
    } as SourceConnection)
    vi.mocked(sourcesApi.sourceRuns).mockResolvedValue(page([]))
    vi.mocked(sourcesApi.sourceRecipeVersions).mockResolvedValue(page([recipeVersion as SourceRecipeVersion]))

    renderPage()

    await screen.findByText('Recipe Feed')
    await user.click(screen.getByRole('tab', { name: 'Post-processing' }))
    await user.selectOptions(screen.getByDisplayValue('No project'), 'project-1')
    await user.click(screen.getByText('Advanced options'))
    await user.click(screen.getByLabelText(/Use project context/))
    await user.click(screen.getByLabelText(/Compare with knowledge base/))

    await user.click(screen.getByRole('button', { name: 'Create rule' }))

    await waitFor(() => {
      expect(sourcesApi.createPostProcessingRule).toHaveBeenCalledWith('conn-1', expect.objectContaining({
        project_id: 'project-1',
        input_config_json: expect.objectContaining({
          retrieval_context: {
            enabled: true,
            domains: ['project', 'knowledge'],
            max_results_per_domain: 6,
            mode: 'hybrid',
          },
        }),
      }))
    })
  })

  it('allows external model processing from the post-processing tab', async () => {
    const user = userEvent.setup()
    vi.mocked(sourcesApi.getConnection).mockResolvedValue({
      ...baseConnection,
      handler_kind: 'recipe',
      active_handler_version_id: null,
      active_recipe_version_id: 'recipe-version-1',
    } as SourceConnection)
    vi.mocked(sourcesApi.sourceRuns).mockResolvedValue(page([]))
    vi.mocked(sourcesApi.sourceRecipeVersions).mockResolvedValue(page([recipeVersion as SourceRecipeVersion]))
    vi.mocked(sourcesApi.updateConnection).mockResolvedValue({
      ...baseConnection,
      consent_json: { allow_external_model_egress: true },
      policy_json: { source_egress_class: 'external_provider_allowed' },
      handler_kind: 'recipe',
      active_handler_version_id: null,
      active_recipe_version_id: 'recipe-version-1',
    } as SourceConnection)

    renderPage()

    await screen.findByText('Recipe Feed')
    await user.click(screen.getByRole('tab', { name: 'Post-processing' }))
    expect(screen.getByText('External model blocked')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /allow external model/i }))

    await waitFor(() => {
      expect(sourcesApi.updateConnection).toHaveBeenCalledWith('conn-1', {
        consent: { allow_external_model_egress: true },
        policy: { source_egress_class: 'external_provider_allowed' },
      })
    })
    await waitFor(() => {
      expect(screen.queryByText('External model blocked')).not.toBeInTheDocument()
    })
  })

  it('shows live status while a post-processing rule runs manually', async () => {
    const user = userEvent.setup()
    const rule = postProcessingRule()
    let resolveRun: (run: SourcePostProcessingRun) => void = () => undefined
    vi.mocked(sourcesApi.getConnection).mockResolvedValue({
      ...baseConnection,
      handler_kind: 'recipe',
      active_handler_version_id: null,
      active_recipe_version_id: 'recipe-version-1',
    } as SourceConnection)
    vi.mocked(sourcesApi.sourceRuns).mockResolvedValue(page([]))
    vi.mocked(sourcesApi.sourceRecipeVersions).mockResolvedValue(page([recipeVersion as SourceRecipeVersion]))
    vi.mocked(sourcesApi.postProcessingRules).mockResolvedValue([rule])
    vi.mocked(sourcesApi.postProcessingBacklog).mockResolvedValue({
      source_connection_id: 'conn-1',
      rules: [{
        rule_id: rule.id,
        rule_name: rule.name,
        status: rule.status,
        trigger_type: rule.trigger_type,
        pending_item_count: 3,
        batch_size: 10,
        max_batches_per_event: 10,
        cursor_json: null,
        last_fired_at: null,
        last_run: null,
        last_success_run: null,
        last_failed_run: null,
      }],
    })
    vi.mocked(sourcesApi.runPostProcessingRule).mockReturnValue(new Promise(resolve => {
      resolveRun = resolve
    }))

    renderPage()

    await screen.findByText('Recipe Feed')
    await user.click(screen.getByRole('tab', { name: 'Post-processing' }))
    await user.click(screen.getByRole('button', { name: /^Run$/ }))

    expect(await screen.findByText('Running post-processing')).toBeInTheDocument()
    expect(screen.getByText('Running the next batch for this rule.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /running/i })).toBeDisabled()

    resolveRun(postProcessingRun())

    await waitFor(() => {
      expect(screen.getByText('Post-processing run finished')).toBeInTheDocument()
      expect(screen.getByText('Run completed successfully.')).toBeInTheDocument()
    })
  })

  it('blocks submitting relevance screening with no objective or include criteria', async () => {
    const user = userEvent.setup()
    vi.mocked(sourcesApi.getConnection).mockResolvedValue({
      ...baseConnection,
      handler_kind: 'recipe',
      active_handler_version_id: null,
      active_recipe_version_id: 'recipe-version-1',
    } as SourceConnection)
    vi.mocked(sourcesApi.sourceRuns).mockResolvedValue(page([]))
    vi.mocked(sourcesApi.sourceRecipeVersions).mockResolvedValue(page([recipeVersion as SourceRecipeVersion]))

    renderPage()

    await screen.findByText('Recipe Feed')
    await user.click(screen.getByRole('tab', { name: 'Post-processing' }))

    await user.click(screen.getByLabelText('Screen for relevance'))
    await user.type(screen.getByLabelText('Exclude criteria (one per line)'), 'pure hardware optimization')
    await user.click(screen.getByRole('button', { name: 'Create rule' }))

    expect(sourcesApi.createPostProcessingRule).not.toHaveBeenCalled()
  })

  it('omits relevance_profile from the payload when the checkbox is unchecked after typing criteria', async () => {
    const user = userEvent.setup()
    vi.mocked(sourcesApi.getConnection).mockResolvedValue({
      ...baseConnection,
      handler_kind: 'recipe',
      active_handler_version_id: null,
      active_recipe_version_id: 'recipe-version-1',
    } as SourceConnection)
    vi.mocked(sourcesApi.sourceRuns).mockResolvedValue(page([]))
    vi.mocked(sourcesApi.sourceRecipeVersions).mockResolvedValue(page([recipeVersion as SourceRecipeVersion]))

    renderPage()

    await screen.findByText('Recipe Feed')
    await user.click(screen.getByRole('tab', { name: 'Post-processing' }))

    await user.click(screen.getByLabelText('Screen for relevance'))
    await user.type(screen.getByLabelText('Objective'), 'Papers on agent memory')
    await user.click(screen.getByLabelText('Screen for relevance'))
    await user.click(screen.getByRole('button', { name: 'Create rule' }))

    await waitFor(() => {
      expect(sourcesApi.createPostProcessingRule).toHaveBeenCalled()
    })
    const body = vi.mocked(sourcesApi.createPostProcessingRule).mock.calls[0]?.[1] as { input_config_json?: Record<string, unknown> }
    expect(body.input_config_json?.relevance_profile).toBeUndefined()
  })
})
