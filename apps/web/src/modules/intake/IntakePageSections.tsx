import { useEffect, useId, useState, type FormEvent, type ReactNode } from 'react'
import {
  Archive,
  Bookmark,
  BookOpen,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Code2,
  FileText,
  Link2,
  Play,
  Radio,
  RefreshCw,
  ShieldCheck,
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
  SourceRecipeActivationResult,
  SourceRecipeDryRunResult,
  SourceRecipePlanResponse,
  SourceCapturePolicy,
  SourceConnection,
  Workspace,
  WorkspaceSourceBinding,
} from '../../types/api'
import { IntakeSummaryLinks } from './IntakeSummaryLinks'
import { SpaceLink as Link } from '../../core/spaceNav'
import {
  CAPTURE_POLICIES,
  capturePolicyDescription,
  FREQUENCIES,
  isScheduleFormComplete,
  isScheduledFrequency,
  textExtractionDisabledReason,
  textExtractionActionLabel,
  evidenceLinked,
  fmt,
  minimumRetentionForCapturePolicy,
  preview,
  retentionAtLeast,
  short,
  sourceCapturePolicyValue,
  WEEKDAY_OPTIONS,
  type EvidenceFilter,
  type IntakeSummaryResult,
  type ItemFilter,
  type ScheduleFormValue,
} from './intakePageModel'

type SelectOption = { value: string; label: string }

const SOURCE_TYPE_OPTIONS = [
  { value: 'auto', label: 'Auto-detect' },
  { value: 'rss', label: 'RSS feed' },
  { value: 'atom', label: 'Atom feed' },
  { value: 'web_list', label: 'Web list' },
  { value: 'web_page', label: 'Web page' },
]

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
          <p className="text-sm text-muted-foreground">Sources, captured items, and citable evidence.</p>
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
        <CardTitle>Save URL</CardTitle>
      </CardHeader>
      <form className="space-y-3" onSubmit={props.onSubmit}>
        <div className="space-y-1.5">
          <Label>Page URL</Label>
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
          <Label>Attach to source</Label>
          {props.connectionOptions.length === 0 ? (
            <p className="text-xs text-muted-foreground">No project-linked sources are available.</p>
          ) : (
            <Select
              options={props.connectionOptions}
              value={props.manualConnectionId}
              onChange={props.onManualConnectionChange}
            />
          )}
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

export function CreateSourceCard(props: {
  name: string
  endpointUrl: string
  fetchFrequency: string
  schedule: ScheduleFormValue
  capturePolicy: SourceCapturePolicy
  sourceType: string
  listSelector: string
  plan: SourceRecipePlanResponse | null
  dryRun: SourceRecipeDryRunResult | null
  activation: SourceRecipeActivationResult | null
  busy: string | null
  onNameChange: (value: string) => void
  onEndpointUrlChange: (value: string) => void
  onFetchFrequencyChange: (value: string) => void
  onScheduleChange: (value: ScheduleFormValue) => void
  onCapturePolicyChange: (value: string) => void
  onSourceTypeChange: (value: string) => void
  onListSelectorChange: (value: string) => void
  onPreview: (event: FormEvent<HTMLFormElement>) => void
  onCreateActivate: () => void
}) {
  const isBusy = props.busy === 'recipe:plan' || props.busy === 'recipe:create'
  const canCreate = Boolean(props.plan) && props.plan?.preview.status === 'succeeded' && props.busy !== 'recipe:create'
  return (
    <Card>
      <CardHeader>
        <CardTitle>Create Source</CardTitle>
      </CardHeader>
      <WebFeedSourceForm {...props} isBusy={isBusy} canCreate={canCreate} />
    </Card>
  )
}

export function PresetSourcesEntryCard() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Preset Sources</CardTitle>
      </CardHeader>
      <div className="space-y-3">
        <div className="flex items-center gap-3">
          <div className="size-9 rounded-md border border-border bg-muted/40 flex items-center justify-center shrink-0">
            <BookOpen className="size-4 text-muted-foreground" />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-medium">Curated source presets</p>
            <p className="text-xs text-muted-foreground truncate">Browse by category</p>
          </div>
        </div>
        <Button type="button" className="w-full" asChild>
          <Link to="/intake/source-presets">
            Open presets
            <ChevronRight className="size-4" />
          </Link>
        </Button>
      </div>
    </Card>
  )
}

function WebFeedSourceForm(props: {
  name: string
  endpointUrl: string
  fetchFrequency: string
  schedule: ScheduleFormValue
  capturePolicy: SourceCapturePolicy
  sourceType: string
  listSelector: string
  plan: SourceRecipePlanResponse | null
  dryRun: SourceRecipeDryRunResult | null
  activation: SourceRecipeActivationResult | null
  busy: string | null
  isBusy: boolean
  canCreate: boolean
  onNameChange: (value: string) => void
  onEndpointUrlChange: (value: string) => void
  onFetchFrequencyChange: (value: string) => void
  onScheduleChange: (value: ScheduleFormValue) => void
  onCapturePolicyChange: (value: string) => void
  onSourceTypeChange: (value: string) => void
  onListSelectorChange: (value: string) => void
  onPreview: (event: FormEvent<HTMLFormElement>) => void
  onCreateActivate: () => void
}) {
  const { isBusy, canCreate } = props
  const scheduleReady = isScheduleFormComplete(props.fetchFrequency, props.schedule)
  return (
    <>
      <form className="space-y-3" onSubmit={props.onPreview}>
        <div className="space-y-1.5">
          <Label>Source URL</Label>
          <Input
            value={props.endpointUrl}
            onChange={event => props.onEndpointUrlChange(event.target.value)}
            placeholder="https://example.com/feed.xml"
            required
          />
        </div>
        <div className="space-y-1.5">
          <Label>Name</Label>
          <Input
            value={props.name}
            onChange={event => props.onNameChange(event.target.value)}
            placeholder="Source name"
          />
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label>Frequency</Label>
            <Select
              options={FREQUENCIES}
              value={props.fetchFrequency}
              onChange={value => {
                props.onFetchFrequencyChange(value)
              }}
            />
          </div>
        </div>
        <ScheduleRuleFields
          fetchFrequency={props.fetchFrequency}
          value={props.schedule}
          onChange={props.onScheduleChange}
        />
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label>Capture</Label>
            <Select options={CAPTURE_POLICIES} value={props.capturePolicy} onChange={props.onCapturePolicyChange} />
            <p className="text-xs text-muted-foreground">{capturePolicyDescription(props.capturePolicy)}</p>
          </div>
          <div className="space-y-1.5">
            <Label>Source type</Label>
            <Select options={SOURCE_TYPE_OPTIONS} value={props.sourceType} onChange={props.onSourceTypeChange} />
          </div>
          <div className="space-y-1.5">
            <Label>List item class</Label>
            <Input
              value={props.listSelector}
              onChange={event => props.onListSelectorChange(event.target.value)}
              placeholder="article"
              disabled={props.sourceType !== 'web_list'}
            />
          </div>
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          <Button type="submit" variant="outline" disabled={props.busy === 'recipe:plan' || !props.endpointUrl.trim()}>
            <Sparkles className="size-4" />
            Preview
          </Button>
          <Button type="button" disabled={!canCreate || !scheduleReady || isBusy} onClick={props.onCreateActivate}>
            <CheckCircle2 className="size-4" />
            Create and activate
          </Button>
        </div>
      </form>

      {props.plan && (
        <div className="mt-4 space-y-3 rounded-md border border-border bg-muted/20 p-3">
          <div className="flex flex-wrap gap-1.5">
            <Badge variant="outline">{sourcePlanKindLabel(props.plan.source_type)}</Badge>
            <Badge variant="muted">{sourcePlanLevelLabel(props.plan.source_type)}</Badge>
            <Badge variant={props.plan.preview.status === 'succeeded' ? 'secondary' : 'warning'}>{props.plan.preview.status}</Badge>
            <Badge variant="muted">{props.plan.preview.item_count} sample items</Badge>
            <Badge variant="muted">{props.plan.analysis.network_access}</Badge>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {props.plan.analysis.primitives.map(primitive => (
              <Badge key={primitive} variant="outline">{sourcePrimitiveLabel(primitive)}</Badge>
            ))}
          </div>
          <SourceRecipeSampleItems items={props.plan.preview.sample_items} />
          {props.plan.preview.warnings.length > 0 && (
            <ul className="space-y-1 text-xs text-muted-foreground">
              {props.plan.preview.warnings.slice(0, 3).map((warning, index) => (
                <li key={`${warning}-${index}`}>{warning}</li>
              ))}
            </ul>
          )}
          {props.plan.preview.error && <p className="text-xs text-destructive">{props.plan.preview.error}</p>}
        </div>
      )}

      {props.dryRun && (
        <div className="mt-3 rounded-md border border-border bg-muted/20 p-3">
          <div className="flex flex-wrap gap-1.5">
            <Badge variant={props.dryRun.status === 'succeeded' ? 'secondary' : 'warning'}>preview {props.dryRun.status}</Badge>
            <Badge variant="muted">{props.dryRun.item_count} items</Badge>
          </div>
          {props.dryRun.errors.length > 0 && <p className="mt-2 text-xs text-destructive">{props.dryRun.errors[0]}</p>}
        </div>
      )}

      {props.activation && (
        <div className="mt-3 rounded-md border border-border bg-muted/20 p-3">
          <div className="flex flex-wrap gap-1.5">
            <Badge variant={props.activation.status === 'active' ? 'secondary' : 'warning'}>{props.activation.status}</Badge>
            <Badge variant="outline">v{props.activation.recipe_version.version_number}</Badge>
            {props.activation.proposal_id && <Badge variant="muted">proposal {short(props.activation.proposal_id)}</Badge>}
          </div>
          {props.activation.deltas.length > 0 && (
            <p className="mt-2 text-xs text-muted-foreground">{props.activation.deltas[0]}</p>
          )}
        </div>
      )}
    </>
  )
}

function SourceRecipeSampleItems({ items }: { items: Array<{ title?: string; source_uri?: string; excerpt?: string | null }> }) {
  if (items.length === 0) {
    return <p className="text-xs text-muted-foreground">No sample items.</p>
  }
  return (
    <div className="space-y-2">
      {items.slice(0, 3).map((item, index) => (
        <div key={`${item.source_uri ?? item.title ?? index}`} className="rounded-md border border-border bg-background/60 p-2">
          <p className="text-sm font-medium line-clamp-1">{item.title || 'Untitled item'}</p>
          <p className="text-xs text-muted-foreground line-clamp-2">{preview(item.excerpt, item.source_uri ?? '')}</p>
        </div>
      ))}
    </div>
  )
}

function sourcePlanKindLabel(sourceType: string) {
  if (sourceType === 'rss') return 'Feed source'
  if (sourceType === 'atom') return 'Feed source'
  if (sourceType === 'web_list') return 'Recipe source'
  if (sourceType === 'web_page') return 'Recipe source'
  return 'Source'
}

function sourcePlanLevelLabel(sourceType: string) {
  if (sourceType === 'rss' || sourceType === 'atom') return 'Level 1'
  if (sourceType === 'web_list' || sourceType === 'web_page') return 'Level 2'
  return 'Auto-detected'
}

function sourcePrimitiveLabel(primitive: string) {
  if (primitive === 'parse_rss') return 'RSS parser'
  if (primitive === 'parse_atom') return 'Atom parser'
  if (primitive === 'fetch_page') return 'Fetch source'
  if (primitive === 'extract_list') return 'List extractor'
  if (primitive === 'extract_single') return 'Page extractor'
  if (primitive === 'follow_link') return 'Link follower'
  if (primitive === 'download_asset') return 'Asset downloader'
  if (primitive === 'paginate') return 'Paginator'
  if (primitive === 'dedupe') return 'Dedupe'
  return primitive.replace(/_/g, ' ')
}

export function AdvancedSourceHandlerCard(props: {
  name: string
  endpointUrl: string
  fetchFrequency: string
  schedule: ScheduleFormValue
  listSelector: string
  busy: string | null
  onNameChange: (value: string) => void
  onEndpointUrlChange: (value: string) => void
  onFetchFrequencyChange: (value: string) => void
  onScheduleChange: (value: ScheduleFormValue) => void
  onListSelectorChange: (value: string) => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Advanced Source Handler</CardTitle>
      </CardHeader>
      <form className="space-y-3" onSubmit={props.onSubmit}>
        <div className="space-y-1.5">
          <Label>Source name</Label>
          <Input
            value={props.name}
            onChange={event => props.onNameChange(event.target.value)}
            placeholder="Research feed"
          />
        </div>
        <div className="space-y-1.5">
          <Label>Endpoint URL</Label>
          <Input
            value={props.endpointUrl}
            onChange={event => props.onEndpointUrlChange(event.target.value)}
            placeholder="https://example.com/articles"
            required
          />
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label>Frequency</Label>
            <Select
              options={FREQUENCIES}
              value={props.fetchFrequency}
              onChange={value => {
                props.onFetchFrequencyChange(value)
              }}
            />
          </div>
        </div>
        <ScheduleRuleFields
          fetchFrequency={props.fetchFrequency}
          value={props.schedule}
          onChange={props.onScheduleChange}
        />
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label>List selector</Label>
            <Input
              value={props.listSelector}
              onChange={event => props.onListSelectorChange(event.target.value)}
              placeholder="article"
            />
          </div>
        </div>
        <Button
          className="w-full"
          disabled={props.busy === 'custom-source:create' || !isScheduleFormComplete(props.fetchFrequency, props.schedule)}
        >
          <Code2 className="size-4" />
          Create handler source
        </Button>
      </form>
    </Card>
  )
}

export function ScheduleRuleFields(props: {
  fetchFrequency: string
  value: ScheduleFormValue
  onChange: (value: ScheduleFormValue) => void
}) {
  const set = (patch: Partial<ScheduleFormValue>) => props.onChange({ ...props.value, ...patch })
  if (!isScheduledFrequency(props.fetchFrequency)) {
    return (
      <div className="space-y-1.5">
        <Label>Schedule</Label>
        <div className="flex h-9 items-center rounded-md border border-border bg-muted/30 px-3 text-sm text-muted-foreground">
          Manual only
        </div>
      </div>
    )
  }
  if (props.fetchFrequency === 'hourly') {
    return (
      <ScheduleNumberField
        label="Minute"
        value={props.value.minute}
        min={0}
        max={59}
        placeholder="0"
        onChange={minute => set({ minute })}
      />
    )
  }
  if (props.fetchFrequency === 'daily') {
    return (
      <div className="grid grid-cols-2 gap-3">
        <ScheduleNumberField
          label="Hour"
          value={props.value.hour}
          min={0}
          max={23}
          placeholder="9"
          onChange={hour => set({ hour })}
        />
        <ScheduleNumberField
          label="Minute"
          value={props.value.minute}
          min={0}
          max={59}
          placeholder="0"
          onChange={minute => set({ minute })}
        />
      </div>
    )
  }
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <div className="space-y-1.5">
        <Label>Weekday</Label>
        <Select
          options={[{ value: '', label: 'Weekday' }, ...WEEKDAY_OPTIONS]}
          value={props.value.weekday}
          onChange={weekday => set({ weekday })}
        />
      </div>
      <ScheduleNumberField
        label="Hour"
        value={props.value.hour}
        min={0}
        max={23}
        placeholder="9"
        onChange={hour => set({ hour })}
      />
      <ScheduleNumberField
        label="Minute"
        value={props.value.minute}
        min={0}
        max={59}
        placeholder="0"
        onChange={minute => set({ minute })}
      />
    </div>
  )
}

function ScheduleNumberField(props: {
  label: string
  value: string
  min: number
  max: number
  placeholder: string
  onChange: (value: string) => void
}) {
  const reactId = useId()
  const inputId = `${reactId}-schedule-${props.label.toLowerCase()}`
  return (
    <div className="space-y-1.5">
      <Label htmlFor={inputId}>{props.label}</Label>
      <Input
        id={inputId}
        type="number"
        inputMode="numeric"
        min={props.min}
        max={props.max}
        step={1}
        value={props.value}
        placeholder={props.placeholder}
        onChange={event => {
          const raw = event.target.value
          if (raw === '' || /^\d{1,2}$/.test(raw)) props.onChange(raw)
        }}
      />
    </div>
  )
}

export function AdvancedSourceTools(props: { children: ReactNode }) {
  return (
    <details className="rounded-md border border-border bg-muted/20 p-3">
      <summary className="cursor-pointer text-sm font-medium">Advanced</summary>
      <div className="mt-3 space-y-6">
        {props.children}
      </div>
    </details>
  )
}

function sourceListKindLabel(connection: SourceConnection, backendKey: string) {
  const sourceType = sourceTypeFromConfig(connection.config_json)
  if (sourceType === 'rss' || sourceType === 'atom') return 'Feed source'
  if (connection.handler_kind === 'generated_custom') return 'Advanced handler'
  if (backendKey === 'rss' || backendKey === 'atom') return 'Feed source'
  if (sourceType === 'web_list' || sourceType === 'web_page' || connection.handler_kind === 'recipe') return 'Recipe source'
  if (backendKey === 'web_page') return 'Web source'
  return 'Built-in source'
}

function sourceTypeFromConfig(config: Record<string, unknown> | null | undefined) {
  const value = config?.source_type
  return typeof value === 'string' ? value : null
}

export function WorkspaceRoutingCard(props: {
  workspaceId: string
  bindingConnectionId: string
  workspaceOptions: SelectOption[]
  connectionOptions: SelectOption[]
  workspaces: Workspace[]
  connections: SourceConnection[]
  bindings: WorkspaceSourceBinding[]
  busy: string | null
  projectScoped: boolean
  onWorkspaceIdChange: (value: string) => void
  onBindingConnectionIdChange: (value: string) => void
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
          <Label>Source</Label>
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
            disabled={!props.projectScoped || !props.workspaces.length || !props.connections.length || props.busy === 'workspace:binding'}
            onClick={props.onCreateWorkspaceBinding}
          >
            <Link2 className="size-4" />
            Bind source
          </Button>
        </div>
        <div className="flex gap-1.5 flex-wrap">
          <Badge variant="outline">{props.bindings.length} bindings</Badge>
        </div>
      </div>
    </Card>
  )
}

export function SourcesSection(props: {
  connections: SourceConnection[]
  loading: boolean
  busy: string | null
  sourceBackendKey: (connection: SourceConnection) => string
  onScanConnection: (connection: SourceConnection) => void
  onUpdateConnection: (connection: SourceConnection, status: 'active' | 'paused' | 'archived') => void
  onSaveGovernance: (
    connection: SourceConnection,
    body: { capture_policy?: SourceCapturePolicy; consent: Record<string, unknown>; policy: Record<string, unknown> },
  ) => void
}) {
  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Sources</h2>
          <p className="text-xs text-muted-foreground">{props.connections.length} configured</p>
        </div>
      </div>
      {props.loading ? (
        <Card><p className="text-muted-foreground text-center py-8 text-sm">Loading...</p></Card>
      ) : props.connections.length === 0 ? (
        <EmptyState title="No sources" description="Create a source or save a URL." />
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          {props.connections.map(connection => {
            const key = props.sourceBackendKey(connection)
            const isCustomSource = connection.handler_kind === 'generated_custom' || (!connection.handler_kind && key === 'custom_source')
            const isRecipeSource = connection.handler_kind === 'recipe'
            const canScan = key === 'rss' || key === 'atom' || key === 'web_page' || key === 'arxiv' || (isCustomSource && Boolean(connection.active_handler_version_id)) || (isRecipeSource && Boolean(connection.active_recipe_version_id))
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
                  <Badge variant="outline">{sourceListKindLabel(connection, key)}</Badge>
                  <Badge variant="muted">{connection.fetch_frequency}</Badge>
                  <Badge variant="muted">{connection.capture_policy}</Badge>
                  <Badge variant="muted">{connection.trust_level}</Badge>
                  {connection.repair_status && <Badge variant="muted">{connection.repair_status}</Badge>}
                </div>
                <div className="flex items-end justify-between gap-2 mt-4">
                  <div className="space-y-0.5">
                    <p className="text-xs text-muted-foreground">Checked: {fmt(connection.last_checked_at)}</p>
                    <p className="text-xs text-muted-foreground">Next: {fmt(connection.next_check_at)}</p>
                  </div>
                  <div className="flex gap-1.5">
                    <Button type="button" size="sm" variant="outline" asChild>
                      <Link to={`/intake/sources/${connection.id}`}>Details</Link>
                    </Button>
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
                    {isCustomSource ? (
                      connection.status === 'active' && (
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          disabled={props.busy === `connection:${connection.id}`}
                          onClick={() => props.onUpdateConnection(connection, 'paused')}
                        >
                          Pause
                        </Button>
                      )
                    ) : (
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        disabled={props.busy === `connection:${connection.id}`}
                        onClick={() => props.onUpdateConnection(connection, connection.status === 'active' ? 'paused' : 'active')}
                      >
                        {connection.status === 'active' ? 'Pause' : 'Activate'}
                      </Button>
                    )}
                  </div>
                </div>
                <SourceGovernanceEditor
                  connection={connection}
                  busy={props.busy === `governance:${connection.id}`}
                  onSave={body => props.onSaveGovernance(connection, body)}
                />
              </Card>
            )
          })}
        </div>
      )}
    </section>
  )
}

const RETENTION_OPTIONS = [
  { value: 'metadata_only', label: 'metadata only' },
  { value: 'summary_only', label: 'summary only' },
  { value: 'full_text', label: 'full text' },
  { value: 'full_snapshot', label: 'full snapshot' },
  { value: 'archived', label: 'archived' },
]

const EGRESS_OPTIONS = [
  { value: 'internal_only', label: 'internal only' },
  { value: 'local_provider_allowed', label: 'local provider allowed' },
  { value: 'external_provider_allowed', label: 'external provider allowed' },
]

const TRUST_OPTIONS = [
  { value: 'trusted', label: 'trusted' },
  { value: 'normal', label: 'normal' },
  { value: 'untrusted', label: 'untrusted' },
]

const DERIVED_WRITE_OPTIONS = [
  { value: 'proposal_required', label: 'proposal required' },
  { value: 'disabled', label: 'disabled' },
]

const IMPORT_TARGET_OPTIONS = [
  { value: 'activity', label: 'Activity' },
  { value: 'source_artifact', label: 'Source artifact' },
  { value: 'knowledge', label: 'Knowledge proposal' },
  { value: 'memory_proposal', label: 'Memory proposal' },
]

function SourceGovernanceEditor(props: {
  connection: SourceConnection
  busy: boolean
  onSave: (body: { capture_policy?: SourceCapturePolicy; consent: Record<string, unknown>; policy: Record<string, unknown> }) => void
}) {
  const [open, setOpen] = useState(false)
  const [capturePolicy, setCapturePolicy] = useState<SourceCapturePolicy>('reference_only')
  const [retention, setRetention] = useState('metadata_only')
  const [egressClass, setEgressClass] = useState('internal_only')
  const [trust, setTrust] = useState('normal')
  const [derivedWrite, setDerivedWrite] = useState('proposal_required')
  const [allowLocalProvider, setAllowLocalProvider] = useState(false)
  const [allowExternalProvider, setAllowExternalProvider] = useState(false)
  const [allowSpaceAdmins, setAllowSpaceAdmins] = useState(true)
  const [targets, setTargets] = useState<string[]>(['activity', 'source_artifact'])
  const [subjects, setSubjects] = useState('')
  const [readers, setReaders] = useState('')
  const [agents, setAgents] = useState('')

  useEffect(() => {
    const consent = props.connection.consent_json ?? {}
    const policy = props.connection.policy_json ?? {}
    const nextCapturePolicy = props.connection.capture_policy
    setCapturePolicy(nextCapturePolicy)
    setRetention(stringFrom(policy.retention_policy, minimumRetentionForCapturePolicy(nextCapturePolicy)))
    setEgressClass(stringFrom(policy.source_egress_class, 'internal_only'))
    setTrust(stringFrom(policy.import_trust_level, props.connection.trust_level))
    setDerivedWrite(stringFrom(policy.derived_write_policy, 'proposal_required'))
    setAllowLocalProvider(consent.allow_local_provider_egress === true)
    setAllowExternalProvider(consent.allow_external_model_egress === true)
    setAllowSpaceAdmins(consent.allow_space_admins !== false)
    setTargets(stringList(policy.allowed_import_targets, ['activity', 'source_artifact']))
    setSubjects(stringList(consent.subject_user_ids, [props.connection.owner_user_id]).join(', '))
    setReaders(stringList(consent.allowed_reader_user_ids, [props.connection.owner_user_id]).join(', '))
    setAgents(stringList(consent.allowed_agent_ids, []).join(', '))
  }, [
    props.connection.id,
    props.connection.capture_policy,
    props.connection.consent_json,
    props.connection.owner_user_id,
    props.connection.policy_json,
    props.connection.trust_level,
  ])

  function toggleTarget(target: string, checked: boolean) {
    setTargets(current => {
      if (checked) return Array.from(new Set([...current, target]))
      return current.filter(item => item !== target)
    })
  }

  function changeCapturePolicy(value: string) {
    const nextCapturePolicy = sourceCapturePolicyValue(value, capturePolicy)
    setCapturePolicy(nextCapturePolicy)
    setRetention(current => retentionAtLeast(current, minimumRetentionForCapturePolicy(nextCapturePolicy)))
  }

  function save() {
    props.onSave({
      capture_policy: capturePolicy,
      consent: {
        ...props.connection.consent_json,
        subject_user_ids: csvList(subjects),
        allowed_reader_user_ids: csvList(readers),
        allowed_agent_ids: csvList(agents),
        allow_space_admins: allowSpaceAdmins,
        allow_local_provider_egress: allowLocalProvider,
        allow_external_model_egress: allowExternalProvider,
      },
      policy: {
        ...props.connection.policy_json,
        source_egress_class: egressClass,
        retention_policy: retention,
        import_trust_level: trust,
        derived_write_policy: derivedWrite,
        allowed_import_targets: targets,
        revalidation: { required: true, viewer_scoped: true },
      },
    })
  }

  return (
    <div className="mt-4 border-t border-border pt-3">
      <button
        type="button"
        onClick={() => setOpen(value => !value)}
        className="flex w-full items-center justify-between gap-2 text-xs text-muted-foreground hover:text-foreground"
      >
        <span className="inline-flex items-center gap-1.5">
          <ShieldCheck className="size-3.5" />
          Governance
        </span>
        {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
      </button>
      {open && (
        <div className="mt-3 space-y-3 rounded-md border border-border bg-muted/20 p-3">
          <div className="grid gap-3 md:grid-cols-2">
            <div className="space-y-1.5">
              <Label>Capture</Label>
              <Select options={CAPTURE_POLICIES} value={capturePolicy} onChange={changeCapturePolicy} />
              <p className="text-xs text-muted-foreground">{capturePolicyDescription(capturePolicy)}</p>
            </div>
            <div className="space-y-1.5">
              <Label>Retention</Label>
              <Select options={RETENTION_OPTIONS} value={retention} onChange={setRetention} />
            </div>
            <div className="space-y-1.5">
              <Label>Source egress</Label>
              <Select options={EGRESS_OPTIONS} value={egressClass} onChange={setEgressClass} />
            </div>
            <div className="space-y-1.5">
              <Label>Trust</Label>
              <Select options={TRUST_OPTIONS} value={trust} onChange={setTrust} />
            </div>
            <div className="space-y-1.5">
              <Label>Derived writes</Label>
              <Select options={DERIVED_WRITE_OPTIONS} value={derivedWrite} onChange={setDerivedWrite} />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label>Allowed import targets</Label>
            <div className="grid gap-2 sm:grid-cols-2">
              {IMPORT_TARGET_OPTIONS.map(option => (
                <label key={option.value} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={targets.includes(option.value)}
                    onChange={event => toggleTarget(option.value, event.target.checked)}
                  />
                  {option.label}
                </label>
              ))}
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-3">
            <TextListField label="Subjects" value={subjects} onChange={setSubjects} />
            <TextListField label="Readers" value={readers} onChange={setReaders} />
            <TextListField label="Agents" value={agents} onChange={setAgents} />
          </div>

          <div className="grid gap-2 sm:grid-cols-3">
            <CheckboxRow label="Space admins" checked={allowSpaceAdmins} onChange={setAllowSpaceAdmins} />
            <CheckboxRow label="Local provider egress" checked={allowLocalProvider} onChange={setAllowLocalProvider} />
            <CheckboxRow label="External model egress" checked={allowExternalProvider} onChange={setAllowExternalProvider} />
          </div>

          <p className="text-xs text-muted-foreground">
            Capture controls how much source content is fetched. Feed sources need Extract text to queue full article retrieval after a scan.
          </p>
          <Button type="button" size="sm" onClick={save} disabled={props.busy}>
            {props.busy ? 'Saving...' : 'Save governance'}
          </Button>
        </div>
      )}
    </div>
  )
}

function TextListField(props: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <div className="space-y-1.5">
      <Label>{props.label}</Label>
      <Input
        value={props.value}
        onChange={event => props.onChange(event.target.value)}
        placeholder="user-id, user-id"
        className="font-mono text-xs"
      />
    </div>
  )
}

function CheckboxRow(props: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <label className="flex items-center gap-2 text-sm">
      <input type="checkbox" checked={props.checked} onChange={event => props.onChange(event.target.checked)} />
      {props.label}
    </label>
  )
}

function stringFrom(value: unknown, fallback: string): string {
  return typeof value === 'string' && value.trim() ? value : fallback
}

function stringList(value: unknown, fallback: string[]): string[] {
  if (!Array.isArray(value)) return fallback
  const strings = value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
  return strings.length ? strings : fallback
}

function csvList(value: string): string[] {
  return value.split(',').map(item => item.trim()).filter(Boolean)
}

function isManualUrlItem(item: IntakeItem) {
  return item.item_type === 'external_url' && item.metadata_json?.created_by === 'manual_url'
}

export function ItemsSection(props: {
  items: IntakeItem[]
  itemFilter: ItemFilter
  itemQuery: string
  scopedProjectId: string
  scopedConnectionId: string
  connectionOptions: SelectOption[]
  busy: string | null
  summaryResults: Record<string, IntakeSummaryResult>
  onItemFilterChange: (value: ItemFilter) => void
  onItemQueryChange: (value: string) => void
  onItemConnectionChange: (item: IntakeItem, connectionId: string | null) => void
  onItemAction: (item: IntakeItem, action: string) => void
  onSummarizeItem: (item: IntakeItem) => void
}) {
  return (
    <section className="space-y-3">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Items</h2>
          <p className="text-xs text-muted-foreground">{props.items.length} visible</p>
          {(props.scopedProjectId || props.scopedConnectionId) && (
            <div className="flex gap-1.5 flex-wrap mt-2">
              {props.scopedProjectId && <Badge variant="outline">project {short(props.scopedProjectId)}</Badge>}
              {props.scopedConnectionId && <Badge variant="outline">source {short(props.scopedConnectionId)}</Badge>}
            </div>
          )}
        </div>
        <div className="flex items-center gap-2 flex-wrap justify-end">
          <Input
            value={props.itemQuery}
            onChange={event => props.onItemQueryChange(event.target.value)}
            placeholder="Search title, excerpt, URI, domain"
            className="h-9 w-full sm:w-72"
          />
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
      </div>
      {props.items.length === 0 ? (
        <EmptyState title="No intake items" description="Saved URLs and source scan results appear here." />
      ) : (
        props.items.map(item => {
          const textExtractionReason = textExtractionDisabledReason(item)
          const textExtractionLabel = textExtractionActionLabel(item)
          const itemBusy = props.busy?.startsWith(`item:${item.id}`) ?? false
          return (
            <Card key={item.id}>
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <Link
                    to={`/intake/items/${item.id}`}
                    className="block font-medium text-sm truncate hover:underline"
                  >
                    {item.title}
                  </Link>
                  <p className="text-xs text-muted-foreground line-clamp-2 mt-1">{preview(item.excerpt, item.source_uri ?? 'No source URI')}</p>
                </div>
                <StatusBadge status={item.status} />
              </div>
              <div className="flex gap-1.5 flex-wrap mt-3">
                <Badge variant="outline">{item.item_type}</Badge>
                <Badge variant="muted">{item.content_state}</Badge>
                {item.source_domain && <Badge variant="muted">{item.source_domain}</Badge>}
                {item.connection_id && <Badge variant="muted">source {short(item.connection_id)}</Badge>}
              </div>
              {isManualUrlItem(item) && (
                <div className="mt-3 max-w-sm space-y-1.5">
                  <Label>Source</Label>
                  {props.connectionOptions.length === 0 ? (
                    <p className="text-xs text-muted-foreground">No project-linked sources are available.</p>
                  ) : (
                    <Select
                      value={item.connection_id ?? ''}
                      options={props.connectionOptions}
                      disabled={itemBusy}
                      onChange={value => props.onItemConnectionChange(item, value || null)}
                    />
                  )}
                </div>
              )}
              <div className="flex flex-wrap gap-1.5 mt-4">
                <Button asChild size="sm" variant="default">
                  <Link to={`/intake/items/${item.id}/read`}>
                    <BookOpen className="size-3.5" />
                    Read
                  </Link>
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  aria-label={`${textExtractionLabel} ${item.title}`}
                  disabled={itemBusy || textExtractionReason !== null}
                  title={textExtractionReason ?? undefined}
                  onClick={() => props.onItemAction(item, 'queue_content')}
                >
                  {item.content_state === 'content_saved' ? <RefreshCw className="size-3.5" /> : <FileText className="size-3.5" />}
                  {textExtractionLabel}
                </Button>
                <Button type="button" size="sm" variant="outline" disabled={itemBusy} onClick={() => props.onItemAction(item, 'extract_evidence')}>
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
                <Button type="button" size="sm" variant="ghost" disabled={itemBusy} onClick={() => props.onItemAction(item, 'read_later')}>
                  <Bookmark className="size-3.5" />
                  Later
                </Button>
                <Button type="button" size="sm" variant="ghost" disabled={itemBusy} onClick={() => props.onItemAction(item, 'mark_selected')}>
                  <CheckCircle2 className="size-3.5" />
                  Select
                </Button>
                <Button type="button" size="sm" variant="ghost" disabled={itemBusy} onClick={() => props.onItemAction(item, 'mark_ignored')}>
                  <XCircle className="size-3.5" />
                  Ignore
                </Button>
              </div>
              {props.summaryResults[item.id] && <IntakeSummaryLinks result={props.summaryResults[item.id]} />}
            </Card>
          )
        })
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
                {job.connection_id && <Badge variant="muted">source {short(job.connection_id)}</Badge>}
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
