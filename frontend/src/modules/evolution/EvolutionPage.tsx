import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
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
import { Card, CardTitle } from '../../components/ui/card'
import { Badge, StatusBadge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../../components/ui/dialog'
import { EmptyState } from '../../components/ui/empty-state'
import { Input } from '../../components/ui/input'
import { Label } from '../../components/ui/label'
import { Select } from '../../components/ui/select'
import { Skeleton } from '../../components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../components/ui/tabs'
import { Textarea } from '../../components/ui/textarea'

const EMPTY_SUMMARY: EvolutionSummaryOut = {
  active_targets: 0,
  signals_collected: 0,
  pending_proposals: 0,
  recent_runs: 0,
}

const SIGNAL_TYPE_LABELS: Record<string, string> = {
  memory_candidate_proposed: 'Memory candidate proposed',
  memory_candidate_rejected: 'Memory candidate rejected',
  memory_candidate_edited: 'Memory candidate edited',
  stable_preference_missed: 'Stable preference missed',
  exploration_misclassified_as_decision: 'Exploration misclassified',
  temporary_note_saved_as_memory: 'Temporary note saved',
  proposal_rejected: 'Proposal rejected',
  user_repeated_same_correction: 'Repeated correction',
  run_validation_failed: 'Validation failed',
}

const SIGNAL_TYPES = Object.entries(SIGNAL_TYPE_LABELS).map(([value, label]) => ({ value, label }))

const SIGNAL_SEVERITIES = ['low', 'medium', 'high', 'critical'].map(value => ({ value, label: value }))
type DetailTab = 'definition' | 'signals' | 'runs' | 'proposals' | 'validation'
type TargetDialogMode = 'create' | 'copy' | 'edit'
type TargetListTab = 'active' | 'archived'

const TARGET_TYPES = ['prompt', 'capability', 'agent_profile', 'workflow', 'policy'].map(value => ({ value, label: value }))
const RISK_LEVELS = ['low', 'medium', 'high', 'critical'].map(value => ({ value, label: value }))
const TARGET_STATUSES = ['active', 'paused', 'archived'].map(value => ({ value, label: value }))
const ENABLED_OPTIONS = [
  { value: 'true', label: 'Enabled' },
  { value: 'false', label: 'Disabled' },
]
const DEFAULT_ENGINE_POLICY = {
  allowed_engines: ['llm_prompt_review'],
  allowed_proposal_types: ['prompt_update'],
}
const DEFAULT_VALIDATION = {
  window: '14d',
  metrics: [{
    id: 'target_signal_count',
    label: 'Target signal count',
    evaluator: 'count_signals',
    source: 'signals',
    signal_type: 'run_validation_failed',
    goal: { direction: 'decrease', threshold: 0 },
  }],
}

function fmt(dt: string | null | undefined) {
  return dt ? new Date(dt).toLocaleString() : '-'
}

function shortId(id: string | null | undefined) {
  return id ? `${id.slice(0, 8)}...` : '-'
}

function displayTargetName(row: { target_name?: string | null; capability_key?: string | null; target_id?: string | null; id?: string | null }) {
  return row.target_name ?? row.capability_key ?? shortId(row.target_id ?? row.id)
}

function displaySignalType(signalType: string) {
  return SIGNAL_TYPE_LABELS[signalType] ?? signalType
}

function jsonText(value: unknown) {
  return JSON.stringify(value ?? {}, null, 2)
}

function parseJsonObject(text: string, label: string): Record<string, unknown> {
  try {
    const value = JSON.parse(text)
    if (value && typeof value === 'object' && !Array.isArray(value)) return value as Record<string, unknown>
  } catch {
    // handled below
  }
  throw new Error(`${label} must be a JSON object.`)
}

function stringListFromText(text: string) {
  return text
    .split('\n')
    .map(line => line.trim())
    .filter(Boolean)
}

function riskVariant(risk: string): 'default' | 'secondary' | 'muted' | 'destructive' {
  if (risk === 'critical') return 'destructive'
  if (risk === 'high') return 'default'
  if (risk === 'medium') return 'secondary'
  return 'muted'
}

function OverviewCards({ summary }: { summary: EvolutionSummaryOut }) {
  const cards = [
    { label: 'Active targets', value: summary.active_targets, empty: 'No active targets' },
    { label: 'Signals collected', value: summary.signals_collected, empty: 'No signals yet' },
    { label: 'Pending evolution proposals', value: summary.pending_proposals, empty: 'No pending proposals' },
    { label: 'Recent evolution runs', value: summary.recent_runs, empty: 'No recent runs' },
  ]
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {cards.map(card => (
        <Card key={card.label} className="mb-0 p-4">
          <div className="text-[11px] font-bold uppercase tracking-widest text-muted-foreground">{card.label}</div>
          <div className="mt-2 text-2xl font-semibold leading-none" style={{ fontFamily: 'var(--font-mono)' }}>{card.value}</div>
          <div className="mt-1 text-xs text-muted-foreground">{card.value === 0 ? card.empty : 'Current space'}</div>
        </Card>
      ))}
    </div>
  )
}

function SectionCard({ title, count, children }: {
  title: string
  count?: number
  children: React.ReactNode
}) {
  return (
    <Card className="mb-0">
      <div className="mb-4 flex items-center justify-between gap-3">
        <CardTitle className="mb-0">{title}</CardTitle>
        {count !== undefined && (
          <span className="text-[11px] text-muted-foreground" style={{ fontFamily: 'var(--font-mono)' }}>
            {String(count).padStart(2, '0')}
          </span>
        )}
      </div>
      {children}
    </Card>
  )
}

function TargetList({
  targets,
  selectedTargetId,
  onSelect,
  onConfigure,
  emptyTitle = 'No targets.',
  emptyDescription = 'Registered evolution targets appear here.',
}: {
  targets: EvolutionTarget[]
  selectedTargetId: string | null
  onSelect: (targetId: string) => void
  onConfigure: (target: EvolutionTarget) => void
  emptyTitle?: string
  emptyDescription?: string
}) {
  if (targets.length === 0) {
    return (
      <EmptyState
        title={emptyTitle}
        description={emptyDescription}
      />
    )
  }
  return (
    <div className="space-y-2">
      {targets.map(target => {
        const selected = selectedTargetId === target.id
        return (
          <button
            key={target.id}
            type="button"
            onClick={() => onSelect(target.id)}
            aria-pressed={selected}
            className={[
              'w-full rounded-md border p-3 text-left transition-colors',
              selected ? 'border-primary bg-accent/50' : 'border-border hover:bg-accent/40',
            ].join(' ')}
          >
            <div className="flex min-w-0 items-center justify-between gap-3">
              <span className="truncate text-sm font-medium text-foreground">{target.target_name ?? target.capability_key ?? shortId(target.id)}</span>
              <StatusBadge status={target.enabled ? target.status : 'disabled'} />
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <Badge variant="secondary">{target.target_type}</Badge>
              <Badge variant={riskVariant(target.risk_level)}>{target.risk_level}</Badge>
              <Badge variant="outline">{target.recent_signal_count} signals</Badge>
            </div>
            <p className="mt-2 truncate text-xs text-muted-foreground" style={{ fontFamily: 'var(--font-mono)' }}>
              {target.capability_key ?? target.target_ref_id ?? target.id}
            </p>
            <div className="mt-3 flex justify-end">
              <span
                role="button"
                tabIndex={0}
                onClick={event => {
                  event.stopPropagation()
                  onConfigure(target)
                }}
                onKeyDown={event => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault()
                    event.stopPropagation()
                    onConfigure(target)
                  }
                }}
                className="rounded-md border border-border px-2 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
              >
                Edit
              </span>
            </div>
          </button>
        )
      })}
    </div>
  )
}

function EvolutionSignalsList({ signals, loading }: { signals: EvolutionSignal[]; loading?: boolean }) {
  if (loading) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-16 w-full" />
      </div>
    )
  }
  if (signals.length === 0) {
    return (
      <EmptyState
        title="No signals for this target."
        description="Typed evidence for this target appears here."
      />
    )
  }
  return (
    <div className="divide-y divide-border">
      {signals.map(signal => (
        <div key={signal.id} className="py-3 first:pt-0 last:pb-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="secondary">{displaySignalType(signal.signal_type)}</Badge>
            <Badge variant={riskVariant(signal.severity)}>{signal.severity}</Badge>
            <span className="text-sm font-medium text-foreground">{displayTargetName(signal)}</span>
          </div>
          <p className="mt-1 text-xs text-muted-foreground" style={{ fontFamily: 'var(--font-mono)' }}>{signal.signal_type}</p>
          <p className="mt-2 text-sm text-muted-foreground">{signal.summary ?? 'No summary provided.'}</p>
          <p className="mt-1 text-xs text-muted-foreground">
            {signal.source_type}{signal.source_id ? ` ${shortId(signal.source_id)}` : ''} - {fmt(signal.created_at)}
          </p>
        </div>
      ))}
    </div>
  )
}

function EvolutionRunsList({ runs }: { runs: EvolutionRunListItem[] }) {
  if (runs.length === 0) {
    return (
      <EmptyState
        title="No runs for this target."
        description="Review runs appear here."
      />
    )
  }
  return (
    <div className="divide-y divide-border">
      {runs.map(run => (
        <div key={run.run_id} className="flex flex-col gap-3 py-3 first:pt-0 last:pb-0 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0 space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge status={run.status} />
              <Badge variant="outline">{run.engine ?? 'unknown engine'}</Badge>
              <span className="font-mono text-xs text-muted-foreground">{shortId(run.run_id)}</span>
            </div>
            <p className="text-sm font-medium text-foreground">{displayTargetName(run)}</p>
            <p className="text-xs text-muted-foreground">
              created {fmt(run.created_at)} - started {fmt(run.started_at)} - artifacts {run.artifact_count}
            </p>
            {run.proposal_id && (
              <Link to={`/proposals/${run.proposal_id}`} className="text-xs text-accent-foreground hover:underline">
                Proposal {shortId(run.proposal_id)}
              </Link>
            )}
          </div>
          <Button size="sm" variant="outline" asChild>
            <Link to={`/runs/${run.run_id}`}>Open run</Link>
          </Button>
        </div>
      ))}
    </div>
  )
}

function EvolutionProposalsList({ proposals }: { proposals: EvolutionProposal[] }) {
  if (proposals.length === 0) {
    return (
      <EmptyState
        title="No proposals for this target."
        description="Reviewable changes appear here."
      />
    )
  }
  return (
    <div className="divide-y divide-border">
      {proposals.map(proposal => (
        <div key={proposal.id} className="py-3 first:pt-0 last:pb-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="secondary">{proposal.proposal_type}</Badge>
            <StatusBadge status={proposal.status} />
            <Link to={`/proposals/${proposal.id}`} className="text-sm font-medium text-accent-foreground hover:underline">
              {displayTargetName(proposal)}
            </Link>
          </div>
          <p className="mt-2 text-sm text-muted-foreground">{proposal.summary ?? 'No summary provided.'}</p>
          <p className="mt-1 text-xs text-muted-foreground">created {fmt(proposal.created_at)}</p>
        </div>
      ))}
    </div>
  )
}

function EvolutionValidationPanel({ results }: { results: EvolutionValidationResult[] }) {
  if (results.length === 0) {
    return (
      <EmptyState
        title="No validation configured for this target."
        description="Configured evaluator results appear here."
      />
    )
  }
  return (
    <div className="divide-y divide-border">
      {results.map(result => (
        <div key={`${result.target_id}-${result.metric_id}`} className="flex flex-col gap-2 py-3 first:pt-0 last:pb-0 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-sm font-medium text-foreground">{result.label}</p>
              <Badge variant="outline">{result.evaluator}</Badge>
              <StatusBadge status={result.status} />
            </div>
            <p className="mt-1 text-xs text-muted-foreground" style={{ fontFamily: 'var(--font-mono)' }}>{result.metric_id}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              window {result.window ?? 'all'} - sample {result.sample_size}
              {result.numerator_count !== null && result.denominator_count !== null
                ? ` - ${result.numerator_count}/${result.denominator_count}`
                : ''}
            </p>
          </div>
          <div className="text-left sm:text-right">
            <p className="text-sm" style={{ fontFamily: 'var(--font-mono)' }}>
              {result.value === null || result.value === undefined ? 'No data yet' : String(result.value)}
            </p>
            <p className="text-xs text-muted-foreground">{fmt(result.updated_at)}</p>
          </div>
        </div>
      ))}
    </div>
  )
}

function TargetConfigDialog({
  open,
  mode,
  target,
  saving,
  onOpenChange,
  onSubmit,
}: {
  open: boolean
  mode: TargetDialogMode
  target: EvolutionTarget | null
  saving: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (body: EvolutionTargetCreateBody | EvolutionTargetUpdateBody, mode: TargetDialogMode) => Promise<void>
}) {
  const isEdit = mode === 'edit'
  const isCopy = mode === 'copy'
  const [targetName, setTargetName] = useState('')
  const [targetType, setTargetType] = useState('prompt')
  const [targetRefType, setTargetRefType] = useState('capability')
  const [targetRefId, setTargetRefId] = useState('')
  const [capabilityKey, setCapabilityKey] = useState('')
  const [riskLevel, setRiskLevel] = useState('medium')
  const [status, setStatus] = useState('active')
  const [enabled, setEnabled] = useState('true')
  const [purpose, setPurpose] = useState('')
  const [constraints, setConstraints] = useState('')
  const [enginePolicyJson, setEnginePolicyJson] = useState(jsonText(DEFAULT_ENGINE_POLICY))
  const [validationJson, setValidationJson] = useState(jsonText(DEFAULT_VALIDATION))
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    const meta = target?.metadata_json ?? {}
    const displayName = typeof meta.display_name === 'string'
      ? meta.display_name
      : typeof meta.name === 'string'
        ? meta.name
        : ''
    const nextName = target ? (displayName || target.target_name || '') : ''
    setTargetName(mode === 'copy' && nextName ? `${nextName} copy` : nextName)
    setTargetType(target?.target_type ?? 'prompt')
    setTargetRefType(target?.target_ref_type ?? 'capability')
    setTargetRefId(target?.target_ref_id ?? '')
    setCapabilityKey(target?.capability_key ?? '')
    setRiskLevel(target?.risk_level ?? 'medium')
    setStatus(isCopy ? 'active' : target?.status ?? 'active')
    setEnabled(String(isCopy ? true : target?.enabled ?? true))
    setPurpose(typeof meta.purpose === 'string' ? meta.purpose : '')
    setConstraints(Array.isArray(meta.constraints) ? meta.constraints.filter(item => typeof item === 'string').join('\n') : '')
    setEnginePolicyJson(jsonText(target?.engine_policy_json && Object.keys(target.engine_policy_json).length > 0 ? target.engine_policy_json : DEFAULT_ENGINE_POLICY))
    setValidationJson(jsonText(meta.validation ?? DEFAULT_VALIDATION))
    setError(null)
  }, [mode, open, target])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    try {
      const enginePolicy = parseJsonObject(enginePolicyJson, 'Engine policy')
      const validation = parseJsonObject(validationJson, 'Validation')
      const metadata: Record<string, unknown> = { ...(target?.metadata_json ?? {}) }
      metadata.validation = validation
      if (isCopy) {
        metadata.origin = {
          type: 'clone',
          source_target_id: target?.id ?? null,
        }
      }
      const constraintRows = stringListFromText(constraints)
      if (constraintRows.length > 0) metadata.constraints = constraintRows
      else delete metadata.constraints
      if (isEdit) {
        await onSubmit({
          target_type: targetType,
          target_ref_type: targetRefType.trim() || null,
          target_ref_id: targetRefId.trim() || null,
          capability_key: capabilityKey.trim() || null,
          risk_level: riskLevel,
          enabled: enabled === 'true',
          status,
          target_name: targetName,
          purpose,
          engine_policy_json: enginePolicy,
          metadata_json: metadata,
        }, mode)
      } else {
        await onSubmit({
          target_type: targetType,
          target_ref_type: targetRefType.trim() || null,
          target_ref_id: targetRefId.trim() || null,
          capability_key: capabilityKey.trim() || null,
          risk_level: riskLevel,
          enabled: enabled === 'true',
          status,
          target_name: targetName,
          purpose,
          engine_policy_json: enginePolicy,
          metadata_json: metadata,
        }, mode)
      }
    } catch (e) {
      setError(errMsg(e))
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{isCopy ? 'Copy target' : isEdit ? 'Edit target' : 'New target'}</DialogTitle>
          <DialogDescription>
            Configure a target instance and its validation evaluators for this space.
          </DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={submit}>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>Name</Label>
              <Input value={targetName} onChange={event => setTargetName(event.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label>Target type</Label>
              <Select value={targetType} onChange={setTargetType} options={TARGET_TYPES} />
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="space-y-1.5">
              <Label>Reference type</Label>
              <Input value={targetRefType} onChange={event => setTargetRefType(event.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label>Reference ID</Label>
              <Input value={targetRefId} onChange={event => setTargetRefId(event.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label>Capability key</Label>
              <Input value={capabilityKey} onChange={event => setCapabilityKey(event.target.value)} />
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="space-y-1.5">
              <Label>Risk</Label>
              <Select value={riskLevel} onChange={setRiskLevel} options={RISK_LEVELS} />
            </div>
            <div className="space-y-1.5">
              <Label>Status</Label>
              <Select value={status} onChange={setStatus} options={TARGET_STATUSES} />
            </div>
            <div className="space-y-1.5">
              <Label>Enabled</Label>
              <Select value={enabled} onChange={setEnabled} options={ENABLED_OPTIONS} />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label>Purpose</Label>
            <Textarea value={purpose} onChange={event => setPurpose(event.target.value)} rows={3} />
          </div>
          <div className="space-y-1.5">
            <Label>Constraints</Label>
            <Textarea value={constraints} onChange={event => setConstraints(event.target.value)} rows={5} />
          </div>
          <div className="grid gap-3 lg:grid-cols-2">
            <div className="space-y-1.5">
              <Label>Engine policy JSON</Label>
              <Textarea value={enginePolicyJson} onChange={event => setEnginePolicyJson(event.target.value)} rows={9} className="font-mono text-xs" />
            </div>
            <div className="space-y-1.5">
              <Label>Validation JSON</Label>
              <Textarea value={validationJson} onChange={event => setValidationJson(event.target.value)} rows={9} className="font-mono text-xs" />
            </div>
          </div>
          {error && <p className="text-xs text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
              Cancel
            </Button>
            <Button type="submit" disabled={saving}>
              {saving && <Loader2 className="size-3.5 animate-spin" />}
              {isEdit ? 'Save target' : 'Create target'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function TargetDefinition({ target, modelProvider }: { target: EvolutionTarget; modelProvider: ModelProviderOut | null }) {
  const enginePolicy = target.engine_policy_json ?? {}
  const allowedEngines = Array.isArray(enginePolicy.allowed_engines) ? enginePolicy.allowed_engines.join(', ') : 'llm_prompt_review'
  const modelLabel = modelProvider
    ? `${modelProvider.name}${modelProvider.default_model ? ` / ${modelProvider.default_model}` : ''}`
    : 'Not configured'
  const rows = [
    ['Scope', target.scope ?? '-'],
    ['Type', target.target_type],
    ['Reference', target.target_ref_id ?? '-'],
    ['Capability', target.capability_key ?? '-'],
    ['Current version', target.current_version ?? target.current_version_id ?? '-'],
    ['Last run', fmt(target.last_run_at)],
  ]
  return (
    <div className="space-y-4">
      {target.purpose && <p className="text-sm text-muted-foreground">{target.purpose}</p>}
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-md border border-border p-3">
          <div className="text-[11px] font-bold uppercase tracking-widest text-muted-foreground">Review engine</div>
          <div className="mt-1 text-sm text-foreground" style={{ fontFamily: 'var(--font-mono)' }}>{allowedEngines}</div>
        </div>
        <div className="rounded-md border border-border p-3">
          <div className="text-[11px] font-bold uppercase tracking-widest text-muted-foreground">Model provider</div>
          <div className="mt-1 text-sm text-foreground">{modelLabel}</div>
        </div>
        <div className="rounded-md border border-border p-3">
          <div className="text-[11px] font-bold uppercase tracking-widest text-muted-foreground">Review input</div>
          <div className="mt-1 text-sm text-foreground">Current prompt + typed signals</div>
        </div>
        <div className="rounded-md border border-border p-3">
          <div className="text-[11px] font-bold uppercase tracking-widest text-muted-foreground">Output</div>
          <div className="mt-1 text-sm text-foreground">Pending prompt revision proposal</div>
        </div>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {rows.map(([label, value]) => (
          <div key={label} className="rounded-md border border-border p-3">
            <div className="text-[11px] font-bold uppercase tracking-widest text-muted-foreground">{label}</div>
            <div className="mt-1 break-words text-sm text-foreground" style={{ fontFamily: label === 'Reference' || label === 'Capability' ? 'var(--font-mono)' : undefined }}>
              {value}
            </div>
          </div>
        ))}
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        <pre className="max-h-64 overflow-auto rounded-md border border-border bg-muted/40 p-3 text-xs">
          {JSON.stringify(target.engine_policy_json ?? {}, null, 2)}
        </pre>
        <pre className="max-h-64 overflow-auto rounded-md border border-border bg-muted/40 p-3 text-xs">
          {JSON.stringify(target.metadata_json ?? {}, null, 2)}
        </pre>
      </div>
    </div>
  )
}

function SignalDialog({
  open,
  target,
  saving,
  onOpenChange,
  onSubmit,
}: {
  open: boolean
  target: EvolutionTarget | null
  saving: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (body: {
    signal_type: string
    source_type: string
    source_id?: string | null
    severity: string
    summary?: string | null
    payload_json: Record<string, unknown>
  }) => void
}) {
  const [signalType, setSignalType] = useState(SIGNAL_TYPES[0].value)
  const [severity, setSeverity] = useState('medium')
  const [sourceType, setSourceType] = useState('manual')
  const [sourceId, setSourceId] = useState('')
  const [summary, setSummary] = useState('')

  useEffect(() => {
    if (!open) {
      setSignalType(SIGNAL_TYPES[0].value)
      setSeverity('medium')
      setSourceType('manual')
      setSourceId('')
      setSummary('')
    }
  }, [open])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Record signal</DialogTitle>
          <DialogDescription>
            A signal is typed evidence for a target, not a keyword.
          </DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={event => {
            event.preventDefault()
            onSubmit({
              signal_type: signalType,
              source_type: sourceType.trim() || 'manual',
              source_id: sourceId.trim() || null,
              severity,
              summary: summary.trim() || null,
              payload_json: {},
            })
          }}
        >
          <div className="space-y-1.5">
            <Label>Target</Label>
            <Input value={target ? displayTargetName(target) : ''} disabled />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>Evidence type</Label>
              <Select value={signalType} onChange={setSignalType} options={SIGNAL_TYPES} />
            </div>
            <div className="space-y-1.5">
              <Label>Severity</Label>
              <Select value={severity} onChange={setSeverity} options={SIGNAL_SEVERITIES} />
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>Source type</Label>
              <Input value={sourceType} onChange={event => setSourceType(event.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label>Source ID</Label>
              <Input value={sourceId} onChange={event => setSourceId(event.target.value)} />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label>Summary</Label>
            <Textarea value={summary} onChange={event => setSummary(event.target.value)} />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
              Cancel
            </Button>
            <Button type="submit" disabled={saving || !target}>
              {saving && <Loader2 className="size-3.5 animate-spin" />}
              Save signal
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

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
