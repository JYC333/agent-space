import { useState, useEffect, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { SpaceLink as Link } from '../../core/spaceNav'
import { FileCheck, FolderKanban, X } from 'lucide-react'
import { toast } from 'sonner'
import { proposalsApi } from '../../api/client'
import { useSpace } from '../../contexts/SpaceContext'
import { cn, errMsg } from '../../lib/utils'
import type { Proposal, ProposalAcceptOut } from '../../types/api'
import { Card } from '../../components/ui/card'
import { Button } from '../../components/ui/button'
import { Badge } from '../../components/ui/badge'
import { Label } from '../../components/ui/label'
import { Select } from '../../components/ui/select'
import { PreviewBadge, UrgencyBadge } from '../../components/PreviewBadge'
import { ScopeBadge } from '../../components/ScopeBadge'
import { EgressReviewNotice, isGrantDerivedProposal } from './EgressReviewNotice'
import { codePatchAcceptOptions } from './codePatchConfirm'

function fmt(dt: string | null | undefined) { return dt ? new Date(dt).toLocaleString() : '—' }

type ProposalTypeFilter = '' | 'memory' | 'knowledge' | 'code_patch' | 'follow_up_task'

const TYPE_FILTERS: { value: ProposalTypeFilter; label: string }[] = [
  { value: '', label: 'All' },
  { value: 'memory', label: 'Memory' },
  { value: 'knowledge', label: 'Knowledge' },
  { value: 'code_patch', label: 'Code' },
  { value: 'follow_up_task', label: 'Tasks' },
]

const RISK_VARIANT: Record<string, 'default' | 'secondary' | 'muted' | 'destructive'> = {
  low:      'muted',
  medium:   'secondary',
  high:     'default',
  critical: 'destructive',
}

function apiTypesForFilter(type: string): (string | undefined)[] {
  if (!type) return [undefined]
  if (type === 'memory') return ['memory_create', 'memory_update', 'memory_archive']
  if (type === 'knowledge') return ['knowledge_create', 'knowledge_update', 'knowledge_archive']
  return [type]
}

function proposalMatchesTypeFilter(p: Proposal, type: string): boolean {
  if (!type) return true
  if (type === 'memory') return p.proposal_type.startsWith('memory_')
  if (type === 'knowledge') return p.proposal_type.startsWith('knowledge_')
  return p.proposal_type === type
}

export default function ProposalsPage() {
  const { activeSpaceId, activeSpaceName, userId } = useSpace()
  const [searchParams, setSearchParams] = useSearchParams()
  const projectFilter = searchParams.get('project_id') ?? ''

  const [proposals, setProposals] = useState<Proposal[]>([])
  const [filterStatus, setFilterStatus]       = useState('pending')
  const [filterUrgency, setFilterUrgency]     = useState('')
  const [filterExpired, setFilterExpired]     = useState<string>('')
  const [approvingId, setApprovingId] = useState<string | null>(null)

  // Proposal type grouping is local to this page; the Review sidebar only switches
  // between real review surfaces (Proposals and Memory).
  const rawUrlType = searchParams.get('type') ?? ''
  const urlType = rawUrlType === 'task_create' ? 'follow_up_task' : rawUrlType

  function setTypeFilter(type: ProposalTypeFilter) {
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      if (type) next.set('type', type)
      else next.delete('type')
      return next
    })
  }

  const load = useCallback(async () => {
    if (!activeSpaceId) {
      setProposals([])
      return
    }
    try {
      const pages = await Promise.all(apiTypesForFilter(urlType).map(type =>
        proposalsApi.list({
          status: filterStatus === '' ? 'all' : filterStatus,
          type,
          urgency: filterUrgency || undefined,
          expired: filterExpired === '' ? undefined : filterExpired === 'true',
          project_id: projectFilter || undefined,
          limit: 80,
        }),
      ))
      const items = pages.flatMap(page => page.items)
      setProposals(items.filter(p => proposalMatchesTypeFilter(p, urlType)))
    } catch (e) { toast.error(errMsg(e)) }
  }, [filterStatus, urlType, filterUrgency, filterExpired, projectFilter, activeSpaceId])

  useEffect(() => { load() }, [load])

  async function decide(id: string, action: 'accept' | 'reject') {
    try {
      if (action === 'accept') {
        const proposal = proposals.find(p => p.id === id) ?? await proposalsApi.get(id)
        const options = codePatchAcceptOptions(proposal)
        if (options === null) return
        const out: ProposalAcceptOut = await proposalsApi.accept(id, options)
        if (out.result_type === 'memory_entry') {
          toast.success('Accepted — memory entry created.')
        } else if (out.result_type === 'code_patch_apply') {
          const n = out.result.updated_paths.length
          toast.success(`Accepted — ${n} file${n === 1 ? '' : 's'} updated.`)
        } else if (out.result_type === 'knowledge_item') {
          toast.success('Accepted — knowledge item created.')
        } else if (out.result_type === 'knowledge_relation') {
          toast.success('Accepted — knowledge relation created.')
        } else if (out.result_type === 'agent_version') {
          toast.success('Accepted — agent version updated.')
        } else {
          toast.success('Proposal accepted.')
        }
      } else {
        await proposalsApi.reject(id)
        toast.success('Proposal rejected.')
      }
      await load()
    } catch (e) {
      const message = errMsg(e)
      if (message.includes('GrantingUserApprovalRequired') || message.includes('egress_granting_user')) {
        toast.error('Granting-user approval is required before this can be applied.')
      } else if (
        message.includes('not_implemented') ||
        message.includes('not implemented') ||
        message.includes('unsupported') ||
        message.includes('422')
      ) {
        toast.error('This proposal type cannot be applied yet. Reject it to dismiss, or leave it pending.')
      } else {
        toast.error(message)
      }
    }
  }

  async function approveEgress(p: Proposal) {
    setApprovingId(p.id)
    try {
      await proposalsApi.approveEgressGrantingUserProposal(p.id, { grant_id: p.grant_id ?? undefined })
      toast.success('Egress review approval recorded')
      await load()
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setApprovingId(null)
    }
  }

  const canDecide = (p: Proposal) => p.status === 'pending'

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
              {' '}— accept/reject use <code className="text-xs bg-muted px-1 rounded">POST /api/v1/proposals/…</code>.
            </p>
            <p className="text-xs text-muted-foreground">Viewing: {activeSpaceName ?? activeSpaceId ?? 'No operational space selected'}</p>
            {projectFilter && (
              <span className="inline-flex items-center gap-1 mt-0.5 px-2 py-0.5 rounded-full bg-accent/40 text-xs text-accent-foreground">
                <FolderKanban className="size-3" />
                Filtered by project
                <button onClick={() => setSearchParams(p => { p.delete('project_id'); return p })} className="ml-0.5 hover:text-foreground" aria-label="Clear project filter">
                  <X className="size-3" />
                </button>
              </span>
            )}
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
                { value: '', label: 'all statuses' },
              ]}
              onChange={setFilterStatus}
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

      <div className="flex flex-wrap gap-1 rounded-md border border-border bg-card p-1 w-fit max-w-full">
        {TYPE_FILTERS.map(filter => {
          const active = urlType === filter.value || (
            filter.value === 'memory' && urlType.startsWith('memory_')
          ) || (
            filter.value === 'knowledge' && urlType.startsWith('knowledge_')
          )
          return (
            <button
              key={filter.label}
              type="button"
              aria-pressed={active}
              onClick={() => setTypeFilter(filter.value)}
              className={cn(
                'h-8 rounded px-3 text-xs font-medium transition-colors',
                active
                  ? 'bg-primary/10 text-accent-foreground'
                  : 'text-muted-foreground hover:bg-accent hover:text-foreground',
              )}
            >
              {filter.label}
            </button>
          )
        })}
      </div>

      {proposals.length === 0
        ? <Card><p className="text-muted-foreground text-center py-10 text-sm">
            {activeSpaceId ? 'No proposals for these filters.' : 'Select an operational space to browse proposals.'}
          </p></Card>
        : proposals.map(p => (
          <Card key={p.id}>
            <div className="flex items-start justify-between gap-4 mb-3 flex-wrap">
              <Link to={`/proposals/${p.id}`} className="font-medium text-sm text-accent-foreground hover:underline">
                {p.proposed_title}
              </Link>
              {canDecide(p) && (
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
              {isGrantDerivedProposal(p) && (
                <Badge variant={p.egress_approval_status === 'approved' ? 'success' : 'warning'}>
                  {p.egress_approval_status === 'approved' ? 'egress approved' : 'egress gated'}
                </Badge>
              )}
              <UrgencyBadge urgency={p.urgency} />
              <ScopeBadge visibility={p.visibility} omitShared />
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
            <EgressReviewNotice
              proposal={p}
              currentUserId={userId}
              targetSpaceName={activeSpaceName ?? activeSpaceId ?? 'this space'}
              approving={approvingId === p.id}
              compact
              onApprove={() => approveEgress(p)}
            />
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
