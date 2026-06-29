import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import MemoriesPage from '../MemoriesPage'
import { knowledgeApi, memoryApi, spacesApi } from '../../../api/client'

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}))

vi.mock('../../../contexts/SpaceContext', () => ({
  useSpace: () => ({
    activeSpaceId: 'space-1',
    activeSpaceName: 'Space One',
  }),
}))

vi.mock('../../../core/spaceNav', () => ({
  SpaceLink: ({ to, children, ...props }: { to: string; children: ReactNode }) => (
    <a href={to} {...props}>{children}</a>
  ),
}))

vi.mock('../../../api/client', () => ({
  memoryApi: {
    list: vi.fn(),
    create: vi.fn(),
    delete: vi.fn(),
    retrievalSearch: vi.fn(),
    feedback: vi.fn(),
    maintenanceScan: vi.fn(),
    accessLogs: vi.fn(),
  },
  spacesApi: {
    getRetrievalSettings: vi.fn(),
  },
  knowledgeApi: {
    claimCandidatePacket: vi.fn(),
  },
}))

const disabledRankingMechanic = {
  state: 'disabled',
  calibration_artifact_id: null,
  shipped_at: null,
  eval_gate: {
    status: 'not_run',
    metric: null,
    value: null,
    threshold: 0,
    checked_at: null,
  },
} as const

const baseSettings = {
  space_id: 'space-1',
  default_search_mode: 'hybrid',
  rerank_enabled: false,
  query_rewrite_enabled: false,
  query_rewrite_default: false,
  use_query_cache: true,
  include_trace: false,
  external_egress_enabled: true,
  retrieval_tool_mode: 'off',
  context_ops_review_mode: 'admins',
  context_ops_scan_mode: 'admins',
  embedding_dimensions: 2560,
  max_results_default: 50,
  ranking_config: {
    version: 1,
    eval_gate: {
      min_primary_metric_delta: 0,
      required_evidence_artifacts: 1,
    },
    mechanics: {
      visible_edge_backlink: disabledRankingMechanic,
      candidate_owned_salience: disabledRankingMechanic,
      richer_dedup: disabledRankingMechanic,
      autocut: disabledRankingMechanic,
      semantic_results_cache: disabledRankingMechanic,
    },
  },
  created_at: '2026-06-26T00:00:00.000Z',
  updated_at: '2026-06-26T00:00:00.000Z',
} as const

function emptyAccessLogPage(offset = 0) {
  return {
    items: [],
    limit: 50,
    offset,
    returned: 0,
    has_more: false,
  }
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/memory?project_id=project-1']}>
      <MemoriesPage />
    </MemoryRouter>,
  )
}

describe('MemoriesPage maintenance and access-log UI', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(memoryApi.list).mockResolvedValue({ items: [], limit: 50, offset: 0, total: 0 })
    vi.mocked(memoryApi.accessLogs).mockResolvedValue(emptyAccessLogPage())
    vi.mocked(memoryApi.maintenanceScan).mockResolvedValue({
      findings: [],
      counts: { duplicate: 0, stale: 0, thin: 0, lifecycle_drift: 0 },
      candidate_limit: 500,
      candidates_examined: 0,
      scanned: 0,
      truncated: false,
      artifact_id: 'report-artifact-1',
      proposal_id: 'maintenance-proposal-1',
      access_safety: {},
    })
    vi.mocked(knowledgeApi.claimCandidatePacket).mockResolvedValue({
      artifact_id: 'claim-packet-artifact-1',
      proposal_id: 'claim-packet-proposal-1',
      candidate_count: 1,
      source_artifact_count: 1,
      generated_child_proposal_count: 0,
    })
    vi.mocked(spacesApi.getRetrievalSettings).mockResolvedValue(baseSettings)
  })

  it('keeps space_ops unavailable when shared review is private_only', async () => {
    vi.mocked(spacesApi.getRetrievalSettings).mockResolvedValue({
      ...baseSettings,
      context_ops_review_mode: 'private_only',
    })

    renderPage()

    expect(await screen.findByText(/space_ops review is disabled/i)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'private' }))

    expect(screen.queryByRole('button', { name: 'space_ops' })).not.toBeInTheDocument()
  })

  it('runs a project-filtered maintenance scan and creates a claim candidate packet from the report', async () => {
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /scan/i }))

    await waitFor(() => {
      expect(memoryApi.maintenanceScan).toHaveBeenCalledWith(expect.objectContaining({
        project_id: 'project-1',
        review_scope: 'private',
      }))
    })
    fireEvent.click(await screen.findByRole('button', { name: /claim packet/i }))

    await waitFor(() => {
      expect(knowledgeApi.claimCandidatePacket).toHaveBeenCalledWith({
        source_artifact_ids: ['report-artifact-1'],
        review_scope: 'private',
      })
    })
    expect(await screen.findByText('Open claim packet proposal')).toBeInTheDocument()
  })

  it('offset-paginates the access log inspector', async () => {
    vi.mocked(memoryApi.accessLogs).mockImplementation(async (params = {}) => ({
      items: [
        {
          id: params.offset ? 'log-2' : 'log-1',
          space_id: 'space-1',
          memory_id: params.offset ? 'memory-2' : 'memory-1',
          user_id: 'user-1',
          agent_id: null,
          run_id: null,
          access_type: 'maintenance_scan',
          reason: params.offset ? 'second page' : 'first page',
          accessed_at: '2026-06-26T10:00:00.000Z',
          memory_title: params.offset ? 'Second visible memory' : 'First visible memory',
          memory_scope: 'user',
          memory_visibility: 'private',
          project_id: null,
        },
      ],
      limit: 50,
      offset: params.offset ?? 0,
      returned: 1,
      has_more: !params.offset,
    }))

    renderPage()

    expect(await screen.findByText('First visible memory')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /next/i }))

    await waitFor(() => {
      expect(memoryApi.accessLogs).toHaveBeenCalledWith(expect.objectContaining({
        offset: 50,
        project_id: 'project-1',
      }))
    })
    expect(await screen.findByText('Second visible memory')).toBeInTheDocument()
    expect(screen.getByText('Showing 51-51')).toBeInTheDocument()
  })
})
