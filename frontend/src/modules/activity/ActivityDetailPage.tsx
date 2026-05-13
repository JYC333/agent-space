import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { toast } from 'sonner'
import { activityApi } from '../../api/client'
import { errMsg } from '../../lib/utils'
import type { ActivityInboxRecord } from '../../types/api'
import { Card } from '../../components/ui/card'
import { Button } from '../../components/ui/button'
import { Badge } from '../../components/ui/badge'
import { Skeleton } from '../../components/ui/skeleton'

function fmt(dt: string) {
  return new Date(dt).toLocaleString()
}

export default function ActivityDetailPage() {
  const { activityId = '' } = useParams()
  const [row, setRow] = useState<ActivityInboxRecord | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!activityId) return
    let cancelled = false
    ;(async () => {
      setLoading(true)
      try {
        const r = await activityApi.get(activityId)
        if (!cancelled) setRow(r)
      } catch (e) {
        if (!cancelled) {
          toast.error(errMsg(e))
          setRow(null)
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [activityId])

  return (
    <div className="p-6 space-y-6 max-w-3xl">
      <Button variant="ghost" size="sm" asChild>
        <Link to="/activity"><ArrowLeft className="size-4 mr-1" />Activity Inbox</Link>
      </Button>

      {loading && <Skeleton className="h-40 w-full" />}

      {!loading && !row && (
        <Card className="p-8 text-center text-sm text-muted-foreground">Record not found.</Card>
      )}

      {!loading && row && (
        <Card className="p-5 space-y-4">
          <div className="flex flex-wrap justify-between gap-2">
            <h1 className="text-lg font-semibold tracking-tight">{row.title ?? row.source_type}</h1>
            <span className="text-xs text-muted-foreground">{fmt(row.created_at)}</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            <Badge variant="secondary">{row.source_type.replace('_', ' ')}</Badge>
            <Badge variant="outline">{row.status.replace('_', ' ')}</Badge>
            {row.source_run_id && (
              <Link to={`/runs/${row.source_run_id}`} className="text-xs text-accent-foreground hover:underline self-center">
                Open run
              </Link>
            )}
          </div>
          <p className="text-sm whitespace-pre-wrap">{row.content}</p>
          {row.metadata_json && Object.keys(row.metadata_json).length > 0 && (
            <pre className="text-xs bg-muted/50 rounded-md p-3 overflow-auto max-h-64">
              {JSON.stringify(row.metadata_json, null, 2)}
            </pre>
          )}
        </Card>
      )}
    </div>
  )
}
