import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { toast } from 'sonner'
import { proposalsApi } from '../../api/client'
import { errMsg } from '../../lib/utils'
import type { Proposal } from '../../types/api'
import { Card } from '../../components/ui/card'
import { Button } from '../../components/ui/button'
import { Badge, StatusBadge } from '../../components/ui/badge'
import { Skeleton } from '../../components/ui/skeleton'
import { PreviewBadge, UrgencyBadge } from '../../components/PreviewBadge'

function fmt(dt: string | null | undefined) {
  return dt ? new Date(dt).toLocaleString() : '—'
}

export default function ProposalDetailPage() {
  const { proposalId = '' } = useParams()
  const [p, setP] = useState<Proposal | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!proposalId) return
    let cancelled = false
    ;(async () => {
      setLoading(true)
      try {
        const r = await proposalsApi.get(proposalId)
        if (!cancelled) setP(r)
      } catch (e) {
        if (!cancelled) {
          toast.error(errMsg(e))
          setP(null)
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [proposalId])

  const canDecide =
    p &&
    p.status === 'pending' &&
    (p.proposal_type === 'memory_update' || p.proposal_type === 'code_patch')

  async function decide(action: 'accept' | 'reject') {
    if (!p) return
    setBusy(true)
    try {
      if (action === 'accept') await proposalsApi.accept(p.id)
      else await proposalsApi.reject(p.id)
      toast.success(`Proposal ${action}ed`)
      const r = await proposalsApi.get(p.id)
      setP(r)
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="p-6 space-y-6 max-w-3xl">
      <Button variant="ghost" size="sm" asChild>
        <Link to="/proposals"><ArrowLeft className="size-4 mr-1" />Proposals</Link>
      </Button>

      {loading && <Skeleton className="h-40 w-full" />}

      {!loading && !p && (
        <Card className="p-8 text-center text-sm text-muted-foreground">Proposal not found.</Card>
      )}

      {!loading && p && (
        <Card className="p-5 space-y-4">
          <div className="flex flex-wrap justify-between gap-3 items-start">
            <h1 className="text-lg font-semibold tracking-tight">{p.proposed_title}</h1>
            {canDecide && (
              <div className="flex gap-1.5 shrink-0">
                <Button size="sm" variant="success" disabled={busy} onClick={() => decide('accept')}>Accept</Button>
                <Button size="sm" variant="destructive" disabled={busy} onClick={() => decide('reject')}>Reject</Button>
              </div>
            )}
          </div>
          <div className="flex flex-wrap gap-1.5 items-center">
            <Badge variant="secondary">{p.proposal_type}</Badge>
            <StatusBadge status={p.status} />
            <UrgencyBadge urgency={p.urgency} />
            {p.preview && <PreviewBadge />}
            {p.created_by_run_id && (
              <Link to={`/runs/${p.created_by_run_id}`} className="text-xs text-accent-foreground hover:underline">
                Open run
              </Link>
            )}
          </div>
          <p className="text-xs text-muted-foreground">
            review_deadline {fmt(p.review_deadline)} · expires {fmt(p.expires_at)}
          </p>
          <p className="text-sm whitespace-pre-wrap">{p.proposed_content}</p>
          <p className="text-xs text-muted-foreground italic">Rationale: {p.rationale}</p>
          <p className="text-xs text-muted-foreground">{fmt(p.created_at)}</p>
        </Card>
      )}
    </div>
  )
}
