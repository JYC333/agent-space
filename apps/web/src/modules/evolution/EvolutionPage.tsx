import { useCallback, useEffect, useMemo, useState } from 'react'
import { Copy as CopyIcon, GitBranch, Loader2, Pencil, Play, Plus, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { evolutionApi, providersApi, type ModelProviderOut } from '../../api/client'
import { SpaceLink as Link } from '../../core/spaceNav'
import { useSpace } from '../../contexts/SpaceContext'
import { errMsg } from '../../lib/utils'
import type {
  EvolutionProposal,
  EvolutionRunListItem,
  EvolutionSignal,
  EvolutionSummaryOut,
  EvolutionTarget,
  EvolutionTargetCreateBody,
  EvolutionTargetUpdateBody,
  EvolutionValidationResult,
} from '../../types/api'
import { Badge, StatusBadge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { EmptyState } from '../../components/ui/empty-state'
import { Skeleton } from '../../components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../components/ui/tabs'
import {
  EMPTY_SUMMARY,
  type DetailTab,
  type TargetDialogMode,
  type TargetListTab,
  EvolutionProposalsList,
  EvolutionRunsList,
  EvolutionSignalsList,
  EvolutionValidationPanel,
  OverviewCards,
  SectionCard,
  SignalDialog,
  TargetConfigDialog,
  TargetDefinition,
  TargetList,
  displayTargetName,
  fmt,
  riskVariant,
} from './EvolutionPageParts'

export default function EvolutionPage() {
  const { activeSpaceId, preferredSpaceId, spaces } = useSpace()
  const viewSpaceId = activeSpaceId ?? preferredSpaceId
  const viewSpaceName = useMemo(
    () => spaces.find(space => space.id === viewSpaceId)?.name ?? viewSpaceId ?? 'No operational space selected',
    [spaces, viewSpaceId],
  )

  const [summary, setSummary] = useState<EvolutionSummaryOut>(EMPTY_SUMMARY)
  const [activeTargets, setActiveTargets] = useState<EvolutionTarget[]>([])
  const [archivedTargets, setArchivedTargets] = useState<EvolutionTarget[]>([])
  const [targetSignals, setTargetSignals] = useState<EvolutionSignal[]>([])
  const [runs, setRuns] = useState<EvolutionRunListItem[]>([])
  const [proposals, setProposals] = useState<EvolutionProposal[]>([])
  const [validationResults, setValidationResults] = useState<EvolutionValidationResult[]>([])
  const [modelProviders, setModelProviders] = useState<ModelProviderOut[]>([])
  const [selectedTargetId, setSelectedTargetId] = useState<string | null>(null)
  const [targetLoading, setTargetLoading] = useState(false)
  const [detailTab, setDetailTab] = useState<DetailTab>('definition')
  const [loading, setLoading] = useState(true)
  const [runningTargetId, setRunningTargetId] = useState<string | null>(null)
  const [signalOpen, setSignalOpen] = useState(false)
  const [savingSignal, setSavingSignal] = useState(false)
  const [targetDialogMode, setTargetDialogMode] = useState<TargetDialogMode>('create')
  const [targetDialogTarget, setTargetDialogTarget] = useState<EvolutionTarget | null>(null)
  const [targetDialogOpen, setTargetDialogOpen] = useState(false)
  const [savingTarget, setSavingTarget] = useState(false)
  const [targetListTab, setTargetListTab] = useState<TargetListTab>('active')

  const targets = useMemo(
    () => [...activeTargets, ...archivedTargets],
    [activeTargets, archivedTargets],
  )
  const visibleTargets = targetListTab === 'active' ? activeTargets : archivedTargets
  const selectedTarget = useMemo(
    () => targets.find(target => target.id === selectedTargetId) ?? null,
    [targets, selectedTargetId],
  )
  const selectedRuns = useMemo(
    () => runs.filter(run => run.target_id === selectedTargetId),
    [runs, selectedTargetId],
  )
  const selectedProposals = useMemo(
    () => proposals.filter(proposal => proposal.target_id === selectedTargetId),
    [proposals, selectedTargetId],
  )
  const selectedValidationResults = useMemo(
    () => validationResults.filter(result => result.target_id === selectedTargetId),
    [validationResults, selectedTargetId],
  )
  const defaultModelProvider = useMemo(
    () => modelProviders.find(provider => provider.enabled && provider.is_default && provider.has_api_key) ?? null,
    [modelProviders],
  )

  const load = useCallback(async () => {
    if (!viewSpaceId) {
      setSummary(EMPTY_SUMMARY)
      setActiveTargets([])
      setArchivedTargets([])
      setTargetSignals([])
      setRuns([])
      setProposals([])
      setValidationResults([])
      setModelProviders([])
      setSelectedTargetId(null)
      setLoading(false)
      return
    }
    setLoading(true)
    try {
      const [nextSummary, nextTargets, nextRuns, nextProposals, nextValidationResults, nextProviders] = await Promise.all([
        evolutionApi.summary(),
        evolutionApi.targets(),
        evolutionApi.runs({ limit: 50 }),
        evolutionApi.proposals({ limit: 50 }),
        evolutionApi.validation(),
        providersApi.list(),
      ])
      const nextActiveTargets = nextTargets.filter(target => target.status !== 'archived')
      const nextArchivedTargets = nextTargets.filter(target => target.status === 'archived')
      setSummary(nextSummary)
      setActiveTargets(nextActiveTargets)
      setArchivedTargets(nextArchivedTargets)
      setRuns(nextRuns)
      setProposals(nextProposals)
      setValidationResults(nextValidationResults)
      setModelProviders(nextProviders)
      setSelectedTargetId(current => {
        if (nextTargets.length === 0) return null
        if (current && nextTargets.some(target => target.id === current)) return current
        return nextActiveTargets[0]?.id ?? nextTargets[0].id
      })
    } catch (e) {
      toast.error(errMsg(e))
      setSummary(EMPTY_SUMMARY)
      setActiveTargets([])
      setArchivedTargets([])
      setTargetSignals([])
      setRuns([])
      setProposals([])
      setValidationResults([])
      setModelProviders([])
      setSelectedTargetId(null)
    } finally {
      setLoading(false)
    }
  }, [viewSpaceId])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    if (visibleTargets.length === 0) {
      setSelectedTargetId(null)
      return
    }
    if (!selectedTargetId || !visibleTargets.some(target => target.id === selectedTargetId)) {
      setSelectedTargetId(visibleTargets[0].id)
    }
  }, [selectedTargetId, visibleTargets])

  const loadTargetSignals = useCallback(async (targetId: string | null) => {
    if (!targetId || !viewSpaceId) {
      setTargetSignals([])
      return
    }
    setTargetLoading(true)
    try {
      setTargetSignals(await evolutionApi.targetSignals(targetId, { limit: 50 }))
    } catch (e) {
      toast.error(errMsg(e))
      setTargetSignals([])
    } finally {
      setTargetLoading(false)
    }
  }, [viewSpaceId])

  useEffect(() => {
    loadTargetSignals(selectedTargetId)
  }, [loadTargetSignals, selectedTargetId])

  async function runTarget(targetId: string) {
    setRunningTargetId(targetId)
    try {
      await evolutionApi.runTarget(targetId, { engine: 'llm_prompt_review' })
      toast.success('LLM review created a proposal.')
      await load()
      await loadTargetSignals(targetId)
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setRunningTargetId(null)
    }
  }

  async function createSignal(body: {
    signal_type: string
    source_type: string
    source_id?: string | null
    severity: string
    summary?: string | null
    payload_json: Record<string, unknown>
  }) {
    if (!selectedTargetId) return
    setSavingSignal(true)
    try {
      await evolutionApi.createSignal(selectedTargetId, body)
      toast.success('Signal recorded.')
      setSignalOpen(false)
      await load()
      await loadTargetSignals(selectedTargetId)
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setSavingSignal(false)
    }
  }

  function openTargetDialog(mode: TargetDialogMode, target: EvolutionTarget | null = null) {
    setTargetDialogMode(mode)
    setTargetDialogTarget(target)
    setTargetDialogOpen(true)
  }

  async function saveTarget(body: EvolutionTargetCreateBody | EvolutionTargetUpdateBody, mode: TargetDialogMode) {
    if (mode === 'edit' && !targetDialogTarget) return
    setSavingTarget(true)
    try {
      if (mode === 'edit') {
        const updated = await evolutionApi.updateTarget(targetDialogTarget!.id, body as EvolutionTargetUpdateBody)
        toast.success('Target updated.')
        setTargetDialogOpen(false)
        await load()
        setSelectedTargetId(updated.id)
      } else {
        const created = await evolutionApi.createTarget(body as EvolutionTargetCreateBody)
        toast.success('Target created.')
        setTargetDialogOpen(false)
        await load()
        setSelectedTargetId(created.id)
      }
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setSavingTarget(false)
    }
  }

  async function toggleTargetEnabled(target: EvolutionTarget) {
    setSavingTarget(true)
    try {
      const updated = await evolutionApi.updateTarget(target.id, { enabled: !target.enabled })
      toast.success(updated.enabled ? 'Target activated.' : 'Target deactivated.')
      await load()
      setSelectedTargetId(updated.id)
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setSavingTarget(false)
    }
  }

  async function archiveTarget(target: EvolutionTarget) {
    setSavingTarget(true)
    try {
      const updated = await evolutionApi.updateTarget(target.id, { status: 'archived', enabled: false })
      toast.success('Target archived.')
      setTargetListTab('archived')
      await load()
      setSelectedTargetId(updated.id)
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setSavingTarget(false)
    }
  }

  async function restoreTarget(target: EvolutionTarget) {
    setSavingTarget(true)
    try {
      const updated = await evolutionApi.updateTarget(target.id, { status: 'active', enabled: true })
      toast.success('Target restored.')
      setTargetListTab('active')
      await load()
      setSelectedTargetId(updated.id)
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setSavingTarget(false)
    }
  }

  const canRunSelected = Boolean(
    selectedTarget?.enabled
    && selectedTarget.status === 'active'
    && selectedTarget.recent_signal_count > 0
    && defaultModelProvider,
  )
  const runningSelected = runningTargetId === selectedTargetId

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
            <GitBranch className="size-5 text-accent-foreground" />
          </div>
          <div>
            <h1 className="text-xl font-semibold tracking-tight">Evolution</h1>
            <p className="text-sm text-muted-foreground">
              Target-scoped review loops for prompts, capabilities, agents, workflows, and policies.
            </p>
            <p className="text-xs text-muted-foreground">Viewing: {viewSpaceName}</p>
          </div>
        </div>
        <Button size="sm" variant="outline" onClick={load} disabled={loading || !viewSpaceId}>
          {loading ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
          Refresh
        </Button>
      </div>

      {loading ? (
        <div className="space-y-3">
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-48 w-full" />
          <Skeleton className="h-48 w-full" />
        </div>
      ) : (
        <>
          <OverviewCards summary={summary} />

          <div className="grid gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
            <SectionCard title="Targets" count={visibleTargets.length}>
              <Button size="sm" variant="outline" className="mb-3 w-full justify-center" onClick={() => openTargetDialog('create')} disabled={!viewSpaceId}>
                <Plus className="size-3.5" />
                New target
              </Button>
              <Tabs value={targetListTab} onValueChange={value => setTargetListTab(value as TargetListTab)}>
                <TabsList className="mb-3 grid w-full grid-cols-2">
                  <TabsTrigger value="active">Active {activeTargets.length}</TabsTrigger>
                  <TabsTrigger value="archived">Archived {archivedTargets.length}</TabsTrigger>
                </TabsList>
                <TabsContent value="active">
                  <TargetList
                    targets={activeTargets}
                    selectedTargetId={selectedTargetId}
                    onSelect={setSelectedTargetId}
                    onConfigure={target => openTargetDialog('edit', target)}
                    emptyTitle="No active targets."
                    emptyDescription="Active and paused targets appear here."
                  />
                </TabsContent>
                <TabsContent value="archived">
                  <TargetList
                    targets={archivedTargets}
                    selectedTargetId={selectedTargetId}
                    onSelect={setSelectedTargetId}
                    onConfigure={target => openTargetDialog('edit', target)}
                    emptyTitle="No archived targets."
                    emptyDescription="Archived targets are kept separately from active work."
                  />
                </TabsContent>
              </Tabs>
            </SectionCard>

            <SectionCard title={selectedTarget ? displayTargetName(selectedTarget) : 'Target'} count={selectedTarget ? selectedTarget.recent_signal_count : undefined}>
              {selectedTarget ? (
                <div className="space-y-4">
                  <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                    <div className="min-w-0 space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="secondary">{selectedTarget.target_type}</Badge>
                        <Badge variant={riskVariant(selectedTarget.risk_level)}>{selectedTarget.risk_level} risk</Badge>
                        <StatusBadge status={selectedTarget.enabled ? selectedTarget.status : 'disabled'} />
                      </div>
                      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                        <span>scope {selectedTarget.scope ?? '-'}</span>
                        <span>version {selectedTarget.current_version ?? selectedTarget.current_version_id ?? '-'}</span>
                        <span>signals {selectedTarget.recent_signal_count}</span>
                        <span>last run {fmt(selectedTarget.last_run_at)}</span>
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => openTargetDialog('edit', selectedTarget)}
                      >
                        <Pencil className="size-3.5" />
                        Edit target
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => openTargetDialog('copy', selectedTarget)}
                      >
                        <CopyIcon className="size-3.5" />
                        Copy target
                      </Button>
                      {selectedTarget.status === 'archived' ? (
                        <Button size="sm" variant="outline" onClick={() => restoreTarget(selectedTarget)} disabled={savingTarget}>
                          Restore
                        </Button>
                      ) : (
                        <>
                          <Button size="sm" variant="outline" onClick={() => toggleTargetEnabled(selectedTarget)} disabled={savingTarget}>
                            {selectedTarget.enabled ? 'Deactivate' : 'Activate'}
                          </Button>
                          <Button size="sm" variant="outline" onClick={() => archiveTarget(selectedTarget)} disabled={savingTarget}>
                            Archive
                          </Button>
                        </>
                      )}
                      <Button size="sm" variant="outline" onClick={() => setSignalOpen(true)}>
                        <Plus className="size-3.5" />
                        Record signal
                      </Button>
                      <Button size="sm" variant="outline" disabled={!canRunSelected || runningSelected} onClick={() => runTarget(selectedTarget.id)}>
                        {runningSelected ? <Loader2 className="size-3.5 animate-spin" /> : <Play className="size-3.5" />}
                        Create LLM review
                      </Button>
                      {!defaultModelProvider && (
                        <Button size="sm" variant="outline" asChild>
                          <Link to="/providers">Configure model</Link>
                        </Button>
                      )}
                    </div>
                  </div>
                  {selectedTarget.recent_signal_count === 0 && selectedTarget.enabled && selectedTarget.status === 'active' && (
                    <p className="text-xs text-muted-foreground">Review creation requires at least one signal for this target.</p>
                  )}
                  {!defaultModelProvider && (
                    <p className="text-xs text-muted-foreground">LLM review requires an enabled default model provider with an API key.</p>
                  )}

                  <Tabs value={detailTab} onValueChange={value => setDetailTab(value as DetailTab)}>
                    <TabsList className="flex h-auto w-full flex-wrap justify-start">
                      <TabsTrigger value="definition">Definition</TabsTrigger>
                      <TabsTrigger value="signals">Signals</TabsTrigger>
                      <TabsTrigger value="runs">Runs</TabsTrigger>
                      <TabsTrigger value="proposals">Proposals</TabsTrigger>
                      <TabsTrigger value="validation">Validation</TabsTrigger>
                    </TabsList>

                    <TabsContent value="definition" className="mt-4">
                      <TargetDefinition target={selectedTarget} modelProvider={defaultModelProvider} />
                    </TabsContent>
                    <TabsContent value="signals" className="mt-4">
                      <EvolutionSignalsList signals={targetSignals} loading={targetLoading} />
                    </TabsContent>
                    <TabsContent value="runs" className="mt-4">
                      <EvolutionRunsList runs={selectedRuns} />
                    </TabsContent>
                    <TabsContent value="proposals" className="mt-4">
                      <EvolutionProposalsList proposals={selectedProposals} />
                    </TabsContent>
                    <TabsContent value="validation" className="mt-4">
                      <EvolutionValidationPanel results={selectedValidationResults} />
                    </TabsContent>
                  </Tabs>
                </div>
              ) : (
                <EmptyState title="No target selected." description="Select or register a target first." />
              )}
            </SectionCard>
          </div>

          <SignalDialog
            open={signalOpen}
            target={selectedTarget}
            saving={savingSignal}
            onOpenChange={setSignalOpen}
            onSubmit={createSignal}
          />
          <TargetConfigDialog
            open={targetDialogOpen}
            mode={targetDialogMode}
            target={targetDialogTarget}
            saving={savingTarget}
            onOpenChange={setTargetDialogOpen}
            onSubmit={saveTarget}
          />
        </>
      )}
    </div>
  )
}
