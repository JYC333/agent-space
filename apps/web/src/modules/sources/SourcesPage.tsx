import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { sourcesApi, projectsApi, workspacesApi } from '../../api/client'
import { EmptyState } from '../../components/ui/empty-state'
import { useSpace } from '../../contexts/SpaceContext'
import { errMsg } from '../../lib/utils'
import type {
  SourceRecipeActivationResult,
  SourceRecipeDryRunResult,
  SourceRecipePlanResponse,
  SourceRecipeSourceType,
  SourceCapturePolicy,
  SourceConnection,
  SourceConnector,
  Workspace,
  WorkspaceSourceBinding,
} from '../../types/api'
import {
  emptyScheduleFormValue,
  scheduleRuleFromForm,
  sourceCapturePolicyValue,
  type ScheduleFormValue,
} from './sourcePageModel'
import {
  AdvancedSourceHandlerCard,
  AdvancedSourceTools,
  CreateSourceCard,
  SourcesPageHeader,
  ManualUrlCard,
  PresetSourcesEntryCard,
  SourcesSection,
  WorkspaceRoutingCard,
} from './SourcesPageSections'
import { runPendingItemJob } from './sourceActions'
import {
  sourcePostProcessingRuleForConnection,
  type SourcePostProcessingPreset,
} from './sourcePostProcessingPresets'

export default function SourcesPage() {
  const { activeSpaceId, activeSpaceName } = useSpace()
  const [searchParams] = useSearchParams()
  const scopedProjectId = searchParams.get('project_id')?.trim() ?? ''
  const scopedConnectionId = searchParams.get('connection_id')?.trim() ?? ''
  const requestedView = searchParams.get('view')

  const [connectors, setConnectors] = useState<SourceConnector[]>([])
  const [connections, setConnections] = useState<SourceConnection[]>([])
  const [pendingConnections, setPendingConnections] = useState<SourceConnection[]>([])
  const [ownedConnections, setOwnedConnections] = useState<SourceConnection[]>([])
  const [connectionView, setConnectionView] = useState<'following' | 'pending' | 'owned'>(
    requestedView === 'pending' || requestedView === 'owned' ? requestedView : 'following',
  )
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [projectWorkspaceIds, setProjectWorkspaceIds] = useState<Set<string> | null>(null)
  const [bindings, setBindings] = useState<WorkspaceSourceBinding[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)

  const [recipeSourceName, setRecipeSourceName] = useState('')
  const [recipeEndpointUrl, setRecipeEndpointUrl] = useState('')
  const [recipeFetchFrequency, setRecipeFetchFrequency] = useState('daily')
  const [recipeSchedule, setRecipeSchedule] = useState<ScheduleFormValue>(() => emptyScheduleFormValue())
  const [recipeCapturePolicy, setRecipeCapturePolicy] = useState<SourceCapturePolicy>('extract_text')
  const [recipeSourceType, setRecipeSourceType] = useState('auto')
  const [recipeListSelector, setRecipeListSelector] = useState('article')
  const [recipePlan, setRecipePlan] = useState<SourceRecipePlanResponse | null>(null)
  const [recipeDryRun, setRecipeDryRun] = useState<SourceRecipeDryRunResult | null>(null)
  const [recipeActivation, setRecipeActivation] = useState<SourceRecipeActivationResult | null>(null)
  const [recipePostProcessingEnabled, setRecipePostProcessingEnabled] = useState(false)
  const [recipePostProcessingPreset, setRecipePostProcessingPreset] = useState<SourcePostProcessingPreset>('batch_digest')
  const [recipePostProcessingCreateProposals, setRecipePostProcessingCreateProposals] = useState(false)
  const [customSourceName, setCustomSourceName] = useState('')
  const [customSourceEndpointUrl, setCustomSourceEndpointUrl] = useState('')
  const [customSourceFetchFrequency, setCustomSourceFetchFrequency] = useState('manual')
  const [customSourceSchedule, setCustomSourceSchedule] = useState<ScheduleFormValue>(() => emptyScheduleFormValue())
  const [customSourceListSelector, setCustomSourceListSelector] = useState('article')

  const [manualUrl, setManualUrl] = useState('')
  const [manualTitle, setManualTitle] = useState('')
  const [manualConnectionId, setManualConnectionId] = useState('')
  const [queueContent, setQueueContent] = useState(false)

  const [workspaceId, setWorkspaceId] = useState('')
  const [bindingConnectionId, setBindingConnectionId] = useState('')
  const [backfillHistoryOnBind, setBackfillHistoryOnBind] = useState(true)

  const connectorById = useMemo(() => new Map(connectors.map(c => [c.id, c])), [connectors])
  const connectionOptions = useMemo(
    () => [
      { value: '', label: 'No source' },
      ...connections.map(c => ({ value: c.id, label: c.name })),
    ],
    [connections],
  )
  const projectBoundConnectionOptions = useMemo(
    () => {
      if (!scopedProjectId) return connectionOptions
      const boundIds = new Set(bindings.map(binding => binding.source_connection_id))
      return connections
        .filter(connection => boundIds.has(connection.id))
        .map(connection => ({ value: connection.id, label: connection.name }))
    },
    [bindings, connectionOptions, connections, scopedProjectId],
  )
  const urlConnectionOptions = scopedProjectId ? projectBoundConnectionOptions : connectionOptions
  const routableWorkspaces = useMemo(
    () => projectWorkspaceIds ? workspaces.filter(w => projectWorkspaceIds.has(w.id)) : workspaces,
    [projectWorkspaceIds, workspaces],
  )
  const workspaceOptions = useMemo(
    () => [
      { value: '', label: 'Select workspace' },
      ...routableWorkspaces.map(w => ({ value: w.id, label: w.name })),
    ],
    [routableWorkspaces],
  )
  const visibleConnections = useMemo(
    () => {
      const rows = connectionView === 'pending'
        ? pendingConnections
        : connectionView === 'owned'
          ? ownedConnections
          : connections
      return scopedConnectionId ? rows.filter(connection => connection.id === scopedConnectionId) : rows
    },
    [connectionView, connections, ownedConnections, pendingConnections, scopedConnectionId],
  )

  useEffect(() => {
    if (urlConnectionOptions.some(option => option.value === manualConnectionId)) return
    setManualConnectionId(urlConnectionOptions[0]?.value ?? '')
  }, [manualConnectionId, urlConnectionOptions])

  const load = useCallback(async () => {
    if (!activeSpaceId) {
      setConnectors([])
      setConnections([])
      setPendingConnections([])
      setOwnedConnections([])
      setWorkspaces([])
      setProjectWorkspaceIds(null)
      setBindings([])
      setLoading(false)
      return
    }

    setLoading(true)
    try {
      const connectionFilter = scopedConnectionId || undefined
      const projectFilter = scopedProjectId || undefined
      const [
        connectorRows,
        followingPage,
        pendingPage,
        ownedPage,
        workspacePage,
        projectWorkspaceLinks,
        bindingRows,
      ] = await Promise.all([
        sourcesApi.connectors(),
        sourcesApi.connections({ view: 'subscribed', limit: 100 }),
        sourcesApi.connections({ view: 'pending', limit: 100 }),
        sourcesApi.connections({ view: 'owned', limit: 100 }),
        workspacesApi.list({ limit: '100' }),
        scopedProjectId ? projectsApi.listWorkspaces(scopedProjectId) : Promise.resolve(null),
        sourcesApi.workspaceBindings({ source_connection_id: connectionFilter, project_id: projectFilter }),
      ])
      setConnectors(connectorRows)
      setConnections(followingPage.items)
      setPendingConnections(pendingPage.items)
      setOwnedConnections(ownedPage.items)
      setWorkspaces(workspacePage.items)
      setProjectWorkspaceIds(projectWorkspaceLinks ? new Set(projectWorkspaceLinks.map(link => link.workspace_id)) : null)
      setBindings(bindingRows)
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setLoading(false)
    }
  }, [activeSpaceId, scopedConnectionId, scopedProjectId])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    if (requestedView === 'pending' || requestedView === 'owned' || requestedView === 'following') {
      setConnectionView(requestedView)
    }
  }, [requestedView])

  async function createManualUrl(event: FormEvent) {
    event.preventDefault()
    if (scopedProjectId && !manualConnectionId) {
      toast.error('Link a source to this project before saving URLs')
      return
    }
    setBusy('manual:create')
    try {
      const row = await sourcesApi.createManualUrl({
        url: manualUrl.trim(),
        title: manualTitle.trim() || undefined,
        connection_id: manualConnectionId || null,
        queue_content: queueContent,
      })
      if (manualConnectionId && row.connection_id !== manualConnectionId) {
        await sourcesApi.updateItem(row.id, { connection_id: manualConnectionId })
      }
      toast.success(`Source item saved: ${row.title}`)
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
      const row = await sourcesApi.createCustomSourceDraft({
        name: customSourceName.trim() || 'Advanced Source',
        endpoint_url: customSourceEndpointUrl.trim(),
        fetch_frequency: customSourceFetchFrequency as 'manual' | 'hourly' | 'daily' | 'weekly',
        schedule_rule: scheduleRuleFromForm(customSourceFetchFrequency, customSourceSchedule),
        config: customSourceListSelector.trim()
          ? { list_selector: customSourceListSelector.trim() }
          : {},
      })
      toast.success(`Handler source created: ${row.name}`)
      setCustomSourceName('')
      setCustomSourceEndpointUrl('')
      setCustomSourceSchedule(emptyScheduleFormValue())
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
      schedule_rule: scheduleRuleFromForm(recipeFetchFrequency, recipeSchedule),
      capture_policy: recipeCapturePolicy,
      ...(sourceType ? { source_type: sourceType } : {}),
      ...(recipeSourceType === 'web_list' && recipeListSelector.trim()
        ? { list_selector: recipeListSelector.trim().replace(/^\./, '') }
        : {}),
    }
  }

  async function createPostProcessingPreset(connection: SourceConnection): Promise<boolean> {
    const rule = sourcePostProcessingRuleForConnection(connection, {
      enabled: recipePostProcessingEnabled,
      preset: recipePostProcessingPreset,
      createProposals: recipePostProcessingCreateProposals,
    })
    if (!rule) return false
    try {
      await sourcesApi.createPostProcessingRule(connection.id, rule)
      toast.success('Post-processing preset added')
      return true
    } catch (e) {
      toast.error(`Source created, post-processing setup failed: ${errMsg(e)}`)
      return false
    }
  }

  function resetRecipePostProcessingPreset() {
    setRecipePostProcessingEnabled(false)
    setRecipePostProcessingPreset('batch_digest')
    setRecipePostProcessingCreateProposals(false)
  }

  async function previewRecipeSource(event: FormEvent) {
    event.preventDefault()
    setBusy('recipe:plan')
    setRecipeDryRun(null)
    setRecipeActivation(null)
    try {
      const plan = await sourcesApi.planSourceRecipe(recipeRequestBase())
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
      const created = await sourcesApi.createSourceRecipe({
        ...recipeRequestBase(),
        name: recipeSourceName.trim() || 'Source',
        source_type: recipePlan.source_type,
        recipe: recipePlan.recipe,
      })
      const dryRun = await sourcesApi.dryRunSourceRecipe(created.connection.id, {
        recipe_version_id: created.recipe_version.id,
      })
      setRecipeDryRun(dryRun.dry_run)
      if (dryRun.dry_run.status !== 'succeeded') {
        toast.error(`Preview ${dryRun.dry_run.status}`)
        await load()
        return
      }

      const activation = await sourcesApi.activateSourceRecipe(created.connection.id, {
        recipe_version_id: dryRun.recipe_version.id,
        schedule_rule: scheduleRuleFromForm(recipeFetchFrequency, recipeSchedule),
      })
      setRecipeActivation(activation)
      await createPostProcessingPreset(created.connection)
      if (activation.status === 'pending_approval') {
        toast.success(`Approval proposal created: ${activation.proposal_id}`)
      } else {
        toast.success(`Source activated: ${created.connection.name}`)
      }
      setRecipeSourceName('')
      setRecipeEndpointUrl('')
      setRecipeSchedule(emptyScheduleFormValue())
      setRecipePlan(null)
      resetRecipePostProcessingPreset()
      await load()
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBusy(null)
    }
  }

  function changeRecipeFetchFrequency(value: string) {
    setRecipeFetchFrequency(value)
    setRecipeSchedule(emptyScheduleFormValue())
  }

  function changeCustomSourceFetchFrequency(value: string) {
    setCustomSourceFetchFrequency(value)
    setCustomSourceSchedule(emptyScheduleFormValue())
  }

  async function scanConnection(connection: SourceConnection) {
    setBusy(`scan:${connection.id}`)
    try {
      const job = await sourcesApi.scanConnection(connection.id)
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
      const result = await sourcesApi.runJob(jobId)
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
      await sourcesApi.updateConnection(connection.id, { status })
      await load()
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBusy(null)
    }
  }

  async function updateSubscription(connection: SourceConnection, action: 'subscribe' | 'dismiss' | 'mute' | 'unsubscribe') {
    setBusy(`subscription:${connection.id}:${action}`)
    try {
      await sourcesApi.updateConnectionSubscription(connection.id, { action })
      toast.success(action === 'subscribe' ? `Following ${connection.name}` : 'Source preference saved')
      await load()
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBusy(null)
    }
  }

  async function recommendAll(connection: SourceConnection) {
    setBusy(`recommend:${connection.id}`)
    try {
      const result = await sourcesApi.recommendConnection(connection.id, { all_space: true })
      toast.success(`Recommended to ${result.recommended} members`)
      await load()
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBusy(null)
    }
  }

  async function saveConnectionGovernance(
    connection: SourceConnection,
    body: { capture_policy?: SourceCapturePolicy; consent: Record<string, unknown>; policy: Record<string, unknown> },
  ) {
    setBusy(`governance:${connection.id}`)
    try {
      await sourcesApi.updateConnection(connection.id, body)
      toast.success('Source governance updated')
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

  async function createWorkspaceBinding() {
    const targetWorkspaceId = workspaceId || routableWorkspaces[0]?.id || ''
    const targetConnectionId = bindingConnectionId || connections[0]?.id || ''
    if (!scopedProjectId) {
      toast.error('Open Sources from a project before binding a source.')
      return
    }
    if (!targetWorkspaceId || !targetConnectionId) return
    setBusy('workspace:binding')
    try {
      const binding = await sourcesApi.createWorkspaceBinding({
        workspace_id: targetWorkspaceId,
        source_connection_id: targetConnectionId,
        project_id: scopedProjectId,
        backfill_history: backfillHistoryOnBind,
      })
      if (binding.backfill_result) {
        toast.success(`Source bound; ${binding.backfill_result.created_links} historical evidence links added`)
      } else {
        toast.success('Source bound')
      }
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
        <EmptyState title="No space selected" description="Select an operational space to use Sources." />
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6">
      <SourcesPageHeader
        activeSpaceId={activeSpaceId}
        activeSpaceName={activeSpaceName}
        loading={loading}
        onRefresh={load}
      />

      <div className="grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
        <div className="space-y-6">
          <PresetSourcesEntryCard />
          <CreateSourceCard
            name={recipeSourceName}
            endpointUrl={recipeEndpointUrl}
            fetchFrequency={recipeFetchFrequency}
            schedule={recipeSchedule}
            capturePolicy={recipeCapturePolicy}
            sourceType={recipeSourceType}
            listSelector={recipeListSelector}
            plan={recipePlan}
            dryRun={recipeDryRun}
            activation={recipeActivation}
            postProcessingEnabled={recipePostProcessingEnabled}
            postProcessingPreset={recipePostProcessingPreset}
            postProcessingCreateProposals={recipePostProcessingCreateProposals}
            busy={busy}
            onNameChange={setRecipeSourceName}
            onEndpointUrlChange={(value) => {
              setRecipeEndpointUrl(value)
              setRecipePlan(null)
              setRecipeDryRun(null)
              setRecipeActivation(null)
            }}
            onFetchFrequencyChange={changeRecipeFetchFrequency}
            onScheduleChange={setRecipeSchedule}
            onCapturePolicyChange={value => setRecipeCapturePolicy(sourceCapturePolicyValue(value, recipeCapturePolicy))}
            onSourceTypeChange={(value) => {
              setRecipeSourceType(value)
              setRecipePlan(null)
            }}
            onListSelectorChange={(value) => {
              setRecipeListSelector(value)
              setRecipePlan(null)
            }}
            onPostProcessingEnabledChange={setRecipePostProcessingEnabled}
            onPostProcessingPresetChange={setRecipePostProcessingPreset}
            onPostProcessingCreateProposalsChange={setRecipePostProcessingCreateProposals}
            onPreview={previewRecipeSource}
            onCreateActivate={createRecipeSource}
          />
          <ManualUrlCard
            manualUrl={manualUrl}
            manualTitle={manualTitle}
            manualConnectionId={manualConnectionId}
            queueContent={queueContent}
            connectionOptions={urlConnectionOptions}
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
            workspaces={routableWorkspaces}
            connections={connections}
            bindings={bindings}
            busy={busy}
            projectScoped={Boolean(scopedProjectId)}
            backfillHistory={backfillHistoryOnBind}
            onWorkspaceIdChange={setWorkspaceId}
            onBindingConnectionIdChange={setBindingConnectionId}
            onBackfillHistoryChange={setBackfillHistoryOnBind}
            onCreateWorkspaceBinding={createWorkspaceBinding}
          />
          <AdvancedSourceTools>
            <AdvancedSourceHandlerCard
              name={customSourceName}
              endpointUrl={customSourceEndpointUrl}
              fetchFrequency={customSourceFetchFrequency}
              schedule={customSourceSchedule}
              listSelector={customSourceListSelector}
              busy={busy}
              onNameChange={setCustomSourceName}
              onEndpointUrlChange={setCustomSourceEndpointUrl}
              onFetchFrequencyChange={changeCustomSourceFetchFrequency}
              onScheduleChange={setCustomSourceSchedule}
              onListSelectorChange={setCustomSourceListSelector}
              onSubmit={createCustomSource}
            />
          </AdvancedSourceTools>
        </div>

        <div className="space-y-6 min-w-0">
          <SourcesSection
            connections={visibleConnections}
            view={connectionView}
            counts={{
              following: connections.length,
              pending: pendingConnections.length,
              owned: ownedConnections.length,
            }}
            loading={loading}
            busy={busy}
            sourceBackendKey={sourceBackendKey}
            onViewChange={setConnectionView}
            onScanConnection={scanConnection}
            onUpdateConnection={updateConnection}
            onSubscriptionAction={updateSubscription}
            onRecommendAll={recommendAll}
            onSaveGovernance={saveConnectionGovernance}
          />
        </div>
      </div>
    </div>
  )
}
