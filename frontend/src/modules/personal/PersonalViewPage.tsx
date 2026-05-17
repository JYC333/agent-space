import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Inbox, ListTodo, Play, ShieldAlert } from 'lucide-react'
import { toast } from 'sonner'
import { meApi } from '../../api/client'
import { useSpace } from '../../contexts/SpaceContext'
import { errMsg } from '../../lib/utils'
import type { MePendingProposalItem, MeSummaryOut, MeTaskItem, MeTimelineEntry } from '../../types/api'
import { Card } from '../../components/ui/card'
import { Badge, StatusBadge } from '../../components/ui/badge'
import { Skeleton } from '../../components/ui/skeleton'
import { ScopeBadge } from '../../components/ScopeBadge'

function fmt(dt: string | null | undefined) {
  return dt ? new Date(dt).toLocaleString() : '—'
}

function objectPath(type: string | null, id: string | null): string | null {
  if (!type || !id) return null
  if (type === 'task') return `/tasks/${id}`
  if (type === 'run') return `/runs/${id}`
  if (type === 'proposal') return `/proposals/${id}`
  if (type === 'activity') return `/activity/${id}`
  if (type === 'artifact') return `/artifacts/${id}`
  return null
}

function timelineText(entry: MeTimelineEntry, spaceName: string) {
  const role = entry.role ?? 'participated in'
  const type = entry.source_object_type ?? 'object'
  const action =
    role === 'created' && type === 'activity' ? 'created an activity' :
    role === 'created' && type === 'task' ? 'created a task' :
    role === 'instructed' && type === 'run' ? 'ran an agent' :
    role === 'reviewed' && type === 'proposal' ? 'reviewed a proposal' :
    `${role} ${type}`
  return `You ${action} in ${spaceName}`
}

export default function PersonalViewPage() {
  const { spaces, personalSpaceId, perspective, setPerspective } = useSpace()
  const [summary, setSummary] = useState<MeSummaryOut | null>(null)
  const [timeline, setTimeline] = useState<MeTimelineEntry[]>([])
  const [tasks, setTasks] = useState<MeTaskItem[]>([])
  const [pending, setPending] = useState<MePendingProposalItem[]>([])
  const [loading, setLoading] = useState(true)

  const spaceName = useMemo(() => {
    const map = new Map<string, string>()
    spaces.forEach(s => map.set(s.id, s.name))
    return (id: string | null | undefined) => (id ? map.get(id) ?? id : 'Unknown space')
  }, [spaces])

  useEffect(() => {
    if (perspective !== 'personal') setPerspective('personal')
  }, [perspective, setPerspective])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      try {
        const [s, tl, t, p] = await Promise.all([
          meApi.summary({ recent_runs_limit: '5', recent_participation_limit: '5' }),
          meApi.timeline({ limit: '30' }),
          meApi.tasks({ limit: '20' }),
          meApi.pending({ limit: '20' }),
        ])
        if (cancelled) return
        setSummary(s)
        setTimeline(tl)
        setTasks(t)
        setPending(p)
      } catch (e) {
        if (!cancelled) toast.error(errMsg(e))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [])

  if (!personalSpaceId) {
    return (
      <div className="p-6">
        <Card className="p-8 max-w-2xl">
          <div className="flex items-start gap-3">
            <ShieldAlert className="size-5 text-warning shrink-0 mt-0.5" />
            <div>
              <h1 className="text-lg font-semibold">Personal space unavailable</h1>
              <p className="text-sm text-muted-foreground mt-1">
                Personal perspective needs a Personal Space write target. Create or restore your personal space before using this view.
              </p>
            </div>
          </div>
        </Card>
      </div>
    )
  }

  const s = summary ?? {
    pending_proposals_count: 0,
    assigned_tasks_count: 0,
    recent_runs: [],
    recent_participation: [],
    accessible_spaces_count: spaces.length,
  }

  const empty = !loading && timeline.length === 0 && tasks.length === 0 && pending.length === 0 && s.recent_runs.length === 0

  return (
    <div className="p-6 space-y-6 max-w-6xl">
      <div className="flex items-start justify-between gap-4 border-b border-border pb-4">
        <div>
          <div className="text-[10px] font-bold tracking-[.1em] uppercase text-muted-foreground">Personal</div>
          <h1 className="text-2xl font-semibold tracking-tight">Personal</h1>
          <p className="text-sm text-muted-foreground">Your private ledger and cross-space activity.</p>
        </div>
        <Badge variant="outline">{s.accessible_spaces_count} spaces</Badge>
      </div>

      {loading ? (
        <div className="space-y-3">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-36 w-full" />
        </div>
      ) : empty ? (
        <Card className="p-10 text-center text-sm text-muted-foreground">
          Your personal view will show your private work and participation across spaces.
        </Card>
      ) : (
        <>
          <div className="grid gap-3 md:grid-cols-3">
            <Card className="p-4">
              <div className="flex items-center gap-2 text-xs text-muted-foreground"><Inbox className="size-3.5" /> Pending</div>
              <div className="text-2xl font-semibold mt-2">{s.pending_proposals_count}</div>
              <div className="text-xs text-muted-foreground">proposals need attention</div>
            </Card>
            <Card className="p-4">
              <div className="flex items-center gap-2 text-xs text-muted-foreground"><ListTodo className="size-3.5" /> Tasks</div>
              <div className="text-2xl font-semibold mt-2">{s.assigned_tasks_count}</div>
              <div className="text-xs text-muted-foreground">assigned, created, or claimed</div>
            </Card>
            <Card className="p-4">
              <div className="flex items-center gap-2 text-xs text-muted-foreground"><Play className="size-3.5" /> Recent Runs</div>
              <div className="text-2xl font-semibold mt-2">{s.recent_runs.length}</div>
              <div className="text-xs text-muted-foreground">instructed by you</div>
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.8fr)]">
            <Card className="p-4 space-y-3">
              <h2 className="text-sm font-semibold">Timeline</h2>
              {timeline.length === 0 ? (
                <p className="text-sm text-muted-foreground py-6">No participation records yet.</p>
              ) : timeline.map(item => {
                const href = objectPath(item.source_object_type, item.source_object_id)
                const label = timelineText(item, spaceName(item.source_space_id))
                return (
                  <div key={item.id} className="flex items-start justify-between gap-3 border-t border-border pt-3 first:border-t-0 first:pt-0">
                    <div className="min-w-0">
                      {href ? (
                        <Link to={href} className="text-sm font-medium text-accent-foreground hover:underline">{label}</Link>
                      ) : (
                        <div className="text-sm font-medium">{label}</div>
                      )}
                      <div className="text-xs text-muted-foreground">
                        {item.source_object_type ?? 'object'} · {fmt(item.occurred_at)}
                      </div>
                    </div>
                    <Badge variant="muted">{item.role ?? 'record'}</Badge>
                  </div>
                )
              })}
            </Card>

            <Card className="p-4 space-y-3">
              <h2 className="text-sm font-semibold">Recent Runs</h2>
              {s.recent_runs.length === 0 ? (
                <p className="text-sm text-muted-foreground py-6">No recent runs.</p>
              ) : s.recent_runs.map(run => (
                <Link key={run.id} to={`/runs/${run.id}`} className="block rounded-md border border-border p-3 hover:bg-accent/30">
                  <div className="flex flex-wrap gap-1.5 items-center">
                    <StatusBadge status={run.status} />
                    <Badge variant="secondary">{run.mode}</Badge>
                    <Badge variant="outline">{spaceName(run.space_id)}</Badge>
                  </div>
                  <div className="text-xs text-muted-foreground mt-1">{fmt(run.created_at)}</div>
                </Link>
              ))}
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card className="p-4 space-y-3">
              <h2 className="text-sm font-semibold">Tasks</h2>
              {tasks.length === 0 ? (
                <p className="text-sm text-muted-foreground py-6">No personal task matches.</p>
              ) : tasks.map(task => (
                <Link key={task.id} to={`/tasks/${task.id}`} className="block rounded-md border border-border p-3 hover:bg-accent/30">
                  <div className="flex flex-wrap gap-1.5 items-center">
                    <span className="font-medium text-sm">{task.title}</span>
                    <StatusBadge status={task.status} />
                    <ScopeBadge visibility={task.visibility} spaceName={spaceName(task.space_id)} />
                  </div>
                  <div className="text-xs text-muted-foreground mt-1">{spaceName(task.space_id)} · updated {fmt(task.updated_at)}</div>
                </Link>
              ))}
            </Card>

            <Card className="p-4 space-y-3">
              <h2 className="text-sm font-semibold">Pending</h2>
              {pending.length === 0 ? (
                <p className="text-sm text-muted-foreground py-6">No pending proposals.</p>
              ) : pending.map(proposal => (
                <div key={proposal.id} className="rounded-md border border-border p-3">
                  <div className="flex flex-wrap gap-1.5 items-center">
                    <Link to={`/proposals/${proposal.id}`} className="font-medium text-sm text-accent-foreground hover:underline">
                      {proposal.title}
                    </Link>
                    <Badge variant="outline">{proposal.proposal_type}</Badge>
                    <StatusBadge status={proposal.status} />
                    <ScopeBadge visibility={proposal.visibility} spaceName={spaceName(proposal.space_id)} />
                  </div>
                  <div className="text-xs text-muted-foreground mt-1">{spaceName(proposal.space_id)} · {fmt(proposal.created_at)}</div>
                </div>
              ))}
            </Card>
          </div>
        </>
      )}
    </div>
  )
}
