import { useState, useEffect, useCallback, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { Play } from 'lucide-react'
import { toast } from 'sonner'
import { runsApi } from '../../api/client'
import { useSpace } from '../../contexts/SpaceContext'
import { errMsg } from '../../lib/utils'
import type { Run } from '../../types/api'
import { Card } from '../../components/ui/card'
import { Button } from '../../components/ui/button'
import { Badge, StatusBadge } from '../../components/ui/badge'
import { Label } from '../../components/ui/label'
import { Select } from '../../components/ui/select'
import { Skeleton } from '../../components/ui/skeleton'
import { PreviewBadge } from '../../components/PreviewBadge'
import { ScopeBadge } from '../../components/ScopeBadge'

function fmt(dt: string | null | undefined) {
  return dt ? new Date(dt).toLocaleString() : '—'
}

function RunRow({ r, onRefresh }: { r: Run; onRefresh: () => void }) {
  return (
    <Card className="p-4 flex flex-wrap items-start justify-between gap-3">
      <div className="space-y-2 min-w-0 flex-1">
        <div className="flex flex-wrap gap-1.5 items-center">
          <StatusBadge status={r.status} />
          <Badge variant="secondary">{r.mode}</Badge>
          {r.run_type && <Badge variant="outline">{r.run_type}</Badge>}
          {r.mode === 'dry_run' && <PreviewBadge />}
          <ScopeBadge visibility={r.visibility} omitShared />
          <span className="font-mono text-xs text-muted-foreground truncate max-w-[200px]">{r.id}</span>
        </div>
        <p className="text-xs text-muted-foreground">
          agent {r.agent_id.slice(0, 10)}… · created {fmt(r.created_at)}
          {r.started_at && ` · started ${fmt(r.started_at)}`}
          {r.ended_at && ` · ended ${fmt(r.ended_at)}`}
        </p>
        {r.task_id && (
          <Link to={`/tasks/${r.task_id}`} className="text-xs text-accent-foreground hover:underline">
            Task {r.task_id.slice(0, 10)}…
          </Link>
        )}
        {r.status === 'failed' && r.error_message && (
          <p className="text-xs text-destructive border border-destructive/20 rounded p-2 bg-destructive/5">
            {r.error_message}
          </p>
        )}
      </div>
      <div className="flex flex-col gap-2 shrink-0">
        <Button size="sm" variant="outline" asChild>
          <Link to={`/runs/${r.id}`}>Open</Link>
        </Button>
        {(r.status === 'queued' || r.status === 'running') && (
          <StopRunButton runId={r.id} onDone={onRefresh} />
        )}
      </div>
    </Card>
  )
}

function StopRunButton({ runId, onDone }: { runId: string; onDone: () => void }) {
  const [busy, setBusy] = useState(false)
  async function stop() {
    setBusy(true)
    try {
      await runsApi.stop(runId)
      toast.success('Stop requested')
      onDone()
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Button size="sm" variant="destructive" onClick={stop} disabled={busy}>
      {busy ? '…' : 'Stop'}
    </Button>
  )
}

export default function RunsPage() {
  const { activeOperationalSpaceId, activeOperationalSpaceName } = useSpace()
  const [runs, setRuns] = useState<Run[]>([])
  const [loading, setLoading] = useState(true)
  const [fStatus, setFStatus] = useState('')
  const [fMode, setFMode] = useState('')
  const [fAgent, setFAgent] = useState('')
  const [fWs, setFWs] = useState('')

  const load = useCallback(async () => {
    if (!activeOperationalSpaceId) {
      setRuns([])
      setLoading(false)
      return
    }
    setLoading(true)
    try {
      const q: Record<string, string> = { limit: '100' }
      if (fStatus) q.status = fStatus
      if (fMode) q.mode = fMode
      if (fAgent) q.agent_id = fAgent
      if (fWs) q.workspace_id = fWs
      const data = await runsApi.list(q)
      setRuns(data)
    } catch (e) {
      toast.error(errMsg(e))
      setRuns([])
    } finally {
      setLoading(false)
    }
  }, [fStatus, fMode, fAgent, fWs, activeOperationalSpaceId])

  useEffect(() => { load() }, [load])

  const agentOpts = useMemo(() => {
    const s = new Set<string>()
    runs.forEach(r => s.add(r.agent_id))
    return [...s].sort().map(v => ({ value: v, label: v.slice(0, 12) + '…' }))
  }, [runs])

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center gap-4 pb-4 border-b border-border">
        <div
          className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
          style={{
            background: 'color-mix(in oklch, var(--primary) 12%, transparent)',
            border: '1px solid color-mix(in oklch, var(--primary) 35%, transparent)',
          }}
        >
          <Play className="size-5 text-accent-foreground" />
        </div>
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Runs</h1>
          <p className="text-sm text-muted-foreground">Canonical runs: queue, status, and links to activity and artifacts.</p>
          <p className="text-xs text-muted-foreground">Viewing: {activeOperationalSpaceName ?? activeOperationalSpaceId ?? 'No operational space selected'}</p>
        </div>
      </div>

      <div className="flex flex-wrap gap-3 items-end">
        <div className="min-w-[120px]">
          <Label className="text-xs">Status</Label>
          <Select
            value={fStatus}
            options={[
              { value: '', label: 'Any' },
              { value: 'queued', label: 'queued' },
              { value: 'running', label: 'running' },
              { value: 'succeeded', label: 'succeeded' },
              { value: 'failed', label: 'failed' },
              { value: 'cancelled', label: 'cancelled' },
              { value: 'degraded', label: 'degraded' },
              { value: 'waiting_for_review', label: 'waiting_for_review' },
            ]}
            onChange={setFStatus}
          />
        </div>
        <div className="min-w-[120px]">
          <Label className="text-xs">Mode</Label>
          <Select
            value={fMode}
            options={[
              { value: '', label: 'Any' },
              { value: 'live', label: 'live' },
              { value: 'dry_run', label: 'dry_run' },
            ]}
            onChange={setFMode}
          />
        </div>
        <div className="min-w-[140px]">
          <Label className="text-xs">Agent id</Label>
          <Select
            value={fAgent}
            options={[{ value: '', label: 'Any' }, ...agentOpts]}
            onChange={setFAgent}
          />
        </div>
        <div className="min-w-[160px]">
          <Label className="text-xs">Workspace id</Label>
          <input
            className="flex h-9 w-full rounded-md border border-border bg-transparent px-2 text-xs font-mono"
            placeholder="filter…"
            value={fWs}
            onChange={e => setFWs(e.target.value)}
          />
        </div>
        <Button variant="secondary" size="sm" onClick={load}>Refresh</Button>
      </div>

      {loading ? (
        <Card className="p-6 space-y-3">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </Card>
      ) : runs.length === 0 ? (
        <Card className="p-10 text-center text-sm text-muted-foreground">
          {activeOperationalSpaceId ? 'No runs in this operational space.' : 'Select an operational space to browse runs.'}
        </Card>
      ) : (
        <div className="space-y-3">
          {runs.map(r => <RunRow key={r.id} r={r} onRefresh={load} />)}
        </div>
      )}
    </div>
  )
}
