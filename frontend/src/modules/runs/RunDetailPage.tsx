import { useEffect, useState, useCallback } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, ExternalLink, FlaskConical } from 'lucide-react'
import { toast } from 'sonner'
import { artifactsApi, runsApi } from '../../api/client'
import { errMsg } from '../../lib/utils'
import type { ActivityRecord, Artifact, Proposal, Run } from '../../types/api'
import { Card } from '../../components/ui/card'
import { Button } from '../../components/ui/button'
import { Badge, StatusBadge } from '../../components/ui/badge'
import { Skeleton } from '../../components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../components/ui/tabs'
import { PreviewBadge, DryRunBanner, UrgencyBadge } from '../../components/PreviewBadge'
import { useRun, RUN_TERMINAL_STATUSES } from '../../hooks/useRun'

function fmt(dt: string | null | undefined) {
  return dt ? new Date(dt).toLocaleString() : '—'
}

export default function RunDetailPage() {
  const { runId = '' } = useParams()
  const [reloadKey, setReloadKey] = useState(0)
  const [executingRun, setExecutingRun] = useState(false)
  const { run: polled, loading, error } = useRun(runId || null, reloadKey)
  const [activities, setActivities] = useState<ActivityRecord[]>([])
  const [artifacts, setArtifacts] = useState<Artifact[]>([])
  const [proposals, setProposals] = useState<Proposal[]>([])
  const [tabLoading, setTabLoading] = useState(true)

  const loadSubs = useCallback(async () => {
    if (!runId) return
    setTabLoading(true)
    try {
      const [a, ar, pr] = await Promise.all([
        runsApi.activities(runId, { limit: '100' }),
        runsApi.artifacts(runId, { limit: '100' }),
        runsApi.proposals(runId, { limit: '100' }),
      ])
      setActivities(a.items)
      setArtifacts(ar.items)
      setProposals(pr.items)
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setTabLoading(false)
    }
  }, [runId])

  useEffect(() => {
    void loadSubs()
  }, [loadSubs])

  // Sub-resources are created when the run finishes; refetch when polling reaches a terminal status
  // (mount-only loadSubs() would leave tabs empty after queued → succeeded without leaving the page).
  useEffect(() => {
    if (!runId || !polled?.status) return
    if (!RUN_TERMINAL_STATUSES.has(polled.status)) return
    void loadSubs()
  }, [runId, polled?.status, loadSubs])

  async function exportArt(id: string) {
    try {
      await artifactsApi.export(id)
      toast.success('Download started')
    } catch (e) {
      toast.error(errMsg(e))
    }
  }

  async function runQueuedExecution() {
    if (!runId) return
    setExecutingRun(true)
    try {
      await runsApi.executeQueuedRun(runId)
      toast.success('Run finished — status should be terminal (e.g. succeeded).')
      setReloadKey(k => k + 1)
      await loadSubs()
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setExecutingRun(false)
    }
  }

  if (loading && !polled) {
    return (
      <div className="p-6 space-y-4 max-w-4xl">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }

  if (error || !polled) {
    return (
      <div className="p-6">
        <Button variant="ghost" asChild>
          <Link to="/runs"><ArrowLeft className="size-4 mr-1" />Runs</Link>
        </Button>
        <p className="text-destructive mt-4 text-sm">{error ?? 'Run not found.'}</p>
      </div>
    )
  }

  const r: Run = polled

  return (
    <div className="p-6 space-y-6 max-w-4xl">
      <Button variant="ghost" size="sm" asChild>
        <Link to="/runs"><ArrowLeft className="size-4" /></Link>
      </Button>

      <div className="space-y-3 border-b border-border pb-4">
        <h1 className="text-xl font-semibold tracking-tight font-mono">{r.id}</h1>
        <div className="flex flex-wrap gap-1.5 items-center">
          <StatusBadge status={r.status} />
          <Badge variant="secondary">{r.mode}</Badge>
          {r.mode === 'dry_run' && <PreviewBadge />}
          <Badge variant="outline">{r.run_type}</Badge>
        </div>
        {r.mode === 'dry_run' && <DryRunBanner />}
        <div className="grid gap-2 text-sm sm:grid-cols-2">
          <p><span className="text-muted-foreground">agent_id</span><br /><span className="font-mono text-xs">{r.agent_id}</span></p>
          <p><span className="text-muted-foreground">agent_version_id</span><br /><span className="font-mono text-xs">{r.agent_version_id}</span></p>
          <p><span className="text-muted-foreground">context_snapshot_id</span><br /><span className="font-mono text-xs">{r.context_snapshot_id ?? '—'}</span></p>
          <p><span className="text-muted-foreground">timestamps</span><br />
            <span className="text-xs">created {fmt(r.created_at)} · started {fmt(r.started_at)} · ended {fmt(r.ended_at)}</span>
          </p>
        </div>
        {r.status === 'failed' && r.error_message && (
          <Card className="p-3 border-destructive/30 bg-destructive/5 text-sm text-destructive">
            {r.error_message}
          </Card>
        )}
        {r.task_id && (
          <Link to={`/tasks/${r.task_id}`} className="text-sm text-accent-foreground hover:underline inline-flex items-center gap-1">
            Open linked task <ExternalLink className="size-3" />
          </Link>
        )}

        {r.status === 'queued' && (
          <div className="rounded-lg border border-border bg-muted/30 p-3 space-y-2 mt-2">
            <p className="text-xs text-muted-foreground">
              Dev: execute this queued run in-process (echo adapter). No real CLI / LLM.
            </p>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              className="gap-1.5"
              disabled={executingRun}
              onClick={runQueuedExecution}
            >
              <FlaskConical className="size-4" />
              {executingRun ? 'Running…' : 'Execute run'}
            </Button>
          </div>
        )}
      </div>

      <Tabs defaultValue="activities">
        <TabsList>
          <TabsTrigger value="activities">Activities</TabsTrigger>
          <TabsTrigger value="artifacts">Artifacts</TabsTrigger>
          <TabsTrigger value="proposals">Proposals</TabsTrigger>
        </TabsList>

        <TabsContent value="activities" className="mt-4 space-y-3">
          {tabLoading ? <Skeleton className="h-24 w-full" /> : activities.length === 0 ? (
            <Card className="p-8 text-center text-sm text-muted-foreground">No activities.</Card>
          ) : (
            activities.map(act => (
              <Card key={act.id} className="p-4 border-l-2 border-l-primary/40">
                <div className="flex justify-between gap-2 flex-wrap">
                  <Link
                    to={`/activity/${act.id}`}
                    className="text-sm font-medium text-accent-foreground hover:underline"
                  >
                    {act.title ?? act.activity_type}
                  </Link>
                  <span className="text-xs text-muted-foreground">{fmt(act.occurred_at)}</span>
                </div>
                <Badge variant="outline" className="mt-2">{act.activity_type}</Badge>
                {act.content && <p className="text-xs text-muted-foreground mt-2 whitespace-pre-wrap">{act.content}</p>}
              </Card>
            ))
          )}
        </TabsContent>

        <TabsContent value="artifacts" className="mt-4 space-y-3">
          {tabLoading ? <Skeleton className="h-24 w-full" /> : artifacts.length === 0 ? (
            <Card className="p-8 text-center text-sm text-muted-foreground">No artifacts.</Card>
          ) : (
            artifacts.map(a => (
              <Card key={a.id} className="p-4 flex flex-wrap justify-between gap-2">
                <div>
                  <Link
                    to={`/artifacts/${a.id}`}
                    className="font-medium text-sm text-accent-foreground hover:underline"
                  >
                    {a.title}
                  </Link>
                  <div className="flex gap-1.5 mt-1 flex-wrap">
                    <Badge variant="secondary">{a.artifact_type}</Badge>
                    {a.preview && <PreviewBadge />}
                    <span className="text-xs text-muted-foreground">{fmt(a.created_at)}</span>
                  </div>
                </div>
                <Button size="sm" variant="outline" onClick={() => exportArt(a.id)}>Export</Button>
              </Card>
            ))
          )}
        </TabsContent>

        <TabsContent value="proposals" className="mt-4 space-y-3">
          {tabLoading ? <Skeleton className="h-24 w-full" /> : proposals.length === 0 ? (
            <Card className="p-8 text-center text-sm text-muted-foreground">No proposals.</Card>
          ) : (
            proposals.map(p => (
              <Card key={p.id} className="p-4 space-y-2">
                <div className="flex flex-wrap gap-1.5 items-center">
                  <Link
                    to={`/proposals/${p.id}`}
                    className="font-medium text-sm text-accent-foreground hover:underline"
                  >
                    {p.proposed_title}
                  </Link>
                  <Badge variant="outline">{p.proposal_type}</Badge>
                  <StatusBadge status={p.status} />
                  <UrgencyBadge urgency={p.urgency} />
                  {p.preview && <PreviewBadge />}
                  {p.expired && <Badge variant="destructive">EXPIRED</Badge>}
                </div>
                <p className="text-xs text-muted-foreground">
                  review_deadline {fmt(p.review_deadline)} · expires {fmt(p.expires_at)}
                </p>
                {p.created_by_run_id && p.created_by_run_id !== runId && (
                  <Link to={`/runs/${p.created_by_run_id}`} className="text-xs text-accent-foreground hover:underline">
                    From run {p.created_by_run_id.slice(0, 10)}…
                  </Link>
                )}
              </Card>
            ))
          )}
        </TabsContent>
      </Tabs>
    </div>
  )
}
