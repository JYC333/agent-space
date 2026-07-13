import { useCallback, useEffect, useState } from 'react'
import { ArrowLeft, ExternalLink, Play, RefreshCw, RotateCcw } from 'lucide-react'
import { useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { plansApi } from '../../api/client'
import { SpaceLink as Link } from '../../core/spaceNav'
import { useSpace } from '../../contexts/SpaceContext'
import { errMsg, isNotFoundError } from '../../lib/utils'
import type { PlanDetail } from '../../types/api'
import { Badge, StatusBadge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Card } from '../../components/ui/card'
import { EmptyState } from '../../components/ui/empty-state'
import { Skeleton } from '../../components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../components/ui/tabs'
import PlanExecuteDialog from './PlanExecuteDialog'

function JsonBlock({ value }: { value: unknown }) {
  return <pre className="max-h-96 overflow-auto rounded-md border border-border bg-muted/40 p-3 text-xs">{JSON.stringify(value ?? {}, null, 2)}</pre>
}

export default function PlanDetailPage() {
  const { planId = '' } = useParams<{ planId: string }>()
  const { activeSpaceId, activeSpaceName } = useSpace()
  const [plan, setPlan] = useState<PlanDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [executeOpen, setExecuteOpen] = useState(false)

  const load = useCallback(async (background = false) => {
    if (!planId || !activeSpaceId) {
      setPlan(null)
      setLoading(false)
      return
    }
    if (background) setRefreshing(true); else setLoading(true)
    try {
      setPlan(await plansApi.get(planId))
    } catch (error) {
      if (!isNotFoundError(error)) toast.error(errMsg(error))
      setPlan(null)
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [activeSpaceId, planId])

  useEffect(() => { void load() }, [load])

  async function reconcilePlan() {
    if (!plan) return
    try {
      await plansApi.reconcile(plan.id)
      toast.success('Plan reconciled')
      await load(true)
    } catch (error) {
      toast.error(errMsg(error))
    }
  }

  if (loading && !plan) return <div className="space-y-4 p-6"><Skeleton className="h-10 w-72" /><Skeleton className="h-56 w-full" /></div>
  if (!plan) return <div className="p-6"><Button variant="ghost" asChild><Link to="/plans"><ArrowLeft className="mr-1 size-4" /> Plans</Link></Button><EmptyState className="mt-6" title={activeSpaceId ? 'Plan not found or not accessible' : 'No space selected'} description="This plan may not exist, or it may not be visible in the current space." /></div>

  const version = plan.current_version
  const reviewProposalId = version?.approval_proposal_id
  return (
    <div className="max-w-6xl space-y-6 p-6">
      <Button variant="ghost" size="sm" asChild><Link to="/plans"><ArrowLeft className="size-4" /> Plans</Link></Button>
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-border pb-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">{plan.name}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{plan.description ?? 'No description'}</p>
          <p className="mt-1 text-xs text-muted-foreground">Viewing: {activeSpaceName ?? activeSpaceId ?? '—'}</p>
          <div className="mt-3 flex flex-wrap gap-1.5"><StatusBadge status={plan.status} />{version && <Badge variant="outline">version {version.version}</Badge>}{version && <Badge variant="muted">{version.status}</Badge>}</div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" asChild><Link to={`/tasks/${plan.source_task_id}`}>Source task <ExternalLink className="size-3.5" /></Link></Button>
          {plan.root_run_id && <Button size="sm" variant="outline" asChild><Link to={`/runs/${plan.root_run_id}`}><ExternalLink className="size-3.5" /> Root run</Link></Button>}
          {version?.status === 'approved' && !plan.root_run_id && !['completed', 'failed', 'cancelled'].includes(plan.status) && <Button size="sm" onClick={() => setExecuteOpen(true)}><Play className="size-3.5" /> Execute</Button>}
          {plan.root_run_id && !['completed', 'failed', 'cancelled'].includes(plan.status) && <Button size="sm" variant="outline" onClick={() => void reconcilePlan()} disabled={refreshing}><RotateCcw className="size-3.5" /> Reconcile</Button>}
          <Button size="sm" variant="outline" onClick={() => void load(true)} disabled={refreshing}><RefreshCw className={refreshing ? 'size-3.5 animate-spin' : 'size-3.5'} /> Refresh</Button>
        </div>
      </div>

      {reviewProposalId && <Card className="border-amber-500/40 bg-amber-500/5 p-4"><div className="flex flex-wrap items-center justify-between gap-3"><div><p className="font-medium">This Agent plan requires review before execution.</p><p className="mt-1 text-sm text-muted-foreground">Approve the plan review proposal, then return here to execute.</p></div><div className="flex gap-2"><Button size="sm" variant="outline" asChild><Link to={`/proposals/${reviewProposalId}`}>Review proposal</Link></Button><Button size="sm" variant="outline" asChild><Link to="/evolution/inbox">Evolution Inbox</Link></Button></div></div></Card>}

      {version ? (
        <Tabs defaultValue="nodes">
          <TabsList><TabsTrigger value="nodes">Plan Nodes ({version.nodes.length})</TabsTrigger><TabsTrigger value="definition">Definition</TabsTrigger><TabsTrigger value="budget">Contract & budget</TabsTrigger></TabsList>
          <TabsContent value="nodes" className="mt-4 space-y-3">
            {version.nodes.map(node => (
              <Card key={node.id} className="mb-0 p-4">
                <div className="flex flex-wrap items-start justify-between gap-3"><div><div className="font-medium">{node.title}</div><div className="mt-1 font-mono text-xs text-muted-foreground">{node.node_key}</div></div><div className="flex gap-1.5"><Badge variant="outline">{node.node_kind}</Badge><StatusBadge status={node.status} /></div></div>
                <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted-foreground"><span>{node.risk_level} risk</span>{node.capability_id && <span>capability {node.capability_id}</span>}{node.latest_run && <Link to={`/runs/${node.latest_run.run_id}`} className="text-accent-foreground hover:underline">Run {node.latest_run.run_id.slice(0, 8)}… ({node.latest_run.outcome_status ?? node.latest_run.status})</Link>}{node.approval_proposal_id && <Link to={`/proposals/${node.approval_proposal_id}`} className="text-accent-foreground hover:underline">Checkpoint proposal</Link>}</div>
                {node.description && <p className="mt-2 text-sm text-muted-foreground">{node.description}</p>}
                {node.blocked_reason && <p className="mt-2 text-xs text-amber-700">{node.blocked_reason}</p>}
              </Card>
            ))}
          </TabsContent>
          <TabsContent value="definition" className="mt-4"><JsonBlock value={version.definition_json} /></TabsContent>
          <TabsContent value="budget" className="mt-4"><JsonBlock value={version.budget_json} /></TabsContent>
        </Tabs>
      ) : <EmptyState title="No current plan version" description="This plan has no materialized version to inspect." />}
      <PlanExecuteDialog open={executeOpen} planId={plan.id} onOpenChange={setExecuteOpen} onExecuted={() => load(true)} />
    </div>
  )
}
