import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { FileCheck } from 'lucide-react'
import { toast } from 'sonner'
import { memoryApi, proposalsApi } from '../../api/client'
import { useSpace } from '../../contexts/SpaceContext'
import { errMsg } from '../../lib/utils'
import type { Proposal } from '../../types/api'
import { Card } from '../../components/ui/card'
import { Button } from '../../components/ui/button'
import { Badge } from '../../components/ui/badge'
import { Label } from '../../components/ui/label'
import { Select } from '../../components/ui/select'
import { PreviewBadge, UrgencyBadge } from '../../components/PreviewBadge'

function fmt(dt: string | null | undefined) { return dt ? new Date(dt).toLocaleString() : '—' }

const RISK_VARIANT: Record<string, 'default' | 'secondary' | 'muted' | 'destructive'> = {
  low:      'muted',
  medium:   'secondary',
  high:     'default',
  critical: 'destructive',
}

export default function ProposalsPage() {
  const { spaceId } = useSpace()
  const [proposals, setProposals] = useState<Proposal[]>([])
  const [filterStatus, setFilterStatus]       = useState('pending')
  const [filterType, setFilterType]           = useState('')
  const [filterUrgency, setFilterUrgency]     = useState('')
  const [filterExpired, setFilterExpired]     = useState<string>('')

  const load = useCallback(async () => {
    try {
      const r = await proposalsApi.list({
        status: filterStatus || undefined,
        type: filterType || undefined,
        urgency: filterUrgency || undefined,
        expired: filterExpired === '' ? undefined : filterExpired === 'true',
        limit: 80,
      })
      setProposals(r.items)
    } catch (e) { toast.error(errMsg(e)) }
  }, [filterStatus, filterType, filterUrgency, filterExpired, spaceId])

  useEffect(() => { load() }, [load])

  async function decide(id: string, action: 'accept' | 'reject') {
    try {
      if (action === 'accept') await memoryApi.accept(id)
      else await memoryApi.reject(id)
      toast.success(`Proposal ${action}ed`)
      await load()
    } catch (e) { toast.error(errMsg(e)) }
  }

  const canMemoryDecide = (p: Proposal) =>
    (p.status === 'pending' || p.status === 'needs_changes') && p.proposal_type === 'memory_update'

  return (
    <div className="p-6 space-y-6">
      <div className="flex flex-col gap-4 pb-4 border-b border-border lg:flex-row lg:items-start lg:justify-between">
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
            <h1 className="text-xl font-semibold tracking-tight">Proposals</h1>
            <p className="text-sm text-muted-foreground">
              Canonical list from <code className="text-xs bg-muted px-1 rounded">GET /api/v1/proposals</code>
              {' '}— memory accept/reject still uses the memory workflow where applicable.
            </p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2 items-end">
          <div className="min-w-[120px]">
            <Label className="text-xs">status</Label>
            <Select
              value={filterStatus}
              options={[
                { value: 'pending', label: 'pending' },
                { value: 'accepted', label: 'accepted' },
                { value: 'rejected', label: 'rejected' },
                { value: 'needs_changes', label: 'needs_changes' },
                { value: '', label: 'any' },
              ]}
              onChange={setFilterStatus}
            />
          </div>
          <div className="min-w-[120px]">
            <Label className="text-xs">proposal_type</Label>
            <input
              className="flex h-9 w-full rounded-md border border-border bg-transparent px-2 text-xs font-mono"
              placeholder="type…"
              value={filterType}
              onChange={e => setFilterType(e.target.value)}
            />
          </div>
          <div className="min-w-[120px]">
            <Label className="text-xs">urgency</Label>
            <Select
              value={filterUrgency}
              options={[
                { value: '', label: 'any' },
                { value: 'low', label: 'low' },
                { value: 'normal', label: 'normal' },
                { value: 'high', label: 'high' },
                { value: 'critical', label: 'critical' },
              ]}
              onChange={setFilterUrgency}
            />
          </div>
          <div className="min-w-[100px]">
            <Label className="text-xs">expired</Label>
            <Select
              value={filterExpired}
              options={[
                { value: '', label: 'any' },
                { value: 'true', label: 'true' },
                { value: 'false', label: 'false' },
              ]}
              onChange={setFilterExpired}
            />
          </div>
        </div>
      </div>

      {proposals.length === 0
        ? <Card><p className="text-muted-foreground text-center py-10 text-sm">No proposals for these filters.</p></Card>
        : proposals.map(p => (
          <Card key={p.id}>
            <div className="flex items-start justify-between gap-4 mb-3 flex-wrap">
              <Link to={`/proposals/${p.id}`} className="font-medium text-sm text-accent-foreground hover:underline">
                {p.proposed_title}
              </Link>
              {canMemoryDecide(p) && (
                <div className="flex gap-1.5 shrink-0">
                  <Button size="sm" variant="success" onClick={() => decide(p.id, 'accept')}>Accept</Button>
                  <Button size="sm" variant="destructive" onClick={() => decide(p.id, 'reject')}>Reject</Button>
                </div>
              )}
            </div>
            <div className="flex gap-1.5 mb-3 flex-wrap items-center">
              <Badge variant="secondary">{p.proposal_type}</Badge>
              <Badge variant="outline">{p.status}</Badge>
              <Badge variant={RISK_VARIANT[p.risk_level] ?? 'muted'}>{p.risk_level} risk</Badge>
              <UrgencyBadge urgency={p.urgency} />
              {p.preview && <PreviewBadge />}
              {p.expired && <Badge variant="destructive">EXPIRED</Badge>}
              {p.created_by_run_id && (
                <Link to={`/runs/${p.created_by_run_id}`} className="text-xs text-accent-foreground hover:underline">
                  from run
                </Link>
              )}
            </div>
            <p className="text-xs text-muted-foreground mb-2">
              review_deadline {fmt(p.review_deadline)} · expires_at {fmt(p.expires_at)}
            </p>
            <p className="text-sm mb-2">{p.proposed_content}</p>
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
