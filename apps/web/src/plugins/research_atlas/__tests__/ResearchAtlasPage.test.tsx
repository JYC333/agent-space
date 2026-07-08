import { render, screen } from '@testing-library/react'
import type { ComponentType, ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { GraphProjection } from '@agent-space/protocol'
import {
  createResearchAtlasPage,
  type ResearchAtlasApi,
  type ResearchAtlasGraphViewProps,
  type ResearchAtlasPaper,
  type ResearchAtlasWebHost,
} from '../../../../../../plugins/official/research_atlas/web/src/ResearchAtlasPage'

const paper: ResearchAtlasPaper = {
  id: 'paper-1',
  title: 'Shared Graph Paper',
  abstract: null,
  publication_date: null,
  publication_year: 2026,
  paper_type: 'article',
  doi: null,
  arxiv_id: null,
  oa_status: 'unknown',
  best_oa_url: null,
  raw_author_names: [],
  merged_into_id: null,
}

const projection: GraphProjection = {
  nodes: [
    { id: 'paper:paper-1', kind: 'paper', label: 'Shared Graph Paper', metadata: { paperId: 'paper-1' } },
  ],
  edges: [],
  view: {
    mode: 'local',
    rootId: 'paper:paper-1',
    depth: 1,
    limit: 100,
    generatedAt: '2026-07-04T12:00:00.000Z',
    totalNodeCount: 1,
  },
  layout: { mode: 'force' },
}

const libraryProjection: GraphProjection = {
  nodes: [
    { id: 'paper:paper-1', kind: 'paper', label: 'Shared Graph Paper', metadata: { paperId: 'paper-1' } },
    { id: 'scholar:scholar-1', kind: 'scholar', label: 'Ada Scholar', metadata: { scholarId: 'scholar-1' } },
  ],
  edges: [{ id: 'authored_by:paper-1:scholar-1', source: 'paper:paper-1', target: 'scholar:scholar-1', kind: 'authored_by' }],
  view: {
    mode: 'global',
    limit: 250,
    generatedAt: '2026-07-04T12:00:00.000Z',
    totalNodeCount: 1,
  },
  layout: { mode: 'clustered' },
}

describe('ResearchAtlasPage graph host', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('keeps the graph view out of the overview and links to the graph page', async () => {
    const graphView = vi.fn((props: ResearchAtlasGraphViewProps) => (
      <div data-testid="atlas-graph-view">
        {props.loading ? 'loading' : `nodes:${props.projection?.nodes.length ?? 0}`}
      </div>
    ))
    const Page = createResearchAtlasPage(createHost({ graphView }))

    render(<Page />)

    expect(await screen.findByText('1 nodes - 0 edges')).toBeInTheDocument()
    expect(screen.getByText('Open graph')).toHaveAttribute('href', '/atlas/graph')
    expect(graphView).not.toHaveBeenCalled()
  })

  it('renders the graph page through the injected host GraphView', async () => {
    const graphView = vi.fn((props: ResearchAtlasGraphViewProps) => (
      <div data-testid="atlas-graph-view">
        {props.loading ? 'loading' : `nodes:${props.projection?.nodes.length ?? 0}`}
      </div>
    ))
    const Page = createResearchAtlasPage(createHost({ graphView, pathname: '/atlas/graph' }))

    render(<Page />)

    expect(await screen.findByText('nodes:2')).toBeInTheDocument()
    expect(graphView.mock.calls.some(([props]) => (
      props.projection === libraryProjection && Boolean(props.theme?.node?.paper)
    ))).toBe(true)
    expect(screen.getByRole('button', { name: 'Library' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Selected paper' })).toBeInTheDocument()
  })

  it('requests the full library graph on the graph page by default', async () => {
    const getGraph = vi.fn((params: { mode?: string }) => (
      Promise.resolve(params.mode ? libraryProjection : projection)
    ))
    const graphView = vi.fn((props: ResearchAtlasGraphViewProps) => (
      <div data-testid="atlas-graph-view">
        {props.loading ? 'loading' : `mode:${props.projection?.view.mode ?? 'none'}`}
      </div>
    ))
    const Page = createResearchAtlasPage(createHost({ graphView, pathname: '/atlas/graph', getGraph }))

    render(<Page />)

    expect(await screen.findByText('mode:global')).toBeInTheDocument()
    expect(getGraph).toHaveBeenCalledWith({ paper_id: 'paper-1' })
    expect(getGraph).toHaveBeenCalledWith({ mode: 'global' })
  })

  it('passes graph fetch failures to GraphView instead of leaving it loading', async () => {
    const graphView = vi.fn((props: ResearchAtlasGraphViewProps) => (
      <div data-testid="atlas-graph-view">
        {props.loading ? 'loading' : props.error ? `error:${props.error}` : `nodes:${props.projection?.nodes.length ?? 0}`}
      </div>
    ))
    const Page = createResearchAtlasPage(createHost({
      graphView,
      pathname: '/atlas/graph',
      getGraph: vi.fn().mockRejectedValue(new Error('graph unavailable')),
    }))

    render(<Page />)

    expect(await screen.findByText('error:graph unavailable')).toBeInTheDocument()
  })
})

function createHost(options: {
  graphView: ComponentType<ResearchAtlasGraphViewProps>
  getGraph?: ResearchAtlasApi['getGraph']
  pathname?: string
}): ResearchAtlasWebHost {
  return {
    api: {
      status: vi.fn().mockResolvedValue({
        ok: true,
        plugin_id: 'research_atlas',
        version: '0.1.0',
        scope: 'space',
        space_id: 'space-1',
      }),
      listPapers: vi.fn().mockResolvedValue({ papers: [paper], next_cursor: null }),
      importPaper: vi.fn(),
      importFile: vi.fn(),
      getPaper: vi.fn().mockResolvedValue({
        paper,
        authorships: [],
        external_ids: [],
        provenance: [],
      }),
      patchPaper: vi.fn(),
      search: vi.fn().mockResolvedValue({ results: [] }),
      getScholar: vi.fn(),
      getPaperReferences: vi.fn(),
      getPaperCitations: vi.fn(),
      getPaperRelated: vi.fn().mockResolvedValue({ references: [], citations: [], coauthors: [] }),
      getGraph: options.getGraph ?? vi.fn((params: { mode?: string }) => (
        Promise.resolve(params.mode ? libraryProjection : projection)
      )),
      listTopics: vi.fn().mockResolvedValue({ topics: [] }),
      listGroups: vi.fn().mockResolvedValue({ groups: [] }),
      createGroup: vi.fn(),
      addGroupMembership: vi.fn(),
      exportEntities: vi.fn(),
      settings: vi.fn().mockResolvedValue({ cursors: [], due_refresh_count: 0 }),
      syncSource: vi.fn(),
      listProjectPapers: vi.fn(),
      addProjectPaper: vi.fn(),
      updateProjectPaper: vi.fn(),
      removeProjectPaper: vi.fn(),
      getPluginSettings: vi.fn().mockResolvedValue({}),
      patchPluginSettings: vi.fn(),
    },
    Link: ({ to, children }: { to: string; children?: ReactNode }) => <a href={to}>{children}</a>,
    GraphView: options.graphView,
    usePluginState: () => ({ enabled: true, loading: false }),
    usePathname: () => options.pathname ?? '/atlas',
  }
}
