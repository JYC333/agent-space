import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

// vi.mock factories are hoisted above the module body, so anything they reference
// must be created via vi.hoisted (which runs first) to avoid a TDZ error.
const { agent, listMock } = vi.hoisted(() => ({
  agent: {
    id: 'a1', space_id: 'personal-1', created_by_user_id: 'u1', name: 'Assistant',
    description: null, visibility: 'private', role_instruction: null, status: 'active',
    agent_kind: 'system_assistant', current_version_id: 'v1', source_template_id: null,
    source_template_version_id: null, model: null, system_prompt: null, created_at: '', updated_at: '',
  },
  listMock: vi.fn(),
}))

vi.mock('../api/client', () => ({
  agentsApi: { get: vi.fn().mockResolvedValue(agent), chat: vi.fn() },
  providersApi: { list: listMock },
}))

vi.mock('../contexts/SpaceContext', () => ({
  useSpace: () => ({ activeSpaceId: 'personal-1', preferredSpaceId: 'personal-1' }),
}))

import AssistantChatPage from '../modules/agents/AssistantChatPage'

function renderPage() {
  render(
    <MemoryRouter initialEntries={['/agents/a1/chat']}>
      <Routes>
        <Route path="/agents/:agentId/chat" element={<AssistantChatPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('AssistantChatPage — default model provider gating', () => {
  beforeEach(() => {
    listMock.mockReset()
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

  it('fails open (shows chat) when the providers check itself errors', async () => {
    listMock.mockRejectedValue(new Error('network'))
    renderPage()
    expect(await screen.findByPlaceholderText(/ask your assistant/i)).toBeInTheDocument()
    expect(screen.queryByText(/no model provider configured/i)).toBeNull()
  })
})
