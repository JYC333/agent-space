import { useState, useEffect, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { useSpaceNavigate as useNavigate, SpaceLink as Link } from '../../core/spaceNav'
import {
  FolderKanban, Target, Edit2, Archive, Plus, Trash2, ChevronLeft,
  Activity, Package, CheckCircle, Folder, Cpu, Database,
} from 'lucide-react'
import { toast } from 'sonner'
import { projectsApi, workspacesApi, activityApi, artifactsApi, proposalsApi, runsApi, memoryApi } from '../../api/client'
import { useSpace } from '../../contexts/SpaceContext'
import { errMsg, isNotFoundError } from '../../lib/utils'
import type {
  Project, ProjectSummary, ProjectWorkspaceLinkOut, Workspace,
  ActivityInboxRecord, Artifact, Proposal, Run, Memory,
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
  const [loading, setLoading] = useState(true)
  const [notFound, setNotFound] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [linkOpen, setLinkOpen] = useState(false)
  const [archiving, setArchiving] = useState(false)

  const loadAll = useCallback(async () => {
    if (!projectId || !activeSpaceId) {
      setLoading(false)
      return
    }
    setLoading(true)
    setNotFound(false)
    try {
      const [proj, summ, linkedWs, allWs] = await Promise.all([
        projectsApi.get(projectId),
        projectsApi.getSummary(projectId),
        projectsApi.listWorkspaces(projectId),
        workspacesApi.list({ limit: '200' }),
      ])
      setProject(proj)
      setSummary(summ)
      setLinks(linkedWs)
      const map: Record<string, Workspace> = {}
      allWs.items.forEach(w => { map[w.id] = w })
      setWorkspaceMap(map)

      const [acts, arts, props, runs, mems] = await Promise.all([
        activityApi.list({ project_id: projectId, limit: 5 }),
        artifactsApi.list({ project_id: projectId, limit: 5 }),
        proposalsApi.list({ project_id: projectId, status: 'pending', limit: 5 }),
        runsApi.list({ project_id: projectId, limit: 5 }),
        memoryApi.list({ project_id: projectId, limit: 5 }),
      ])
      setRecentActivities(acts)
      setRecentArtifacts(arts.items)
      setPendingProposals(props.items)
      setRecentRuns(runs)
      setProjectMemory(mems.items)
    } catch (e) {
      if (isNotFoundError(e)) {
        setNotFound(true)
      } else {
        toast.error(errMsg(e))
      }
    } finally {
      setLoading(false)
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
            <FolderKanban className="size-5 text-accent-foreground" />
          </div>
          <div className="space-y-1">
            <div className="flex items-center gap-2 flex-wrap">
              <h1 className="text-xl font-semibold tracking-tight">{project.name}</h1>
              <StatusBadge status={project.status} />
            </div>
            {project.description && (
              <p className="text-sm text-muted-foreground max-w-2xl">{project.description}</p>
            )}
            <p className="text-xs text-muted-foreground">Updated {fmt(project.updated_at)}</p>
          </div>
        </div>
        <div className="flex gap-2 shrink-0">
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

      {/* Current focus */}
      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">Current focus</h2>
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
              No current focus set. Add one to help agents and future project views understand what matters right now.
            </p>
            <Button variant="ghost" size="sm" className="mt-2 -ml-1" onClick={() => setEditOpen(true)}>
              <Edit2 className="size-3.5 mr-1.5" />
              Set focus
            </Button>
          </Card>
        )}
      </section>

      {/* Research workflows */}
      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">Research workflows</h2>
        <ResearchWorkflowPanel
          projectId={project.id}
          projectName={project.name}
          workspaceOptions={workflowWorkspaceOptions}
          onRunCreated={loadAll}
        />
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
        <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">Project activity</h2>

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
    </div>
  )
}
