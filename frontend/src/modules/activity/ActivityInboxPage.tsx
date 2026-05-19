import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { Inbox } from 'lucide-react'
import { toast } from 'sonner'
import { activityApi } from '../../api/client'
import { useSpace } from '../../contexts/SpaceContext'
import { errMsg } from '../../lib/utils'
import type { ActivityInboxRecord, ActivityStatus, ActivitySourceType } from '../../types/api'
import { Card } from '../../components/ui/card'
import { Button } from '../../components/ui/button'
import { Badge } from '../../components/ui/badge'
import { EmptyState } from '../../components/ui/empty-state'
import { ScopeBadge } from '../../components/ScopeBadge'

function fmt(dt: string) { return new Date(dt).toLocaleString() }

const STATUS_FILTERS: ActivityStatus[] = ['raw', 'processed', 'proposals_generated', 'archived']

const SOURCE_COLORS: Record<ActivitySourceType, string> = {
  user_capture:    'default',
  chat_message:    'secondary',
  external_chat:   'secondary',
  web_capture:     'secondary',
  file_import:     'secondary',
  run_event:       'muted',
  workspace_event: 'muted',
  system_event:    'muted',
  external_source: 'secondary',
}

export default function ActivityInboxPage() {
  const { activeOperationalSpaceId, activeOperationalSpaceName } = useSpace()
  const [records, setRecords]   = useState<ActivityInboxRecord[]>([])
  const [filter, setFilter]     = useState<ActivityStatus>('raw')
  const [loading, setLoading]   = useState(false)
  const [busy, setBusy]         = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!activeOperationalSpaceId) {
      setRecords([])
      setLoading(false)
      return
    }
    setLoading(true)
    try {
      const items = await activityApi.list({ status: filter })
      setRecords(items)
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setLoading(false)
    }
  }, [filter, activeOperationalSpaceId])

  useEffect(() => { load() }, [load])

  async function doProcess(id: string) {
    setBusy(id)
    try {
      await activityApi.process(id)
      toast.success('Marked as processed')
      await load()
    } catch (e) { toast.error(errMsg(e)) }
    finally { setBusy(null) }
  }

  async function doArchive(id: string) {
    setBusy(id)
    try {
      await activityApi.archive(id)
      toast.success('Archived')
      await load()
    } catch (e) { toast.error(errMsg(e)) }
    finally { setBusy(null) }
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between pb-4 border-b border-border">
        <div className="flex items-center gap-4">
          <div
            className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
            style={{
              background: 'color-mix(in oklch, var(--primary) 12%, transparent)',
              border: '1px solid color-mix(in oklch, var(--primary) 35%, transparent)',
            }}
          >
            <Inbox className="size-5 text-accent-foreground" />
          </div>
          <div>
            <h1 className="text-xl font-semibold tracking-tight">Activity Inbox</h1>
            <p className="text-sm text-muted-foreground">Raw input records before they become memory proposals.</p>
            <p className="text-xs text-muted-foreground">Viewing: {activeOperationalSpaceName ?? activeOperationalSpaceId ?? 'No operational space selected'}</p>
          </div>
        </div>
        <div className="flex gap-1.5">
          {STATUS_FILTERS.map(s => (
            <Button key={s} size="sm" variant={filter === s ? 'default' : 'ghost'} onClick={() => setFilter(s)}>
              {s.replace('_', ' ')}
            </Button>
          ))}
        </div>
      </div>

      {loading && (
        <Card><p className="text-muted-foreground text-center py-10 text-sm">Loading…</p></Card>
      )}

      {!loading && records.length === 0 && (
        !activeOperationalSpaceId ? (
          <EmptyState
            title="No space selected"
            description="Select an operational space to browse activity."
          />
        ) : filter === 'raw' ? (
          <EmptyState
            title="Nothing to process"
            description="Capture a thought, paste a link, or save a snippet to get started."
            action={
              <Button variant="outline" asChild>
                <Link to="/capture">Open Capture</Link>
              </Button>
            }
          />
        ) : (
          <EmptyState
            title={`No ${filter.replace(/_/g, ' ')} activity`}
            description={filter === 'archived'
              ? 'Archived records appear here after you dismiss them.'
              : 'Records that have been processed appear here.'}
          />
        )
      )}

      {!loading && records.map(r => (
        <Card key={r.id}>
          <div className="flex items-start justify-between gap-4 mb-3">
            <div>
              <span className="font-medium text-sm">
                <Link to={`/activity/${r.id}`} className="text-accent-foreground hover:underline">
                  {r.title ?? r.content.slice(0, 80)}
                </Link>
              </span>
              {r.title && <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">{r.content}</p>}
            </div>
            {(r.status === 'raw' || r.status === 'proposals_generated') && (
              <div className="flex gap-1.5 shrink-0">
                {r.status === 'raw' && (
                  <Button
                    size="sm" variant="secondary"
                    disabled={busy === r.id}
                    onClick={() => doProcess(r.id)}
                  >
                    Mark processed
                  </Button>
                )}
                <Button
                  size="sm" variant="ghost"
                  disabled={busy === r.id}
                  onClick={() => doArchive(r.id)}
                >
                  Archive
                </Button>
              </div>
            )}
          </div>

          <div className="flex gap-1.5 flex-wrap mb-2">
            <Badge variant={SOURCE_COLORS[r.source_type] as 'default' | 'secondary' | 'muted' ?? 'secondary'}>
              {r.source_type.replace('_', ' ')}
            </Badge>
            <Badge variant="outline">{r.status.replace('_', ' ')}</Badge>
            <ScopeBadge visibility={r.visibility} omitShared />
            {r.workspace_id && <Badge variant="muted">ws: {r.workspace_id.slice(0, 8)}…</Badge>}
            {r.source_run_id && <Badge variant="muted">run: {r.source_run_id.slice(0, 8)}…</Badge>}
          </div>

          <p className="text-xs text-muted-foreground">{fmt(r.created_at)}</p>
        </Card>
      ))}
    </div>
  )
}
