import { useState, useEffect, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { SpaceLink as Link } from '../../core/spaceNav'
import { ArrowLeft, ExternalLink } from 'lucide-react'
import { toast } from 'sonner'
import { agentsApi, artifactsApi, tasksApi } from '../../api/client'
import { useSpace } from '../../contexts/SpaceContext'
import { errMsg, isNotFoundError } from '../../lib/utils'
import type { AgentOut, Task, TaskArtifact, TaskProposal, TaskRunCreateBody, TaskRunListItem } from '../../types/api'
import { Card } from '../../components/ui/card'
import { Button } from '../../components/ui/button'
import { Badge, StatusBadge } from '../../components/ui/badge'
import { Label } from '../../components/ui/label'
import { Select } from '../../components/ui/select'
import { Skeleton } from '../../components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../components/ui/tabs'
import { EmptyState } from '../../components/ui/empty-state'
import { PreviewBadge, DryRunBanner } from '../../components/PreviewBadge'
import { ScopeBadge } from '../../components/ScopeBadge'
import { ContextArtifactPicker } from '../artifacts/ContextArtifactPicker'

function fmt(dt: string | null | undefined) {
  return dt ? new Date(dt).toLocaleString() : '—'
}

function JsonBlock({ value }: { value: unknown }) {
  if (value === undefined || value === null) return <span className="text-muted-foreground text-sm">—</span>
  return (
    <pre className="text-xs bg-muted/40 rounded-md p-3 overflow-x-auto border border-border">
      {typeof value === 'string' ? value : JSON.stringify(value, null, 2)}
    </pre>
  )
}

export default function TaskDetailPage() {
  const { taskId = '' } = useParams()
  const { activeSpaceId, activeSpaceName } = useSpace()
  const [task, setTask] = useState<Task | null>(null)
  const [runs, setRuns] = useState<TaskRunListItem[]>([])
  const [arts, setArts] = useState<TaskArtifact[]>([])
  const [props, setProps] = useState<TaskProposal[]>([])
  const [agents, setAgents] = useState<AgentOut[]>([])
  const [loading, setLoading] = useState(true)
  const [mode, setMode] = useState<string>('live')
  const [agentPick, setAgentPick] = useState<string>('')
  const [contextArtifactIds, setContextArtifactIds] = useState<string[]>([])
  const [creatingRun, setCreatingRun] = useState(false)

  const load = useCallback(async () => {
    if (!taskId) return
    if (!activeSpaceId) {
      setTask(null)
      setRuns([])
      setArts([])
      setProps([])
      setAgents([])
      setLoading(false)
      return
    }
    setLoading(true)
    try {
      const [t, r, a, p, ag] = await Promise.all([
        tasksApi.get(taskId),
        tasksApi.runs(taskId, { limit: '50' }),
        tasksApi.artifacts(taskId, { limit: '50' }),
        tasksApi.proposals(taskId, { limit: '50' }),
        agentsApi.list({ limit: '50' }).catch(() => []),
      ])
      setTask(t)
      setRuns(r.items)
      setArts(a.items)
      setProps(p.items)
      setAgents(ag)
    } catch (e) {
      if (!isNotFoundError(e)) toast.error(errMsg(e))
      setTask(null)
    } finally {
      setLoading(false)
    }
  }, [taskId, activeSpaceId])

  useEffect(() => { load() }, [load])

  async function createRun() {
    if (!taskId || !task) return
    setCreatingRun(true)
    try {
      const body: TaskRunCreateBody = { mode }
      const aid = task.assigned_agent_id || agentPick || undefined
      if (aid) body.agent_id = aid
      if (contextArtifactIds.length > 0) body.context_artifact_ids = contextArtifactIds
      await tasksApi.createRun(taskId, body)
      toast.success('Queued run created')
      await load()
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setCreatingRun(false)
    }
  }

  async function exportArt(artifactId: string) {
    try {
      await artifactsApi.export(artifactId)
      toast.success('Download started')
    } catch (e) {
      toast.error(errMsg(e))
    }
  }

  if (loading && !task) {
    return (
      <div className="p-6 space-y-4">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-48 w-full" />
      </div>
    )
  }

  if (!task) {
    return (
      <div className="p-6">
        <Button variant="ghost" asChild>
          <Link to="/tasks"><ArrowLeft className="size-4 mr-1" />Back</Link>
        </Button>
        <EmptyState
          className="mt-6"
          title={activeSpaceId ? 'Task not found or not accessible' : 'No space selected'}
          description={activeSpaceId
            ? 'This task may not exist, or it may not be visible in your current space.'
            : 'Select an operational space to inspect this task.'}
          action={
            <Button variant="ghost" asChild>
              <Link to="/tasks">Back to Tasks</Link>
            </Button>
          }
        />
      </div>
    )
  }

  const agentOptions = agents.map(a => ({ value: a.id, label: a.name }))
  const needsAgentPick = !task.assigned_agent_id

  return (
    <div className="p-6 space-y-6 max-w-5xl">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" asChild>
          <Link to="/tasks"><ArrowLeft className="size-4" /></Link>
        </Button>
      </div>

      <div className="border-b border-border pb-4 space-y-3">
        <h1 className="text-xl font-semibold tracking-tight">{task.title}</h1>
        <p className="text-xs text-muted-foreground">Viewing: {activeSpaceName ?? activeSpaceId ?? 'No operational space selected'}</p>
        <div className="flex flex-wrap gap-1.5 items-center">
          <StatusBadge status={task.status} />
          <Badge variant="outline">{task.priority}</Badge>
          <Badge variant="muted">{task.risk_level} risk</Badge>
          <Badge variant="secondary">{task.task_type}</Badge>
          <ScopeBadge visibility={task.visibility} />
          {task.assigned_agent_id && (
            <Badge variant="outline">agent {task.assigned_agent_id.slice(0, 8)}…</Badge>
          )}
          {task.assigned_user_id && (
            <Badge variant="outline">user {task.assigned_user_id.slice(0, 8)}…</Badge>
          )}
          {task.due_at && <span className="text-xs text-muted-foreground">Due {fmt(task.due_at)}</span>}
        </div>
        {mode === 'dry_run' && <DryRunBanner />}
        <div className="flex flex-wrap gap-3 items-end pt-2">
          {needsAgentPick && (
            <div className="min-w-[200px]">
              <Label className="text-xs">Agent for this run</Label>
              <Select
                value={agentPick}
                options={[{ value: '', label: 'Select agent…' }, ...agentOptions]}
                onChange={setAgentPick}
              />
            </div>
          )}
          <div className="min-w-[140px]">
            <Label className="text-xs">Mode</Label>
            <Select
              value={mode}
              options={[
                { value: 'live', label: 'live' },
                { value: 'dry_run', label: 'dry_run' },
              ]}
              onChange={setMode}
            />
          </div>
          <Button
            onClick={createRun}
            disabled={creatingRun || (needsAgentPick && !agentPick)}
          >
            {creatingRun ? 'Creating…' : 'Create queued run'}
          </Button>
        </div>
        <ContextArtifactPicker
          className="pt-2"
          title="Run context artifacts"
          description="Selected artifacts will be attached to the queued task run."
          selectedArtifactIds={contextArtifactIds}
          onChange={setContextArtifactIds}
          workspaceId={task.workspace_id}
        />
      </div>

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="runs">Runs</TabsTrigger>
          <TabsTrigger value="artifacts">Artifacts</TabsTrigger>
          <TabsTrigger value="proposals">Proposals</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-4 mt-4">
          <Card className="p-4 space-y-3">
            <div>
              <Label className="text-xs text-muted-foreground">Description</Label>
              <p className="text-sm mt-1 whitespace-pre-wrap">{task.description ?? '—'}</p>
            </div>
            <div>
              <Label className="text-xs text-muted-foreground">Acceptance criteria</Label>
              <div className="mt-1"><JsonBlock value={task.acceptance_criteria_json ?? null} /></div>
            </div>
            <div>
              <Label className="text-xs text-muted-foreground">Definition of done</Label>
              <p className="text-sm mt-1 whitespace-pre-wrap">{task.definition_of_done ?? '—'}</p>
            </div>
            <div>
              <Label className="text-xs text-muted-foreground">Required outputs</Label>
              <div className="mt-1"><JsonBlock value={task.required_outputs_json ?? null} /></div>
            </div>
            <div>
              <Label className="text-xs text-muted-foreground">Blocked reason</Label>
              <p className="text-sm mt-1">{task.blocked_reason ?? '—'}</p>
            </div>
            <div>
              <Label className="text-xs text-muted-foreground">Tags</Label>
              <p className="text-sm mt-1">
                {task.tags?.length ? task.tags.join(', ') : '—'}
              </p>
            </div>
          </Card>
        </TabsContent>

        <TabsContent value="runs" className="space-y-3 mt-4">
          {runs.length === 0 ? (
            <Card className="p-8 text-center text-sm text-muted-foreground">No runs yet.</Card>
          ) : runs.map(({ link, run }) => (
            <Card key={link.id} className="p-4 flex flex-wrap items-center justify-between gap-2">
              <div className="space-y-1">
                <div className="flex flex-wrap gap-1.5 items-center">
                  <StatusBadge status={run.status} />
                  <Badge variant="secondary">{run.mode}</Badge>
                  <ScopeBadge visibility={run.visibility} omitShared />
                  <span className="font-mono text-xs text-muted-foreground">{run.id}</span>
                  {run.mode === 'dry_run' && <PreviewBadge />}
                </div>
                <p className="text-xs text-muted-foreground">
                  created {fmt(run.created_at)} · started {fmt(run.started_at)} · ended {fmt(run.ended_at)}
                </p>
              </div>
              <Button size="sm" variant="outline" asChild>
                <Link to={`/runs/${run.id}`}>Open run <ExternalLink className="size-3 ml-1" /></Link>
              </Button>
            </Card>
          ))}
        </TabsContent>

        <TabsContent value="artifacts" className="space-y-3 mt-4">
          {arts.length === 0 ? (
            <Card className="p-8 text-center text-sm text-muted-foreground">No artifacts linked.</Card>
          ) : arts.map(row => (
            <Card key={row.id} className="p-4 flex flex-wrap justify-between gap-2">
              <div>
                <Link
                  to={`/artifacts/${row.artifact.id}`}
                  className="font-medium text-sm text-accent-foreground hover:underline"
                >
                  {row.artifact.title}
                </Link>
                <div className="flex gap-1.5 mt-1 flex-wrap">
                  <Badge variant="secondary">{row.artifact.artifact_type}</Badge>
                  {row.run_id && <Badge variant="outline">run: {row.run_id.slice(0, 8)}…</Badge>}
                  {row.artifact.run_id && row.artifact.run_id !== row.run_id && (
                    <Badge variant="muted">produced: {row.artifact.run_id.slice(0, 8)}…</Badge>
                  )}
                  <ScopeBadge visibility={row.artifact.visibility} omitShared />
                  {row.artifact.preview && <PreviewBadge />}
                  <span className="text-xs text-muted-foreground">{fmt(row.created_at)}</span>
                </div>
              </div>
              <Button size="sm" variant="outline" onClick={() => exportArt(row.artifact.id)}>Export</Button>
            </Card>
          ))}
        </TabsContent>

        <TabsContent value="proposals" className="space-y-3 mt-4">
          {props.length === 0 ? (
            <Card className="p-8 text-center text-sm text-muted-foreground">No proposals linked.</Card>
          ) : props.map(row => (
            <Card key={row.id} className="p-4 space-y-2">
              <div className="flex flex-wrap gap-1.5 items-center">
                <Link
                  to={`/proposals/${row.proposal.id}`}
                  className="font-medium text-sm text-accent-foreground hover:underline"
                >
                  {row.proposal.title}
                </Link>
                <Badge variant="outline">{row.proposal.proposal_type}</Badge>
                <StatusBadge status={row.proposal.status} />
                <ScopeBadge visibility={row.proposal.visibility} omitShared />
                {row.proposal.preview && <PreviewBadge />}
                {row.proposal.expired && <Badge variant="destructive">EXPIRED</Badge>}
              </div>
            </Card>
          ))}
        </TabsContent>
      </Tabs>
    </div>
  )
}
