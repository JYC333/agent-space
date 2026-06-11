import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import { knowledgeApi } from '../../api/client'
import { useSpace } from '../../contexts/SpaceContext'
import { errMsg } from '../../lib/utils'
import type { KnowledgeItemSummary } from '../../types/api'
import KnowledgeCreateProposalForm from './KnowledgeCreateProposalForm'
import KnowledgeList, { type KnowledgeFilters } from './KnowledgeList'
import KnowledgeSectionHeader from './KnowledgeSectionHeader'

const DEFAULT_FILTERS: KnowledgeFilters = {
  itemType: '',
  status: 'active',
  visibility: '',
  q: '',
}

/**
 * Wiki sub-area of the Knowledge module: canonical, review-gated KnowledgeItems.
 * (The broader module — notes, sources, cards — lives in KnowledgeModule.)
 */
export default function KnowledgePage() {
  const { activeSpaceId } = useSpace()
  const [items, setItems] = useState<KnowledgeItemSummary[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [filters, setFilters] = useState<KnowledgeFilters>(DEFAULT_FILTERS)
  const [appliedQ, setAppliedQ] = useState('')

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
      <KnowledgeSectionHeader
        section="wiki"
        description="Canonical structured knowledge powered by KnowledgeItems. Changes are review-gated."
      />

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
