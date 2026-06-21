import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { SCENES, type FilterScene, type RouteScene } from '../core/navigation'
import { SceneSidebar } from '../components/shell/SceneSidebar'

const agents = SCENES.find(s => s.id === 'agents') as RouteScene
const inbox = SCENES.find(s => s.id === 'inbox') as FilterScene
const routerFuture = { v7_relativeSplatPath: true, v7_startTransition: true } as const

describe('SceneSidebar changes by scene', () => {
  it('shows Agents sub-areas on the Agents scene', () => {
    render(<MemoryRouter initialEntries={['/spaces/personal-1/agents']} future={routerFuture}><SceneSidebar scene={agents} onCollapse={() => {}} spaceId="personal-1" /></MemoryRouter>)
    expect(screen.getByText('My agents')).toBeInTheDocument()
    expect(screen.getByText('Runs')).toBeInTheDocument()
    expect(screen.getByText('Templates')).toBeInTheDocument()
    expect(screen.getByText('Capabilities')).toBeInTheDocument()
    expect(screen.queryByText('Projects')).toBeNull()
    expect(screen.queryByText('Raw')).toBeNull()
  })

  it('shows Inbox items on the Inbox scene', () => {
    render(<MemoryRouter initialEntries={['/spaces/personal-1/activity']} future={routerFuture}><SceneSidebar scene={inbox} onCollapse={() => {}} spaceId="personal-1" /></MemoryRouter>)
    expect(screen.getByText('Raw')).toBeInTheDocument()
    expect(screen.getByText('Archived')).toBeInTheDocument()
    expect(screen.queryByText('My agents')).toBeNull()
  })
})
