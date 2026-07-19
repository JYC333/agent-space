import { forwardRef, useImperativeHandle, type ReactNode } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ResearchWorkspacePage from '../ResearchWorkspacePage'
import { projectResearchApi } from '../../../api/client'
import type { Project, ProjectResearchScanSummary, ResearchNotebookRevision, ResearchNotebookSection, ResearchReadingList, ResearchWorkspace } from '../../../types/api'

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('../../../core/spaceNav', async () => {
  const { Link } = await import('react-router-dom')
  return { SpaceLink: ({ to, children, ...props }: { to: string; children: ReactNode }) => <Link to={to} {...props}>{children}</Link> }
})
vi.mock('../../../components/editor/RichTextEditor', () => ({
  RichTextEditor: forwardRef(function FakeEditor({ onChange }: { onChange?: () => void }, ref) {
    useImperativeHandle(ref, () => ({ getSnapshot: () => ({ content_json: { type: 'doc', content: [] } }) }))
    return <button onClick={onChange}>Edit document</button>
  }),
}))
vi.mock('../../../api/client', () => ({
  ApiRequestError: class ApiRequestError extends Error {
    constructor(message: string, readonly status: number) { super(message) }
  },
  projectResearchApi: {
    initializeWorkspace: vi.fn(), workspace: vi.fn(), readingList: vi.fn(), updateNotebookSection: vi.fn(),
    notebookRevisions: vi.fn(), rollbackNotebookSection: vi.fn(),
    updatePaperCard: vi.fn(), createChecklistItem: vi.fn(), updateChecklistItem: vi.fn(), deleteChecklistItem: vi.fn(),
    askAi: vi.fn(), generateReportSnapshot: vi.fn(),
    scanSummaries: vi.fn(),
  },
  projectsApi: { get: vi.fn(), updateCorpusItem: vi.fn() },
  providersApi: { list: vi.fn() },
}))

const section = {
  id: 'section-1', section_key: 'understanding', content_json: { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Original claim' }] }] }, normalized_text: 'Original claim',
  content_hash: 'hash', refs_json: [], version: 2, updated_by_user_id: null, updated_by_run_id: 'run-9', updated_at: '2026-07-19T00:00:00.000Z',
} satisfies ResearchNotebookSection
const revisions: ResearchNotebookRevision[] = [
  {
    id: 'revision-2', version: 2, content_json: section.content_json, normalized_text: section.normalized_text, refs_json: [],
    source: 'ai_monitoring', diff_json: { ops: [{ op: 'append', markdown: '## Monitoring update\n\n- Contradiction' }] },
    created_by_user_id: null, created_by_run_id: 'run-9', created_at: '2026-07-19T00:00:00.000Z',
  },
  {
    id: 'revision-1', version: 1, content_json: { type: 'doc', content: [] }, normalized_text: '', refs_json: [],
    source: 'seed', diff_json: null, created_by_user_id: null, created_by_run_id: null, created_at: '2026-07-18T00:00:00.000Z',
  },
]
const workspace = {
  notebook: { id: 'notebook-1', project_id: 'project-1', sections: [section] },
  checklist: [{ id: 'task-1', text: 'Check evidence', status: 'open', sort_order: 0, origin: 'agent', origin_run_id: 'run-1', created_at: '2026-07-19T00:00:00.000Z', updated_at: '2026-07-19T00:00:00.000Z' }],
  reports: [{ id: 'report-1', research_question: 'How?', research_question_version: 1, status: 'awaiting_review', run_kind: 'baseline', created_at: '2026-07-19T00:00:00.000Z' }],
} as ResearchWorkspace
const reading = {
  items: [{ id: 'corpus-1', source_item_id: 'source-1', triage_status: 'relevant', read_status: 'unread', source_item: { title: 'Paper one', excerpt: 'Evidence excerpt' }, paper_card: { why_md: 'Relevant', how_md: 'Trial', what_md: 'Result', stance: null } }],
  total: 1, limit: 50, offset: 0,
} as unknown as ResearchReadingList

describe('ResearchWorkspacePage', () => {
  beforeEach(async () => {
    vi.clearAllMocks()
    const api = await import('../../../api/client')
    vi.mocked(api.projectsApi.get).mockResolvedValue({ id: 'project-1', name: 'Study', current_focus: 'How?' } as Project)
    vi.mocked(projectResearchApi.initializeWorkspace).mockResolvedValue(workspace)
    vi.mocked(projectResearchApi.workspace).mockResolvedValue(workspace)
    vi.mocked(projectResearchApi.readingList).mockResolvedValue(reading)
    vi.mocked(projectResearchApi.scanSummaries).mockResolvedValue([])
    vi.mocked(projectResearchApi.updateNotebookSection).mockResolvedValue({ ...section, version: 3 })
    vi.mocked(projectResearchApi.notebookRevisions).mockResolvedValue(revisions)
    vi.mocked(projectResearchApi.rollbackNotebookSection).mockResolvedValue({ ...section, version: 3, updated_by_run_id: null })
    vi.mocked(projectResearchApi.updateChecklistItem).mockImplementation(async (_projectId, _itemId, body) => ({ ...workspace.checklist[0], ...body }))
    vi.mocked(projectResearchApi.askAi).mockResolvedValue({ run_id: 'run-12345678', job_id: 'job-1', status: 'queued', daily_limit: 20, daily_used: 1 })
    vi.mocked(projectResearchApi.generateReportSnapshot).mockResolvedValue({ id: 'operation-1' } as never)
    vi.mocked(api.providersApi.list).mockResolvedValue([{ id: 'provider-1', name: 'Provider', enabled: true }] as never)
  })

  async function renderPage() {
    render(<MemoryRouter initialEntries={['/projects/project-1/research']}><Routes><Route path="/projects/:projectId/research" element={<ResearchWorkspacePage />} /></Routes></MemoryRouter>)
    await screen.findByRole('heading', { name: 'Current understanding' })
  }

  it('saves notebook sections with optimistic versions', async () => {
    await renderPage()
    await userEvent.click(screen.getByRole('button', { name: 'Edit document' }))
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(projectResearchApi.updateNotebookSection).toHaveBeenCalledWith('project-1', 'understanding', expect.objectContaining({ base_version: 2 })))
  })

  it('highlights the latest AI edit with its diff and one-click rollback', async () => {
    await renderPage()
    expect(screen.getByText(/AI edited this section/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'View change' }))
    await userEvent.click((await screen.findAllByRole('button', { name: 'Changes' }))[0])
    expect(await screen.findByText(/## Monitoring update/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Undo AI change/ }))
    await waitFor(() => expect(projectResearchApi.rollbackNotebookSection).toHaveBeenCalledWith('project-1', 'understanding', 1))
  })

  it('restores an old version from the history panel', async () => {
    await renderPage()
    await userEvent.click(screen.getByRole('button', { name: 'History' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Restore' }))
    await waitFor(() => expect(projectResearchApi.rollbackNotebookSection).toHaveBeenCalledWith('project-1', 'understanding', 1))
  })

  it('moves corpus review, checklist, and report snapshot actions into workspace tabs', async () => {
    await renderPage()
    await userEvent.click(screen.getByRole('tab', { name: 'Reading List' }))
    expect(await screen.findByText('Paper one')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: 'Checklist' }))
    expect(await screen.findByText('Check evidence')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: /Reports/ }))
    await userEvent.click(screen.getByRole('button', { name: /Generate new snapshot/ }))
    await waitFor(() => expect(projectResearchApi.generateReportSnapshot).toHaveBeenCalledWith('project-1'))
  })

  it('shows the uninitialized empty state instead of loading forever for readers', async () => {
    const { ApiRequestError } = await import('../../../api/client')
    vi.mocked(projectResearchApi.initializeWorkspace).mockRejectedValue(new ApiRequestError('not initialized', 404))
    render(<MemoryRouter initialEntries={['/projects/project-1/research']}><Routes><Route path="/projects/:projectId/research" element={<ResearchWorkspacePage />} /></Routes></MemoryRouter>)
    expect(await screen.findByText('Research workspace not initialized')).toBeInTheDocument()
  })

  it('does not disguise server failures as an uninitialized workspace', async () => {
    const { ApiRequestError } = await import('../../../api/client')
    vi.mocked(projectResearchApi.initializeWorkspace).mockRejectedValue(new ApiRequestError('service unavailable', 503))
    render(<MemoryRouter initialEntries={['/projects/project-1/research']}><Routes><Route path="/projects/:projectId/research" element={<ResearchWorkspacePage />} /></Routes></MemoryRouter>)
    expect(await screen.findByText('Research workspace unavailable')).toBeInTheDocument()
    expect(screen.queryByText('Research workspace not initialized')).not.toBeInTheDocument()
  })

  it('surfaces contradiction and publication integrity monitoring in the workspace rail', async () => {
    vi.mocked(projectResearchApi.scanSummaries).mockResolvedValue([{
      workflow_id: 'workflow-1', scan_date: '2026-07-19', scanned_at: '2026-07-19T12:00:00.000Z',
      new_item_count: 2, relevant_count: 2, maybe_count: 0, excluded_count: 0, scan_count: 2,
      supports_count: 1, contradicts_count: 1, new_direction_count: 0,
      comparisons: [{ source_item_id: 'source-1', stance: 'contradicts', detail: 'No effect under controls.', affected_sections: ['understanding'] }],
      integrity_alerts: [{ id: 'alert-1', doi: '10.1000/retracted', event_type: 'retraction', source: 'retraction-watch', notice_doi: '10.1000/notice', detected_at: '2026-07-19T12:00:00.000Z' }],
    } satisfies ProjectResearchScanSummary])
    await renderPage()
    expect(screen.getByText('1 integrity alert')).toBeInTheDocument()
    expect(screen.getByText('retraction · 10.1000/retracted')).toBeInTheDocument()
    expect(screen.getByText(/1 contradicts/)).toBeInTheDocument()
  })
})
