import { useCallback, useEffect, useState } from 'react'
import { ArrowLeft, BookOpen, FileText, RefreshCw } from 'lucide-react'
import { useParams } from 'react-router-dom'
import { toast } from 'sonner'
import {
  projectResearchApi,
  projectsApi,
  providersApi,
  ApiRequestError,
  type ModelProviderOut,
} from '../../api/client'
import type { Project, ProjectResearchScanSummary, ResearchReadingList, ResearchWorkspace } from '../../types/api'
import { SpaceLink as Link } from '../../core/spaceNav'
import { StatusBadge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Card } from '../../components/ui/card'
import { EmptyState } from '../../components/ui/empty-state'
import { Select } from '../../components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../components/ui/tabs'
import { Textarea } from '../../components/ui/textarea'
import { errMsg } from '../../lib/utils'
import { defaultModelProvider } from '../providers/defaultProvider'
import { ChecklistView } from './researchWorkspace/ChecklistView'
import { SECTION_LABELS } from './researchWorkspace/constants'
import { NotebookSectionCard } from './researchWorkspace/NotebookView'
import { ReadingListView } from './researchWorkspace/ReadingListView'

export default function ResearchWorkspacePage() {
  const { projectId = '' } = useParams()
  const [project, setProject] = useState<Project | null>(null)
  const [workspace, setWorkspace] = useState<ResearchWorkspace | null>(null)
  const [reading, setReading] = useState<ResearchReadingList | null>(null)
  const [providers, setProviders] = useState<ModelProviderOut[]>([])
  const [monitoring, setMonitoring] = useState<ProjectResearchScanSummary[]>([])
  const [tab, setTab] = useState('notebook')
  const [loading, setLoading] = useState(true)
  const [notInitialized, setNotInitialized] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [askPrompt, setAskPrompt] = useState('')
  const [askSection, setAskSection] = useState('understanding')
  const [askProvider, setAskProvider] = useState('')
  const [asking, setAsking] = useState(false)
  const [generatingReport, setGeneratingReport] = useState(false)

  async function loadReading() {
    if (projectId) setReading(await projectResearchApi.readingList(projectId))
  }

  const refreshWorkspace = useCallback(async () => {
    try {
      setWorkspace(await projectResearchApi.workspace(projectId))
    } catch (error) {
      toast.error(errMsg(error))
    }
  }, [projectId])

  useEffect(() => {
    if (!projectId) return
    setLoading(true)
    setNotInitialized(false)
    setLoadError(null)
    void Promise.all([
      projectsApi.get(projectId),
      // Writers get the workspace created on first visit; readers on an
      // uninitialized project fall through to the empty state below.
      projectResearchApi.initializeWorkspace(projectId).catch((error) => {
        if (error instanceof ApiRequestError && error.status === 404) return null
        throw error
      }),
      projectResearchApi.readingList(projectId),
      providersApi.list(),
      projectResearchApi.scanSummaries(projectId, 5),
    ]).then(([nextProject, nextWorkspace, nextReading, nextProviders, nextMonitoring]) => {
      setProject(nextProject)
      setWorkspace(nextWorkspace)
      setNotInitialized(!nextWorkspace)
      setReading(nextReading)
      setProviders(nextProviders.filter((provider) => provider.enabled))
      setAskProvider(defaultModelProvider(nextProviders)?.id ?? '')
      setMonitoring(nextMonitoring)
    }).catch((error) => {
      const message = errMsg(error)
      setLoadError(message)
      toast.error(message)
    }).finally(() => setLoading(false))
  }, [projectId])

  async function askAi() {
    if (!askPrompt.trim() || !askProvider) return
    setAsking(true)
    try {
      const result = await projectResearchApi.askAi(projectId, {
        prompt: askPrompt,
        section_key: askSection,
        execution: { model_provider_id: askProvider },
      })
      toast.success(`Analysis queued · run ${result.run_id.slice(0, 8)} · ${result.daily_limit - result.daily_used} ad-hoc runs left today. The notebook updates when it finishes; every AI edit can be rolled back.`)
      setAskPrompt('')
    } catch (error) {
      toast.error(errMsg(error))
    } finally {
      setAsking(false)
    }
  }

  async function generateReport() {
    setGeneratingReport(true)
    try {
      const operation = await projectResearchApi.generateReportSnapshot(projectId)
      toast.success(`Report snapshot queued · operation ${operation.id.slice(0, 8)}`)
    } catch (error) {
      toast.error(errMsg(error))
    } finally {
      setGeneratingReport(false)
    }
  }

  if (loading) {
    return <div className="p-6 text-sm text-muted-foreground">Loading research workspace…</div>
  }
  if (loadError) {
    return (
      <div className="p-6">
        <Link to={`/projects/${projectId}`}><Button variant="ghost" size="sm"><ArrowLeft className="size-4" />Project</Button></Link>
        <EmptyState title="Research workspace unavailable" description={loadError} />
      </div>
    )
  }
  if (notInitialized || !workspace) {
    return (
      <div className="p-6">
        <Link to={`/projects/${projectId}`}><Button variant="ghost" size="sm"><ArrowLeft className="size-4" />Project</Button></Link>
        <EmptyState
          title="Research workspace not initialized"
          description="A project writer opens this page once to create the notebook, reading list, and checklist."
        />
      </div>
    )
  }

  return (
    <div className="space-y-5 p-4 md:p-6">
      <header className="flex flex-wrap items-center gap-3">
        <Link to={`/projects/${projectId}`}><Button variant="ghost" size="sm"><ArrowLeft className="size-4" />Project</Button></Link>
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-xl font-semibold">{project?.current_focus ?? project?.name ?? 'Research workspace'}</h1>
          <p className="text-sm text-muted-foreground">Living research documents evolve independently from report snapshots.</p>
        </div>
        <Button size="sm" variant="ghost" onClick={() => void refreshWorkspace()}><RefreshCw className="size-3.5" />Refresh</Button>
      </header>
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_18rem]">
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList className="grid w-full grid-cols-4">
            <TabsTrigger value="notebook"><BookOpen className="mr-1 size-4" />Notebook</TabsTrigger>
            <TabsTrigger value="reading">Reading List</TabsTrigger>
            <TabsTrigger value="checklist">Checklist</TabsTrigger>
            <TabsTrigger value="reports"><FileText className="mr-1 size-4" />Reports</TabsTrigger>
          </TabsList>
          <TabsContent value="notebook" className="space-y-4">
            {workspace.notebook.sections.map((section) => (
              <NotebookSectionCard
                key={section.id}
                projectId={projectId}
                section={section}
                onSaved={(next) => setWorkspace((current) => current ? {
                  ...current,
                  notebook: {
                    ...current.notebook,
                    sections: current.notebook.sections.map((value) => value.id === next.id ? next : value),
                  },
                } : current)}
              />
            ))}
          </TabsContent>
          <TabsContent value="reading"><ReadingListView projectId={projectId} value={reading} reload={loadReading} /></TabsContent>
          <TabsContent value="checklist">
            <ChecklistView
              projectId={projectId}
              items={workspace.checklist}
              onChange={(items) => setWorkspace({ ...workspace, checklist: items })}
            />
          </TabsContent>
          <TabsContent value="reports" className="space-y-3">
            <div className="flex justify-end">
              <Button size="sm" variant="outline" disabled={generatingReport} onClick={() => void generateReport()}>
                <RefreshCw className="size-3.5" />{generatingReport ? 'Queueing…' : 'Generate new snapshot'}
              </Button>
            </div>
            {workspace.reports.length ? workspace.reports.map((report) => (
              <Link key={report.id} to={`/projects/${projectId}/research/reports/${report.id}`}>
                <Card className="mb-3 flex items-center justify-between p-4">
                  <div><p className="font-medium">{report.research_question}</p><p className="text-xs text-muted-foreground">Version {report.research_question_version} · {new Date(report.created_at).toLocaleString()}</p></div>
                  <StatusBadge status={report.status} />
                </Card>
              </Link>
            )) : <EmptyState title="No report snapshots" description="Completed synthesis reports will appear here." />}
          </TabsContent>
        </Tabs>
        <aside className="space-y-3">
          {monitoring.length > 0 && <Card className="space-y-2 p-4">
            <h2 className="font-semibold">Recent monitoring</h2>
            {monitoring.slice(0, 3).map((summary) => <div key={`${summary.workflow_id}:${summary.scan_date}`} className="border-t border-border/70 pt-2 first:border-0 first:pt-0">
              <p className="text-xs font-medium">{summary.scan_date}</p>
              {summary.integrity_alerts.length > 0 && <p className="text-xs font-medium text-destructive">{summary.integrity_alerts.length} integrity alert{summary.integrity_alerts.length === 1 ? '' : 's'}</p>}
              {summary.integrity_alerts.slice(0, 2).map((alert) => <p key={alert.id} className="truncate text-xs text-destructive">{alert.event_type.replace(/_/g, ' ')} · {alert.doi}</p>)}
              <p className="text-xs text-muted-foreground">{summary.supports_count} supports · <span className={summary.contradicts_count ? 'text-destructive' : ''}>{summary.contradicts_count} contradicts</span> · {summary.new_direction_count} new</p>
            </div>)}
          </Card>}
          <Card className="space-y-3 p-4">
            <h2 className="font-semibold">Ask AI</h2>
            <p className="text-xs text-muted-foreground">A scoped, separately budgeted run edits the notebook directly. Its change is highlighted in the section and can always be rolled back.</p>
            <Textarea value={askPrompt} onChange={(event) => setAskPrompt(event.target.value)} placeholder="Summarize, compare, or update the current understanding…" />
            <Select value={askSection} onChange={setAskSection} ariaLabel="Target notebook section" options={Object.entries(SECTION_LABELS).map(([value, label]) => ({ value, label }))} />
            <Select value={askProvider} onChange={setAskProvider} ariaLabel="AI provider" options={providers.map((provider) => ({ value: provider.id, label: provider.name }))} />
            <Button className="w-full" onClick={() => void askAi()} disabled={asking || !askPrompt.trim() || !askProvider}>{asking ? 'Queueing…' : 'Run analysis'}</Button>
          </Card>
        </aside>
      </div>
    </div>
  )
}
