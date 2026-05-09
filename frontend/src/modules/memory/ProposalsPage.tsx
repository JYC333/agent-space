import { useState, useEffect, useCallback } from 'react'
import { FileCheck } from 'lucide-react'
import { toast } from 'sonner'
import { memoryApi } from '../../api/client'
import { useSpace } from '../../contexts/SpaceContext'
import { errMsg } from '../../lib/utils'
import type { MemoryProposal, ProposalStatus } from '../../types/api'
import { Card } from '../../components/ui/card'
import { Button } from '../../components/ui/button'
import { Badge } from '../../components/ui/badge'

function fmt(dt: string | null | undefined) { return dt ? new Date(dt).toLocaleString() : '—' }

const FILTERS: ProposalStatus[] = ['pending', 'accepted', 'rejected', 'needs_changes']

const RISK_VARIANT: Record<string, 'default' | 'secondary' | 'muted' | 'destructive'> = {
  low:      'muted',
  medium:   'secondary',
  high:     'default',
  critical: 'destructive',
}

export default function ProposalsPage() {
  const { spaceId } = useSpace()
  const [proposals, setProposals] = useState<MemoryProposal[]>([])
  const [filter, setFilter]       = useState<ProposalStatus>('pending')

  const load = useCallback(async () => {
    try { setProposals((await memoryApi.proposals(filter)).items) }
    catch (e) { toast.error(errMsg(e)) }
  }, [filter])

  useEffect(() => { load() }, [load, spaceId])

  async function decide(id: string, action: 'accept' | 'reject') {
    try {
      if (action === 'accept') await memoryApi.accept(id)
      else await memoryApi.reject(id)
      toast.success(`Proposal ${action}ed`)
      await load()
    } catch (e) { toast.error(errMsg(e)) }
  }

  return (
    <div className="p-6 space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between pb-4 border-b border-border">
        <div className="flex items-center gap-4">
          <div
            className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
            style={{
              background: 'color-mix(in oklch, var(--primary) 12%, transparent)',
              border: '1px solid color-mix(in oklch, var(--primary) 35%, transparent)',
            }}
          >
            <FileCheck className="size-5 text-accent-foreground" />
          </div>
          <div>
            <h1 className="text-xl font-semibold tracking-tight">Memory Proposals</h1>
            <p className="text-sm text-muted-foreground">Review and accept or reject agent-generated memory proposals.</p>
          </div>
        </div>
        <div className="flex gap-1.5">
          {FILTERS.map(s => (
            <Button key={s} size="sm" variant={filter === s ? 'default' : 'ghost'} onClick={() => setFilter(s)}>
              {s}
            </Button>
          ))}
        </div>
      </div>

      {proposals.length === 0
        ? <Card><p className="text-muted-foreground text-center py-10 text-sm">No {filter} proposals.</p></Card>
        : proposals.map(p => (
          <Card key={p.id}>
            <div className="flex items-start justify-between gap-4 mb-3">
              <span className="font-medium text-sm">{p.proposed_title}</span>
              {(p.status === 'pending' || p.status === 'needs_changes') && (
                <div className="flex gap-1.5 shrink-0">
                  <Button size="sm" variant="success" onClick={() => decide(p.id, 'accept')}>Accept</Button>
                  <Button size="sm" variant="destructive" onClick={() => decide(p.id, 'reject')}>Reject</Button>
                </div>
              )}
            </div>
            <div className="flex gap-1.5 mb-3 flex-wrap">
              <Badge variant="secondary">{p.memory_type}</Badge>
              <Badge variant="secondary">{p.target_namespace}</Badge>
              {p.risk_level && (
                <Badge variant={RISK_VARIANT[p.risk_level] ?? 'muted'}>{p.risk_level} risk</Badge>
              )}
              {p.target_visibility && p.target_visibility !== 'private' && (
                <Badge variant="muted">{p.target_visibility}</Badge>
              )}
              {p.source_session_id && (
                <Badge variant="muted">session: {p.source_session_id.slice(0, 8)}…</Badge>
              )}
              {p.source_activity_id && (
                <Badge variant="muted">activity: {p.source_activity_id.slice(0, 8)}…</Badge>
              )}
            </div>
            <p className="text-sm mb-2">{p.proposed_content}</p>
            {p.source_evidence && (
              <blockquote className="border-l-2 border-border pl-3 text-xs text-muted-foreground italic mb-2">
                {p.source_evidence}
              </blockquote>
            )}
            <p className="text-xs text-muted-foreground italic">Rationale: {p.rationale}</p>
            <p className="text-xs text-muted-foreground mt-2">
              {fmt(p.created_at)}
              {p.decided_at && ` · decided ${fmt(p.decided_at)}`}
            </p>
          </Card>
        ))}
    </div>
  )
}
