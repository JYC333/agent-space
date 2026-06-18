import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

const { listMock } = vi.hoisted(() => ({ listMock: vi.fn() }))

vi.mock('../api/client', () => ({
  authApi: { mySpaces: vi.fn().mockResolvedValue([]) },
  providersApi: { list: listMock, create: vi.fn(), delete: vi.fn(), test: vi.fn(), patch: vi.fn(), grant: vi.fn() },
}))

vi.mock('../contexts/SpaceContext', () => ({
  useSpace: () => ({ activeSpaceId: 'personal-1', activeSpaceName: 'My Personal' }),
}))

import ModelProvidersPage from '../modules/providers/ModelProvidersPage'

const EMPTY = /no model providers configured/i

const provider = {
  id: 'p1', space_id: 'personal-1', name: 'My OpenAI', provider_type: 'openai',
  base_url: 'https://api.openai.com/v1', claude_compatible_base_url: null, openai_compatible_base_url: 'https://api.openai.com/v1', default_model: 'gpt-4o', available_models: ['gpt-4o'],
  enabled: true, is_default: true, has_api_key: true, created_at: '', updated_at: '',
}

describe('ModelProvidersPage — open add form takes over the view', () => {
  beforeEach(() => { listMock.mockReset() })

  it('shows the empty-state when there are no providers and the form is closed', async () => {
    listMock.mockResolvedValue([])
    render(<ModelProvidersPage />)
    expect(await screen.findByText(EMPTY)).toBeInTheDocument()
  })

  it('hides the empty-state while the add form is open', async () => {
    listMock.mockResolvedValue([])
    render(<ModelProvidersPage />)
    await screen.findByText(EMPTY)
    fireEvent.click(screen.getByRole('button', { name: /add provider/i }))
    // The form is open now; the "no providers" notice must not also be shown.
    expect(screen.queryByText(EMPTY)).toBeNull()
    expect(screen.getByText(/set as default provider/i)).toBeInTheDocument()
  })

  it('hides the existing provider list while the add form is open', async () => {
    listMock.mockResolvedValue([provider])
    render(<ModelProvidersPage />)
    expect(await screen.findByText('My OpenAI')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /add provider/i }))
    // Existing providers are not shown mid-add.
    expect(screen.queryByText('My OpenAI')).toBeNull()
  })

  it('applies the MiniMax preset to the add form', async () => {
    listMock.mockResolvedValue([])
    render(<ModelProvidersPage />)
    await screen.findByText(EMPTY)
    fireEvent.click(screen.getByRole('button', { name: /add provider/i }))

    fireEvent.change(screen.getAllByRole('combobox')[0], { target: { value: 'minimax' } })

    expect(screen.getAllByDisplayValue('MiniMax').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByRole('combobox')[1]).toHaveValue('anthropic')
    expect(screen.getAllByDisplayValue('https://api.minimaxi.com/anthropic')).toHaveLength(2)
    expect(screen.getByDisplayValue('https://api.minimaxi.com/v1')).toBeInTheDocument()
    expect(screen.getByDisplayValue('MiniMax-M3')).toBeInTheDocument()
    expect(screen.getByDisplayValue(
      'MiniMax-M3, MiniMax-M2.7, MiniMax-M2.7-highspeed, MiniMax-M2.5, MiniMax-M2.5-highspeed, MiniMax-M2.1, MiniMax-M2.1-highspeed, MiniMax-M2',
    )).toBeInTheDocument()
  })
})
