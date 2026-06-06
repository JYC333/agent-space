import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../contexts/ThemeContext', () => ({ useTheme: () => ({ theme: 'light', toggleTheme: vi.fn() }) }))
vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ currentUser: { id: 'u1', display_name: 'Ada', email: 'a@x', avatar_url: null, default_space_id: 'personal-1', created_at: '', last_login_at: null }, logout: vi.fn() }),
}))
vi.mock('../contexts/SpaceContext', () => ({
  useSpace: () => ({
    spaces: [{ id: 'personal-1', name: 'My Personal', type: 'personal', role: 'owner', created_at: '', updated_at: '' }],
    personalSpaceId: 'personal-1',
    activeSpaceId: 'personal-1',
    activeSpaceName: 'My Personal',
    preferredSpaceId: 'personal-1',
    writeTargetSpaceId: 'personal-1',
    setWriteTarget: vi.fn(),
  }),
}))

import Shell from '../core/Shell'

describe('Shell scene sidebar collapse', () => {
  it('shows a visible expand handle in the header when the scene sidebar is collapsed', () => {
    localStorage.setItem('agent-space:scene-collapsed', JSON.stringify({ wiki: true }))
    render(<MemoryRouter initialEntries={['/spaces/personal-1/knowledge']}><Shell /></MemoryRouter>)

    // Expand handle visible in the header, labelled with the scene title (e.g. "☰ Wiki").
    const handle = screen.getByRole('button', { name: 'Show sidebar' })
    expect(handle).toBeInTheDocument()
    expect(handle).toHaveTextContent('Wiki')

    // The full sidebar is collapsed (not rendered).
    expect(screen.queryByLabelText('Wiki navigation')).toBeNull()
  })

  it('renders the scene sidebar when not collapsed', () => {
    render(<MemoryRouter initialEntries={['/spaces/personal-1/knowledge']}><Shell /></MemoryRouter>)
    expect(screen.getByLabelText('Wiki navigation')).toBeInTheDocument()
  })
})
