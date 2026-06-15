import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

// vi.mock factories are hoisted above the module body, so anything they reference
// must be created via vi.hoisted (which runs first) to avoid a TDZ error.
const { agent, listMock, getMock, messagesMock } = vi.hoisted(() => ({
  agent: {
    id: 'a1', space_id: 'personal-1', created_by_user_id: 'u1', name: 'Assistant',
    description: null, visibility: 'private', role_instruction: null, status: 'active',
    agent_kind: 'system_assistant', current_version_id: 'v1', source_template_id: null,
    source_template_version_id: null, model: null, adapter_type: 'model_api',
    requires_model_provider: true, system_prompt: null, created_at: '', updated_at: '',
  },
  listMock: vi.fn(),
  getMock: vi.fn(),
  messagesMock: vi.fn(),
}))

vi.mock('../api/client', () => ({
  agentsApi: { get: getMock, chat: vi.fn() },
  providersApi: { list: listMock },
  sessionsApi: { messages: messagesMock },
}))

vi.mock('../contexts/SpaceContext', () => ({
  useSpace: () => ({ activeSpaceId: 'personal-1', preferredSpaceId: 'personal-1' }),
}))

import AssistantChatPage from '../modules/agents/AssistantChatPage'

const routerFuture = { v7_relativeSplatPath: true, v7_startTransition: true } as const

function renderPage(entry = '/agents/a1/chat') {
  render(
    <MemoryRouter initialEntries={[entry]} future={routerFuture}>
      <Routes>
        <Route path="/agents/:agentId/chat" element={<AssistantChatPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('AssistantChatPage — default model provider gating', () => {
  beforeEach(() => {
    listMock.mockReset()
    getMock.mockReset()
    messagesMock.mockReset()
    getMock.mockResolvedValue(agent)
    messagesMock.mockResolvedValue([])
    // jsdom doesn't implement Element.scrollTo, which ChatPanel calls on mount.
    Element.prototype.scrollTo = vi.fn() as unknown as typeof Element.prototype.scrollTo
  })

  it('blocks chat with a configure-provider notice when no default provider is configured', async () => {
    // A provider exists but is not the default → backend cannot resolve one for the run.
    listMock.mockResolvedValue([{ id: 'p1', is_default: false, enabled: true }])
    renderPage()
    expect(await screen.findByText(/no model provider configured/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /configure a provider/i })).toBeInTheDocument()
    // The chat input must not render — the assistant is unusable until configured.
    expect(screen.queryByPlaceholderText(/ask your assistant/i)).toBeNull()
  })

  it('shows the chat when a default provider is configured', async () => {
    listMock.mockResolvedValue([{ id: 'p1', is_default: true, enabled: true }])
    renderPage()
    expect(await screen.findByPlaceholderText(/ask your assistant/i)).toBeInTheDocument()
    expect(screen.queryByText(/no model provider configured/i)).toBeNull()
  })

  it('shows the chat for a CLI runtime even with no default provider', async () => {
    // CLI runtimes manage their own model/login — the provider gate must not block them.
    getMock.mockResolvedValue({ ...agent, adapter_type: 'claude_code', requires_model_provider: false })
    listMock.mockResolvedValue([{ id: 'p1', is_default: false, enabled: true }])
    renderPage()
    expect(await screen.findByPlaceholderText(/ask your assistant/i)).toBeInTheDocument()
    expect(screen.queryByText(/no model provider configured/i)).toBeNull()
  })

  it('fails open (shows chat) when the providers check itself errors', async () => {
    listMock.mockRejectedValue(new Error('network'))
    renderPage()
    expect(await screen.findByPlaceholderText(/ask your assistant/i)).toBeInTheDocument()
    expect(screen.queryByText(/no model provider configured/i)).toBeNull()
  })

  it('loads persisted messages when opened with a session query param', async () => {
    listMock.mockResolvedValue([{ id: 'p1', is_default: true, enabled: true }])
    messagesMock.mockResolvedValue([
      {
        id: 'm1',
        session_id: 's1',
        space_id: 'personal-1',
        user_id: 'u1',
        role: 'user',
        content: 'What did we decide?',
        metadata_json: null,
        created_at: '',
      },
      {
        id: 'm2',
        session_id: 's1',
        space_id: 'personal-1',
        user_id: 'u1',
        role: 'assistant',
        content: 'We moved chat turns to TS.',
        metadata_json: null,
        created_at: '',
      },
    ])

    renderPage('/agents/a1/chat?session=s1')

    expect(await screen.findByText('What did we decide?')).toBeInTheDocument()
    expect(screen.getByText('We moved chat turns to TS.')).toBeInTheDocument()
    expect(messagesMock).toHaveBeenCalledWith('s1')
  })
})
