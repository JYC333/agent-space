import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import { knowledgeApi } from '../../api/client'
import { useSpace } from '../../contexts/SpaceContext'
import { errMsg } from '../../lib/utils'
import type { KnowledgeItemSummary, RetrievalSearchResult } from '../../types/api'
import KnowledgeCreateProposalForm from './KnowledgeCreateProposalForm'
import KnowledgeList, { type KnowledgeFilters } from './KnowledgeList'
import KnowledgeSectionHeader from './KnowledgeSectionHeader'

const DEFAULT_FILTERS: KnowledgeFilters = {
  knowledgeKind: '',
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
  const [searchResults, setSearchResults] = useState<RetrievalSearchResult[] | null>(null)

  const load = useCallback(async () => {
    if (!activeSpaceId) {
      setItems([])
      setTotal(0)
      setSearchResults(null)
      setLoading(false)
      return
    }
    setLoading(true)
    try {
      const useRetrievalSearch =
        appliedQ &&
        !filters.knowledgeKind &&
        filters.status === 'active' &&
        !filters.visibility
      if (useRetrievalSearch) {
        const r = await knowledgeApi.search({
          query: appliedQ,
          object_types: ['knowledge_item'],
        })
        setSearchResults(r.items)
        setItems([])
        setTotal(r.total)
        return
      }
      const r = await knowledgeApi.list({
        knowledge_kind: filters.knowledgeKind || undefined,
        status: filters.status || undefined,
        visibility: filters.visibility || undefined,
        q: appliedQ || undefined,
        limit: 80,
      })
      setItems(r.items)
      setTotal(r.total)
      setSearchResults(null)
    } catch (e) {
      toast.error(errMsg(e))
      setItems([])
      setTotal(0)
      setSearchResults(null)
    } finally {
      setLoading(false)
    }
  }, [activeSpaceId, filters.knowledgeKind, filters.status, filters.visibility, appliedQ])

  useEffect(() => { load() }, [load])

  function resetFilters() {
    setFilters(DEFAULT_FILTERS)
    setAppliedQ('')
  }

  function recordSearchResultOpen(result: RetrievalSearchResult) {
    if (!appliedQ) return
    void knowledgeApi.feedback({
      query: appliedQ,
      object_type: 'knowledge_item',
      object_id: result.object_id,
      signal_type: 'opened',
      metadata: { source: 'result_open' },
    }).catch(() => undefined)
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
        searchResults={searchResults}
        onSearchResultOpen={recordSearchResultOpen}
      />
    </div>
  )
}
