import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Archive,
  Bookmark,
  CheckCircle2,
  FileText,
  Folder,
  Link2,
  Play,
  Radio,
  RefreshCw,
  Sparkles,
  XCircle,
} from 'lucide-react'
import { toast } from 'sonner'
import { intakeApi, workspacesApi } from '../../api/client'
import { Badge, StatusBadge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Card, CardHeader, CardTitle } from '../../components/ui/card'
import { EmptyState } from '../../components/ui/empty-state'
import { Input } from '../../components/ui/input'
import { Label } from '../../components/ui/label'
import { Select } from '../../components/ui/select'
import { Tabs, TabsList, TabsTrigger } from '../../components/ui/tabs'
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

type ItemFilter = 'open' | 'new' | 'triaged' | 'selected' | 'ignored'
type EvidenceFilter = 'candidate' | 'active' | 'all'

const CAPTURE_POLICIES = [
  { value: 'metadata_only', label: 'Metadata' },
  { value: 'excerpt_only', label: 'Excerpt' },
  { value: 'auto_extract_relevant', label: 'Extract relevant' },
  { value: 'auto_extract_all_text', label: 'Extract text' },
  { value: 'archive_all_snapshots', label: 'Archive snapshots' },
]

const FREQUENCIES = [
  { value: 'manual', label: 'Manual' },
  { value: 'hourly', label: 'Hourly' },
  { value: 'daily', label: 'Daily' },
  { value: 'weekly', label: 'Weekly' },
]

function fmt(dt: string | null) {
  return dt ? new Date(dt).toLocaleString() : 'never'
}

function short(id: string | null | undefined) {
  return id ? `${id.slice(0, 8)}...` : ''
}

function preview(text: string | null | undefined, fallback = 'No excerpt') {
  const raw = (text || '').trim()
  if (!raw) return fallback
  return raw.length > 280 ? `${raw.slice(0, 280)}...` : raw
}

export default function IntakePage() {
  const { activeOperationalSpaceId, activeOperationalSpaceName } = useSpace()

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
  const [summaryResults, setSummaryResults] = useState<Record<string, { run_id: string; artifact_id: string; preview: string; proposal_ids: string[] }>>({})
  const [itemSummaryResults, setItemSummaryResults] = useState<Record<string, { run_id: string; artifact_id: string; preview: string; proposal_ids: string[] }>>({})

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
    if (!activeOperationalSpaceId) {
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
  }, [activeOperationalSpaceId, itemFilter, evidenceFilter, connectorKey])

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

  function evidenceLinked(row: ExtractedEvidence) {
    return links.some(l => l.evidence_id === row.id && l.status === 'active' && l.target_type === 'space')
  }

  if (!activeOperationalSpaceId) {
    return (
      <div className="p-6">
        <EmptyState title="No space selected" description="Select an operational space to use Intake." />
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between gap-4 pb-4 border-b border-border">
        <div className="flex items-center gap-4">
          <div
            className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
            style={{
              background: 'color-mix(in oklch, var(--primary) 12%, transparent)',
              border: '1px solid color-mix(in oklch, var(--primary) 35%, transparent)',
            }}
          >
            <Radio className="size-5 text-accent-foreground" />
          </div>
          <div>
            <h1 className="text-xl font-semibold tracking-tight">Intake</h1>
            <p className="text-sm text-muted-foreground">Source connections, candidate items, and citable evidence.</p>
            <p className="text-xs text-muted-foreground">Viewing: {activeOperationalSpaceName ?? activeOperationalSpaceId}</p>
          </div>
        </div>
        <Button variant="outline" onClick={load} disabled={loading} type="button">
          <RefreshCw className="size-4" />
          Refresh
        </Button>
      </div>

      <div className="grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Manual URL</CardTitle>
            </CardHeader>
            <form className="space-y-3" onSubmit={createManualUrl}>
              <div className="space-y-1.5">
                <Label>URL</Label>
                <Input value={manualUrl} onChange={e => setManualUrl(e.target.value)} placeholder="https://example.com/post" required />
              </div>
              <div className="space-y-1.5">
                <Label>Title</Label>
                <Input value={manualTitle} onChange={e => setManualTitle(e.target.value)} placeholder="Optional" />
              </div>
              <div className="space-y-1.5">
                <Label>Connection</Label>
                <Select options={connectionOptions} value={manualConnectionId} onChange={setManualConnectionId} />
              </div>
              <label className="flex items-center gap-2 text-sm text-muted-foreground">
                <input
                  type="checkbox"
                  className="size-4 rounded border-border"
                  checked={queueContent}
                  onChange={e => setQueueContent(e.target.checked)}
                />
                Queue extraction
              </label>
              <Button className="w-full" disabled={busy === 'manual:create'}>
                <Link2 className="size-4" />
                Save URL
              </Button>
            </form>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Connection</CardTitle>
            </CardHeader>
            <form className="space-y-3" onSubmit={createConnection}>
              <div className="space-y-1.5">
                <Label>Connector</Label>
                <Select options={connectorOptions} value={connectorKey} onChange={setConnectorKey} />
              </div>
              <div className="space-y-1.5">
                <Label>Name</Label>
                <Input value={connectionName} onChange={e => setConnectionName(e.target.value)} placeholder={selectedConnector?.display_name ?? 'Connection'} />
              </div>
              <div className="space-y-1.5">
                <Label>Endpoint</Label>
                <Input value={endpointUrl} onChange={e => setEndpointUrl(e.target.value)} placeholder="https://example.com/feed.xml" />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label>Frequency</Label>
                  <Select options={FREQUENCIES} value={fetchFrequency} onChange={setFetchFrequency} />
                </div>
                <div className="space-y-1.5">
                  <Label>Capture</Label>
                  <Select options={CAPTURE_POLICIES} value={capturePolicy} onChange={setCapturePolicy} />
                </div>
              </div>
              <Button className="w-full" disabled={busy === 'connection:create'}>
                <Radio className="size-4" />
                Create connection
              </Button>
            </form>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Workspace Routing</CardTitle>
            </CardHeader>
            <div className="space-y-3">
              <div className="space-y-1.5">
                <Label>Workspace</Label>
                <Select options={workspaceOptions} value={workspaceId} onChange={setWorkspaceId} />
              </div>
              <div className="space-y-1.5">
                <Label>Connection</Label>
                <Select options={connectionOptions} value={bindingConnectionId} onChange={setBindingConnectionId} />
              </div>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  className="flex-1"
                  disabled={!workspaces.length || busy === 'workspace:profile'}
                  onClick={createWorkspaceProfile}
                >
                  <Folder className="size-4" />
                  Profile
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  className="flex-1"
                  disabled={!workspaces.length || !connections.length || busy === 'workspace:binding'}
                  onClick={createWorkspaceBinding}
                >
                  <Link2 className="size-4" />
                  Bind
                </Button>
              </div>
              <div className="flex gap-1.5 flex-wrap">
                <Badge variant="outline">{profiles.length} profiles</Badge>
                <Badge variant="outline">{bindings.length} bindings</Badge>
              </div>
            </div>
          </Card>
        </div>

        <div className="space-y-6 min-w-0">
          <section className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Connections</h2>
                <p className="text-xs text-muted-foreground">{connections.length} configured</p>
              </div>
            </div>
            {loading ? (
              <Card><p className="text-muted-foreground text-center py-8 text-sm">Loading...</p></Card>
            ) : connections.length === 0 ? (
              <EmptyState title="No connections" description="Create a source connection or save a manual URL." />
            ) : (
              <div className="grid gap-3 lg:grid-cols-2">
                {connections.map(connection => {
                  const key = connectorName(connection)
                  const canScan = key === 'rss' || key === 'atom'
                  return (
                    <Card key={connection.id} className="mb-0">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="font-medium text-sm truncate">{connection.name}</p>
                          <p className="text-xs text-muted-foreground truncate">{connection.endpoint_url ?? key}</p>
                        </div>
                        <StatusBadge status={connection.status} />
                      </div>
                      <div className="flex gap-1.5 flex-wrap mt-3">
                        <Badge variant="outline">{key}</Badge>
                        <Badge variant="muted">{connection.fetch_frequency}</Badge>
                        <Badge variant="muted">{connection.capture_policy}</Badge>
                        <Badge variant="muted">{connection.trust_level}</Badge>
                      </div>
                      <div className="flex items-center justify-between gap-2 mt-4">
                        <p className="text-xs text-muted-foreground">Checked: {fmt(connection.last_checked_at)}</p>
                        <div className="flex gap-1.5">
                          {canScan && (
                            <Button
                              type="button"
                              size="sm"
                              variant="secondary"
                              disabled={busy === `scan:${connection.id}`}
                              onClick={() => scanConnection(connection)}
                            >
                              <RefreshCw className="size-3.5" />
                              Scan
                            </Button>
                          )}
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            disabled={busy === `connection:${connection.id}`}
                            onClick={() => updateConnection(connection, connection.status === 'active' ? 'paused' : 'active')}
                          >
                            {connection.status === 'active' ? 'Pause' : 'Activate'}
                          </Button>
                        </div>
                      </div>
                    </Card>
                  )
                })}
              </div>
            )}
          </section>

          <section className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Items</h2>
                <p className="text-xs text-muted-foreground">{items.length} visible</p>
              </div>
              <Tabs value={itemFilter} onValueChange={v => setItemFilter(v as ItemFilter)}>
                <TabsList>
                  <TabsTrigger value="open">Open</TabsTrigger>
                  <TabsTrigger value="new">New</TabsTrigger>
                  <TabsTrigger value="triaged">Triaged</TabsTrigger>
                  <TabsTrigger value="selected">Selected</TabsTrigger>
                  <TabsTrigger value="ignored">Ignored</TabsTrigger>
                </TabsList>
              </Tabs>
            </div>
            {items.length === 0 ? (
              <EmptyState title="No intake items" description="Candidate items appear after manual URL capture or a connection scan." />
            ) : (
              items.map(item => (
                <Card key={item.id}>
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <p className="font-medium text-sm truncate">{item.title}</p>
                      <p className="text-xs text-muted-foreground line-clamp-2 mt-1">{preview(item.excerpt, item.source_uri ?? 'No source URI')}</p>
                    </div>
                    <StatusBadge status={item.status} />
                  </div>
                  <div className="flex gap-1.5 flex-wrap mt-3">
                    <Badge variant="outline">{item.item_type}</Badge>
                    <Badge variant="muted">{item.content_state}</Badge>
                    {item.source_domain && <Badge variant="muted">{item.source_domain}</Badge>}
                    {item.connection_id && <Badge variant="muted">conn {short(item.connection_id)}</Badge>}
                  </div>
                  <div className="flex flex-wrap gap-1.5 mt-4">
                    <Button type="button" size="sm" variant="outline" disabled={busy?.startsWith(`item:${item.id}`) ?? false} onClick={() => itemAction(item, 'queue_content')}>
                      <FileText className="size-3.5" />
                      Extract
                    </Button>
                    <Button type="button" size="sm" variant="outline" disabled={busy?.startsWith(`item:${item.id}`) ?? false} onClick={() => itemAction(item, 'extract_evidence')}>
                      <Sparkles className="size-3.5" />
                      Evidence
                    </Button>
                    {(item.excerpt || item.title) && (
                      <Button
                        type="button"
                        size="sm"
                        variant="secondary"
                        disabled={busy === `item:summarize:${item.id}`}
                        onClick={() => summarizeItem(item)}
                        title={!item.excerpt ? 'Only metadata available — summary will be limited' : undefined}
                      >
                        <Sparkles className="size-3.5" />
                        {item.excerpt ? 'Summarize' : 'Summarize metadata'}
                      </Button>
                    )}
                    <Button type="button" size="sm" variant="ghost" disabled={busy?.startsWith(`item:${item.id}`) ?? false} onClick={() => itemAction(item, 'read_later')}>
                      <Bookmark className="size-3.5" />
                      Later
                    </Button>
                    <Button type="button" size="sm" variant="ghost" disabled={busy?.startsWith(`item:${item.id}`) ?? false} onClick={() => itemAction(item, 'mark_selected')}>
                      <CheckCircle2 className="size-3.5" />
                      Select
                    </Button>
                    <Button type="button" size="sm" variant="ghost" disabled={busy?.startsWith(`item:${item.id}`) ?? false} onClick={() => itemAction(item, 'mark_ignored')}>
                      <XCircle className="size-3.5" />
                      Ignore
                    </Button>
                  </div>
                  {itemSummaryResults[item.id] && (
                    <div className="mt-3 text-xs border-t border-border pt-2 space-y-0.5">
                      <p className="text-muted-foreground line-clamp-2">{itemSummaryResults[item.id].preview}</p>
                      <Link to={`/artifacts/${itemSummaryResults[item.id].artifact_id}`} className="text-accent-foreground hover:underline block">
                        View summary artifact →
                      </Link>
                      <Link to={`/runs/${itemSummaryResults[item.id].run_id}`} className="text-muted-foreground hover:underline block">
                        View run →
                      </Link>
                      {itemSummaryResults[item.id].proposal_ids.length > 0 && (
                        <Link to="/proposals" className="text-muted-foreground hover:underline block">
                          {itemSummaryResults[item.id].proposal_ids.length} proposal{itemSummaryResults[item.id].proposal_ids.length !== 1 ? 's' : ''} pending review →
                        </Link>
                      )}
                    </div>
                  )}
                </Card>
              ))
            )}
          </section>

          <section className="space-y-3">
            <div>
              <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Extraction Jobs</h2>
              <p className="text-xs text-muted-foreground">{jobs.length} recent</p>
            </div>
            {jobs.length === 0 ? (
              <EmptyState title="No jobs" description="Queued extraction and scan jobs appear here." />
            ) : (
              <div className="grid gap-3 lg:grid-cols-2">
                {jobs.map(job => (
                  <Card key={job.id} className="mb-0">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="font-medium text-sm">{job.job_type.replace('_', ' ')}</p>
                        <p className="text-xs text-muted-foreground">{fmt(job.created_at)}</p>
                      </div>
                      <StatusBadge status={job.status} />
                    </div>
                    <div className="flex gap-1.5 flex-wrap mt-3">
                      {job.intake_item_id && <Badge variant="muted">item {short(job.intake_item_id)}</Badge>}
                      {job.connection_id && <Badge variant="muted">conn {short(job.connection_id)}</Badge>}
                      {job.items_created !== null && <Badge variant="outline">{job.items_created} created</Badge>}
                    </div>
                    {job.error_message && <p className="text-xs text-destructive mt-3 line-clamp-2">{job.error_message}</p>}
                    {job.status === 'pending' && (
                      <Button type="button" size="sm" variant="secondary" className="mt-4" disabled={busy === `job:${job.id}`} onClick={() => runJob(job)}>
                        <Play className="size-3.5" />
                        Run
                      </Button>
                    )}
                  </Card>
                ))}
              </div>
            )}
          </section>

          <section className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Evidence</h2>
                <p className="text-xs text-muted-foreground">{evidence.length} visible</p>
              </div>
              <Tabs value={evidenceFilter} onValueChange={v => setEvidenceFilter(v as EvidenceFilter)}>
                <TabsList>
                  <TabsTrigger value="candidate">Candidate</TabsTrigger>
                  <TabsTrigger value="active">Active</TabsTrigger>
                  <TabsTrigger value="all">All</TabsTrigger>
                </TabsList>
              </Tabs>
            </div>
            {evidence.length === 0 ? (
              <EmptyState title="No evidence" description="Evidence is extracted from intake items before context selection." />
            ) : (
              evidence.map(row => {
                const linked = evidenceLinked(row)
                return (
                  <Card key={row.id}>
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0">
                        <p className="font-medium text-sm truncate">{row.title}</p>
                        <p className="text-xs text-muted-foreground line-clamp-3 mt-1">{preview(row.content_excerpt)}</p>
                      </div>
                      <div className="flex gap-1.5 shrink-0">
                        <StatusBadge status={row.status} />
                        {linked && <Badge variant="success">context</Badge>}
                      </div>
                    </div>
                    <div className="flex gap-1.5 flex-wrap mt-3">
                      <Badge variant="outline">{row.evidence_type}</Badge>
                      <Badge variant="muted">{row.extraction_method}</Badge>
                      <Badge variant="muted">{row.trust_level}</Badge>
                      {row.intake_item_id && <Badge variant="muted">item {short(row.intake_item_id)}</Badge>}
                    </div>
                    <div className="flex gap-1.5 mt-4 flex-wrap">
                      <Button
                        type="button"
                        size="sm"
                        variant={linked ? 'success' : 'secondary'}
                        disabled={busy === `evidence:${row.id}`}
                        onClick={() => useEvidenceInContext(row)}
                      >
                        <CheckCircle2 className="size-3.5" />
                        {linked ? 'Linked' : 'Use in context'}
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        disabled={busy === `evidence:summarize:${row.id}`}
                        onClick={() => summarizeEvidence(row)}
                      >
                        <Sparkles className="size-3.5" />
                        Summarize
                      </Button>
                      {row.source_uri && (
                        <Button type="button" size="sm" variant="ghost" asChild>
                          <a href={row.source_uri} target="_blank" rel="noreferrer">
                            <Archive className="size-3.5" />
                            Source
                          </a>
                        </Button>
                      )}
                    </div>
                    {summaryResults[row.id] && (
                      <div className="mt-3 text-xs border-t border-border pt-2 space-y-0.5">
                        <p className="text-muted-foreground line-clamp-2">{summaryResults[row.id].preview}</p>
                        <Link to={`/artifacts/${summaryResults[row.id].artifact_id}`} className="text-accent-foreground hover:underline block">
                          View summary artifact →
                        </Link>
                        <Link to={`/runs/${summaryResults[row.id].run_id}`} className="text-muted-foreground hover:underline block">
                          View run →
                        </Link>
                        {summaryResults[row.id].proposal_ids.length > 0 && (
                          <Link to="/proposals" className="text-muted-foreground hover:underline block">
                            {summaryResults[row.id].proposal_ids.length} proposal{summaryResults[row.id].proposal_ids.length !== 1 ? 's' : ''} pending review →
                          </Link>
                        )}
                      </div>
                    )}
                  </Card>
                )
              })
            )}
          </section>
        </div>
      </div>
    </div>
  )
}
