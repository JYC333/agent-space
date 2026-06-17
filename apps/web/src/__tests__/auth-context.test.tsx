import { describe, it, expect, vi } from 'vitest'
import { act, render, screen } from '@testing-library/react'
import { AuthProvider, useAuth } from '../contexts/AuthContext'

vi.mock('../api/client', () => ({
  setAuth: vi.fn(),
  authApi: {
    me: vi.fn().mockResolvedValue({
      id: 'u1',
      display_name: 'Ada',
      email: 'ada@example.test',
      avatar_url: null,
      default_space_id: 'personal-1',
      created_at: '',
      last_login_at: null,
    }),
    logout: vi.fn().mockResolvedValue(null),
  },
}))

function Probe() {
  const { currentUser, isLoading } = useAuth()
  if (isLoading) return <div>loading</div>
  return <div>{currentUser ? currentUser.display_name : 'signed out'}</div>
}

describe('AuthProvider', () => {
  it('clears the current user when the API reports authentication is required', async () => {
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )

    expect(await screen.findByText('Ada')).toBeInTheDocument()

    act(() => {
      window.dispatchEvent(new CustomEvent('auth:required'))
    })

    expect(screen.getByText('signed out')).toBeInTheDocument()
  })
})
