import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { SCENES, type FilterScene } from '../core/navigation'
import { SceneSidebar } from '../components/shell/SceneSidebar'

const wiki = SCENES.find(s => s.id === 'wiki') as FilterScene
const inbox = SCENES.find(s => s.id === 'inbox') as FilterScene

describe('SceneSidebar changes by scene', () => {
  it('shows Wiki items on the Wiki scene', () => {
    render(<MemoryRouter initialEntries={['/spaces/personal-1/knowledge']}><SceneSidebar scene={wiki} onCollapse={() => {}} spaceId="personal-1" /></MemoryRouter>)
    expect(screen.getByText('All items')).toBeInTheDocument()
    expect(screen.getByText('Ideas')).toBeInTheDocument()
    expect(screen.queryByText('Raw')).toBeNull()
  })

  it('shows Inbox items on the Inbox scene', () => {
    render(<MemoryRouter initialEntries={['/spaces/personal-1/activity']}><SceneSidebar scene={inbox} onCollapse={() => {}} spaceId="personal-1" /></MemoryRouter>)
    expect(screen.getByText('Raw')).toBeInTheDocument()
    expect(screen.getByText('Archived')).toBeInTheDocument()
    expect(screen.queryByText('Ideas')).toBeNull()
  })
})
