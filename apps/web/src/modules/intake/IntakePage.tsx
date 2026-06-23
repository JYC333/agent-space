import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
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
  ConnectionCard,
  ConnectionsSection,
  EvidenceSection,
  IntakePageHeader,
  ItemsSection,
  JobsSection,
  ManualUrlCard,
  WorkspaceRoutingCard,
} from './IntakePageSections'

export default function IntakePage() {
  const { activeSpaceId, activeSpaceName } = useSpace()

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

  const [connectorKey, setConnectorKey] = useState('rss')
  const [connectionName, setConnectionName] = useState('')
  const [endpointUrl, setEndpointUrl] = useState('')
  const [fetchFrequency, setFetchFrequency] = useState('manual')
  const [capturePolicy, setCapturePolicy] = useState('metadata_only')

  const [manualUrl, setManualUrl] = useState('')
  const [manualTitle, setManualTitle] = useState('')
  const [manualConnectionId, setManualConnectionId] = useState('')
  const [queueContent, setQueueContent] = useState(false)

  const [workspaceId, setWorkspaceId] = useState('')
  const [bindingConnectionId, setBindingConnectionId] = useState('')

  const connectorById = useMemo(() => new Map(connectors.map(c => [c.id, c])), [connectors])
  const connectorOptions = useMemo(
    () => connectors.map(c => ({ value: c.connector_key, label: c.display_name })),
    [connectors],
  )
  const connectionOptions = useMemo(
    () => [
      { value: '', label: 'No connection' },
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
  const selectedConnector = useMemo(
    () => connectors.find(c => c.connector_key === connectorKey) ?? null,
    [connectors, connectorKey],
  )

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
        intakeApi.items({ status: itemStatus, limit: 80 }),
        intakeApi.jobs({ limit: 60 }),
        intakeApi.evidence({ status: evidenceStatus, limit: 80 }),
        intakeApi.evidenceLinks({ status: 'active' }),
        workspacesApi.list({ limit: '100' }),
        intakeApi.workspaceProfiles(),
        intakeApi.workspaceBindings(),
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

      if (!connectorRows.some(c => c.connector_key === connectorKey)) {
        setConnectorKey(connectorRows[0]?.connector_key ?? 'rss')
      }
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setLoading(false)
    }
  }, [activeSpaceId, itemFilter, evidenceFilter, connectorKey])

  useEffect(() => { load() }, [load])

  async function createConnection(event: FormEvent) {
    event.preventDefault()
    setBusy('connection:create')
    try {
      const name = connectionName.trim() || selectedConnector?.display_name || connectorKey
      const row = await intakeApi.createConnection({
        connector_key: connectorKey,
        name,
        endpoint_url: endpointUrl.trim() || null,
        fetch_frequency: fetchFrequency as 'manual' | 'hourly' | 'daily' | 'weekly',
        capture_policy: capturePolicy,
      })
      toast.success(`Connection created: ${row.name}`)
      setConnectionName('')
      setEndpointUrl('')
      await load()
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBusy(null)
    }
  }

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

  async function scanConnection(connection: SourceConnection) {
    setBusy(`scan:${connection.id}`)
    try {
      const job = await intakeApi.scanConnection(connection.id)
      toast.success(`Scan ${job.status}: ${job.items_created ?? 0} new`)
      await load()
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBusy(null)
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
    body: { consent: Record<string, unknown>; policy: Record<string, unknown> },
  ) {
    setBusy(`governance:${connection.id}`)
    try {
      await intakeApi.updateConnection(connection.id, body)
      toast.success('Connection governance updated')
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
      await load()
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBusy(null)
    }
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

  function connectorName(connection: SourceConnection) {
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
          <ConnectionCard
            connectorOptions={connectorOptions}
            connectorKey={connectorKey}
            connectionName={connectionName}
            endpointUrl={endpointUrl}
            fetchFrequency={fetchFrequency}
            capturePolicy={capturePolicy}
            selectedConnector={selectedConnector}
            busy={busy}
            onConnectorKeyChange={setConnectorKey}
            onConnectionNameChange={setConnectionName}
            onEndpointUrlChange={setEndpointUrl}
            onFetchFrequencyChange={setFetchFrequency}
            onCapturePolicyChange={setCapturePolicy}
            onSubmit={createConnection}
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
        </div>

        <div className="space-y-6 min-w-0">
          <ConnectionsSection
            connections={connections}
            loading={loading}
            busy={busy}
            connectorName={connectorName}
            onScanConnection={scanConnection}
            onUpdateConnection={updateConnection}
            onSaveGovernance={saveConnectionGovernance}
          />
          <ItemsSection
            items={items}
            itemFilter={itemFilter}
            busy={busy}
            summaryResults={itemSummaryResults}
            onItemFilterChange={setItemFilter}
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
