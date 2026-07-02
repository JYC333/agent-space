import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { intakeApi, workspacesApi } from '../../api/client'
import { EmptyState } from '../../components/ui/empty-state'
import { useSpace } from '../../contexts/SpaceContext'
import { errMsg } from '../../lib/utils'
import type {
  EvidenceLink,
  ExtractedEvidence,
  ExtractionJob,
  IntakeItem,
  SourceRecipeActivationResult,
  SourceRecipeDryRunResult,
  SourceRecipePlanResponse,
  SourceRecipeSourceType,
  SourceConnection,
  SourceConnector,
  Workspace,
  WorkspaceIntakeProfile,
  WorkspaceSourceBinding,
} from '../../types/api'
import {
  type EvidenceFilter,
  type IntakeSummaryResult,
  type ItemFilter,
} from './intakePageModel'
import {
  AdvancedSourceHandlerCard,
  AdvancedSourceTools,
  CreateSourceCard,
  EvidenceSection,
  IntakePageHeader,
  ItemsSection,
  JobsSection,
  ManualUrlCard,
  SourcesSection,
  WorkspaceRoutingCard,
} from './IntakePageSections'
import { runPendingItemJob } from './intakeActions'

export default function IntakePage() {
  const { activeSpaceId, activeSpaceName } = useSpace()
  const [searchParams, setSearchParams] = useSearchParams()
  const scopedProjectId = searchParams.get('project_id')?.trim() ?? ''
  const scopedConnectionId = searchParams.get('connection_id')?.trim() ?? ''

  const [connectors, setConnectors] = useState<SourceConnector[]>([])
  const [connections, setConnections] = useState<SourceConnection[]>([])
  const [items, setItems] = useState<IntakeItem[]>([])
  const [jobs, setJobs] = useState<ExtractionJob[]>([])
  const [evidence, setEvidence] = useState<ExtractedEvidence[]>([])
  const [links, setLinks] = useState<EvidenceLink[]>([])
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [profiles, setProfiles] = useState<WorkspaceIntakeProfile[]>([])
  const [bindings, setBindings] = useState<WorkspaceSourceBinding[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [summaryResults, setSummaryResults] = useState<Record<string, IntakeSummaryResult>>({})
  const [itemSummaryResults, setItemSummaryResults] = useState<Record<string, IntakeSummaryResult>>({})

  const [itemFilter, setItemFilter] = useState<ItemFilter>('open')
  const [evidenceFilter, setEvidenceFilter] = useState<EvidenceFilter>('candidate')
  const [itemQuery, setItemQuery] = useState(searchParams.get('q') ?? '')

  const [recipeSourceName, setRecipeSourceName] = useState('')
  const [recipeEndpointUrl, setRecipeEndpointUrl] = useState('')
  const [recipeFetchFrequency, setRecipeFetchFrequency] = useState('daily')
  const [recipeCapturePolicy, setRecipeCapturePolicy] = useState('auto_extract_relevant')
  const [recipeSourceType, setRecipeSourceType] = useState('auto')
  const [recipeListSelector, setRecipeListSelector] = useState('article')
  const [recipePlan, setRecipePlan] = useState<SourceRecipePlanResponse | null>(null)
  const [recipeDryRun, setRecipeDryRun] = useState<SourceRecipeDryRunResult | null>(null)
  const [recipeActivation, setRecipeActivation] = useState<SourceRecipeActivationResult | null>(null)
  const [customSourceName, setCustomSourceName] = useState('')
  const [customSourceEndpointUrl, setCustomSourceEndpointUrl] = useState('')
  const [customSourceFetchFrequency, setCustomSourceFetchFrequency] = useState('manual')
  const [customSourceListSelector, setCustomSourceListSelector] = useState('article')

  const [manualUrl, setManualUrl] = useState('')
  const [manualTitle, setManualTitle] = useState('')
  const [manualConnectionId, setManualConnectionId] = useState('')
  const [queueContent, setQueueContent] = useState(false)

  const [workspaceId, setWorkspaceId] = useState('')
  const [bindingConnectionId, setBindingConnectionId] = useState('')

  const connectorById = useMemo(() => new Map(connectors.map(c => [c.id, c])), [connectors])
  const connectionOptions = useMemo(
    () => [
      { value: '', label: 'No source' },
      ...connections.map(c => ({ value: c.id, label: c.name })),
    ],
    [connections],
  )
  const workspaceOptions = useMemo(
    () => [
      { value: '', label: 'Select workspace' },
      ...workspaces.map(w => ({ value: w.id, label: w.name })),
    ],
    [workspaces],
  )
  const visibleConnections = useMemo(
    () => scopedConnectionId ? connections.filter(connection => connection.id === scopedConnectionId) : connections,
    [connections, scopedConnectionId],
  )

  useEffect(() => {
    const q = searchParams.get('q') ?? ''
    setItemQuery(current => current === q ? current : q)
  }, [searchParams])

  const updateItemQuery = useCallback((value: string) => {
    setItemQuery(value)
    setSearchParams(current => {
      const next = new URLSearchParams(current)
      const trimmed = value.trim()
      if (trimmed) next.set('q', trimmed)
      else next.delete('q')
      return next
    }, { replace: true })
  }, [setSearchParams])

  const load = useCallback(async () => {
    if (!activeSpaceId) {
      setConnectors([])
      setConnections([])
      setItems([])
      setJobs([])
      setEvidence([])
      setLinks([])
      setWorkspaces([])
      setProfiles([])
      setBindings([])
      setLoading(false)
      return
    }

    setLoading(true)
    try {
      const itemStatus = itemFilter === 'open' ? undefined : itemFilter
      const evidenceStatus = evidenceFilter === 'all' ? undefined : evidenceFilter
      const connectionFilter = scopedConnectionId || undefined
      const projectFilter = scopedProjectId || undefined
      const queryFilter = itemQuery.trim() || undefined
      const [
        connectorRows,
        connectionPage,
        itemPage,
        jobPage,
        evidencePage,
        linkPage,
        workspacePage,
        profileRows,
        bindingRows,
      ] = await Promise.all([
        intakeApi.connectors(),
        intakeApi.connections({ limit: 100 }),
        intakeApi.items({ status: itemStatus, connection_id: connectionFilter, project_id: projectFilter, q: queryFilter, limit: 80 }),
        intakeApi.jobs({ connection_id: connectionFilter, limit: 60 }),
        intakeApi.evidence({ status: evidenceStatus, project_id: projectFilter, limit: 80 }),
        intakeApi.evidenceLinks({ status: 'active' }),
        workspacesApi.list({ limit: '100' }),
        intakeApi.workspaceProfiles(),
        intakeApi.workspaceBindings({ source_connection_id: connectionFilter, project_id: projectFilter }),
      ])
      setConnectors(connectorRows)
      setConnections(connectionPage.items)
      setItems(itemPage.items)
      setJobs(jobPage.items)
      setEvidence(evidencePage.items)
      setLinks(linkPage.items)
      setWorkspaces(workspacePage.items)
      setProfiles(profileRows)
      setBindings(bindingRows)
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setLoading(false)
    }
  }, [activeSpaceId, itemFilter, evidenceFilter, scopedConnectionId, scopedProjectId, itemQuery])

  useEffect(() => { load() }, [load])

  const refreshDynamicIntakeState = useCallback(async () => {
    if (!activeSpaceId) return
    const itemStatus = itemFilter === 'open' ? undefined : itemFilter
    const evidenceStatus = evidenceFilter === 'all' ? undefined : evidenceFilter
    const connectionFilter = scopedConnectionId || undefined
    const projectFilter = scopedProjectId || undefined
    const queryFilter = itemQuery.trim() || undefined
    try {
      const [itemPage, jobPage, evidencePage, linkPage] = await Promise.all([
        intakeApi.items({ status: itemStatus, connection_id: connectionFilter, project_id: projectFilter, q: queryFilter, limit: 80 }),
        intakeApi.jobs({ connection_id: connectionFilter, limit: 60 }),
        intakeApi.evidence({ status: evidenceStatus, project_id: projectFilter, limit: 80 }),
        intakeApi.evidenceLinks({ status: 'active' }),
      ])
      setItems(itemPage.items)
      setJobs(jobPage.items)
      setEvidence(evidencePage.items)
      setLinks(linkPage.items)
    } catch {
      // Keep polling quiet; explicit user actions still surface toast errors.
    }
  }, [activeSpaceId, itemFilter, evidenceFilter, scopedConnectionId, scopedProjectId, itemQuery])

  useEffect(() => {
    const hasActiveJobs = jobs.some(job => job.status === 'pending' || job.status === 'running')
    if (!activeSpaceId || (!hasActiveJobs && !busy)) return
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') void refreshDynamicIntakeState()
    }, 5000)
    return () => window.clearInterval(timer)
  }, [activeSpaceId, busy, jobs, refreshDynamicIntakeState])

  async function createManualUrl(event: FormEvent) {
    event.preventDefault()
    setBusy('manual:create')
    try {
      const row = await intakeApi.createManualUrl({
        url: manualUrl.trim(),
        title: manualTitle.trim() || undefined,
        connection_id: manualConnectionId || null,
        queue_content: queueContent,
      })
      toast.success(`Intake item saved: ${row.title}`)
      if (queueContent) {
        await runQueuedItemJob(row.id, 'manual_url', 'Text extraction')
      }
      setManualUrl('')
      setManualTitle('')
      setQueueContent(false)
      await load()
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBusy(null)
    }
  }

  async function createCustomSource(event: FormEvent) {
    event.preventDefault()
    setBusy('custom-source:create')
    try {
      const row = await intakeApi.createCustomSourceDraft({
        name: customSourceName.trim() || 'Advanced Source',
        endpoint_url: customSourceEndpointUrl.trim(),
        fetch_frequency: customSourceFetchFrequency as 'manual' | 'hourly' | 'daily' | 'weekly',
        config: customSourceListSelector.trim()
          ? { list_selector: customSourceListSelector.trim() }
          : {},
      })
      toast.success(`Handler source created: ${row.name}`)
      setCustomSourceName('')
      setCustomSourceEndpointUrl('')
      setCustomSourceListSelector('article')
      await load()
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBusy(null)
    }
  }

  function recipeRequestBase() {
    const sourceType = recipeSourceType === 'auto' ? undefined : recipeSourceType as SourceRecipeSourceType
    return {
      name: recipeSourceName.trim() || recipeEndpointUrl.trim(),
      endpoint_url: recipeEndpointUrl.trim(),
      fetch_frequency: recipeFetchFrequency as 'manual' | 'hourly' | 'daily' | 'weekly',
      capture_policy: recipeCapturePolicy,
      ...(sourceType ? { source_type: sourceType } : {}),
      ...(recipeSourceType === 'web_list' && recipeListSelector.trim()
        ? { list_selector: recipeListSelector.trim().replace(/^\./, '') }
        : {}),
    }
  }

  async function previewRecipeSource(event: FormEvent) {
    event.preventDefault()
    setBusy('recipe:plan')
    setRecipeDryRun(null)
    setRecipeActivation(null)
    try {
      const plan = await intakeApi.planSourceRecipe(recipeRequestBase())
      setRecipePlan(plan)
      toast.success(`Plan preview: ${plan.preview.item_count} sample item${plan.preview.item_count === 1 ? '' : 's'}`)
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBusy(null)
    }
  }

  async function createRecipeSource() {
    if (!recipePlan) return
    setBusy('recipe:create')
    setRecipeDryRun(null)
    setRecipeActivation(null)
    try {
      const created = await intakeApi.createSourceRecipe({
        ...recipeRequestBase(),
        name: recipeSourceName.trim() || 'Source',
        source_type: recipePlan.source_type,
        recipe: recipePlan.recipe,
      })
      const dryRun = await intakeApi.dryRunSourceRecipe(created.connection.id, {
        recipe_version_id: created.recipe_version.id,
      })
      setRecipeDryRun(dryRun.dry_run)
      if (dryRun.dry_run.status !== 'succeeded') {
        toast.error(`Preview ${dryRun.dry_run.status}`)
        await load()
        return
      }

      const activation = await intakeApi.activateSourceRecipe(created.connection.id, {
        recipe_version_id: dryRun.recipe_version.id,
      })
      setRecipeActivation(activation)
      if (activation.status === 'pending_approval') {
        toast.success(`Approval proposal created: ${activation.proposal_id}`)
      } else {
        toast.success(`Source activated: ${created.connection.name}`)
      }
      setRecipeSourceName('')
      setRecipeEndpointUrl('')
      setRecipePlan(null)
      await load()
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBusy(null)
    }
  }

  async function scanConnection(connection: SourceConnection) {
    setBusy(`scan:${connection.id}`)
    try {
      const job = await intakeApi.scanConnection(connection.id)
      toast.success('Scan queued')
      void runQueuedScan(job.id)
      await load()
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBusy(null)
    }
  }

  async function runQueuedScan(jobId: string) {
    try {
      const result = await intakeApi.runJob(jobId)
      toast.success(`Scan ${result.status}: ${result.items_created ?? 0} new`)
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      await load()
    }
  }

  async function updateConnection(connection: SourceConnection, status: 'active' | 'paused' | 'archived') {
    setBusy(`connection:${connection.id}`)
    try {
      await intakeApi.updateConnection(connection.id, { status })
      await load()
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBusy(null)
    }
  }

  async function saveConnectionGovernance(
    connection: SourceConnection,
    body: { capture_policy?: string; consent: Record<string, unknown>; policy: Record<string, unknown> },
  ) {
    setBusy(`governance:${connection.id}`)
    try {
      await intakeApi.updateConnection(connection.id, body)
      toast.success('Source governance updated')
      await load()
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBusy(null)
    }
  }

  async function itemAction(item: IntakeItem, action: string) {
    setBusy(`item:${item.id}:${action}`)
    try {
      await intakeApi.itemAction(item.id, action)
      if (action === 'queue_content') {
        await runQueuedItemJob(item.id, 'extract_text', 'Text extraction')
      } else if (action === 'archive_snapshot') {
        await runQueuedItemJob(item.id, 'snapshot', 'Snapshot capture')
      }
      await load()
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBusy(null)
    }
  }

  async function runQueuedItemJob(itemId: string, jobType: string, label: string) {
    const result = await runPendingItemJob(itemId, jobType)
    if (!result) {
      toast.success(`${label} queued`)
      return
    }
    toast.success(`${label} ${result.status}`)
  }

  async function runJob(job: ExtractionJob) {
    setBusy(`job:${job.id}`)
    try {
      const result = await intakeApi.runJob(job.id)
      toast.success(`Job ${result.status}`)
      await load()
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBusy(null)
    }
  }

  async function summarizeEvidence(row: ExtractedEvidence) {
    setBusy(`evidence:summarize:${row.id}`)
    try {
      const result = await intakeApi.summarize({ evidence_ids: [row.id] })
      setSummaryResults(prev => ({ ...prev, [row.id]: { run_id: result.run_id, artifact_id: result.artifact_id, preview: result.summary_preview, proposal_ids: result.proposal_ids } }))
      toast.success('Summary saved as artifact')
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBusy(null)
    }
  }

  async function summarizeItem(item: IntakeItem) {
    setBusy(`item:summarize:${item.id}`)
    try {
      const result = await intakeApi.summarize({ intake_item_ids: [item.id] })
      setItemSummaryResults(prev => ({ ...prev, [item.id]: { run_id: result.run_id, artifact_id: result.artifact_id, preview: result.summary_preview, proposal_ids: result.proposal_ids } }))
      toast.success('Summary saved as artifact')
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBusy(null)
    }
  }

  async function useEvidenceInContext(row: ExtractedEvidence) {
    setBusy(`evidence:${row.id}`)
    try {
      if (row.status !== 'active') {
        await intakeApi.updateEvidence(row.id, { status: 'active' })
      }
      await intakeApi.createEvidenceLink({
        evidence_id: row.id,
        target_type: 'space',
        target_id: null,
        link_type: 'context_candidate',
        status: 'active',
      })
      toast.success('Evidence linked to context')
      await load()
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBusy(null)
    }
  }

  async function createWorkspaceProfile() {
    const targetWorkspaceId = workspaceId || workspaces[0]?.id || ''
    const workspace = workspaces.find(w => w.id === targetWorkspaceId)
    if (!targetWorkspaceId) return
    setBusy('workspace:profile')
    try {
      await intakeApi.createWorkspaceProfile({
        workspace_id: targetWorkspaceId,
        name: `${workspace?.name ?? 'Workspace'} intake`,
        observation_policy: 'manual',
      })
      await load()
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBusy(null)
    }
  }

  async function createWorkspaceBinding() {
    const targetWorkspaceId = workspaceId || workspaces[0]?.id || ''
    const targetConnectionId = bindingConnectionId || connections[0]?.id || ''
    if (!targetWorkspaceId || !targetConnectionId) return
    setBusy('workspace:binding')
    try {
      await intakeApi.createWorkspaceBinding({
        workspace_id: targetWorkspaceId,
        source_connection_id: targetConnectionId,
      })
      await load()
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBusy(null)
    }
  }

  function sourceBackendKey(connection: SourceConnection) {
    return connectorById.get(connection.connector_id)?.connector_key ?? 'connector'
  }

  if (!activeSpaceId) {
    return (
      <div className="p-6">
        <EmptyState title="No space selected" description="Select an operational space to use Intake." />
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6">
      <IntakePageHeader
        activeSpaceId={activeSpaceId}
        activeSpaceName={activeSpaceName}
        loading={loading}
        onRefresh={load}
      />

      <div className="grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
        <div className="space-y-6">
          <CreateSourceCard
            name={recipeSourceName}
            endpointUrl={recipeEndpointUrl}
            fetchFrequency={recipeFetchFrequency}
            capturePolicy={recipeCapturePolicy}
            sourceType={recipeSourceType}
            listSelector={recipeListSelector}
            plan={recipePlan}
            dryRun={recipeDryRun}
            activation={recipeActivation}
            busy={busy}
            onNameChange={setRecipeSourceName}
            onEndpointUrlChange={(value) => {
              setRecipeEndpointUrl(value)
              setRecipePlan(null)
              setRecipeDryRun(null)
              setRecipeActivation(null)
            }}
            onFetchFrequencyChange={setRecipeFetchFrequency}
            onCapturePolicyChange={setRecipeCapturePolicy}
            onSourceTypeChange={(value) => {
              setRecipeSourceType(value)
              setRecipePlan(null)
            }}
            onListSelectorChange={(value) => {
              setRecipeListSelector(value)
              setRecipePlan(null)
            }}
            onPreview={previewRecipeSource}
            onCreateActivate={createRecipeSource}
          />
          <ManualUrlCard
            manualUrl={manualUrl}
            manualTitle={manualTitle}
            manualConnectionId={manualConnectionId}
            queueContent={queueContent}
            connectionOptions={connectionOptions}
            busy={busy}
            onManualUrlChange={setManualUrl}
            onManualTitleChange={setManualTitle}
            onManualConnectionChange={setManualConnectionId}
            onQueueContentChange={setQueueContent}
            onSubmit={createManualUrl}
          />
          <WorkspaceRoutingCard
            workspaceId={workspaceId}
            bindingConnectionId={bindingConnectionId}
            workspaceOptions={workspaceOptions}
            connectionOptions={connectionOptions}
            workspaces={workspaces}
            connections={connections}
            profiles={profiles}
            bindings={bindings}
            busy={busy}
            onWorkspaceIdChange={setWorkspaceId}
            onBindingConnectionIdChange={setBindingConnectionId}
            onCreateWorkspaceProfile={createWorkspaceProfile}
            onCreateWorkspaceBinding={createWorkspaceBinding}
          />
          <AdvancedSourceTools>
            <AdvancedSourceHandlerCard
              name={customSourceName}
              endpointUrl={customSourceEndpointUrl}
              fetchFrequency={customSourceFetchFrequency}
              listSelector={customSourceListSelector}
              busy={busy}
              onNameChange={setCustomSourceName}
              onEndpointUrlChange={setCustomSourceEndpointUrl}
              onFetchFrequencyChange={setCustomSourceFetchFrequency}
              onListSelectorChange={setCustomSourceListSelector}
              onSubmit={createCustomSource}
            />
          </AdvancedSourceTools>
        </div>

        <div className="space-y-6 min-w-0">
          <SourcesSection
            connections={visibleConnections}
            loading={loading}
            busy={busy}
            sourceBackendKey={sourceBackendKey}
            onScanConnection={scanConnection}
            onUpdateConnection={updateConnection}
            onSaveGovernance={saveConnectionGovernance}
          />
          <ItemsSection
            items={items}
            itemFilter={itemFilter}
            itemQuery={itemQuery}
            scopedProjectId={scopedProjectId}
            scopedConnectionId={scopedConnectionId}
            busy={busy}
            summaryResults={itemSummaryResults}
            onItemFilterChange={setItemFilter}
            onItemQueryChange={updateItemQuery}
            onItemAction={itemAction}
            onSummarizeItem={summarizeItem}
          />
          <JobsSection jobs={jobs} busy={busy} onRunJob={runJob} />
          <EvidenceSection
            evidence={evidence}
            links={links}
            evidenceFilter={evidenceFilter}
            busy={busy}
            summaryResults={summaryResults}
            onEvidenceFilterChange={setEvidenceFilter}
            onUseEvidenceInContext={useEvidenceInContext}
            onSummarizeEvidence={summarizeEvidence}
          />
        </div>
      </div>
    </div>
  )
}
