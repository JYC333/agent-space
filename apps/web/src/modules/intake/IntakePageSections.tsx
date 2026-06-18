import type { FormEvent } from 'react'
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
import { Badge, StatusBadge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Card, CardHeader, CardTitle } from '../../components/ui/card'
import { EmptyState } from '../../components/ui/empty-state'
import { Input } from '../../components/ui/input'
import { Label } from '../../components/ui/label'
import { Select } from '../../components/ui/select'
import { Tabs, TabsList, TabsTrigger } from '../../components/ui/tabs'
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
import { IntakeSummaryLinks } from './IntakeSummaryLinks'
import {
  CAPTURE_POLICIES,
  FREQUENCIES,
  evidenceLinked,
  fmt,
  preview,
  short,
  type EvidenceFilter,
  type IntakeSummaryResult,
  type ItemFilter,
} from './intakePageModel'

type SelectOption = { value: string; label: string }

export function IntakePageHeader(props: {
  activeSpaceId: string
  activeSpaceName?: string | null
  loading: boolean
  onRefresh: () => void
}) {
  return (
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
          <p className="text-xs text-muted-foreground">Viewing: {props.activeSpaceName ?? props.activeSpaceId}</p>
        </div>
      </div>
      <Button variant="outline" onClick={props.onRefresh} disabled={props.loading} type="button">
        <RefreshCw className="size-4" />
        Refresh
      </Button>
    </div>
  )
}

export function ManualUrlCard(props: {
  manualUrl: string
  manualTitle: string
  manualConnectionId: string
  queueContent: boolean
  connectionOptions: SelectOption[]
  busy: string | null
  onManualUrlChange: (value: string) => void
  onManualTitleChange: (value: string) => void
  onManualConnectionChange: (value: string) => void
  onQueueContentChange: (value: boolean) => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Manual URL</CardTitle>
      </CardHeader>
      <form className="space-y-3" onSubmit={props.onSubmit}>
        <div className="space-y-1.5">
          <Label>URL</Label>
          <Input
            value={props.manualUrl}
            onChange={event => props.onManualUrlChange(event.target.value)}
            placeholder="https://example.com/post"
            required
          />
        </div>
        <div className="space-y-1.5">
          <Label>Title</Label>
          <Input
            value={props.manualTitle}
            onChange={event => props.onManualTitleChange(event.target.value)}
            placeholder="Optional"
          />
        </div>
        <div className="space-y-1.5">
          <Label>Connection</Label>
          <Select
            options={props.connectionOptions}
            value={props.manualConnectionId}
            onChange={props.onManualConnectionChange}
          />
        </div>
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          <input
            type="checkbox"
            className="size-4 rounded border-border"
            checked={props.queueContent}
            onChange={event => props.onQueueContentChange(event.target.checked)}
          />
          Queue extraction
        </label>
        <Button className="w-full" disabled={props.busy === 'manual:create'}>
          <Link2 className="size-4" />
          Save URL
        </Button>
      </form>
    </Card>
  )
}

export function ConnectionCard(props: {
  connectorOptions: SelectOption[]
  connectorKey: string
  connectionName: string
  endpointUrl: string
  fetchFrequency: string
  capturePolicy: string
  selectedConnector: SourceConnector | null
  busy: string | null
  onConnectorKeyChange: (value: string) => void
  onConnectionNameChange: (value: string) => void
  onEndpointUrlChange: (value: string) => void
  onFetchFrequencyChange: (value: string) => void
  onCapturePolicyChange: (value: string) => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Connection</CardTitle>
      </CardHeader>
      <form className="space-y-3" onSubmit={props.onSubmit}>
        <div className="space-y-1.5">
          <Label>Connector</Label>
          <Select options={props.connectorOptions} value={props.connectorKey} onChange={props.onConnectorKeyChange} />
        </div>
        <div className="space-y-1.5">
          <Label>Name</Label>
          <Input
            value={props.connectionName}
            onChange={event => props.onConnectionNameChange(event.target.value)}
            placeholder={props.selectedConnector?.display_name ?? 'Connection'}
          />
        </div>
        <div className="space-y-1.5">
          <Label>Endpoint</Label>
          <Input
            value={props.endpointUrl}
            onChange={event => props.onEndpointUrlChange(event.target.value)}
            placeholder="https://example.com/feed.xml"
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label>Frequency</Label>
            <Select options={FREQUENCIES} value={props.fetchFrequency} onChange={props.onFetchFrequencyChange} />
          </div>
          <div className="space-y-1.5">
            <Label>Capture</Label>
            <Select options={CAPTURE_POLICIES} value={props.capturePolicy} onChange={props.onCapturePolicyChange} />
          </div>
        </div>
        <Button className="w-full" disabled={props.busy === 'connection:create'}>
          <Radio className="size-4" />
          Create connection
        </Button>
      </form>
    </Card>
  )
}

export function WorkspaceRoutingCard(props: {
  workspaceId: string
  bindingConnectionId: string
  workspaceOptions: SelectOption[]
  connectionOptions: SelectOption[]
  workspaces: Workspace[]
  connections: SourceConnection[]
  profiles: WorkspaceIntakeProfile[]
  bindings: WorkspaceSourceBinding[]
  busy: string | null
  onWorkspaceIdChange: (value: string) => void
  onBindingConnectionIdChange: (value: string) => void
  onCreateWorkspaceProfile: () => void
  onCreateWorkspaceBinding: () => void
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Workspace Routing</CardTitle>
      </CardHeader>
      <div className="space-y-3">
        <div className="space-y-1.5">
          <Label>Workspace</Label>
          <Select options={props.workspaceOptions} value={props.workspaceId} onChange={props.onWorkspaceIdChange} />
        </div>
        <div className="space-y-1.5">
          <Label>Connection</Label>
          <Select
            options={props.connectionOptions}
            value={props.bindingConnectionId}
            onChange={props.onBindingConnectionIdChange}
          />
        </div>
        <div className="flex gap-2">
          <Button
            type="button"
            variant="outline"
            className="flex-1"
            disabled={!props.workspaces.length || props.busy === 'workspace:profile'}
            onClick={props.onCreateWorkspaceProfile}
          >
            <Folder className="size-4" />
            Profile
          </Button>
          <Button
            type="button"
            variant="outline"
            className="flex-1"
            disabled={!props.workspaces.length || !props.connections.length || props.busy === 'workspace:binding'}
            onClick={props.onCreateWorkspaceBinding}
          >
            <Link2 className="size-4" />
            Bind
          </Button>
        </div>
        <div className="flex gap-1.5 flex-wrap">
          <Badge variant="outline">{props.profiles.length} profiles</Badge>
          <Badge variant="outline">{props.bindings.length} bindings</Badge>
        </div>
      </div>
    </Card>
  )
}

export function ConnectionsSection(props: {
  connections: SourceConnection[]
  loading: boolean
  busy: string | null
  connectorName: (connection: SourceConnection) => string
  onScanConnection: (connection: SourceConnection) => void
  onUpdateConnection: (connection: SourceConnection, status: 'active' | 'paused' | 'archived') => void
}) {
  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Connections</h2>
          <p className="text-xs text-muted-foreground">{props.connections.length} configured</p>
        </div>
      </div>
      {props.loading ? (
        <Card><p className="text-muted-foreground text-center py-8 text-sm">Loading...</p></Card>
      ) : props.connections.length === 0 ? (
        <EmptyState title="No connections" description="Create a source connection or save a manual URL." />
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          {props.connections.map(connection => {
            const key = props.connectorName(connection)
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
                        disabled={props.busy === `scan:${connection.id}`}
                        onClick={() => props.onScanConnection(connection)}
                      >
                        <RefreshCw className="size-3.5" />
                        Scan
                      </Button>
                    )}
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      disabled={props.busy === `connection:${connection.id}`}
                      onClick={() => props.onUpdateConnection(connection, connection.status === 'active' ? 'paused' : 'active')}
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
  )
}

export function ItemsSection(props: {
  items: IntakeItem[]
  itemFilter: ItemFilter
  busy: string | null
  summaryResults: Record<string, IntakeSummaryResult>
  onItemFilterChange: (value: ItemFilter) => void
  onItemAction: (item: IntakeItem, action: string) => void
  onSummarizeItem: (item: IntakeItem) => void
}) {
  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Items</h2>
          <p className="text-xs text-muted-foreground">{props.items.length} visible</p>
        </div>
        <Tabs value={props.itemFilter} onValueChange={value => props.onItemFilterChange(value as ItemFilter)}>
          <TabsList>
            <TabsTrigger value="open">Open</TabsTrigger>
            <TabsTrigger value="new">New</TabsTrigger>
            <TabsTrigger value="triaged">Triaged</TabsTrigger>
            <TabsTrigger value="selected">Selected</TabsTrigger>
            <TabsTrigger value="ignored">Ignored</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>
      {props.items.length === 0 ? (
        <EmptyState title="No intake items" description="Candidate items appear after manual URL capture or a connection scan." />
      ) : (
        props.items.map(item => (
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
              <Button type="button" size="sm" variant="outline" disabled={props.busy?.startsWith(`item:${item.id}`) ?? false} onClick={() => props.onItemAction(item, 'queue_content')}>
                <FileText className="size-3.5" />
                Extract
              </Button>
              <Button type="button" size="sm" variant="outline" disabled={props.busy?.startsWith(`item:${item.id}`) ?? false} onClick={() => props.onItemAction(item, 'extract_evidence')}>
                <Sparkles className="size-3.5" />
                Evidence
              </Button>
              {(item.excerpt || item.title) && (
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  disabled={props.busy === `item:summarize:${item.id}`}
                  onClick={() => props.onSummarizeItem(item)}
                  title={!item.excerpt ? 'Only metadata available — summary will be limited' : undefined}
                >
                  <Sparkles className="size-3.5" />
                  {item.excerpt ? 'Summarize' : 'Summarize metadata'}
                </Button>
              )}
              <Button type="button" size="sm" variant="ghost" disabled={props.busy?.startsWith(`item:${item.id}`) ?? false} onClick={() => props.onItemAction(item, 'read_later')}>
                <Bookmark className="size-3.5" />
                Later
              </Button>
              <Button type="button" size="sm" variant="ghost" disabled={props.busy?.startsWith(`item:${item.id}`) ?? false} onClick={() => props.onItemAction(item, 'mark_selected')}>
                <CheckCircle2 className="size-3.5" />
                Select
              </Button>
              <Button type="button" size="sm" variant="ghost" disabled={props.busy?.startsWith(`item:${item.id}`) ?? false} onClick={() => props.onItemAction(item, 'mark_ignored')}>
                <XCircle className="size-3.5" />
                Ignore
              </Button>
            </div>
            {props.summaryResults[item.id] && <IntakeSummaryLinks result={props.summaryResults[item.id]} />}
          </Card>
        ))
      )}
    </section>
  )
}

export function JobsSection(props: {
  jobs: ExtractionJob[]
  busy: string | null
  onRunJob: (job: ExtractionJob) => void
}) {
  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Extraction Jobs</h2>
        <p className="text-xs text-muted-foreground">{props.jobs.length} recent</p>
      </div>
      {props.jobs.length === 0 ? (
        <EmptyState title="No jobs" description="Queued extraction and scan jobs appear here." />
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          {props.jobs.map(job => (
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
                <Button type="button" size="sm" variant="secondary" className="mt-4" disabled={props.busy === `job:${job.id}`} onClick={() => props.onRunJob(job)}>
                  <Play className="size-3.5" />
                  Run
                </Button>
              )}
            </Card>
          ))}
        </div>
      )}
    </section>
  )
}

export function EvidenceSection(props: {
  evidence: ExtractedEvidence[]
  links: EvidenceLink[]
  evidenceFilter: EvidenceFilter
  busy: string | null
  summaryResults: Record<string, IntakeSummaryResult>
  onEvidenceFilterChange: (value: EvidenceFilter) => void
  onUseEvidenceInContext: (row: ExtractedEvidence) => void
  onSummarizeEvidence: (row: ExtractedEvidence) => void
}) {
  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Evidence</h2>
          <p className="text-xs text-muted-foreground">{props.evidence.length} visible</p>
        </div>
        <Tabs value={props.evidenceFilter} onValueChange={value => props.onEvidenceFilterChange(value as EvidenceFilter)}>
          <TabsList>
            <TabsTrigger value="candidate">Candidate</TabsTrigger>
            <TabsTrigger value="active">Active</TabsTrigger>
            <TabsTrigger value="all">All</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>
      {props.evidence.length === 0 ? (
        <EmptyState title="No evidence" description="Evidence is extracted from intake items before context selection." />
      ) : (
        props.evidence.map(row => {
          const linked = evidenceLinked(row, props.links)
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
                  disabled={props.busy === `evidence:${row.id}`}
                  onClick={() => props.onUseEvidenceInContext(row)}
                >
                  <CheckCircle2 className="size-3.5" />
                  {linked ? 'Linked' : 'Use in context'}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={props.busy === `evidence:summarize:${row.id}`}
                  onClick={() => props.onSummarizeEvidence(row)}
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
              {props.summaryResults[row.id] && <IntakeSummaryLinks result={props.summaryResults[row.id]} />}
            </Card>
          )
        })
      )}
    </section>
  )
}
