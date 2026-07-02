import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { intakeApi } from '../../api/client'
import { SpaceLink as Link } from '../../core/spaceNav'
import { useSpace } from '../../contexts/SpaceContext'
import { errMsg, isNotFoundError } from '../../lib/utils'
import type { IntakeItem } from '../../types/api'
import { Card } from '../../components/ui/card'
import { Button } from '../../components/ui/button'
import { Badge } from '../../components/ui/badge'
import { Skeleton } from '../../components/ui/skeleton'
import { EmptyState } from '../../components/ui/empty-state'
import { ArrowLeft, BookOpen, FileText, RefreshCw } from 'lucide-react'
import { textExtractionActionLabel, textExtractionDisabledReason } from './intakePageModel'
import { runPendingItemJob } from './intakeActions'

function fmt(dt: string | null) {
  return dt ? new Date(dt).toLocaleString() : '—'
}

function contentStateBadge(state: string) {
  const map: Record<string, 'default' | 'secondary' | 'destructive' | 'outline'> = {
    content_saved: 'default',
    metadata_only: 'secondary',
    extraction_failed: 'destructive',
  }
  return map[state] ?? 'outline'
}

export default function IntakeItemDetailPage() {
  const { itemId = '' } = useParams()
  const { activeSpaceId } = useSpace()
  const [item, setItem] = useState<IntakeItem | null>(null)
  const [loading, setLoading] = useState(true)
  const [actioning, setActioning] = useState(false)

  useEffect(() => {
    if (!itemId || !activeSpaceId) {
      setItem(null)
      setLoading(false)
      return
    }
    let cancelled = false
    ;(async () => {
      setLoading(true)
      try {
        const r = await intakeApi.getItem(itemId)
        if (!cancelled) setItem(r)
      } catch (e) {
        if (!cancelled) {
          if (!isNotFoundError(e)) toast.error(errMsg(e))
          setItem(null)
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [itemId, activeSpaceId])

  async function doAction(action: string) {
    if (!itemId) return
    setActioning(true)
    try {
      const updated = await intakeApi.itemAction(itemId, action)
      if (action === 'queue_content') {
        await runQueuedItemJob(itemId, 'extract_text', 'Text extraction')
        setItem(await intakeApi.getItem(itemId))
      } else {
        setItem(updated)
        toast.success(`Action '${action}' completed`)
      }
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setActioning(false)
    }
  }

  async function runQueuedItemJob(itemId: string, jobType: string, label: string) {
    const result = await runPendingItemJob(itemId, jobType)
    if (!result) {
      toast.success(`${label} queued`)
      return
    }
    toast.success(`${label} ${result.status}`)
  }

  const canRead = item && (
    item.extracted_artifact_id ||
    item.raw_artifact_id ||
    item.excerpt
  )
  const textExtractionReason = item ? textExtractionDisabledReason(item) : 'Item unavailable.'
  const textExtractionLabel = item ? textExtractionActionLabel(item) : 'Extract text'

  if (loading) {
    return (
      <div className="p-6 space-y-4 max-w-3xl">
        <Skeleton className="h-6 w-32" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }

  if (!item) {
    return (
      <div className="p-6">
        <Button variant="ghost" size="sm" asChild>
          <Link to="/intake"><ArrowLeft className="size-4 mr-1" />Intake</Link>
        </Button>
        <EmptyState title="Item not found" description="This intake item does not exist or is not accessible." />
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6 max-w-3xl">
      <Button variant="ghost" size="sm" asChild>
        <Link to="/intake"><ArrowLeft className="size-4 mr-1" />Intake</Link>
      </Button>

      <div className="space-y-1">
        <h1 className="text-xl font-semibold">{item.title}</h1>
        {item.source_uri && (
          <a href={item.source_uri} target="_blank" rel="noopener noreferrer"
            className="text-sm text-muted-foreground hover:underline break-all">
            {item.source_uri}
          </a>
        )}
      </div>

      <div className="flex flex-wrap gap-2 items-center">
        <Badge variant={contentStateBadge(item.content_state)}>{item.content_state}</Badge>
        <Badge variant="outline">{item.status}</Badge>
        <Badge variant="outline">{item.read_status}</Badge>
        <Badge variant="outline">{item.retention_policy}</Badge>
      </div>

      {canRead && (
        <Button asChild>
          <Link to={`/intake/items/${itemId}/read`}>
            <BookOpen className="size-4 mr-2" />
            Open Reader
          </Link>
        </Button>
      )}

      <Card className="p-4 space-y-3 text-sm">
        <div className="grid grid-cols-2 gap-x-4 gap-y-2">
          <span className="text-muted-foreground">Type</span>
          <span>{item.item_type}</span>
          <span className="text-muted-foreground">Author</span>
          <span>{item.author ?? '—'}</span>
          <span className="text-muted-foreground">Occurred</span>
          <span>{fmt(item.occurred_at)}</span>
          <span className="text-muted-foreground">First seen</span>
          <span>{fmt(item.first_seen_at)}</span>
          <span className="text-muted-foreground">Last seen</span>
          <span>{fmt(item.last_seen_at)}</span>
          {item.raw_artifact_id && (
            <>
              <span className="text-muted-foreground">Raw artifact</span>
              <span className="font-mono text-xs">{item.raw_artifact_id}</span>
            </>
          )}
          {item.extracted_artifact_id && (
            <>
              <span className="text-muted-foreground">Extracted artifact</span>
              <span className="font-mono text-xs">{item.extracted_artifact_id}</span>
            </>
          )}
        </div>
      </Card>

      {item.excerpt && (
        <div>
          <p className="text-sm font-medium text-muted-foreground mb-1">Excerpt</p>
          <p className="text-sm whitespace-pre-wrap">{item.excerpt}</p>
        </div>
      )}

      <div className="flex gap-2 flex-wrap">
        <Button
          variant="outline"
          size="sm"
          disabled={actioning || textExtractionReason !== null}
          title={textExtractionReason ?? undefined}
          onClick={() => doAction('queue_content')}
        >
          {item.content_state === 'content_saved' ? <RefreshCw className="size-4 mr-1" /> : <FileText className="size-4 mr-1" />}
          {textExtractionLabel}
        </Button>
        <Button variant="outline" size="sm" disabled={actioning}
          onClick={() => doAction('mark_selected')}>
          Mark Selected
        </Button>
        <Button variant="outline" size="sm" disabled={actioning}
          onClick={() => doAction('mark_ignored')}>
          Mark Ignored
        </Button>
      </div>
    </div>
  )
}
