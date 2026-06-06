import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../contexts/SpaceContext', () => ({
  useSpace: () => ({
    spaces: [
      { id: 'personal-1', name: 'My Personal', type: 'personal', role: 'owner', created_at: '', updated_at: '' },
      { id: 'team-1', name: 'Acme Team', type: 'team', role: 'member', created_at: '', updated_at: '' },
    ],
    personalSpaceId: 'personal-1',
    activeSpaceId: 'team-1',
    activeSpaceName: 'Acme Team',
    writeTargetSpaceId: 'personal-1',
    setWriteTarget: vi.fn(),
  }),
}))

import { FloatingQuickCapture } from '../components/FloatingQuickCapture'

describe('FloatingQuickCapture on Home', () => {
  it('shows an explicit write target defaulting to Personal Space', () => {
    render(<MemoryRouter><FloatingQuickCapture scope="home" /></MemoryRouter>)
    // Opens from the floating button.
    fireEvent.click(screen.getByLabelText('Quick capture'))
    expect(screen.getByText('Save to:')).toBeInTheDocument()
    // Personal Space is the default Home write target (personal type → "Personal Space" label).
    expect(screen.getByText('Personal Space')).toBeInTheDocument()
  })

  it('shows the active space as target on space-scoped routes', () => {
    render(<MemoryRouter><FloatingQuickCapture scope="space" /></MemoryRouter>)
    fireEvent.click(screen.getByLabelText('Quick capture'))
    expect(screen.getByText('Save to:')).toBeInTheDocument()
    expect(screen.getByText('Acme Team')).toBeInTheDocument()
  })
})
