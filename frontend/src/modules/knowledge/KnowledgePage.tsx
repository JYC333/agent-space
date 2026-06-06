import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { BookOpen } from 'lucide-react'
import { toast } from 'sonner'
import { knowledgeApi } from '../../api/client'
import { useSpace } from '../../contexts/SpaceContext'
import { errMsg } from '../../lib/utils'
import type { KnowledgeItemSummary } from '../../types/api'
import KnowledgeCreateProposalForm from './KnowledgeCreateProposalForm'
import KnowledgeList, { type KnowledgeFilters } from './KnowledgeList'
import { getKnowledgeDisplayName } from './display'

const DEFAULT_FILTERS: KnowledgeFilters = {
  itemType: '',
  status: 'active',
  visibility: '',
  q: '',
}

export default function KnowledgePage() {
  const { activeSpaceId, activeSpaceName, spaces } = useSpace()
  const activeSpace = useMemo(
    () => spaces.find(s => s.id === activeSpaceId) ?? null,
    [spaces, activeSpaceId],
  )
  const displayName = getKnowledgeDisplayName(activeSpace)
  const [items, setItems] = useState<KnowledgeItemSummary[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [filters, setFilters] = useState<KnowledgeFilters>(DEFAULT_FILTERS)
  const [appliedQ, setAppliedQ] = useState('')

  // The Wiki scene sidebar drives the item-type filter through the URL (?item_type=…).
  const [searchParams] = useSearchParams()
  const urlItemType = searchParams.get('item_type') ?? ''
  useEffect(() => {
    setFilters(f => (f.itemType === urlItemType ? f : { ...f, itemType: urlItemType }))
  }, [urlItemType])

  const load = useCallback(async () => {
    if (!activeSpaceId) {
      setItems([])
      setTotal(0)
      setLoading(false)
      return
    }
    setLoading(true)
    try {
      const r = await knowledgeApi.list({
        item_type: filters.itemType || undefined,
        status: filters.status || undefined,
        visibility: filters.visibility || undefined,
        q: appliedQ || undefined,
        limit: 80,
      })
      setItems(r.items)
      setTotal(r.total)
    } catch (e) {
      toast.error(errMsg(e))
      setItems([])
      setTotal(0)
    } finally {
      setLoading(false)
    }
  }, [activeSpaceId, filters.itemType, filters.status, filters.visibility, appliedQ])

  useEffect(() => { load() }, [load])

  function resetFilters() {
    setFilters(DEFAULT_FILTERS)
    setAppliedQ('')
  }

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
          <BookOpen className="size-5 text-accent-foreground" />
        </div>
        <div>
          <h1 className="text-xl font-semibold tracking-tight">{displayName}</h1>
          <p className="text-sm text-muted-foreground">Browse approved knowledge and submit review-gated changes.</p>
          <p className="text-xs text-muted-foreground">Viewing: {activeSpaceName ?? activeSpaceId ?? 'No operational space selected'}</p>
        </div>
      </div>

      <KnowledgeCreateProposalForm hasOperationalSpace={Boolean(activeSpaceId)} />
      <KnowledgeList
        items={items}
        total={total}
        loading={loading}
        hasOperationalSpace={Boolean(activeSpaceId)}
        filters={filters}
        onFiltersChange={setFilters}
        onSearch={() => setAppliedQ(filters.q.trim())}
        onReset={resetFilters}
      />
    </div>
  )
}
