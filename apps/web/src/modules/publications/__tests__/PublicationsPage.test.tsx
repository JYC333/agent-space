import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

const { listPublications, importPublication } = vi.hoisted(() => ({
  listPublications: vi.fn(),
  importPublication: vi.fn(),
}))

vi.mock('../../../api/client', () => ({
  publicationsApi: {
    list: listPublications,
    import: importPublication,
    revoke: vi.fn(),
  },
}))

vi.mock('../../../contexts/SpaceContext', () => ({
  useSpace: () => ({
    activeSpaceId: 'space-2',
    spaces: [{ id: 'space-2', name: 'Target space', type: 'team', role: 'member' }],
  }),
}))

import PublicationsPage from '../PublicationsPage'

const publication = {
  id: 'publication-1',
  source_space_id: 'space-1',
  source_resource_type: 'artifact' as const,
  source_resource_id: 'artifact-1',
  version: 1,
  snapshot_schema_version: 1,
  snapshot_hash: 'a'.repeat(64),
  title: 'Shared report',
  snapshot: {
    schema_version: 1,
    resource_type: 'artifact' as const,
    title: 'Shared report',
    payload: { content: '# Report' },
  },
  published_by_user_id: 'user-1',
  target_space_ids: ['space-2'],
  status: 'active' as const,
  created_at: '2026-07-10T10:00:00.000Z',
  updated_at: '2026-07-10T10:00:00.000Z',
  revoked_at: null,
  revoked_by_user_id: null,
  import: null,
}

describe('PublicationsPage', () => {
  it('imports a received snapshot without linking to the source resource', async () => {
    listPublications
      .mockResolvedValueOnce({ items: [publication] })
      .mockResolvedValueOnce({
        items: [{
          ...publication,
          import: {
            id: 'import-1',
            imported_resource_type: 'artifact',
            imported_resource_id: 'artifact-copy',
            imported_by_user_id: 'user-2',
            created_at: '2026-07-10T11:00:00.000Z',
          },
        }],
      })
    importPublication.mockResolvedValue({ imported_resource_id: 'artifact-copy' })

    render(
      <MemoryRouter future={{ v7_relativeSplatPath: true, v7_startTransition: true }}>
        <PublicationsPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Shared report')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Open source' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Import' }))

    await waitFor(() => expect(importPublication).toHaveBeenCalledWith('publication-1'))
    expect(await screen.findByRole('link', { name: 'Open copy' })).toHaveAttribute(
      'href',
      '/spaces/space-2/artifacts/artifact-copy',
    )
  })
})
