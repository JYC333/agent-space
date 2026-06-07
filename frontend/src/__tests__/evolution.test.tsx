import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import type {
  EvolutionProposal,
  EvolutionRunListItem,
  EvolutionSignal,
  EvolutionSummaryOut,
  EvolutionTarget,
  EvolutionValidationResult,
} from '../types/api'

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
  runs?: EvolutionRunListItem[]
  proposals?: EvolutionProposal[]
  validationResults?: EvolutionValidationResult[]
  providers?: Array<{
    id: string
    space_id: string
    name: string
    provider_type: string
    base_url: string | null
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
  runs = [],
  proposals = [],
  validationResults = [],
  providers = [{
    id: 'provider-1',
    space_id: 'personal-1',
    name: 'Test Provider',
    provider_type: 'openai',
    base_url: null,
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
    target_type: 'prompt',
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
    metadata_json: {},
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
    target_type: 'prompt',
    capability_key: 'capture-memory-extraction',
    signal_type: 'memory_candidate_rejected',
    source_type: 'manual',
    source_id: null,
    severity: 'medium',
    summary: null,
    payload_json: {},
    created_at: '2026-01-01T00:00:00Z',
  })
  evolutionApiMock.runs.mockResolvedValue(runs)
  evolutionApiMock.proposals.mockResolvedValue(proposals)
  evolutionApiMock.validation.mockResolvedValue(validationResults)
  providersApiMock.list.mockResolvedValue(providers)
  evolutionApiMock.runTarget.mockResolvedValue({
    run_id: 'run-1',
    target_id: 'target-1',
    context_artifact_id: 'ctx-1',
    report_artifact_id: 'report-1',
    revision_artifact_id: 'revision-1',
    proposal_id: 'proposal-1',
    proposal_type: 'prompt_update',
    run_status: 'succeeded',
  })
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/evolution']}>
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

    expect(await screen.findByRole('heading', { name: 'Evolution' })).toBeInTheDocument()
    expect(screen.getByText('Target-scoped review loops for prompts, capabilities, agents, workflows, and policies.')).toBeInTheDocument()
    expect(await screen.findByText('No active targets.')).toBeInTheDocument()
    expect(screen.getByText('No target selected.')).toBeInTheDocument()
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

    expect(await screen.findByText('Active targets')).toBeInTheDocument()
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
        target_type: 'prompt',
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
        metadata_json: {},
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      }],
      signals: [{
        id: 'signal-1',
        space_id: 'personal-1',
        target_id: 'target-1',
        target_name: 'Capture Memory Extraction',
        target_type: 'prompt',
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
        target_type: 'prompt',
        capability_key: 'capture-memory-extraction',
        engine: 'llm_prompt_review',
        status: 'succeeded',
        created_at: '2026-01-03T00:00:00Z',
        started_at: '2026-01-03T00:00:00Z',
        artifact_count: 3,
        proposal_id: 'proposal-123456789',
      }],
      proposals: [{
        id: 'proposal-123456789',
        proposal_type: 'prompt_update',
        target_id: 'target-1',
        target_name: 'Capture Memory Extraction',
        target_type: 'prompt',
        capability_key: 'capture-memory-extraction',
        status: 'pending',
        summary: 'Evolution engine proposed a scoped prompt revision.',
        created_at: '2026-01-03T00:00:00Z',
        created_by_run_id: 'run-123456789',
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

    await user.click(screen.getByRole('tab', { name: 'Signals' }))
    expect(await screen.findByText('exploration_misclassified_as_decision')).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Runs' }))
    expect(screen.getByText('llm_prompt_review')).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Proposals' }))
    expect(screen.getByText('prompt_update')).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Validation' }))
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
        target_type: 'prompt',
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
        metadata_json: {},
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      }],
    })
    renderPage()
    const user = userEvent.setup()

    expect(await screen.findAllByText('Capture Memory Extraction')).not.toHaveLength(0)
    await user.click(screen.getByRole('button', { name: /Copy target/i }))
    expect(screen.getByRole('heading', { name: 'Copy target' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Create target/i }))

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
        target_type: 'prompt',
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
        metadata_json: {},
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      }],
    })

    renderPage()
    expect(await screen.findAllByText('Capture Memory Extraction')).not.toHaveLength(0)
    const button = screen.getByRole('button', { name: /Create LLM review/i })
    fireEvent.click(button)

    await waitFor(() => expect(evolutionApi.runTarget).toHaveBeenCalled())
    expect(evolutionApi.runTarget).toHaveBeenCalledWith('target-1', { engine: 'llm_prompt_review' })
    expect(evolutionApi.summary).toHaveBeenCalledTimes(2)
    expect(proposalsApi.accept).not.toHaveBeenCalled()
    expect(proposalsApi.reject).not.toHaveBeenCalled()
  })
})
