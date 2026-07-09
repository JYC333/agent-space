import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import ProjectsPage from '../ProjectsPage'
import { projectPresetsApi, projectsApi } from '../../../api/client'

const navigateMock = vi.fn()

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

vi.mock('../../../contexts/SpaceContext', () => ({
  useSpace: () => ({ activeSpaceId: 'space-1', activeSpaceName: 'Space One' }),
}))

vi.mock('../../../core/spaceNav', () => ({
  useSpaceNavigate: () => navigateMock,
}))

vi.mock('../../../api/client', () => ({
  projectsApi: {
    list: vi.fn(),
    create: vi.fn(),
  },
  projectPresetsApi: {
    list: vi.fn(),
  },
}))

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(projectsApi.list).mockResolvedValue({ items: [], total: 0, limit: 100, offset: 0 })
  vi.mocked(projectPresetsApi.list).mockResolvedValue([{
    key: 'academic_research',
    name: 'Academic Research',
    description: 'Literature monitoring workflow over normal Project Sources with academic paper extraction defaults.',
    sections: ['source_monitoring', 'corpus', 'project_graph'],
    source_preset_ids: ['arxiv'],
    extraction_profile_key: 'academic_paper_v1',
    graph_lens_id: 'academic_citation_v1',
  }])
  vi.mocked(projectsApi.create).mockResolvedValue({
    id: 'project-1',
    space_id: 'space-1',
    owner_user_id: 'user-1',
    name: 'Paper map',
    description: null,
    status: 'active',
    current_focus: null,
    settings_json: { preset: 'academic_research' },
    archived_at: null,
    created_at: '2026-07-01T00:00:00.000Z',
    updated_at: '2026-07-01T00:00:00.000Z',
  })
})

describe('ProjectsPage', () => {
  it('selects the Academic Research preset at project creation time', async () => {
    render(
      <MemoryRouter>
        <ProjectsPage />
      </MemoryRouter>,
    )

    fireEvent.click(await screen.findByRole('button', { name: /new project/i }))
    fireEvent.change(screen.getByPlaceholderText('e.g. Research paper on memory systems'), { target: { value: 'Paper map' } })
    fireEvent.click(await screen.findByRole('button', { name: /academic research/i }))
    fireEvent.click(screen.getByRole('button', { name: /^create project$/i }))

    await waitFor(() => {
      expect(projectsApi.create).toHaveBeenCalledWith({
        name: 'Paper map',
        description: null,
        current_focus: null,
        settings_json: { preset: 'academic_research' },
      })
    })
    expect(navigateMock).toHaveBeenCalledWith('/projects/project-1')
  })
})
