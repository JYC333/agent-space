import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AgentGroupsPage from '../AgentGroupsPage'
import { agentGroupsApi, agentsApi, runsApi } from '../../../api/client'
import type {
  AgentOut,
  AgentRunGroup,
  AgentRunGroupTimeline,
  AgentRunGroupTrace,
  Run,
} from '../../../types/api'

vi.mock('../../../api/client', () => ({
  agentsApi: {
    list: vi.fn(),
  },
  agentGroupsApi: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    timeline: vi.fn(),
    trace: vi.fn(),
    sendMessage: vi.fn(),
    pause: vi.fn(),
    resume: vi.fn(),
    cancel: vi.fn(),
  },
  runsApi: {
    get: vi.fn(),
  },
}))

vi.mock('../../../contexts/SpaceContext', () => ({
  useSpace: () => ({
    activeSpaceId: 'space-1',
    activeSpaceName: 'Space One',
  }),
}))

const routerFuture = { v7_relativeSplatPath: true, v7_startTransition: true } as const

function agent(id: string, name: string): AgentOut {
  return {
    id,
    space_id: 'space-1',
    created_by_user_id: 'user-1',
    name,
    description: null,
    visibility: 'space_shared',
    access_level: 'full',
    role_instruction: null,
    status: 'active',
    agent_kind: 'standard',
    current_version_id: `version-${id}`,
    source_template_id: null,
    source_template_version_id: null,
    model: null,
    adapter_type: 'model_api',
    requires_model_provider: true,
    system_prompt: null,
    created_at: '2026-07-05T00:00:00.000Z',
    updated_at: '2026-07-05T00:00:00.000Z',
  }
}

function group(overrides: Partial<AgentRunGroup> = {}): AgentRunGroup {
  return {
    id: 'group-1',
    space_id: 'space-1',
    root_run_id: 'run-root',
    manager_user_id: 'user-1',
    manager_agent_id: 'agent-manager',
    title: 'Research room',
    goal: 'Synthesize the current evidence.',
    status: 'active',
    budget_json: {},
    policy_snapshot_json: {},
    created_at: '2026-07-05T00:00:00.000Z',
    updated_at: '2026-07-05T00:01:00.000Z',
    ended_at: null,
    ...overrides,
  }
}

function timeline(room = group()): AgentRunGroupTimeline {
  return {
    group: room,
    members: [
      {
        id: 'member-manager',
        space_id: 'space-1',
        group_id: room.id,
        agent_id: 'agent-manager',
        role: 'manager',
        status: 'active',
        capabilities_json: {},
        context_policy_json: {},
        created_at: room.created_at,
        updated_at: room.updated_at,
      },
      {
        id: 'member-reviewer',
        space_id: 'space-1',
        group_id: room.id,
        agent_id: 'agent-reviewer',
        role: 'worker',
        status: 'active',
        capabilities_json: {},
        context_policy_json: {},
        created_at: room.created_at,
        updated_at: room.updated_at,
      },
    ],
    messages: [
      {
        id: 'message-1',
        space_id: 'space-1',
        group_id: room.id,
        run_id: 'run-root',
        parent_message_id: null,
        sender_actor_ref_json: { actor_type: 'user', user_id: 'user-1' },
        sender_user_id: 'user-1',
        sender_agent_id: null,
        message_type: 'user_instruction',
        content: 'Start with the evidence packet.',
        mentions_json: [{ agent_id: 'agent-manager' }],
        metadata_json: {},
        created_at: room.created_at,
      },
      {
        id: 'message-2',
        space_id: 'space-1',
        group_id: room.id,
        run_id: 'run-child',
        parent_message_id: null,
        sender_actor_ref_json: { actor_type: 'agent', agent_id: 'agent-reviewer' },
        sender_user_id: null,
        sender_agent_id: 'agent-reviewer',
        message_type: 'delegation_result',
        content: 'Evidence summary is ready.',
        mentions_json: [{ agent_id: 'agent-manager' }],
        metadata_json: { delegation_id: 'delegation-1' },
        created_at: room.updated_at,
      },
      {
        id: 'message-3',
        space_id: 'space-1',
        group_id: room.id,
        run_id: 'run-manager-summary',
        parent_message_id: 'message-1',
        sender_actor_ref_json: { actor_type: 'agent', agent_id: 'agent-manager' },
        sender_user_id: null,
        sender_agent_id: 'agent-manager',
        message_type: 'agent_message',
        content: 'Both reviewers are consistent.',
        mentions_json: [],
        metadata_json: { projected_from_run_id: 'run-manager-summary' },
        created_at: room.updated_at,
      },
    ],
    delegations: [
      {
        id: 'delegation-1',
        space_id: 'space-1',
        group_id: room.id,
        parent_run_id: 'run-root',
        child_run_id: 'run-child',
        request_message_id: 'message-1',
        requesting_agent_id: 'agent-manager',
        target_agent_id: 'agent-reviewer',
        requested_by_user_id: 'user-1',
        policy_decision_record_id: 'policy-1',
        status: 'succeeded',
        instruction: 'Summarize the evidence packet.',
        reason: 'runtime_delegation',
        budget_json: {},
        context_policy_json: {},
        result_summary: 'Evidence summary is ready.',
        created_at: room.created_at,
        updated_at: room.updated_at,
        completed_at: room.updated_at,
      },
    ],
  }
}

function trace(room = group()): AgentRunGroupTrace {
  return {
    group: room,
    members: timeline(room).members,
    root_run_id: 'run-root',
    timeline: timeline(room),
    child_run_ids: ['run-child'],
    artifact_ids: ['artifact-1'],
    proposal_ids: ['proposal-1'],
    policy_decision_record_ids: ['policy-1'],
  }
}

function run(id: string, overrides: Partial<Run> = {}): Run {
  return {
    id,
    space_id: 'space-1',
    agent_id: id === 'run-root' ? 'agent-manager' : 'agent-reviewer',
    agent_version_id: 'version-1',
    run_role: 'execution',
    requested_runtime_profile_id: null,
    selected_runtime_profile_id: 'profile-1',
    runtime_profile_selection_source: 'default',
    active_route_decision_id: 'route-1',
    context_snapshot_id: 'snapshot-1',
    workspace_id: null,
    session_id: null,
    parent_run_id: id === 'run-root' ? null : 'run-root',
    instructed_by_user_id: 'user-1',
    instructed_by_agent_id: id === 'run-root' ? null : 'agent-manager',
    run_type: 'agent',
    trigger_origin: id === 'run-root' ? 'manual' : 'delegation',
    status: 'succeeded',
    mode: 'live',
    prompt: null,
    instruction: null,
    scheduled_at: null,
    started_at: '2026-07-05T00:00:00.000Z',
    ended_at: '2026-07-05T00:01:00.000Z',
    created_at: '2026-07-05T00:00:00.000Z',
    updated_at: '2026-07-05T00:01:00.000Z',
    error_message: null,
    error_json: null,
    output_json: null,
    usage: null,
    selected_adapter_type: 'model_api',
    capability_id: null,
    capabilities_json: [],
    selected_model_provider_id: 'provider-1',
    resolved_model: null,
    visibility: 'space_shared',
    task_id: null,
    ...overrides,
  }
}

function renderPage() {
  return render(
    <MemoryRouter future={routerFuture}>
      <AgentGroupsPage />
    </MemoryRouter>,
  )
}

async function openExistingRoom() {
  await userEvent.click(await screen.findByRole('button', { name: /Research room/i }))
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(agentsApi.list).mockResolvedValue([
    agent('agent-manager', 'Manager'),
    agent('agent-reviewer', 'Reviewer'),
  ])
  vi.mocked(agentGroupsApi.list).mockResolvedValue({
    items: [group()],
    total: 1,
    limit: 50,
    offset: 0,
  })
  vi.mocked(agentGroupsApi.timeline).mockResolvedValue(timeline())
  vi.mocked(agentGroupsApi.trace).mockResolvedValue(trace())
  vi.mocked(runsApi.get).mockImplementation(async (id: string) => {
    if (id === 'run-root') return run('run-root')
    if (id === 'run-child') return run('run-child')
    return run(id)
  })
  vi.mocked(agentGroupsApi.create).mockResolvedValue({
    group: group({ id: 'group-new', title: 'New room', root_run_id: null }),
    members: timeline(group({ id: 'group-new', title: 'New room' })).members,
  })
  vi.mocked(agentGroupsApi.update).mockResolvedValue({
    group: group({ title: 'Updated room', goal: '' }),
  })
  vi.mocked(agentGroupsApi.sendMessage).mockResolvedValue({
    message: timeline().messages[0],
  })
})

describe('AgentGroupsPage', () => {
  it('opens a room as a chat surface and keeps audit details behind settings', async () => {
    renderPage()

    await openExistingRoom()

    expect(await screen.findByText('Both reviewers are consistent.')).toBeInTheDocument()
    expect(screen.getByText('Agent calls')).toBeInTheDocument()
    expect(screen.queryByText('Evidence summary is ready.')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /agent calls/i }))
    expect(await screen.findByText('Evidence summary is ready.')).toBeInTheDocument()
    expect(screen.queryByText('Root run')).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /settings/i }))
    expect(screen.getByText('Outputs')).toBeInTheDocument()
    expect(screen.getByText('artifact-1')).toBeInTheDocument()
    expect(screen.getByText('proposal-1')).toBeInTheDocument()
    expect(screen.queryByText('Root run')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /show audit/i }))
    expect(screen.getByText('Root run')).toBeInTheDocument()
    expect(agentGroupsApi.trace).toHaveBeenCalledWith('group-1')
    expect(runsApi.get).toHaveBeenCalledWith('run-root')
    expect(runsApi.get).toHaveBeenCalledWith('run-child')
    expect(screen.getByRole('button', { name: /cancel room work/i })).toHaveAttribute(
      'title',
      expect.stringContaining('prevents more room work'),
    )
  })

  it('renders markdown in agent chat replies', async () => {
    const room = group()
    const mdTimeline = timeline(room)
    mdTimeline.messages = mdTimeline.messages.map(message => message.id === 'message-3'
      ? {
          ...message,
          content: [
            '## Results',
            '',
            '- **Reviewer A** returned `2`',
            '- Reviewer B returned 2',
            '',
            '| Agent | Result |',
            '| --- | --- |',
            '| Reviewer A | 2 |',
          ].join('\n'),
        }
      : message)
    vi.mocked(agentGroupsApi.timeline).mockResolvedValue(mdTimeline)
    vi.mocked(agentGroupsApi.trace).mockResolvedValue({
      ...trace(room),
      timeline: mdTimeline,
    })

    renderPage()
    await openExistingRoom()

    expect(await screen.findByRole('heading', { name: 'Results' })).toBeInTheDocument()
    expect(screen.getByText((_, node) => node?.tagName.toLowerCase() === 'li' && node.textContent === 'Reviewer A returned 2')).toBeInTheDocument()
    expect(screen.getByRole('table')).toBeInTheDocument()
    expect(screen.queryByText('## Results')).not.toBeInTheDocument()
  })

  it('confirms before cancelling room work', async () => {
    renderPage()

    await openExistingRoom()
    await userEvent.click(screen.getByRole('button', { name: /settings/i }))
    await userEvent.click(await screen.findByRole('button', { name: /cancel room work/i }))

    expect(agentGroupsApi.cancel).not.toHaveBeenCalled()
    const dialog = screen.getByRole('dialog', { name: /cancel room work/i })
    expect(within(dialog).getByText(/prevents more work from starting/i)).toBeInTheDocument()

    await userEvent.click(within(dialog).getByRole('button', { name: /cancel room work/i }))

    await waitFor(() => expect(agentGroupsApi.cancel).toHaveBeenCalledWith('group-1'))
  })

  it('shows root run failure details inside the room', async () => {
    const room = group()
    const failedTimeline = timeline(room)
    failedTimeline.messages = [failedTimeline.messages[0]]
    failedTimeline.delegations = []
    vi.mocked(agentGroupsApi.timeline).mockResolvedValue(failedTimeline)
    vi.mocked(agentGroupsApi.trace).mockResolvedValue({
      ...trace(room),
      timeline: failedTimeline,
      child_run_ids: [],
      artifact_ids: [],
      proposal_ids: [],
      policy_decision_record_ids: [],
    })
    vi.mocked(runsApi.get).mockImplementation(async (id: string) => {
      if (id === 'run-root') {
        return run('run-root', {
          status: 'failed',
          error_message: 'server runtime host provider invocation failed.',
          ended_at: '2026-07-05T00:01:00.000Z',
        })
      }
      return run(id)
    })
    renderPage()

    await openExistingRoom()

    expect(await screen.findByText('Agent turn stopped')).toBeInTheDocument()
    expect((await screen.findAllByText('server runtime host provider invocation failed.')).length).toBe(1)
    expect((await screen.findAllByText('failed')).length).toBeGreaterThan(0)
    expect(screen.queryByText(/failure record/i)).not.toBeInTheDocument()
    expect(screen.getByText('No active agent work')).toBeInTheDocument()
  })

  it('shows active agents and delegated calls while room work is running', async () => {
    const room = group()
    const liveTimeline = timeline(room)
    liveTimeline.messages = [liveTimeline.messages[0]]
    liveTimeline.delegations = [{
      ...liveTimeline.delegations[0],
      status: 'running',
      result_summary: null,
      completed_at: null,
    }]
    vi.mocked(agentGroupsApi.timeline).mockResolvedValue(liveTimeline)
    vi.mocked(agentGroupsApi.trace).mockResolvedValue({
      ...trace(room),
      timeline: liveTimeline,
      artifact_ids: [],
      proposal_ids: [],
      policy_decision_record_ids: [],
    })
    vi.mocked(runsApi.get).mockImplementation(async (id: string) => {
      if (id === 'run-root') return run('run-root', { status: 'running', ended_at: null })
      if (id === 'run-child') return run('run-child', { status: 'running', ended_at: null })
      return run(id)
    })

    renderPage()

    await openExistingRoom()

    await waitFor(() => expect(screen.getByText('Running')).toBeInTheDocument())
    expect((await screen.findAllByText('Manager -> Reviewer')).length).toBeGreaterThan(0)
    expect((await screen.findAllByText('running')).length).toBeGreaterThan(0)
  })

  it('keeps refreshing when a completed run has not projected its chat message yet', async () => {
    const room = group()
    const pendingTimeline = timeline(room)
    pendingTimeline.messages = [{
      ...pendingTimeline.messages[0],
      metadata_json: {
        recipient_run_id: 'run-root',
        recipient_run_ids: ['run-root'],
      },
    }]
    pendingTimeline.delegations = []
    vi.mocked(agentGroupsApi.timeline).mockResolvedValue(pendingTimeline)
    vi.mocked(agentGroupsApi.trace).mockResolvedValue({
      ...trace(room),
      timeline: pendingTimeline,
      child_run_ids: [],
      artifact_ids: [],
      proposal_ids: [],
      policy_decision_record_ids: [],
    })
    vi.mocked(runsApi.get).mockResolvedValue(run('run-root', {
      status: 'succeeded',
      output_json: { output_text: 'Projected reply is not visible yet.' },
    }))

    renderPage()

    await openExistingRoom()

    expect(await screen.findByText('Waiting for agent messages')).toBeInTheDocument()
    await waitFor(() => expect(agentGroupsApi.timeline).toHaveBeenCalledTimes(2), { timeout: 2500 })
  })

  it('shows manager turns created by room messages', async () => {
    const room = group()
    const roomTimeline = timeline(room)
    roomTimeline.messages = [{
      ...roomTimeline.messages[0],
      id: 'message-manager-turn',
      run_id: 'run-manager-turn',
      content: 'Continue the room',
    }]
    roomTimeline.delegations = []
    vi.mocked(agentGroupsApi.timeline).mockResolvedValue(roomTimeline)
    vi.mocked(agentGroupsApi.trace).mockResolvedValue({
      ...trace(room),
      timeline: roomTimeline,
      child_run_ids: ['run-manager-turn'],
      artifact_ids: [],
      proposal_ids: [],
      policy_decision_record_ids: [],
    })
    vi.mocked(runsApi.get).mockImplementation(async (id: string) => {
      if (id === 'run-root') return run('run-root')
      if (id === 'run-manager-turn') {
        return run('run-manager-turn', {
          agent_id: 'agent-manager',
          parent_run_id: 'run-root',
          trigger_origin: 'manual',
          status: 'running',
          prompt: 'Continue the room',
          instruction: 'Synthesize the current evidence.',
          ended_at: null,
        })
      }
      return run(id)
    })

    renderPage()

    await openExistingRoom()

    expect((await screen.findAllByText('Continue the room')).length).toBeGreaterThan(0)
    expect(screen.getByText('Running')).toBeInTheDocument()
    expect(runsApi.get).toHaveBeenCalledWith('run-manager-turn')
  })

  it('keeps delegated calls scoped to their user turn inside one conversation', async () => {
    const room = group()
    const roomTimeline = timeline(room)
    roomTimeline.messages.push(
      {
        id: 'message-second-turn',
        space_id: 'space-1',
        group_id: room.id,
        run_id: 'run-second-turn',
        parent_message_id: 'message-1',
        sender_actor_ref_json: { actor_type: 'user', user_id: 'user-1' },
        sender_user_id: 'user-1',
        sender_agent_id: null,
        message_type: 'user_instruction',
        content: 'Ask the reviewer to calculate 331 + 333.',
        mentions_json: [{ agent_id: 'agent-manager' }],
        metadata_json: {},
        created_at: '2026-07-05T00:02:00.000Z',
      },
      {
        id: 'message-second-summary',
        space_id: 'space-1',
        group_id: room.id,
        run_id: 'run-second-summary',
        parent_message_id: 'message-second-turn',
        sender_actor_ref_json: { actor_type: 'agent', agent_id: 'agent-manager' },
        sender_user_id: null,
        sender_agent_id: 'agent-manager',
        message_type: 'agent_message',
        content: 'The reviewer returned 664.',
        mentions_json: [],
        metadata_json: {},
        created_at: '2026-07-05T00:04:00.000Z',
      },
    )
    roomTimeline.delegations.push({
      ...roomTimeline.delegations[0],
      id: 'delegation-2',
      parent_run_id: 'run-second-turn',
      child_run_id: 'run-child-2',
      request_message_id: 'message-second-turn',
      instruction: 'Calculate 331 + 333.',
      result_summary: '331 + 333 = 664.',
      created_at: '2026-07-05T00:03:00.000Z',
      updated_at: '2026-07-05T00:03:30.000Z',
      completed_at: '2026-07-05T00:03:30.000Z',
    })
    vi.mocked(agentGroupsApi.timeline).mockResolvedValue(roomTimeline)
    vi.mocked(agentGroupsApi.trace).mockResolvedValue({
      ...trace(room),
      timeline: roomTimeline,
      child_run_ids: ['run-child', 'run-second-turn', 'run-child-2', 'run-second-summary'],
    })
    vi.mocked(runsApi.get).mockImplementation(async (id: string) => run(id))

    renderPage()

    await openExistingRoom()

    expect(await screen.findByText('The reviewer returned 664.')).toBeInTheDocument()
    const callButtons = await screen.findAllByRole('button', { name: /agent calls/i })
    expect(callButtons).toHaveLength(2)
    expect(screen.queryByText('331 + 333 = 664.')).not.toBeInTheDocument()

    await userEvent.click(callButtons[0])
    expect(await screen.findByText('Evidence summary is ready.')).toBeInTheDocument()
    expect(screen.queryByText('331 + 333 = 664.')).not.toBeInTheDocument()

    await userEvent.click(callButtons[1])
    expect(await screen.findByText('331 + 333 = 664.')).toBeInTheDocument()
  })

  it('creates an agent room from the form', async () => {
    vi.mocked(agentGroupsApi.list).mockResolvedValueOnce({
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
    })
    renderPage()

    await screen.findByText('No rooms.')
    await userEvent.type(screen.getByLabelText('Title'), 'New room')
    await userEvent.type(screen.getByLabelText(/goal/i), 'Coordinate the review')
    await userEvent.click(screen.getByRole('button', { name: /^create$/i }))

    await waitFor(() => expect(agentGroupsApi.create).toHaveBeenCalledWith(expect.objectContaining({
      space_id: 'space-1',
      title: 'New room',
      goal: 'Coordinate the review',
      manager_agent_id: 'agent-manager',
      member_agent_ids: ['agent-manager'],
    })))
    expect(vi.mocked(agentGroupsApi.create).mock.calls[0]?.[0]).not.toHaveProperty('initial_message')
  })

  it('creates an agent room without a goal', async () => {
    vi.mocked(agentGroupsApi.list).mockResolvedValueOnce({
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
    })
    renderPage()

    await screen.findByText('No rooms.')
    await userEvent.type(screen.getByLabelText('Title'), 'No goal room')
    await userEvent.click(screen.getByRole('button', { name: /^create$/i }))

    await waitFor(() => expect(agentGroupsApi.create).toHaveBeenCalled())
    expect(vi.mocked(agentGroupsApi.create).mock.calls[0]?.[0]).toMatchObject({
      space_id: 'space-1',
      title: 'No goal room',
      manager_agent_id: 'agent-manager',
      member_agent_ids: ['agent-manager'],
    })
    expect(vi.mocked(agentGroupsApi.create).mock.calls[0]?.[0]).not.toHaveProperty('goal')
  })

  it('updates room details from settings', async () => {
    renderPage()

    await openExistingRoom()
    await userEvent.click(screen.getByRole('button', { name: /settings/i }))
    await userEvent.clear(screen.getByLabelText('Title'))
    await userEvent.type(screen.getByLabelText('Title'), 'Updated room')
    await userEvent.clear(screen.getByLabelText('Goal'))
    await userEvent.click(screen.getByRole('button', { name: /save details/i }))

    await waitFor(() => expect(agentGroupsApi.update).toHaveBeenCalledWith('group-1', {
      space_id: 'space-1',
      title: 'Updated room',
      goal: '',
    }))
  })

  it('sends room messages to the default manager recipient', async () => {
    renderPage()

    await openExistingRoom()
    await userEvent.type(screen.getByLabelText('Room message'), 'Please inspect the draft.')
    await userEvent.click(screen.getByRole('button', { name: /^send$/i }))

    await waitFor(() => expect(agentGroupsApi.sendMessage).toHaveBeenCalled())
    const body = vi.mocked(agentGroupsApi.sendMessage).mock.calls[0]?.[1]
    expect(body).toMatchObject({
      space_id: 'space-1',
      group_id: 'group-1',
      content: 'Please inspect the draft.',
      routing_mode: 'direct',
    })
    expect(body).not.toHaveProperty('recipient_agent_id')
    expect(body).not.toHaveProperty('recipient_segments')
    expect(screen.getByText('Manager default')).toBeInTheDocument()
  })

  it('routes a single explicit @mention directly to that room agent', async () => {
    renderPage()

    await openExistingRoom()
    const composer = screen.getByLabelText('Room message')
    await userEvent.type(composer, '@Rev')
    expect(await screen.findByRole('option', { name: /@Reviewer/i })).toBeInTheDocument()
    await userEvent.keyboard('{Enter}')
    await userEvent.type(composer, 'Please inspect the draft.')
    expect(screen.getByText('@Reviewer: Please inspect the draft.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /^send$/i }))

    await waitFor(() => expect(agentGroupsApi.sendMessage).toHaveBeenCalled())
    const body = vi.mocked(agentGroupsApi.sendMessage).mock.calls[0]?.[1]
    expect(body).toMatchObject({
      space_id: 'space-1',
      group_id: 'group-1',
      content: '@Reviewer Please inspect the draft.',
      routing_mode: 'direct',
      recipient_segments: [{
        recipient_agent_ids: ['agent-reviewer'],
        content: 'Please inspect the draft.',
      }],
    })
    expect(body).not.toHaveProperty('recipient_agent_id')
  })

  it('routes continuous explicit @mentions as one parallel recipient segment', async () => {
    renderPage()

    await openExistingRoom()
    const composer = screen.getByLabelText('Room message')
    await userEvent.type(composer, '@Man')
    expect(await screen.findByRole('option', { name: /@Manager/i })).toBeInTheDocument()
    await userEvent.keyboard('{Enter}')
    await userEvent.type(composer, '@Rev')
    expect(await screen.findByRole('option', { name: /@Reviewer/i })).toBeInTheDocument()
    await userEvent.keyboard('{Enter}')
    await userEvent.type(composer, 'compare notes.')
    expect(screen.getByText('Parallel direct')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /^send$/i }))

    await waitFor(() => expect(agentGroupsApi.sendMessage).toHaveBeenCalled())
    const body = vi.mocked(agentGroupsApi.sendMessage).mock.calls[0]?.[1]
    expect(body).toMatchObject({
      space_id: 'space-1',
      group_id: 'group-1',
      content: '@Manager @Reviewer compare notes.',
      routing_mode: 'direct',
      recipient_segments: [{
        recipient_agent_ids: ['agent-manager', 'agent-reviewer'],
        content: 'compare notes.',
      }],
    })
    expect(body).not.toHaveProperty('recipient_agent_id')
  })

  it('does not reuse previous segment text for a trailing unfinished @mention', async () => {
    renderPage()

    await openExistingRoom()
    const composer = screen.getByLabelText('Room message')
    await userEvent.type(composer, '@Rev')
    expect(await screen.findByRole('option', { name: /@Reviewer/i })).toBeInTheDocument()
    await userEvent.keyboard('{Enter}')
    await userEvent.type(composer, 'test ')
    await userEvent.type(composer, '@Man')
    expect(await screen.findByRole('option', { name: /@Manager/i })).toBeInTheDocument()
    await userEvent.keyboard('{Enter}')

    expect(screen.getByText('@Reviewer: test')).toBeInTheDocument()
    expect(screen.getByText('@Manager pending')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^send$/i })).toBeDisabled()
    expect(agentGroupsApi.sendMessage).not.toHaveBeenCalled()
  })

  it('routes segmented @mentions as separate recipient segments', async () => {
    renderPage()

    await openExistingRoom()
    const composer = screen.getByLabelText('Room message')
    await userEvent.type(composer, '@Man')
    expect(await screen.findByRole('option', { name: /@Manager/i })).toBeInTheDocument()
    await userEvent.keyboard('{Enter}')
    await userEvent.type(composer, 'check logic ')
    await userEvent.type(composer, '@Rev')
    expect(await screen.findByRole('option', { name: /@Reviewer/i })).toBeInTheDocument()
    await userEvent.keyboard('{Enter}')
    await userEvent.type(composer, 'check style.')
    expect(screen.getByText('Segmented direct')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /^send$/i }))

    await waitFor(() => expect(agentGroupsApi.sendMessage).toHaveBeenCalled())
    const body = vi.mocked(agentGroupsApi.sendMessage).mock.calls[0]?.[1]
    expect(body).toMatchObject({
      space_id: 'space-1',
      group_id: 'group-1',
      content: '@Manager check logic @Reviewer check style.',
      routing_mode: 'direct',
      recipient_segments: [
        { recipient_agent_ids: ['agent-manager'], content: 'check logic' },
        { recipient_agent_ids: ['agent-reviewer'], content: 'check style.' },
      ],
    })
  })

  it('previews a trailing manager mention as a normal direct segment', async () => {
    renderPage()

    await openExistingRoom()
    const composer = screen.getByLabelText('Room message')
    await userEvent.type(composer, '@Rev')
    expect(await screen.findByRole('option', { name: /@Reviewer/i })).toBeInTheDocument()
    await userEvent.keyboard('{Enter}')
    await userEvent.type(composer, 'answer 1+1 ')
    await userEvent.type(composer, '@Man')
    expect(await screen.findByRole('option', { name: /@Manager/i })).toBeInTheDocument()
    await userEvent.keyboard('{Enter}')
    await userEvent.type(composer, 'summarize the result')

    expect(screen.getByText('Segmented direct')).toBeInTheDocument()
    expect(screen.getByText('2 runs')).toBeInTheDocument()
    expect(screen.getByText('@Manager: summarize the result')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /^send$/i }))

    await waitFor(() => expect(agentGroupsApi.sendMessage).toHaveBeenCalled())
    const body = vi.mocked(agentGroupsApi.sendMessage).mock.calls[0]?.[1]
    expect(body).toMatchObject({
      space_id: 'space-1',
      group_id: 'group-1',
      content: '@Reviewer answer 1+1 @Manager summarize the result',
      routing_mode: 'direct',
      recipient_segments: [
        { recipient_agent_ids: ['agent-reviewer'], content: 'answer 1+1' },
        { recipient_agent_ids: ['agent-manager'], content: 'summarize the result' },
      ],
      metadata_json: {
        route_preview: {
          kind: 'Segmented direct',
          run_count: 2,
        },
      },
    })
  })

  it('uses explicit agent coordination mode instead of direct @ routing', async () => {
    renderPage()

    await openExistingRoom()
    const composer = screen.getByLabelText('Room message')
    await userEvent.click(screen.getByRole('button', { name: /coordinate/i }))
    await userEvent.type(composer, '@Rev')
    expect(await screen.findByRole('option', { name: /@Reviewer/i })).toBeInTheDocument()
    await userEvent.keyboard('{Enter}')
    await userEvent.type(composer, 'inspect and coordinate follow-up.')
    await userEvent.click(screen.getByRole('button', { name: /^send$/i }))

    await waitFor(() => expect(agentGroupsApi.sendMessage).toHaveBeenCalled())
    const body = vi.mocked(agentGroupsApi.sendMessage).mock.calls[0]?.[1]
    expect(body).toMatchObject({
      space_id: 'space-1',
      group_id: 'group-1',
      content: '@Reviewer inspect and coordinate follow-up.',
      routing_mode: 'agent_coordination',
    })
    expect(body).not.toHaveProperty('recipient_segments')
    expect(body?.metadata_json).toMatchObject({
      coordination_target_agent_ids: ['agent-reviewer'],
    })
    expect(screen.getAllByText('Agent coordination').length).toBeGreaterThan(0)
  })
})
