import { useState, useEffect, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { useSpaceNavigate as useNavigate, SpaceLink as Link } from '../../core/spaceNav'
import {
  FolderKanban, Target, Edit2, Archive, Plus, Trash2, ChevronLeft,
  Activity, Package, CheckCircle, Folder, Cpu, Database, Rss, Link2, FileText, RefreshCw,
  BookOpen, MessageSquareText,
} from 'lucide-react'
import { toast } from 'sonner'
import { projectsApi, workspacesApi, activityApi, artifactsApi, proposalsApi, runsApi, memoryApi, sourcesApi, sourceReaderApi, automationsApi, projectPresetsApi, projectResearchApi } from '../../api/client'
import { useSpace } from '../../contexts/SpaceContext'
import { errMsg, isNotFoundError } from '../../lib/utils'
import type {
  Project, ProjectSummary, ProjectWorkspaceLinkOut, Workspace,
  ActivityInboxRecord, Artifact, Proposal, Run, Memory,
  SourceConnection, ProjectSourceBinding, SourceItem, ExtractedEvidence,
  ReaderAnnotation, AutomationOut, SourcePostProcessingItemDecision,
  ProjectResearchArtifactLink, ProjectResearchCheckpoint, ProjectResearchLiteratureMatrixItem,
  ProjectResearchProfile, ProjectResearchScreeningCriteria, ProjectResearchWorkflow,
  ProjectOperation,
} from '../../types/api'
import { Card } from '../../components/ui/card'
import { Button } from '../../components/ui/button'
import { Badge, StatusBadge } from '../../components/ui/badge'
import { Label } from '../../components/ui/label'
import { Input } from '../../components/ui/input'
import { Textarea } from '../../components/ui/textarea'
import { Select } from '../../components/ui/select'
import { Skeleton } from '../../components/ui/skeleton'
import { EmptyState } from '../../components/ui/empty-state'
import { ResearchWorkflowPanel } from '../capabilities/ResearchWorkflowPanel'
import { AcademicResearchWorkbench, activeResearchWorkflowFrom } from './AcademicResearchWorkbench'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '../../components/ui/dialog'

function fmt(dt: string | null | undefined) {
  return dt ? new Date(dt).toLocaleString() : '—'
}

const WORKSPACE_ROLES = [
  { value: 'reference', label: 'Reference' },
  { value: 'primary_codebase', label: 'Primary codebase' },
  { value: 'capability_library', label: 'Capability library' },
  { value: 'docs', label: 'Docs' },
  { value: 'data', label: 'Data' },
  { value: 'deployment', label: 'Deployment' },
]

const ACADEMIC_PRESET_KEY = 'academic_research'

function presetKeyFromProject(project: Project): string | null {
  const value = project.settings_json?.preset
  return typeof value === 'string' ? value : null
}

/* ── Summary card ─────────────────────────────────────────────────────────── */
interface SummaryCardProps {
  icon: React.ReactNode
  label: string
  count: number
}

function SummaryCard({ icon, label, count }: SummaryCardProps) {
  return (
    <div className="bg-card border border-border rounded-lg p-4 flex flex-col gap-2">
      <div className="flex items-center gap-2 text-muted-foreground">
        {icon}
        <span className="text-xs font-medium uppercase tracking-wide">{label}</span>
      </div>
      <div className="text-2xl font-semibold" style={{ fontFamily: 'var(--font-mono)' }}>
        {count}
      </div>
    </div>
  )
}

/* ── Edit project dialog ──────────────────────────────────────────────────── */
interface EditDialogProps {
  project: Project
  open: boolean
  onOpenChange: (v: boolean) => void
  onSaved: (updated: Project) => void
}

function EditProjectDialog({ project, open, onOpenChange, onSaved }: EditDialogProps) {
  const [name, setName] = useState(project.name)
  const [description, setDescription] = useState(project.description ?? '')
  const [focus, setFocus] = useState(project.current_focus ?? '')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (open) {
      setName(project.name)
      setDescription(project.description ?? '')
      setFocus(project.current_focus ?? '')
    }
  }, [open, project])

  async function save() {
    if (!name.trim()) {
      toast.error('Name is required')
      return
    }
    setSaving(true)
    try {
      const updated = await projectsApi.update(project.id, {
        name: name.trim(),
        description: description.trim() || null,
        current_focus: focus.trim() || null,
      })
      toast.success('Project updated')
      onSaved(updated)
      onOpenChange(false)
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit project</DialogTitle>
          <DialogDescription className="sr-only">
            Update this project's name, description, and current focus.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <Label>Name <span className="text-destructive">*</span></Label>
            <Input value={name} onChange={e => setName(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label>Description</Label>
            <Textarea
              value={description}
              onChange={e => setDescription(e.target.value)}
              rows={3}
            />
          </div>
          <div className="space-y-1.5">
            <Label>Current focus</Label>
            <Input
              value={focus}
              onChange={e => setFocus(e.target.value)}
              placeholder="What are you actively working on right now?"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={save} disabled={saving || !name.trim()}>
            {saving ? 'Saving…' : 'Save changes'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/* ── Link workspace dialog ────────────────────────────────────────────────── */
interface LinkWorkspaceDialogProps {
  projectId: string
  existingIds: Set<string>
  open: boolean
  onOpenChange: (v: boolean) => void
  onLinked: () => void
}

function LinkWorkspaceDialog({ projectId, existingIds, open, onOpenChange, onLinked }: LinkWorkspaceDialogProps) {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [role, setRole] = useState('reference')
  const [linking, setLinking] = useState(false)

  useEffect(() => {
    if (!open) return
    workspacesApi.list({ limit: '100' }).then(p => {
      setWorkspaces(p.items.filter(w => w.status === 'active' && !existingIds.has(w.id)))
    }).catch(() => {})
    setSelectedId('')
    setRole('reference')
  }, [open, existingIds])

  const wsOptions = workspaces.map(w => ({ value: w.id, label: w.name }))

  async function submit() {
    if (!selectedId) {
      toast.error('Select a workspace')
      return
    }
    setLinking(true)
    try {
      await projectsApi.linkWorkspace(projectId, { workspace_id: selectedId, role })
      toast.success('Workspace linked')
      onLinked()
      onOpenChange(false)
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setLinking(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Link workspace</DialogTitle>
          <DialogDescription>
            Link workspaces that this project uses for code, docs, data, deployment, or reference material.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <Label>Workspace</Label>
            {wsOptions.length === 0 ? (
              <p className="text-xs text-muted-foreground">No available workspaces to link.</p>
            ) : (
              <Select value={selectedId} options={[{ value: '', label: 'Select a workspace…' }, ...wsOptions]} onChange={setSelectedId} />
            )}
          </div>
          <div className="space-y-1.5">
            <Label>Role</Label>
            <Select value={role} options={WORKSPACE_ROLES} onChange={setRole} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={submit} disabled={linking || !selectedId}>
            {linking ? 'Linking…' : 'Link workspace'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/* ── Link source dialog ───────────────────────────────────────────────────── */
interface LinkSourceConnectionDialogProps {
  projectId: string
  open: boolean
  onOpenChange: (v: boolean) => void
  connections: SourceConnection[]
  bindings: ProjectSourceBinding[]
  onLinked: () => void
}

function LinkSourceConnectionDialog({
  projectId,
  open,
  onOpenChange,
  connections,
  bindings,
  onLinked,
}: LinkSourceConnectionDialogProps) {
  const [connectionId, setConnectionId] = useState('')
  const [backfillHistory, setBackfillHistory] = useState(true)
  const [linking, setLinking] = useState(false)

  function sourceOptionsForProject() {
    return connections
      .filter(connection => !bindings.some(binding =>
        binding.source_connection_id === connection.id &&
        binding.binding_key === 'default'
      ))
      .map(connection => ({
        value: connection.id,
        label: connection.name,
      }))
  }

  useEffect(() => {
    if (!open) return
    setConnectionId(sourceOptionsForProject()[0]?.value ?? '')
    setBackfillHistory(true)
  }, [open, connections, bindings])

  const sourceOptions = sourceOptionsForProject()

  async function submit() {
    if (!connectionId) {
      toast.error('Select a source')
      return
    }
    setLinking(true)
    try {
      const binding = await sourcesApi.createProjectSourceBinding({
        project_id: projectId,
        source_connection_id: connectionId,
        backfill_history: backfillHistory,
      })
      if (binding.backfill_result) {
        toast.success(`Source linked; ${binding.backfill_result.created_links} project items added`)
      } else {
        toast.success('Source linked')
      }
      onLinked()
      onOpenChange(false)
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setLinking(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Link source</DialogTitle>
          <DialogDescription>
            Bind an existing source directly to this project.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <Label>Source</Label>
            {connections.length === 0 ? (
              <p className="text-xs text-muted-foreground">No sources are configured yet.</p>
            ) : sourceOptions.length === 0 ? (
              <p className="text-xs text-muted-foreground">All available sources are already linked to this project.</p>
            ) : (
              <Select
                value={connectionId}
                options={sourceOptions}
                onChange={setConnectionId}
              />
            )}
          </div>
          <label className="flex items-start gap-2 rounded-md border border-border px-3 py-2 text-xs">
            <input
              type="checkbox"
              className="mt-0.5 accent-primary"
              checked={backfillHistory}
              onChange={event => setBackfillHistory(event.target.checked)}
            />
            <span>
              <span className="block font-medium text-foreground">Include historical evidence</span>
              <span className="text-muted-foreground">Link already extracted source evidence into this project.</span>
            </span>
          </label>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={submit} disabled={linking || !connectionId}>
            {linking ? 'Linking…' : 'Link source'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function isManualUrlItem(item: SourceItem) {
  return item.item_type === 'external_url' && item.metadata_json?.created_by === 'manual_url'
}

interface ProjectSourceOption {
  value: string
  label: string
}

interface SaveProjectUrlDialogProps {
  open: boolean
  onOpenChange: (v: boolean) => void
  sourceOptions: ProjectSourceOption[]
  onSaved: () => void
}

function SaveProjectUrlDialog({ open, onOpenChange, sourceOptions, onSaved }: SaveProjectUrlDialogProps) {
  const [url, setUrl] = useState('')
  const [title, setTitle] = useState('')
  const [connectionId, setConnectionId] = useState('')
  const [queueContent, setQueueContent] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!open) return
    setUrl('')
    setTitle('')
    setQueueContent(false)
    setConnectionId(sourceOptions[0]?.value ?? '')
  }, [open, sourceOptions])

  async function submit() {
    if (!url.trim()) {
      toast.error('URL is required')
      return
    }
    if (!connectionId) {
      toast.error('Link a source before saving URLs to this project')
      return
    }
    setSaving(true)
    try {
      const row = await sourcesApi.createManualUrl({
        url: url.trim(),
        title: title.trim() || undefined,
        connection_id: connectionId,
        queue_content: queueContent,
      })
      if (row.connection_id !== connectionId) {
        await sourcesApi.updateItem(row.id, { connection_id: connectionId })
      }
      toast.success('URL saved')
      onSaved()
      onOpenChange(false)
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Save URL</DialogTitle>
          <DialogDescription>
            Save a URL into this project by attaching it to one of the project-linked sources.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <Label>Page URL</Label>
            <Input
              value={url}
              onChange={event => setUrl(event.target.value)}
              placeholder="https://example.com/post"
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label>Title</Label>
            <Input
              value={title}
              onChange={event => setTitle(event.target.value)}
              placeholder="Optional"
            />
          </div>
          <div className="space-y-1.5">
            <Label>Source</Label>
            {sourceOptions.length === 0 ? (
              <p className="text-xs text-muted-foreground">Link a source before saving URLs to this project.</p>
            ) : (
              <Select
                value={connectionId}
                options={sourceOptions}
                onChange={setConnectionId}
              />
            )}
          </div>
          <label className="flex items-center gap-2 text-sm text-muted-foreground">
            <input
              type="checkbox"
              className="size-4 rounded border-border"
              checked={queueContent}
              onChange={event => setQueueContent(event.target.checked)}
            />
            Queue extraction
          </label>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={submit} disabled={saving || !url.trim() || !connectionId}>
            {saving ? 'Saving…' : 'Save URL'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/* ── Main page ─────────────────────────────────────────────────────────────── */
export default function ProjectDetailPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const { activeSpaceId } = useSpace()

  const [project, setProject] = useState<Project | null>(null)
  const [summary, setSummary] = useState<ProjectSummary | null>(null)
  const [links, setLinks] = useState<ProjectWorkspaceLinkOut[]>([])
  const [workspaceMap, setWorkspaceMap] = useState<Record<string, Workspace>>({})
  const [recentActivities, setRecentActivities] = useState<ActivityInboxRecord[]>([])
  const [recentArtifacts, setRecentArtifacts] = useState<Artifact[]>([])
  const [pendingProposals, setPendingProposals] = useState<Proposal[]>([])
  const [recentRuns, setRecentRuns] = useState<Run[]>([])
  const [projectMemory, setProjectMemory] = useState<Memory[]>([])
  const [sourceConnections, setSourceConnections] = useState<SourceConnection[]>([])
  const [sourceBindings, setSourceBindings] = useState<ProjectSourceBinding[]>([])
  const [recentSourceItems, setRecentSourceItems] = useState<SourceItem[]>([])
  const [recentEvidence, setRecentEvidence] = useState<ExtractedEvidence[]>([])
  const [sourceRecommendations, setSourceRecommendations] = useState<SourcePostProcessingItemDecision[]>([])
  const [readerAnnotations, setReaderAnnotations] = useState<ReaderAnnotation[]>([])
  const [automations, setAutomations] = useState<AutomationOut[]>([])
  const [operations, setOperations] = useState<ProjectOperation[]>([])
  const [projectPresetKey, setProjectPresetKey] = useState<string | null>(null)
  const [researchProfile, setResearchProfile] = useState<ProjectResearchProfile | null>(null)
  const [researchWorkflows, setResearchWorkflows] = useState<ProjectResearchWorkflow[]>([])
  const [researchCheckpoints, setResearchCheckpoints] = useState<ProjectResearchCheckpoint[]>([])
  const [literatureMatrix, setLiteratureMatrix] = useState<ProjectResearchLiteratureMatrixItem[]>([])
  const [synthesisArtifacts, setSynthesisArtifacts] = useState<ProjectResearchArtifactLink[]>([])
  const [screeningCriteria, setScreeningCriteria] = useState<ProjectResearchScreeningCriteria | null>(null)
  const [researchActionBusy, setResearchActionBusy] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [detailsLoading, setDetailsLoading] = useState(false)
  const [notFound, setNotFound] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [linkOpen, setLinkOpen] = useState(false)
  const [sourceLinkOpen, setSourceLinkOpen] = useState(false)
  const [saveUrlOpen, setSaveUrlOpen] = useState(false)
  const [updatingItemSourceId, setUpdatingItemSourceId] = useState<string | null>(null)
  const [backfillingBindingId, setBackfillingBindingId] = useState<string | null>(null)
  const [archiving, setArchiving] = useState(false)

  const loadAll = useCallback(async () => {
    if (!projectId || !activeSpaceId) {
      setLoading(false)
      return
    }
    setLoading(true)
    setNotFound(false)
    let resolvedPresetKey: string | null = null
    try {
      const [proj, summ, linkedWs, projectPresetSelection] = await Promise.all([
        projectsApi.get(projectId),
        projectsApi.getSummary(projectId),
        projectsApi.listWorkspaces(projectId),
        projectPresetsApi.getProjectPreset(projectId).catch(() => ({ preset_key: null })),
      ])
      setProject(proj)
      setSummary(summ)
      setLinks(linkedWs)
      resolvedPresetKey = projectPresetSelection.preset_key ?? presetKeyFromProject(proj)
      setProjectPresetKey(resolvedPresetKey)
      setLoading(false)
    } catch (e) {
      setDetailsLoading(false)
      if (isNotFoundError(e)) {
        setNotFound(true)
      } else {
        toast.error(errMsg(e))
      }
      setLoading(false)
      return
    }

    setDetailsLoading(true)
    try {
      const [allWs, acts, arts, props, runs, mems, sourceConnections, sourceBindings, sourceItems, evidenceItems, recommendations, readerAnns, allAutomations, operationRows] = await Promise.all([
        workspacesApi.list({ limit: '200' }),
        activityApi.list({ project_id: projectId, limit: 5 }),
        artifactsApi.list({ project_id: projectId, limit: 5 }),
        proposalsApi.list({ project_id: projectId, status: 'pending', limit: 5 }),
        runsApi.list({ project_id: projectId, limit: 5 }),
        memoryApi.list({ project_id: projectId, limit: 5 }),
        sourcesApi.connections({ limit: 100 }),
        sourcesApi.projectSourceBindings({ project_id: projectId }),
        sourcesApi.projectItems({ project_id: projectId, limit: 5 }),
        sourcesApi.evidence({ project_id: projectId, status: 'active', limit: 5 }),
        sourcesApi.postProcessingDecisions({ project_id: projectId, limit: 20 }).catch(() => ({ items: [] as SourcePostProcessingItemDecision[], total: 0, limit: 20, offset: 0 })),
        sourceReaderApi.listByProject(projectId, 5).catch(() => ({ items: [] as ReaderAnnotation[] })),
        automationsApi.list({ project_id: projectId }).catch(() => [] as AutomationOut[]),
        projectsApi.operations ? projectsApi.operations(projectId).catch(() => [] as ProjectOperation[]) : Promise.resolve([] as ProjectOperation[]),
      ])
      const map: Record<string, Workspace> = {}
      allWs.items.forEach(w => { map[w.id] = w })
      setWorkspaceMap(map)
      setRecentActivities(acts)
      setRecentArtifacts(arts.items)
      setPendingProposals(props.items)
      setRecentRuns(runs)
      setProjectMemory(mems.items)
      setSourceConnections(sourceConnections.items)
      setSourceBindings(sourceBindings)
      setRecentSourceItems(sourceItems.items.map(projectItem => projectItem.item))
      setRecentEvidence(evidenceItems.items)
      setSourceRecommendations(recommendations.items.filter(item => item.relevance !== 'not_relevant').slice(0, 5))
      setOperations(operationRows)
      setReaderAnnotations(readerAnns.items)
      setAutomations(allAutomations.filter(a => a.status !== 'archived'))

      if (resolvedPresetKey === ACADEMIC_PRESET_KEY) {
        try {
          const [profile, workflows, criteria, matrix, synthesis] = await Promise.all([
            projectResearchApi.profile(projectId).catch(error => {
              if (isNotFoundError(error)) return null
              throw error
            }),
            projectResearchApi.workflows(projectId),
            projectResearchApi.screeningCriteria(projectId),
            projectResearchApi.literatureMatrix(projectId),
            projectResearchApi.synthesis(projectId),
          ])
          const activeWorkflow = activeResearchWorkflowFrom(workflows)
          const checkpoints = activeWorkflow
            ? await projectResearchApi.checkpoints(projectId, activeWorkflow.id)
            : []
          setResearchProfile(profile)
          setResearchWorkflows(workflows)
          setResearchCheckpoints(checkpoints)
          setScreeningCriteria(criteria)
          setLiteratureMatrix(matrix)
          setSynthesisArtifacts(synthesis)
        } catch (researchError) {
          setResearchProfile(null)
          setResearchWorkflows([])
          setResearchCheckpoints([])
          setScreeningCriteria(null)
          setLiteratureMatrix([])
          setSynthesisArtifacts([])
          throw researchError
        }
      } else {
        setResearchProfile(null)
        setResearchWorkflows([])
        setResearchCheckpoints([])
        setScreeningCriteria(null)
        setLiteratureMatrix([])
        setSynthesisArtifacts([])
      }
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setDetailsLoading(false)
    }
  }, [projectId, activeSpaceId])

  useEffect(() => { loadAll() }, [loadAll])

  async function archive() {
    if (!project) return
    if (!confirm(`Archive "${project.name}"? Archived projects are hidden from the active list but all their records remain preserved.`)) return
    setArchiving(true)
    try {
      const updated = await projectsApi.archive(project.id)
      setProject(updated)
      toast.success('Project archived')
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setArchiving(false)
    }
  }

  async function unlink(link: ProjectWorkspaceLinkOut) {
    try {
      await projectsApi.unlinkWorkspace(project!.id, link.workspace_id, link.role)
      toast.success('Workspace unlinked')
      setLinks(prev => prev.filter(l => l.id !== link.id))
    } catch (e) {
      toast.error(errMsg(e))
    }
  }

  async function updateProjectItemSource(item: SourceItem, connectionId: string) {
    if (item.connection_id === connectionId) return
    setUpdatingItemSourceId(item.id)
    try {
      await sourcesApi.updateItem(item.id, { connection_id: connectionId })
      toast.success('Item source updated')
      await loadAll()
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setUpdatingItemSourceId(null)
    }
  }

  async function backfillSourceBinding(binding: ProjectSourceBinding) {
    if (!projectId) return
    setBackfillingBindingId(binding.id)
    try {
      const result = await sourcesApi.backfillProjectSourceBinding(projectId, binding.id)
      toast.success(`Backfilled ${result.created_links} project items`)
      await loadAll()
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBackfillingBindingId(null)
    }
  }

  async function ensureApprovedResearchProfile(): Promise<ProjectResearchProfile | null> {
    if (!project) return null
    const researchQuestion = project.current_focus?.trim()
    if (!researchQuestion) {
      toast.error('Set a research question before starting auto research')
      setEditOpen(true)
      return null
    }

    let nextProfile = researchProfile
    if (!nextProfile || nextProfile.research_question?.trim() !== researchQuestion) {
      nextProfile = await projectResearchApi.upsertProfile(project.id, {
        research_question: researchQuestion,
        working_title: project.name,
        output_type: 'paper',
        paper_type: 'survey',
        language: 'en',
        experiment_intake_declaration: 'undecided',
      })
    }
    if (nextProfile.status !== 'approved') {
      nextProfile = await projectResearchApi.approveProfile(project.id)
    }
    return nextProfile
  }

  async function prepareResearchProfile() {
    setResearchActionBusy('prepare-profile')
    try {
      const profile = await ensureApprovedResearchProfile()
      if (!profile) return
      setResearchProfile(profile)
      toast.success('Research profile approved')
      await loadAll()
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setResearchActionBusy(null)
    }
  }

  async function startAutoResearchWorkflow() {
    if (!project) return
    setResearchActionBusy('start-workflow')
    try {
      const profile = await ensureApprovedResearchProfile()
      if (!profile) return
      const existingWorkflow = activeResearchWorkflowFrom(researchWorkflows)
      const workflow = existingWorkflow ?? await projectResearchApi.startWorkflow(project.id, {
        workflow_type: 'literature_review',
        mode: 'agent_assisted',
      })
      await projectResearchApi.runStage(project.id, workflow.id, 'research_profile')
      if (sourceBindings.length > 0) {
        await projectResearchApi.runStage(project.id, workflow.id, 'literature_monitoring')
      }
      toast.success(existingWorkflow ? 'Research workflow refreshed' : 'Auto research workflow started')
      await loadAll()
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setResearchActionBusy(null)
    }
  }

  async function rebuildLiteratureMatrix() {
    if (!project) return
    setResearchActionBusy('rebuild-matrix')
    try {
      const rows = await projectResearchApi.rebuildLiteratureMatrix(project.id)
      setLiteratureMatrix(rows)
      const workflow = activeResearchWorkflowFrom(researchWorkflows)
      if (workflow?.status === 'active') {
        await projectResearchApi.runStage(project.id, workflow.id, 'screening_matrix')
      }
      toast.success(`Literature matrix rebuilt with ${rows.length} papers`)
      await loadAll()
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setResearchActionBusy(null)
    }
  }

  async function runIntegrityGate() {
    if (!project) return
    const workflow = activeResearchWorkflowFrom(researchWorkflows)
    if (!workflow || workflow.status !== 'active') {
      toast.error('Start an active research workflow before running integrity')
      return
    }
    setResearchActionBusy('run-integrity')
    try {
      await projectResearchApi.runIntegrity(project.id, {
        workflow_id: workflow.id,
        stage_key: 'integrity_gate',
      })
      toast.success('Integrity checkpoint created')
      await loadAll()
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setResearchActionBusy(null)
    }
  }

  if (loading) {
    return (
      <div className="p-6 space-y-4">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-32 w-full" />
      </div>
    )
  }

  if (notFound || !project) {
    return (
      <div className="p-6">
        <EmptyState
          title="Project not found"
          description="This project may have been deleted or you may not have access."
          action={<Button variant="ghost" onClick={() => navigate('/projects')}>Back to projects</Button>}
        />
      </div>
    )
  }

  const existingIds = new Set(links.map(l => l.workspace_id))
  const workflowWorkspaceOptions = links.map(link => {
    const ws = workspaceMap[link.workspace_id]
    return {
      id: link.workspace_id,
      name: ws?.name ?? link.workspace_id,
      role: link.role,
      root_path: ws?.root_path ?? null,
    }
  })
  const sourceConnectionById = Object.fromEntries(sourceConnections.map(connection => [connection.id, connection])) as Record<string, SourceConnection>
  const linkedSourceConnections = sourceBindings
    .map(binding => sourceConnectionById[binding.source_connection_id])
    .filter((connection): connection is SourceConnection => Boolean(connection))
  const projectSourceOptions = Array.from(
    new Map(
      linkedSourceConnections.map(connection => [
        connection.id,
        { value: connection.id, label: connection.name },
      ]),
    ).values(),
  )
  const isAcademicProject = projectPresetKey === ACADEMIC_PRESET_KEY

  return (
    <div className="p-6 space-y-6">
      {/* Breadcrumb */}
      <Link to="/projects" className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors">
        <ChevronLeft className="size-3" />
        Projects
      </Link>

      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap pb-4 border-b border-border">
        <div className="flex items-start gap-4">
          <div
            className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0 mt-0.5"
            style={{
              background: 'color-mix(in oklch, var(--primary) 12%, transparent)',
              border: '1px solid color-mix(in oklch, var(--primary) 35%, transparent)',
            }}
          >
            {isAcademicProject
              ? <BookOpen className="size-5 text-accent-foreground" />
              : <FolderKanban className="size-5 text-accent-foreground" />}
          </div>
          <div className="space-y-1">
            <div className="flex items-center gap-2 flex-wrap">
              <h1 className="text-xl font-semibold tracking-tight">{project.name}</h1>
              <StatusBadge status={project.status} />
              {isAcademicProject && <Badge variant="secondary">Academic Research</Badge>}
            </div>
            {project.description && (
              <p className="text-sm text-muted-foreground max-w-2xl">{project.description}</p>
            )}
            <p className="text-xs text-muted-foreground">Updated {fmt(project.updated_at)}</p>
          </div>
        </div>
        <div className="flex gap-2 shrink-0">
          <Button asChild size="sm" className="gap-1.5"><Link to={`/projects/${project.id}/chat`}><MessageSquareText className="size-3.5" />Chat</Link></Button>
          <Button variant="outline" size="sm" className="gap-1.5" onClick={() => setEditOpen(true)}>
            <Edit2 className="size-3.5" />
            Edit
          </Button>
          {project.status === 'active' && (
            <Button variant="outline" size="sm" className="gap-1.5" onClick={archive} disabled={archiving}>
              <Archive className="size-3.5" />
              {archiving ? 'Archiving…' : 'Archive'}
            </Button>
          )}
        </div>
      </div>

      {/* Summary cards */}
      {summary && (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">Overview</h2>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
            <SummaryCard icon={<Activity className="size-3.5" />} label="Activities" count={summary.activity_count} />
            <SummaryCard icon={<Package className="size-3.5" />} label="Artifacts" count={summary.artifact_count} />
            <SummaryCard icon={<CheckCircle className="size-3.5" />} label="Proposals" count={summary.pending_proposal_count} />
            <SummaryCard icon={<Folder className="size-3.5" />} label="Workspaces" count={summary.workspace_count} />
            <SummaryCard icon={<Cpu className="size-3.5" />} label="Active runs" count={summary.active_run_count} />
            <SummaryCard icon={<Database className="size-3.5" />} label="Memory" count={summary.memory_entry_count} />
          </div>
        </section>
      )}

      {operations.some(operation => ['draft', 'active', 'waiting_review'].includes(operation.status)) && <section className="space-y-2">
        <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">Operations</h2>
        <div className="grid gap-3 md:grid-cols-2">
          {operations.filter(operation => ['draft', 'active', 'waiting_review'].includes(operation.status)).map(operation => {
            const total=Number(operation.progress_json.total ?? 0),completed=Number(operation.progress_json.completed ?? 0),failed=Number(operation.progress_json.failed ?? 0)
            return <Card key={operation.id} className="p-4 space-y-2"><div className="flex items-center justify-between gap-2"><p className="text-sm font-medium truncate">{operation.title}</p><StatusBadge status={operation.status} /></div><p className="text-xs text-muted-foreground">{operation.kind.replace(/_/g,' ')} · {total ? `${completed}/${total} complete` : 'Preparing'}{failed ? ` · ${failed} failed` : ''}</p><div className="h-1.5 rounded bg-muted overflow-hidden"><div className="h-full bg-primary" style={{width:total?`${Math.min(100,completed/total*100)}%`:'5%'}} /></div>{operation.links&&operation.links.length>0&&<div className="flex flex-wrap gap-2">{operation.links.map(link=>{const to=link.target_type==='run'?`/runs/${link.target_id}`:link.target_type==='proposal'?`/proposals/${link.target_id}`:link.target_type==='source_backfill_plan'?`/projects/${project.id}/sources`:null;return to?<Link key={`${link.target_type}:${link.target_id}`} to={to} className="text-xs text-accent-foreground hover:underline">{link.role.replace(/_/g,' ')}</Link>:<span key={`${link.target_type}:${link.target_id}`} className="text-xs text-muted-foreground">{link.role.replace(/_/g,' ')}</span>})}</div>}</Card>
          })}
        </div>
      </section>}

      {/* Current focus */}
      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
          {isAcademicProject ? 'Research question' : 'Current focus'}
        </h2>
        {project.current_focus ? (
          <Card className="p-4">
            <div className="flex items-start gap-2">
              <Target className="size-4 text-accent-foreground mt-0.5 shrink-0" />
              <p className="text-sm">{project.current_focus}</p>
            </div>
          </Card>
        ) : (
          <Card className="p-4">
            <p className="text-sm text-muted-foreground">
              {isAcademicProject
                ? 'No research question set. Add one to focus source monitoring, screening, and analysis.'
                : 'No current focus set. Add one to help agents and future project views understand what matters right now.'}
            </p>
            <Button variant="ghost" size="sm" className="mt-2 -ml-1" onClick={() => setEditOpen(true)}>
              <Edit2 className="size-3.5 mr-1.5" />
              {isAcademicProject ? 'Set research question' : 'Set focus'}
            </Button>
          </Card>
        )}
      </section>

      {isAcademicProject && (
        <AcademicResearchWorkbench
          project={project}
          sourceBindings={sourceBindings}
          recentSourceItems={recentSourceItems}
          recentEvidence={recentEvidence}
          sourceRecommendations={sourceRecommendations}
          readerAnnotations={readerAnnotations}
          researchProfile={researchProfile}
          researchWorkflows={researchWorkflows}
          researchCheckpoints={researchCheckpoints}
          literatureMatrix={literatureMatrix}
          synthesisArtifacts={synthesisArtifacts}
          screeningCriteria={screeningCriteria}
          researchActionBusy={researchActionBusy}
          onPrepareProfile={prepareResearchProfile}
          onStartWorkflow={startAutoResearchWorkflow}
          onRebuildMatrix={rebuildLiteratureMatrix}
          onRunIntegrity={runIntegrityGate}
          onEditQuestion={() => setEditOpen(true)}
        />
      )}

      {!isAcademicProject && (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">Research workflows</h2>
          <ResearchWorkflowPanel
            projectId={project.id}
            projectName={project.name}
            workspaceOptions={workflowWorkspaceOptions}
            onRunCreated={loadAll}
          />
        </section>
      )}

      {/* Sources consumption */}
      <section className="space-y-2">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
              {isAcademicProject ? 'Research corpus' : 'Sources'}
            </h2>
            {detailsLoading && <Badge variant="muted">Loading</Badge>}
          </div>
          <div className="flex gap-2">
            {project.status === 'active' && (
              <>
                <Button variant="secondary" size="sm" className="gap-1.5" onClick={() => setSaveUrlOpen(true)}>
                  <FileText className="size-3.5" />
                  Save URL
                </Button>
                <Button variant="secondary" size="sm" className="gap-1.5" onClick={() => setSourceLinkOpen(true)}>
                  <Link2 className="size-3.5" />
                  Link source
                </Button>
              </>
            )}
            <Button variant="outline" size="sm" asChild>
              <Link to={`/projects/${project.id}/sources`}>
                <Rss className="size-3.5" />
                Manage sources
              </Link>
            </Button>
          </div>
        </div>
        <div className="grid gap-3 lg:grid-cols-3">
          <Card className="p-4">
            <div className="flex items-center gap-2 text-muted-foreground mb-3">
              <Link2 className="size-3.5" />
              <span className="text-xs font-medium uppercase tracking-wide">
                {isAcademicProject ? 'Literature sources' : 'Linked sources'}
              </span>
            </div>
            {sourceBindings.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                {isAcademicProject
                  ? 'No literature sources are scoped to this research project.'
                  : 'No source bindings are scoped to this project.'}
              </p>
            ) : (
              <div className="space-y-2">
                {sourceBindings.slice(0, 4).map(binding => {
                  const connection = sourceConnectionById[binding.source_connection_id]
                  return (
                    <div key={binding.id} className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="text-sm font-medium truncate">{connection?.name ?? binding.source_connection_id}</p>
                        <p className="text-xs text-muted-foreground truncate">{connection?.endpoint_url ?? binding.binding_key}</p>
                      </div>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="shrink-0 gap-1.5"
                        disabled={project.status !== 'active' || binding.status !== 'active' || backfillingBindingId === binding.id}
                        onClick={() => backfillSourceBinding(binding)}
                      >
                        <RefreshCw className="size-3.5" />
                        {backfillingBindingId === binding.id ? 'Backfilling…' : 'Backfill history'}
                      </Button>
                    </div>
                  )
                })}
                {sourceBindings.length > 4 && <p className="text-xs text-muted-foreground">+{sourceBindings.length - 4} more</p>}
              </div>
            )}
            <div className="flex gap-1.5 flex-wrap mt-3">
              <Badge variant="outline">{sourceBindings.length} bindings</Badge>
              <Badge variant="muted">{linkedSourceConnections.length} connections</Badge>
            </div>
          </Card>
          <Card className="p-4">
            <div className="flex items-center gap-2 text-muted-foreground mb-3">
              <FileText className="size-3.5" />
              <span className="text-xs font-medium uppercase tracking-wide">
                {isAcademicProject ? 'Recent papers' : 'Recent items'}
              </span>
            </div>
            {recentSourceItems.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                {isAcademicProject ? 'No project-linked papers or source items yet.' : 'No project-linked source items yet.'}
              </p>
            ) : (
              <div className="space-y-2">
                {recentSourceItems.map(item => (
                  <div key={item.id} className="min-w-0">
                    <p className="text-sm font-medium truncate">{item.title || 'Untitled item'}</p>
                    <p className="text-xs text-muted-foreground truncate">{item.source_domain ?? item.source_uri ?? item.library_status}</p>
                    {isManualUrlItem(item) && projectSourceOptions.length > 0 && (
                      <div className="mt-2">
                        <Select
                          size="sm"
                          value={item.connection_id ?? ''}
                          options={projectSourceOptions}
                          disabled={updatingItemSourceId === item.id}
                          onChange={value => updateProjectItemSource(item, value)}
                        />
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </Card>
          <Card className="p-4">
            <div className="flex items-center gap-2 text-muted-foreground mb-3">
              <CheckCircle className="size-3.5" />
              <span className="text-xs font-medium uppercase tracking-wide">Active evidence</span>
            </div>
            {recentEvidence.length === 0 ? (
              <p className="text-xs text-muted-foreground">No active evidence is linked to this project.</p>
            ) : (
              <div className="space-y-2">
                {recentEvidence.map(row => (
                  <div key={row.id} className="min-w-0">
                    <p className="text-sm font-medium truncate">{row.title}</p>
                    <p className="text-xs text-muted-foreground line-clamp-2">{row.content_excerpt ?? row.source_uri ?? row.evidence_type}</p>
                  </div>
                ))}
              </div>
            )}
          </Card>

          <Card className="p-4">
            <div className="flex items-center gap-2 text-muted-foreground mb-3">
              <Target className="size-3.5" />
              <span className="text-xs font-medium uppercase tracking-wide">
                {isAcademicProject ? 'Screening recommendations' : 'Source recommendations'}
              </span>
            </div>
            {sourceRecommendations.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                {isAcademicProject
                  ? 'No screening recommendations for this research corpus yet.'
                  : 'No post-processing recommendations for this project yet.'}
              </p>
            ) : (
              <div className="space-y-2">
                {sourceRecommendations.map(decision => {
                  const connection = sourceConnectionById[decision.source_connection_id]
                  return (
                    <div key={decision.id} className="min-w-0">
                      <div className="flex items-center gap-1.5">
                        <Badge variant={decision.relevance === 'relevant' ? 'default' : decision.relevance === 'maybe' ? 'outline' : 'muted'}>
                          {decision.relevance}
                        </Badge>
                        {decision.confidence !== null && <Badge variant="muted">{Math.round(decision.confidence * 100)}%</Badge>}
                      </div>
                      <p className="mt-1 text-sm font-medium truncate">{decision.item.title ?? decision.source_item_id}</p>
                      <p className="text-xs text-muted-foreground line-clamp-2">{decision.reason ?? decision.item.source_domain ?? decision.review_status}</p>
                      {connection && (
                        <Link to={`/sources/sources/${connection.id}`} className="mt-1 block text-xs text-accent-foreground hover:underline">
                          {connection.name}
                        </Link>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </Card>

          <Card className="p-4">
            <div className="flex items-center gap-2 text-muted-foreground mb-3">
              <FileText className="size-3.5" />
              <span className="text-xs font-medium uppercase tracking-wide">Reader annotations</span>
            </div>
            {readerAnnotations.length === 0 ? (
              <p className="text-xs text-muted-foreground">No shared reader annotations from sources bound to this project.</p>
            ) : (
              <div className="space-y-2">
                {readerAnnotations.map(ann => (
                  ann.source_item_id ? (
                    <Link
                      key={ann.id}
                      to={`/library/items/${ann.source_item_id}`}
                      className="block min-w-0 rounded hover:bg-muted/50 -mx-1 px-1 py-0.5 transition-colors"
                    >
                      <p className="text-xs text-muted-foreground capitalize">{ann.annotation_type}</p>
                      <p className="text-sm line-clamp-2 italic">{ann.quote_text}</p>
                    </Link>
                  ) : (
                    <div key={ann.id} className="min-w-0">
                      <p className="text-xs text-muted-foreground capitalize">{ann.annotation_type}</p>
                      <p className="text-sm line-clamp-2 italic">{ann.quote_text}</p>
                    </div>
                  )
                ))}
              </div>
            )}
          </Card>
        </div>
      </section>

      {/* Linked workspaces */}
      <section className="space-y-2">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">Linked workspaces</h2>
          {project.status === 'active' && (
            <Button variant="outline" size="sm" className="gap-1.5" onClick={() => setLinkOpen(true)}>
              <Plus className="size-3.5" />
              Link workspace
            </Button>
          )}
        </div>
        {links.length === 0 ? (
          <Card className="p-4">
            <p className="text-sm text-muted-foreground">
              No workspaces linked. Link workspaces that this project uses for code, docs, data, deployment, or reference material.
            </p>
          </Card>
        ) : (
          <div className="space-y-2">
            {links.map(link => {
              const ws = workspaceMap[link.workspace_id]
              return (
                <Card key={link.id} className="p-3 flex items-center justify-between gap-3">
                  <div className="flex items-center gap-3 min-w-0">
                    <Folder className="size-4 text-muted-foreground shrink-0" />
                    <div className="min-w-0">
                      <p className="text-sm font-medium truncate">{ws?.name ?? link.workspace_id}</p>
                      {ws?.root_path && (
                        <p className="text-xs text-muted-foreground font-mono truncate">{ws.root_path}</p>
                      )}
                    </div>
                    <Badge variant="outline" className="shrink-0">{link.role}</Badge>
                  </div>
                  {project.status === 'active' && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-muted-foreground hover:text-destructive shrink-0"
                      onClick={() => unlink(link)}
                    >
                      <Trash2 className="size-3.5" />
                    </Button>
                  )}
                </Card>
              )
            })}
          </div>
        )}
      </section>

      {/* Project activity — scoped to this project */}
      <section className="space-y-4">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">Project activity</h2>
          {detailsLoading && <Badge variant="muted">Loading</Badge>}
        </div>

        {/* Recent activities */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-muted-foreground">Recent Activities</span>
            <Link to={`/activity?project_id=${project.id}`} className="text-xs text-accent-foreground hover:underline">View all →</Link>
          </div>
          {recentActivities.length === 0 ? (
            <Card className="p-3"><p className="text-xs text-muted-foreground">No activities for this project.</p></Card>
          ) : (
            <div className="space-y-1.5">
              {recentActivities.map(a => (
                <Card key={a.id} className="px-3 py-2 flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-xs font-medium truncate">{a.title || a.content?.slice(0, 60) || '—'}</p>
                    <p className="text-xs text-muted-foreground">{a.source_type}</p>
                  </div>
                  <Badge variant="outline">{a.status}</Badge>
                </Card>
              ))}
            </div>
          )}
        </div>

        {/* Recent artifacts */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-muted-foreground">Recent Artifacts</span>
            <Link to={`/artifacts?project_id=${project.id}`} className="text-xs text-accent-foreground hover:underline">View all →</Link>
          </div>
          {recentArtifacts.length === 0 ? (
            <Card className="p-3"><p className="text-xs text-muted-foreground">No artifacts for this project.</p></Card>
          ) : (
            <div className="space-y-1.5">
              {recentArtifacts.map(a => (
                <Card key={a.id} className="px-3 py-2 flex items-center justify-between gap-2">
                  <p className="text-xs font-medium truncate">{a.title}</p>
                  <Badge variant="outline">{a.artifact_type}</Badge>
                </Card>
              ))}
            </div>
          )}
        </div>

        {/* Pending proposals */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-muted-foreground">Pending Proposals</span>
            <Link to={`/proposals?project_id=${project.id}`} className="text-xs text-accent-foreground hover:underline">View all →</Link>
          </div>
          {pendingProposals.length === 0 ? (
            <Card className="p-3"><p className="text-xs text-muted-foreground">No pending proposals for this project.</p></Card>
          ) : (
            <div className="space-y-1.5">
              {pendingProposals.map(p => (
                <Card key={p.id} className="px-3 py-2 flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-xs font-medium truncate">{p.proposed_title || p.proposal_type}</p>
                    <p className="text-xs text-muted-foreground">{p.proposal_type}</p>
                  </div>
                  <Badge variant="outline">{p.urgency}</Badge>
                </Card>
              ))}
            </div>
          )}
        </div>

        {/* Recent runs */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-muted-foreground">Recent Runs</span>
            <Link to={`/runs?project_id=${project.id}`} className="text-xs text-accent-foreground hover:underline">View all →</Link>
          </div>
          {recentRuns.length === 0 ? (
            <Card className="p-3"><p className="text-xs text-muted-foreground">No runs for this project.</p></Card>
          ) : (
            <div className="space-y-1.5">
              {recentRuns.map(r => (
                <Card key={r.id} className="px-3 py-2 flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-xs font-medium font-mono truncate">{r.id.slice(-8)}</p>
                    <p className="text-xs text-muted-foreground">{r.mode} · {r.agent_id?.slice(-8)}</p>
                  </div>
                  <Badge variant="outline">{r.status}</Badge>
                </Card>
              ))}
            </div>
          )}
        </div>

        {/* Automations bound to this project */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-muted-foreground">Automations</span>
            <Link to="/automations" className="text-xs text-accent-foreground hover:underline">View all →</Link>
          </div>
          {automations.length === 0 ? (
            <Card className="p-3"><p className="text-xs text-muted-foreground">No automations bound to this project.</p></Card>
          ) : (
            <div className="space-y-1.5">
              {automations.map(a => (
                <Card key={a.id} className="px-3 py-2 flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-xs font-medium truncate">{a.name}</p>
                    <p className="text-xs text-muted-foreground">{a.trigger_type}{a.next_run_at ? ` · next ${new Date(a.next_run_at).toLocaleString()}` : ''}</p>
                  </div>
                  <Badge variant="outline">{a.status}</Badge>
                </Card>
              ))}
            </div>
          )}
        </div>

        {/* Project memory */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-muted-foreground">Project Memory</span>
            <Link to={`/memory?project_id=${project.id}`} className="text-xs text-accent-foreground hover:underline">View all →</Link>
          </div>
          {projectMemory.length === 0 ? (
            <Card className="p-3"><p className="text-xs text-muted-foreground">No memory entries for this project.</p></Card>
          ) : (
            <div className="space-y-1.5">
              {projectMemory.map(m => (
                <Card key={m.id} className="px-3 py-2 flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-xs font-medium truncate">{m.title || m.content?.slice(0, 60) || '—'}</p>
                    <p className="text-xs text-muted-foreground">{m.type} · {m.scope}</p>
                  </div>
                  <Badge variant="outline">{m.status}</Badge>
                </Card>
              ))}
            </div>
          )}
        </div>
      </section>

      {/* Dialogs */}
      <EditProjectDialog
        project={project}
        open={editOpen}
        onOpenChange={setEditOpen}
        onSaved={updated => setProject(updated)}
      />

      <LinkWorkspaceDialog
        projectId={project.id}
        existingIds={existingIds}
        open={linkOpen}
        onOpenChange={setLinkOpen}
        onLinked={loadAll}
      />

      <LinkSourceConnectionDialog
        projectId={project.id}
        open={sourceLinkOpen}
        onOpenChange={setSourceLinkOpen}
        connections={sourceConnections}
        bindings={sourceBindings}
        onLinked={loadAll}
      />

      <SaveProjectUrlDialog
        open={saveUrlOpen}
        onOpenChange={setSaveUrlOpen}
        sourceOptions={projectSourceOptions}
        onSaved={loadAll}
      />
    </div>
  )
}
