import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import ProviderSelector from '../ProviderSelector'

vi.mock('../../../api/client', () => ({
  providersApi: {
    list: vi.fn().mockResolvedValue([]),
    models: vi.fn(),
  },
}))

vi.mock('../../../contexts/SpaceContext', () => ({
  useSpace: () => ({
    activeSpaceId: 'personal-1',
    preferredSpaceId: 'personal-1',
  }),
}))

const routerFuture = { v7_relativeSplatPath: true, v7_startTransition: true } as const

describe('ProviderSelector', () => {
  it('links provider creation to the current space in the same tab', async () => {
    render(
      <MemoryRouter future={routerFuture}>
        <ProviderSelector value={null} onChange={() => {}} required />
      </MemoryRouter>,
    )

    const link = await screen.findByRole('link', { name: /define a provider/i })
    expect(link).toHaveAttribute('href', '/spaces/personal-1/providers')
    expect(link).not.toHaveAttribute('target')
  })
})
