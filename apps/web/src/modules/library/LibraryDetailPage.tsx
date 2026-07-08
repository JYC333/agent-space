import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { ArrowLeft, BookOpenText } from 'lucide-react'
import { SpaceLink as Link } from '../../core/spaceNav'
import { sourcesApi } from '../../api/client'
import { errMsg, isNotFoundError } from '../../lib/utils'
import type {
  SourcePostProcessingBriefingDetail,
  SourcePostProcessingItemDecision,
  SourcePostProcessingItemRelevance,
} from '../../types/api'
import { MarkdownReader } from '../../components/editor/MarkdownReader'
import { Card } from '../../components/ui/card'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Skeleton } from '../../components/ui/skeleton'
import { EmptyState } from '../../components/ui/empty-state'

type BriefingItemSummary = SourcePostProcessingBriefingDetail['item_summaries'][number]

function fmtDate(date: string): string {
  return new Date(`${date}T00:00:00`).toLocaleDateString(undefined, {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  })
}

const RELEVANCE_SECTIONS: Array<{ key: SourcePostProcessingItemRelevance; label: string; variant: 'success' | 'warning' | 'muted' }> = [
  { key: 'relevant', label: 'Relevant', variant: 'success' },
  { key: 'maybe', label: 'Maybe', variant: 'warning' },
  { key: 'not_relevant', label: 'Not relevant', variant: 'muted' },
]

function DecisionRow({
  connectionId,
  date,
  decision,
  summary,
}: {
  connectionId: string
  date: string
  decision: SourcePostProcessingItemDecision
  summary: BriefingItemSummary | undefined
}) {
  return (
    <div className="rounded-md border border-border p-3 space-y-1.5">
      <div className="flex flex-wrap items-center gap-2">
        <Link
          to={`/library/digests/${connectionId}/${date}/items/${decision.source_item_id}`}
          className="text-sm font-medium text-accent-foreground hover:underline"
        >
          {decision.item.title ?? decision.source_item_id}
        </Link>
        {decision.confidence !== null && <Badge variant="outline">{Math.round(decision.confidence * 100)}%</Badge>}
      </div>
      {decision.reason && <p className="text-sm text-muted-foreground whitespace-pre-wrap">{decision.reason}</p>}
      {summary && (
        <div className="pt-1.5 border-t border-border space-y-1">
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <BookOpenText className="size-3.5" />
            {summary.title}
          </div>
          <MarkdownReader markdown={summary.content} />
        </div>
      )}
    </div>
  )
}

function groupFirstDecisionsByRelevance(
  decisions: SourcePostProcessingItemDecision[],
): Map<SourcePostProcessingItemRelevance, SourcePostProcessingItemDecision[]> {
  const seenItemIds = new Set<string>()
  const groups = new Map<SourcePostProcessingItemRelevance, SourcePostProcessingItemDecision[]>()

  for (const { key } of RELEVANCE_SECTIONS) {
    for (const decision of decisions) {
      if (decision.relevance !== key || seenItemIds.has(decision.source_item_id)) continue
      seenItemIds.add(decision.source_item_id)
      const list = groups.get(key) ?? []
      list.push(decision)
      groups.set(key, list)
    }
  }

  return groups
}

export default function LibraryDetailPage() {
  const { connectionId = '', date = '' } = useParams<{ connectionId: string; date: string }>()
  const [briefing, setBriefing] = useState<SourcePostProcessingBriefingDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [notFound, setNotFound] = useState(false)

  const load = useCallback(async () => {
    if (!connectionId || !date) return
    setLoading(true)
    setNotFound(false)
    try {
      const result = await sourcesApi.briefing(connectionId, date)
      setBriefing(result)
    } catch (e) {
      if (isNotFoundError(e)) setNotFound(true)
      else toast.error(errMsg(e))
    } finally {
      setLoading(false)
    }
  }, [connectionId, date])

  useEffect(() => { load() }, [load])

  if (loading && !briefing) {
    return (
      <div className="p-6 space-y-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  if (notFound || !briefing) {
    return (
      <div className="p-6 space-y-4">
        <Button variant="ghost" size="sm" asChild>
          <Link to="/library/digests"><ArrowLeft className="size-4" />Library</Link>
        </Button>
        <EmptyState title="Digest not found" description="This source has no digest for that date." />
      </div>
    )
  }

  const itemSummaryByItemId = new Map(briefing.item_summaries.map((s) => [s.source_item_id, s]))
  const decisionsByRelevance = groupFirstDecisionsByRelevance(briefing.item_decisions)

  return (
    <div className="p-6 space-y-6 max-w-3xl">
      <div className="space-y-2">
        <Button variant="ghost" size="sm" asChild>
          <Link to="/library/digests"><ArrowLeft className="size-4" />Library</Link>
        </Button>
        <div>
          <h1 className="text-xl font-semibold tracking-tight">{briefing.connection_name}</h1>
          <p className="text-sm text-muted-foreground">{fmtDate(briefing.date)}</p>
        </div>
      </div>

      {briefing.digests.map((digest) => (
        <Card key={digest.artifact_id} className="p-4">
          <MarkdownReader markdown={digest.content} />
        </Card>
      ))}

      {RELEVANCE_SECTIONS.map(({ key, label, variant }) => {
        const decisions = decisionsByRelevance.get(key) ?? []
        if (decisions.length === 0) return null
        return (
          <div key={key} className="space-y-2">
            <div className="flex items-center gap-2">
              <Badge variant={variant}>{label}</Badge>
              <span className="text-xs text-muted-foreground">{decisions.length}</span>
            </div>
            <div className="space-y-2">
              {decisions.map((decision) => (
                <DecisionRow
                  key={decision.id}
                  connectionId={connectionId}
                  date={date}
                  decision={decision}
                  summary={itemSummaryByItemId.get(decision.source_item_id)}
                />
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}
