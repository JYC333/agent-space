import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { toast } from 'sonner'
import type { SourceChannel } from '../../types/api'
import { ResearchSetupDialog } from './ResearchSetupDialog'
import { projectResearchApi, researchEngineApi, sourcesApi } from '../../api/client'

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const channel = {
  id: 'channel-1',
  status: 'active',
  name: 'Research feed',
  source_name: 'Research source',
  endpoint_url: null,
  query: { search_query: 'agent tools' },
  provider: { key: 'generic_rss', display_name: 'RSS' },
} as unknown as SourceChannel

const initialDraft = {
  research_question: 'How should agent tools be evaluated?',
  source_channel_ids: ['channel-1'],
  history_mode: 'bounded_range' as const,
  from: '2025-01-01',
  to: '2025-12-31',
  max_items: '15',
  monitoring_field: 'submittedDate' as const,
  report_depth: 'quick' as const,
  question_refine_skipped: false,
  execution: { model_provider_id: 'provider-1', model_name: '' },
}

describe('ResearchSetupDialog', () => {
  beforeEach(() => {
    window.localStorage.clear()
    vi.spyOn(sourcesApi, 'customSourceCredentials').mockReturnValue(new Promise(() => {}))
    vi.spyOn(projectResearchApi, 'saveInitialIntakeDraft').mockResolvedValue({} as never)
  })

  it('assesses an unanswerable question and lets the user adopt an actionable rewrite', async () => {
    const user = userEvent.setup()
    const onRefineQuestion = vi.fn().mockResolvedValue({
      assessment: { answerable: false, finer: { feasible: 1, interesting: 3, novel: 1, ethical: 3, relevant: 1 }, issues: ['Too broad'] },
      suggested_questions: ['How do tool-using agents recover from failed calls?'],
      sub_questions: [],
      scope: { in: ['tool use'], out: ['all agents'] },
      clarifying_questions: [{ question: 'Which agent environment?', options: ['Coding agents', 'Assistant agents'], allow_multiple: true }],
    })
    render(
      <ResearchSetupDialog
        open
        draft={{ ...initialDraft, research_question: 'agent' }}
        sourceChannels={[channel]}
        busyAction={null}
        modelProviders={[{ id: 'provider-1', name: 'Provider', provider_type: 'openai', enabled: true } as never]}
        canAct
        onOpenChange={vi.fn()}
        onSave={vi.fn().mockResolvedValue(true)}
        onRefineQuestion={onRefineQuestion}
        onStart={vi.fn()}
        onSourceCreated={vi.fn()}
        onEditQuestion={vi.fn()}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Assess question' }))
    expect(await screen.findByText('Not yet answerable')).toBeInTheDocument()
    // Refinement milestones are durably auto-saved to the server-side draft.
    expect(projectResearchApi.saveInitialIntakeDraft).toHaveBeenCalledWith('project-1', expect.objectContaining({
      question_refinement: expect.objectContaining({ assessment: expect.objectContaining({ answerable: false }) }),
    }))
    await user.click(screen.getByRole('button', { name: 'How do tool-using agents recover from failed calls?' }))
    expect(screen.getByDisplayValue('How do tool-using agents recover from failed calls?')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'How do tool-using agents recover from failed calls?' })).toHaveAttribute('aria-pressed', 'true')
    expect(projectResearchApi.saveInitialIntakeDraft).toHaveBeenLastCalledWith('project-1', expect.objectContaining({
      research_question: 'How do tool-using agents recover from failed calls?',
      question_refine_skipped: false,
    }))

    // Clarifying options are clickable, support multi-select, and combine with the Other input.
    await user.click(screen.getByRole('button', { name: 'Coding agents' }))
    await user.click(screen.getByRole('button', { name: 'Assistant agents' }))
    expect(screen.getByRole('button', { name: 'Coding agents' })).toHaveAttribute('aria-pressed', 'true')
    await user.type(screen.getByPlaceholderText('Other — add your own answer'), 'RL agents')
    await user.click(screen.getByRole('button', { name: 'Reassess with answers' }))
    const history = onRefineQuestion.mock.calls[1]![0].history as Array<{ role: string; content: string }>
    expect(history[history.length - 1]?.content).toContain('Coding agents; Assistant agents; RL agents')
  })

  it('locks discovery and start until the question passes refinement, and unlocks after adoption', async () => {
    const user = userEvent.setup()
    const onRefineQuestion = vi.fn().mockResolvedValue({
      assessment: { answerable: false, finer: { feasible: 1, interesting: 3, novel: 1, ethical: 3, relevant: 1 }, issues: ['Too broad'] },
      suggested_questions: ['How do tool-using agents recover from failed calls?'],
      sub_questions: [],
      scope: { in: [], out: [] },
      clarifying_questions: [],
    })
    render(
      <ResearchSetupDialog
        open
        draft={{ ...initialDraft, research_question: 'agent', question_refine_skipped: true }}
        sourceChannels={[channel]}
        busyAction={null}
        modelProviders={[{ id: 'provider-1', name: 'Provider', provider_type: 'openai', enabled: true } as never]}
        canAct
        onOpenChange={vi.fn()}
        onSave={vi.fn().mockResolvedValue(true)}
        onRefineQuestion={onRefineQuestion}
        onStart={vi.fn()}
        onSourceCreated={vi.fn()}
        onEditQuestion={vi.fn()}
      />,
    )

    expect(screen.getByRole('button', { name: /start initial research/i })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: /Sources/ }))
    expect(screen.getByRole('button', { name: 'Discover sources' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: /Question/ }))
    await user.click(screen.getByRole('button', { name: 'Assess question' }))
    // Still failing after assessment: the gate stays closed until a rewrite is adopted.
    expect(await screen.findByText('Not yet answerable')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /start initial research/i })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'How do tool-using agents recover from failed calls?' }))
    await user.click(screen.getByRole('button', { name: /Sources/ }))
    expect(screen.getByRole('button', { name: 'Discover sources' })).toBeEnabled()
  })

  it('interrupts start with a dedicated dialog when clarification answers were never reassessed', async () => {
    const user = userEvent.setup()
    const onStart = vi.fn()
    const onRefineQuestion = vi.fn().mockResolvedValue({
      assessment: { answerable: true, finer: { feasible: 4, interesting: 4, novel: 3, ethical: 5, relevant: 4 }, issues: [] },
      suggested_questions: ['How do tool-using agents recover from failed calls?'],
      sub_questions: [],
      scope: { in: [], out: [] },
      clarifying_questions: [{ question: 'Which agent environment?', options: ['Coding agents'], allow_multiple: false }],
    })
    render(
      <ResearchSetupDialog
        open
        draft={initialDraft}
        sourceChannels={[channel]}
        busyAction={null}
        modelProviders={[{ id: 'provider-1', name: 'Provider', provider_type: 'openai', enabled: true } as never]}
        canAct
        onOpenChange={vi.fn()}
        onSave={vi.fn().mockResolvedValue(true)}
        onRefineQuestion={onRefineQuestion}
        onStart={onStart}
        onSourceCreated={vi.fn()}
        onEditQuestion={vi.fn()}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Assess question' }))
    await user.click(await screen.findByRole('button', { name: 'Coding agents' }))
    await user.click(screen.getByRole('button', { name: /start initial research/i }))
    expect(await screen.findByText('Unused clarification answers')).toBeInTheDocument()
    expect(onStart).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: 'Start without them' }))
    expect(onStart).toHaveBeenCalledTimes(1)
  })

  it('preselects the space default provider and its default model when the draft has none', async () => {
    render(
      <ResearchSetupDialog
        open
        draft={{ ...initialDraft, execution: { model_provider_id: '', model_name: '' } }}
        sourceChannels={[channel]}
        busyAction={null}
        modelProviders={[
          { id: 'provider-1', name: 'First provider', provider_type: 'openai', enabled: true } as never,
          { id: 'provider-2', name: 'Default provider', provider_type: 'openai', enabled: true, is_default: true, default_model: 'MiniMax-M3' } as never,
        ]}
        canAct
        onOpenChange={vi.fn()}
        onSave={vi.fn().mockResolvedValue(true)}
        onRefineQuestion={vi.fn()}
        onStart={vi.fn()}
        onSourceCreated={vi.fn()}
        onEditQuestion={vi.fn()}
      />,
    )

    expect(await screen.findByText('Default provider (default)')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Assess question' })).toBeEnabled()
    await userEvent.setup().click(screen.getByRole('button', { name: /Execution/ }))
    expect(await screen.findByDisplayValue('MiniMax-M3')).toBeInTheDocument()
  })

  it('saves the draft with a visible confirmation when stepping forward', async () => {
    const user = userEvent.setup()
    render(
      <ResearchSetupDialog
        open
        draft={initialDraft}
        sourceChannels={[channel]}
        busyAction={null}
        modelProviders={[]}
        canAct
        onOpenChange={vi.fn()}
        onSave={vi.fn().mockResolvedValue(true)}
        onRefineQuestion={vi.fn()}
        onStart={vi.fn()}
        onSourceCreated={vi.fn()}
        onEditQuestion={vi.fn()}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Next' }))
    expect(projectResearchApi.saveInitialIntakeDraft).toHaveBeenCalledWith('project-1', expect.objectContaining({
      research_question: initialDraft.research_question,
    }))
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Setup progress saved to the project'))
  })

  it('keeps the refinement session when the dialog is closed and reopened', async () => {
    const user = userEvent.setup()
    const onRefineQuestion = vi.fn().mockResolvedValue({
      assessment: { answerable: false, finer: { feasible: 1, interesting: 3, novel: 1, ethical: 3, relevant: 1 }, issues: ['Too broad'] },
      suggested_questions: ['How do tool-using agents recover from failed calls?'],
      sub_questions: [],
      scope: { in: ['tool use'], out: ['all agents'] },
      clarifying_questions: [{ question: 'Which agent environment?', options: [], allow_multiple: false }],
    })
    const props = {
      draft: { ...initialDraft, research_question: 'agent' },
      sourceChannels: [channel],
      busyAction: null,
      modelProviders: [{ id: 'provider-1', name: 'Provider', provider_type: 'openai', enabled: true } as never],
      canAct: true,
      onOpenChange: vi.fn(),
      onSave: vi.fn().mockResolvedValue(true),
      onRefineQuestion,
      onStart: vi.fn(),
      onSourceCreated: vi.fn(),
      onEditQuestion: vi.fn(),
    }
    const { rerender } = render(<ResearchSetupDialog open {...props} />)
    await user.click(screen.getByRole('button', { name: 'Assess question' }))
    expect(await screen.findByText('Not yet answerable')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'How do tool-using agents recover from failed calls?' }))

    rerender(<ResearchSetupDialog open={false} {...props} />)
    rerender(<ResearchSetupDialog open {...props} />)

    expect(await screen.findByText('Not yet answerable')).toBeInTheDocument()
    expect(screen.getByText('Too broad')).toBeInTheDocument()
    expect(screen.getByDisplayValue('How do tool-using agents recover from failed calls?')).toBeInTheDocument()
    expect(onRefineQuestion).toHaveBeenCalledTimes(1)
  })

  it('keeps the in-progress refinement when the parent draft changes while the dialog stays open', async () => {
    const user = userEvent.setup()
    const onRefineQuestion = vi.fn().mockResolvedValue({
      assessment: { answerable: true, finer: { feasible: 4, interesting: 4, novel: 3, ethical: 5, relevant: 4 }, issues: [] },
      suggested_questions: ['How do tool-using agents recover from failed calls?'],
      sub_questions: [],
      scope: { in: [], out: [] },
      clarifying_questions: [],
    })
    const props = {
      sourceChannels: [channel],
      busyAction: null,
      modelProviders: [{ id: 'provider-1', name: 'Provider', provider_type: 'openai', enabled: true } as never],
      canAct: true,
      onOpenChange: vi.fn(),
      onSave: vi.fn().mockResolvedValue(true),
      onRefineQuestion,
      onStart: vi.fn(),
      onSourceCreated: vi.fn(),
      onEditQuestion: vi.fn(),
    }
    const { rerender } = render(<ResearchSetupDialog open draft={{ ...initialDraft, research_question: 'agent', question_refine_skipped: true }} {...props} />)
    await user.click(screen.getByRole('button', { name: 'Assess question' }))
    await user.click(await screen.findByRole('button', { name: 'How do tool-using agents recover from failed calls?' }))

    // A monitor confirmation refreshes the parent, which rebuilds the incoming
    // draft (different fingerprint) while the dialog is still open.
    rerender(<ResearchSetupDialog open draft={{ ...initialDraft, source_channel_ids: ['channel-1', 'channel-2'] }} {...props} />)

    expect(screen.getByDisplayValue('How do tool-using agents recover from failed calls?')).toBeInTheDocument()
    expect(screen.getByText('Answerable')).toBeInTheDocument()
  })

  it('previews engine suggestions and confirms selected providers as project sources', async () => {
    const user = userEvent.setup()
    vi.spyOn(researchEngineApi, 'search').mockResolvedValue({
      strategy: { id: 'strategy-1', status: 'completed', providers: [], hit_counts: { arxiv: 42 }, provider_errors: {}, result_count: 1 },
      candidates: [{ candidate_id: 'candidate-1', kind: 'academic_paper', title: 'Agent paper', authors: ['Ada'], source_uri: 'https://arxiv.org/abs/1', occurred_at: null, excerpt: 'Summary', providers: ['arxiv'], trust_level: 'normal' }],
      monitor_suggestions: [{ provider_key: 'arxiv', rationale: 'Recent preprints', approximate_hit_count: 42, samples: [{ title: 'Agent paper', source_uri: 'https://arxiv.org/abs/1', occurred_at: null }], create_body: {} }],
    })
    vi.spyOn(researchEngineApi, 'createMonitors').mockResolvedValue({ strategy_id: 'strategy-1', channels: [channel], bindings: [] })
    const onSourceCreated = vi.fn()
    render(
      <ResearchSetupDialog
        open
        draft={{ ...initialDraft, source_channel_ids: [] }}
        sourceChannels={[]}
        busyAction={null}
        modelProviders={[{ id: 'provider-1', name: 'Provider', provider_type: 'openai', enabled: true } as never]}
        canAct
        onOpenChange={vi.fn()}
        onSave={vi.fn().mockResolvedValue(true)}
        onRefineQuestion={vi.fn()}
        onStart={vi.fn()}
        onSourceCreated={onSourceCreated}
        onEditQuestion={vi.fn()}
      />,
    )

    await user.click(screen.getByRole('button', { name: /Sources/ }))
    await user.click(screen.getByRole('button', { name: 'Discover sources' }))
    expect(await screen.findByText(/about 42 hits/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Confirm suggested sources' }))
    expect(await screen.findByText(/Ready/)).toBeInTheDocument()
    expect(onSourceCreated).toHaveBeenCalledWith(channel)
  })

  it('preserves edited values across equivalent parent refreshes and starts with them', () => {
    const onStart = vi.fn()
    const { rerender } = render(
      <ResearchSetupDialog
        open
        draft={initialDraft}
        sourceChannels={[channel]}
        busyAction={null}
        modelProviders={[]}
        canAct
        onOpenChange={vi.fn()}
        onSave={vi.fn().mockResolvedValue(true)}
        onRefineQuestion={vi.fn()}
        onStart={onStart}
        onSourceCreated={vi.fn()}
        onEditQuestion={vi.fn()}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /Initial import/ }))
    fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '5' } })
    rerender(
      <ResearchSetupDialog
        open
        draft={{ ...initialDraft, source_channel_ids: [...initialDraft.source_channel_ids], execution: { ...initialDraft.execution } }}
        sourceChannels={[channel]}
        busyAction={null}
        modelProviders={[]}
        canAct
        onOpenChange={vi.fn()}
        onSave={vi.fn().mockResolvedValue(true)}
        onRefineQuestion={vi.fn()}
        onStart={onStart}
        onSourceCreated={vi.fn()}
        onEditQuestion={vi.fn()}
      />,
    )

    expect(screen.getByRole('spinbutton')).toHaveValue(5)
    fireEvent.click(screen.getByRole('button', { name: /start initial research/i }))

    expect(onStart).toHaveBeenCalledWith(expect.objectContaining({ max_items: 5 }))
  })
})
