import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import type {
  EvolutionExperience,
  EvolutionProposal,
  EvolutionRunListItem,
  EvolutionSelectorDecision,
  EvolutionSignal,
  EvolutionStrategy,
  EvolutionSummaryOut,
  EvolutionTarget,
  EvolutionValidationResult,
} from '../types/api'

const routerFuture = { v7_relativeSplatPath: true, v7_startTransition: true } as const

const emptySummary: EvolutionSummaryOut = {
  active_targets: 0,
  signals_collected: 0,
  pending_proposals: 0,
  recent_runs: 0,
}

const { evolutionApiMock, providersApiMock, proposalsApiMock } = vi.hoisted(() => ({
  evolutionApiMock: {
    summary: vi.fn(),
    targets: vi.fn(),
    createTarget: vi.fn(),
    updateTarget: vi.fn(),
    signals: vi.fn(),
    targetSignals: vi.fn(),
    createSignal: vi.fn(),
    strategies: vi.fn(),
    selectorDecisions: vi.fn(),
    experiences: vi.fn(),
    runs: vi.fn(),
    proposals: vi.fn(),
    validation: vi.fn(),
    runTarget: vi.fn(),
  },
  providersApiMock: {
    list: vi.fn(),
  },
  proposalsApiMock: {
    accept: vi.fn(),
    reject: vi.fn(),
  },
}))

vi.mock('../api/client', () => ({
  evolutionApi: evolutionApiMock,
  providersApi: providersApiMock,
  proposalsApi: proposalsApiMock,
}))

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}))

vi.mock('../contexts/SpaceContext', () => ({
  useSpace: () => ({
    spaces: [{ id: 'personal-1', name: 'My Personal', type: 'personal', role: 'owner', created_at: '', updated_at: '' }],
    personalSpaceId: 'personal-1',
    activeSpaceId: null,
    activeSpaceName: null,
    preferredSpaceId: 'personal-1',
    writeTargetSpaceId: 'personal-1',
    setWriteTarget: vi.fn(),
  }),
}))

import { evolutionApi, proposalsApi } from '../api/client'
import { moduleForPath } from '../modules/registry'
import EvolutionPage from '../modules/evolution/EvolutionPage'

interface MockEvolutionData {
  summary?: EvolutionSummaryOut
  targets?: EvolutionTarget[]
  signals?: EvolutionSignal[]
  strategies?: EvolutionStrategy[]
  selectorDecisions?: EvolutionSelectorDecision[]
  experiences?: EvolutionExperience[]
  runs?: EvolutionRunListItem[]
  proposals?: EvolutionProposal[]
  validationResults?: EvolutionValidationResult[]
  providers?: Array<{
    id: string
    space_id: string
    name: string
    provider_type: string
    base_url: string
    claude_compatible_base_url: string | null
    openai_compatible_base_url: string | null
    default_model: string | null
    available_models: string[]
    enabled: boolean
    is_default: boolean
    has_api_key: boolean
    created_at: string
    updated_at: string
  }>
}

function mockEvolutionData({
  summary = emptySummary,
  targets = [],
  signals = [],
  strategies = [],
  selectorDecisions = [],
  experiences = [],
  runs = [],
  proposals = [],
  validationResults = [],
  providers = [{
    id: 'provider-1',
    space_id: 'personal-1',
    name: 'Test Provider',
    provider_type: 'openai',
    base_url: 'https://api.openai.com/v1',
    claude_compatible_base_url: null,
    openai_compatible_base_url: 'https://api.openai.com/v1',
    default_model: 'gpt-test',
    available_models: ['gpt-test'],
    enabled: true,
    is_default: true,
    has_api_key: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  }],
}: MockEvolutionData = {}) {
  evolutionApiMock.summary.mockResolvedValue(summary)
  evolutionApiMock.targets.mockResolvedValue(targets)
  evolutionApiMock.createTarget.mockResolvedValue(targets[0] ?? {
    id: 'target-created',
    space_id: 'personal-1',
    target_name: 'Created Target',
    target_type: 'agent_version',
    target_ref_type: 'capability',
    target_ref_id: 'created-capability',
    capability_key: 'created-capability',
    current_version_id: null,
    current_version: null,
    scope: 'space',
    purpose: null,
    risk_level: 'medium',
    status: 'active',
    enabled: true,
    recent_signal_count: 0,
    last_run_at: null,
    engine_policy_json: {},
    metadata_json: { agent_id: 'agent-1' },
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  })
  evolutionApiMock.updateTarget.mockResolvedValue(targets[0] ?? null)
  evolutionApiMock.signals.mockResolvedValue(signals)
  evolutionApiMock.targetSignals.mockResolvedValue(signals)
  evolutionApiMock.createSignal.mockResolvedValue(signals[0] ?? {
    id: 'signal-1',
    space_id: 'personal-1',
    target_id: 'target-1',
    target_name: 'Capture Memory Extraction',
    target_type: 'agent_version',
    capability_key: 'capture-memory-extraction',
    signal_type: 'memory_candidate_rejected',
    source_type: 'manual',
    source_id: null,
    severity: 'medium',
    summary: null,
    payload_json: {},
    created_at: '2026-01-01T00:00:00Z',
  })
  evolutionApiMock.strategies.mockResolvedValue(strategies)
  evolutionApiMock.selectorDecisions.mockResolvedValue(selectorDecisions)
  evolutionApiMock.experiences.mockResolvedValue(experiences)
  evolutionApiMock.runs.mockResolvedValue(runs)
  evolutionApiMock.proposals.mockResolvedValue(proposals)
  evolutionApiMock.validation.mockResolvedValue(validationResults)
  providersApiMock.list.mockResolvedValue(providers)
  evolutionApiMock.runTarget.mockResolvedValue({
    run_id: 'run-1',
    target_id: 'target-1',
    selector_decision_id: 'decision-1',
    selected_strategy_key: 'repair.runtime_failure',
    run_status: 'succeeded',
    proposal_ids: [],
    is_fallback_agent: false,
  })
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/evolution']} future={routerFuture}>
      <EvolutionPage />
    </MemoryRouter>,
  )
}

describe('Evolution module', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockEvolutionData()
  })

  it('registers the /evolution route module', () => {
    const module = moduleForPath('/evolution')
    expect(module?.id).toBe('evolution')
    expect(module?.perspectiveType).toBe('neutral')
  })

  it('renders the /evolution page and empty states from empty backend arrays', async () => {
    renderPage()

    expect(await screen.findByRole('heading', { name: '自进化' })).toBeInTheDocument()
    expect(screen.getByText('改进目标、触发信号、策略选择、验证经验和待审核改进的审计闭环。')).toBeInTheDocument()
    expect(await screen.findByText('暂无活跃目标。')).toBeInTheDocument()
    expect(screen.getByText('未选择改进目标。')).toBeInTheDocument()
  })

  it('renders overview counts from backend summary', async () => {
    mockEvolutionData({
      summary: {
        active_targets: 2,
        signals_collected: 7,
        pending_proposals: 1,
        recent_runs: 3,
      },
    })

    renderPage()

    expect(await screen.findAllByText('改进目标')).not.toHaveLength(0)
    expect(screen.getByText('2')).toBeInTheDocument()
    expect(screen.getByText('7')).toBeInTheDocument()
    expect(screen.getByText('1')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
  })

  it('renders a selected target and target-scoped signals, runs, proposals, and validation results', async () => {
    mockEvolutionData({
      summary: {
        active_targets: 1,
        signals_collected: 1,
        pending_proposals: 1,
        recent_runs: 1,
      },
      targets: [{
        id: 'target-1',
        space_id: null,
        target_name: 'Capture Memory Extraction',
        target_type: 'agent_version',
        target_ref_type: 'capability',
        target_ref_id: 'capture-memory-extraction',
        capability_key: 'capture-memory-extraction',
        current_version_id: null,
        current_version: null,
        scope: 'system',
        purpose: 'Improves capture classification.',
        risk_level: 'medium',
        status: 'active',
        enabled: true,
        recent_signal_count: 1,
        last_run_at: '2026-01-01T00:00:00Z',
        engine_policy_json: {},
        metadata_json: { agent_id: 'agent-1' },
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      }],
      signals: [{
        id: 'signal-1',
        space_id: 'personal-1',
        target_id: 'target-1',
        target_name: 'Capture Memory Extraction',
        target_type: 'agent_version',
        capability_key: 'capture-memory-extraction',
        signal_type: 'exploration_misclassified_as_decision',
        source_type: 'proposal',
        source_id: 'proposal-old',
        severity: 'medium',
        summary: 'Exploration became a stable decision.',
        payload_json: {},
        created_at: '2026-01-02T00:00:00Z',
      }],
      runs: [{
        run_id: 'run-123456789',
        target_id: 'target-1',
        target_name: 'Capture Memory Extraction',
        target_type: 'agent_version',
        capability_key: 'capture-memory-extraction',
        strategy_key: 'repair.runtime_failure',
        engine: 'codex_cli',
        status: 'waiting_for_review',
        created_at: '2026-01-03T00:00:00Z',
        started_at: '2026-01-03T00:00:00Z',
        artifact_count: 1,
      }],
      proposals: [{
        id: 'proposal-123456789',
        proposal_type: 'capability_update',
        target_id: 'target-1',
        target_name: 'Capture Memory Extraction',
        target_type: 'agent_version',
        capability_key: 'capture-memory-extraction',
        status: 'pending',
        summary: 'Evolution strategy produced a review-gated capability update.',
        created_at: '2026-01-03T00:00:00Z',
        created_by_run_id: 'run-123456789',
      }],
      strategies: [{
        id: 'strategy-1',
        space_id: null,
        strategy_key: 'repair.runtime_failure',
        name: 'Repair runtime failure',
        description: 'Inspect failed runtime evidence and propose a correction path.',
        category: 'repair',
        target_type: 'system',
        status: 'active',
        risk_level: 'medium',
        signals_match: ['runtime_failure'],
        preconditions_json: {},
        strategy_steps: ['collect_run_trace'],
        constraints: ['do_not_mutate_target_directly'],
        validation_policy_json: {},
        tool_policy_json: {},
        routing_hint_json: {},
        provenance_type: 'built_in',
        source_ref_json: {},
        success_count: 2,
        failure_count: 0,
        confidence_score: 0.61,
        last_selected_at: '2026-01-03T00:00:00Z',
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-03T00:00:00Z',
      }],
      selectorDecisions: [{
        id: 'decision-123456789',
        space_id: 'personal-1',
        target_id: 'target-1',
        target_name: 'Capture Memory Extraction',
        target_type: 'agent_version',
        run_id: 'run-123456789',
        selected_strategy_asset_id: 'strategy-1',
        selected_strategy_key: 'repair.runtime_failure',
        selected_strategy_name: 'Repair runtime failure',
        candidate_strategy_ids: ['strategy-1'],
        input_signal_ids: ['signal-1'],
        decision_reason: 'Selected repair.runtime_failure from 1 compatible active strategies.',
        score_trace_json: {},
        rejected_reasons_json: [],
        created_at: '2026-01-03T00:00:00Z',
      }],
      experiences: [{
        id: 'experience-123456789',
        space_id: 'personal-1',
        strategy_asset_id: 'strategy-1',
        strategy_key: 'repair.runtime_failure',
        strategy_name: 'Repair runtime failure',
        target_id: 'target-1',
        target_name: 'Capture Memory Extraction',
        source_run_id: 'run-123456789',
        source_proposal_id: null,
        experience_key: 'repair.runtime_failure/run-123456789',
        summary: 'Runtime repair plan passed review.',
        trigger_signals: ['signal-1'],
        outcome_status: 'success',
        confidence_score: 0.7,
        blast_radius_json: {},
        validation_trace_json: {},
        execution_trace_json: {},
        lessons: ['Keep the change scoped.'],
        anti_patterns: [],
        environment_fingerprint_json: {},
        provenance_type: 'run_observed',
        created_at: '2026-01-04T00:00:00Z',
      }],
      validationResults: [{
        metric_id: 'memory_candidate_reject_rate',
        label: 'Memory candidate reject rate',
        evaluator: 'rate',
        target_id: 'target-1',
        target_name: 'Capture Memory Extraction',
        value: 0.25,
        status: 'fail',
        window: '14d',
        goal: { direction: 'decrease', threshold: 0.2 },
        sample_size: 4,
        numerator_count: 1,
        denominator_count: 4,
        updated_at: '2026-01-04T00:00:00Z',
        metadata_json: {},
      }],
    })

    renderPage()
    const user = userEvent.setup()

    expect(await screen.findAllByText('Capture Memory Extraction')).not.toHaveLength(0)
    expect(evolutionApi.targetSignals).toHaveBeenCalledWith('target-1', { limit: 50 })

    await user.click(screen.getByRole('tab', { name: '触发信号' }))
    expect(await screen.findAllByText('exploration_misclassified_as_decision')).not.toHaveLength(0)

    await user.click(screen.getByRole('tab', { name: '选择的策略' }))
    expect(screen.getByText('repair.runtime_failure')).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: '选择记录' }))
    expect(screen.getByText('Selected repair.runtime_failure from 1 compatible active strategies.')).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: '验证经验' }))
    expect(screen.getByText('Runtime repair plan passed review.')).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: '运行记录' }))
    expect(screen.getByText('codex_cli')).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: '待审核改进' }))
    expect(screen.getByText('capability_update')).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: '验证' }))
    expect(screen.getByText('Memory candidate reject rate')).toBeInTheDocument()
    expect(screen.getByText('memory_candidate_reject_rate')).toBeInTheDocument()
    expect(screen.getByText('0.25')).toBeInTheDocument()
  })

  it('copies a selected target as a clone instead of updating the source target', async () => {
    mockEvolutionData({
      targets: [{
        id: 'target-1',
        space_id: null,
        target_name: 'Capture Memory Extraction',
        target_type: 'agent_version',
        target_ref_type: 'capability',
        target_ref_id: 'capture-memory-extraction',
        capability_key: 'capture-memory-extraction',
        current_version_id: null,
        current_version: null,
        scope: 'system',
        purpose: 'Improves capture classification.',
        risk_level: 'medium',
        status: 'active',
        enabled: true,
        recent_signal_count: 1,
        last_run_at: null,
        engine_policy_json: {},
        metadata_json: { agent_id: 'agent-1' },
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      }],
    })
    renderPage()
    const user = userEvent.setup()

    expect(await screen.findAllByText('Capture Memory Extraction')).not.toHaveLength(0)
    await user.click(screen.getByRole('button', { name: /复制目标/i }))
    expect(screen.getByRole('heading', { name: '复制改进目标' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /创建目标/i }))

    await waitFor(() => expect(evolutionApi.createTarget).toHaveBeenCalled())
    expect(evolutionApi.updateTarget).not.toHaveBeenCalled()
    const [body] = evolutionApiMock.createTarget.mock.calls[0]
    expect(body.target_name).toBe('Capture Memory Extraction copy')
    expect(body.metadata_json.origin).toEqual({
      type: 'clone',
      source_target_id: 'target-1',
    })
  })

  it('runs an evolution review through the backend endpoint and refreshes data', async () => {
    mockEvolutionData({
      targets: [{
        id: 'target-1',
        space_id: null,
        target_name: 'Capture Memory Extraction',
        target_type: 'agent_version',
        target_ref_type: 'capability',
        target_ref_id: 'capture-memory-extraction',
        capability_key: 'capture-memory-extraction',
        current_version_id: null,
        current_version: null,
        scope: 'system',
        purpose: 'Improves capture classification.',
        risk_level: 'medium',
        status: 'active',
        enabled: true,
        recent_signal_count: 1,
        last_run_at: null,
        engine_policy_json: {},
        metadata_json: { agent_id: 'agent-1' },
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      }],
    })

    renderPage()
    expect(await screen.findAllByText('Capture Memory Extraction')).not.toHaveLength(0)
    const button = screen.getByRole('button', { name: /创建改进计划/i })
    fireEvent.click(button)

    await waitFor(() => expect(evolutionApi.runTarget).toHaveBeenCalled())
    expect(evolutionApi.runTarget).toHaveBeenCalledWith('target-1', { agent_id: 'agent-1', mode: 'dry_run' })
    expect(evolutionApi.summary).toHaveBeenCalledTimes(2)
    expect(proposalsApi.accept).not.toHaveBeenCalled()
    expect(proposalsApi.reject).not.toHaveBeenCalled()
  })
})
