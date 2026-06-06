import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Gauge, Power, Radar, Terminal, Trash2 } from 'lucide-react'
import { runtimeAdaptersApi } from '../../api/client'
import { useSpace } from '../../contexts/SpaceContext'
import type { RuntimeAdapterStatus, RuntimeAdapter, RuntimeAdapterSpec, RuntimeAdapterType } from '../../types/api'
import { Card, CardTitle } from '../../components/ui/card'
import { Button } from '../../components/ui/button'
import { Badge } from '../../components/ui/badge'
import { Skeleton } from '../../components/ui/skeleton'
import { Select } from '../../components/ui/select'
import { Input } from '../../components/ui/input'
import { errMsg } from '../../lib/utils'
import CLILoginSection from './CLILoginSection'

// ── Quota badge ───────────────────────────────────────────────────────────

const QUOTA_CLASSES: Record<string, string> = {
  enough:    'bg-emerald-500/15 text-emerald-600',
  medium:    'bg-yellow-500/15 text-yellow-600',
  low:       'bg-orange-500/15 text-orange-600',
  exhausted: 'bg-red-500/15 text-red-600',
  unknown:   'bg-muted text-muted-foreground',
}

function QuotaBadge({ status }: { status: string }) {
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${QUOTA_CLASSES[status] ?? QUOTA_CLASSES.unknown}`}>
      {status}
    </span>
  )
}

const QUOTA_OPTIONS = ['enough', 'medium', 'low', 'exhausted', 'unknown'] as const
const HEALTH_CLASSES: Record<string, string> = {
  ok: 'bg-emerald-500/15 text-emerald-600',
  warning: 'bg-yellow-500/15 text-yellow-600',
  error: 'bg-red-500/15 text-red-600',
  unimplemented: 'bg-muted text-muted-foreground',
  disabled: 'bg-muted text-muted-foreground',
  unknown: 'bg-muted text-muted-foreground',
}

function HealthBadge({ status }: { status: string }) {
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${HEALTH_CLASSES[status] ?? HEALTH_CLASSES.unknown}`}>
      {status}
    </span>
  )
}

// ── Single detected adapter card ──────────────────────────────────────────

function DetectionCard({ status }: { status: RuntimeAdapterStatus }) {
  return (
    <Card className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="font-medium">{status.adapter_type}</span>
          {status.configured_count > 0 && (
            <span className="text-xs text-muted-foreground">{status.configured_count} configured</span>
          )}
          {status.version && (
            <span className="text-xs text-muted-foreground font-mono">{status.version}</span>
          )}
        </div>
        <Badge variant={status.installed && status.implementation_status === 'implemented' ? 'default' : 'secondary'}>
          {status.implementation_status === 'implemented' ? (status.installed ? 'installed' : 'not found') : status.implementation_status}
        </Badge>
      </div>

      {status.warnings.map(w => <p key={w} className="text-xs text-muted-foreground">{w}</p>)}

      {status.executable_path && (
        <p className="text-xs font-mono text-muted-foreground">{status.executable_path}</p>
      )}

      {status.installed && (
        <div className="flex flex-wrap gap-1 pt-1">
          {status.supports_headless     && <span className="text-xs bg-muted px-2 py-0.5 rounded">headless</span>}
          {status.supports_interactive  && <span className="text-xs bg-muted px-2 py-0.5 rounded">interactive</span>}
          {status.supports_model_override && <span className="text-xs bg-muted px-2 py-0.5 rounded">model override</span>}
          {status.credential_required && <span className="text-xs bg-muted px-2 py-0.5 rounded">{status.credential_ready ? 'credential ready' : 'credential missing'}</span>}
          <span className="text-xs bg-muted px-2 py-0.5 rounded">usage: {status.usage_accuracy}</span>
          <span className="text-xs bg-muted px-2 py-0.5 rounded">sandbox: {status.minimum_sandbox_level}</span>
        </div>
      )}
    </Card>
  )
}

// ── Per-space config row ──────────────────────────────────────────────────

function ConfigRow({
  config,
  spec,
  status,
  usage,
  onQuotaChange,
  onReadUsage,
  onProbe,
  onToggle,
  onDelete,
}: {
  config: RuntimeAdapter
  spec?: RuntimeAdapterSpec
  status?: RuntimeAdapterStatus
  usage?: Record<string, unknown>
  onQuotaChange: (id: string, status: string) => void
  onReadUsage: (id: string) => void
  onProbe: (id: string) => void
  onToggle: (id: string, enabled: boolean) => void
  onDelete: (id: string) => void
}) {
  const isPlanned = spec?.implementation_status && spec.implementation_status !== 'implemented'
  return (
    <div className="py-3 border-b last:border-0 space-y-2">
    <div className="flex items-center gap-3">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-medium text-sm truncate">{config.name}</span>
          <span className="text-xs text-muted-foreground font-mono">{config.adapter_type}</span>
          {!config.enabled && <Badge variant="secondary">disabled</Badge>}
          {isPlanned && <Badge variant="secondary">not executable</Badge>}
        </div>
        {config.notes && (
          <p className="text-xs text-muted-foreground truncate mt-0.5">{config.notes}</p>
        )}
        {usage && (
          <p className="text-xs text-muted-foreground mt-0.5">
            usage {String(usage.usage_accuracy ?? 'unknown')} · runs {String(usage.run_count ?? 0)} · seconds {String(usage.runtime_seconds ?? 0)}
          </p>
        )}
        {status && (
          <div className="flex flex-wrap gap-1 mt-1">
            <span className="text-xs bg-muted px-2 py-0.5 rounded">{status.installed ? 'installed' : 'not found'}</span>
            {status.credential_required && (
              <span className="text-xs bg-muted px-2 py-0.5 rounded">
                {status.credential_ready ? 'credential ready' : 'credential missing'}
              </span>
            )}
            <span className="text-xs bg-muted px-2 py-0.5 rounded">usage: {status.usage_accuracy}</span>
          </div>
        )}
      </div>

      <div className="flex items-center gap-2 shrink-0">
        <HealthBadge status={config.health_status} />
        <Select
          size="sm"
          className="w-28"
          value={config.quota_status}
          options={QUOTA_OPTIONS.map(o => ({ value: o, label: o }))}
          onChange={v => onQuotaChange(config.id, v)}
          dropUp
        />
        <QuotaBadge status={config.quota_status} />
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onReadUsage(config.id)}
          className="text-xs h-7"
        >
          <Gauge className="size-3.5" />
          read usage
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onProbe(config.id)}
          className="text-xs h-7"
        >
          <Radar className="size-3.5" />
          probe
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onToggle(config.id, !config.enabled)}
          className="text-xs h-7"
        >
          <Power className="size-3.5" />
          {config.enabled ? 'disable' : 'enable'}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onDelete(config.id)}
          className="text-xs h-7 text-destructive"
        >
          <Trash2 className="size-3.5" />
          remove
        </Button>
      </div>
    </div>
    </div>
  )
}

// ── Add config form ───────────────────────────────────────────────────────

function AddConfigForm({ onAdded, canCreate, catalog }: { onAdded: () => void; canCreate: boolean; catalog: RuntimeAdapterSpec[] }) {
  const implemented = catalog.filter(spec => spec.implementation_status === 'implemented')
  const [adapterType, setAdapterType] = useState(implemented[0]?.adapter_type ?? 'echo')
  const [displayName, setDisplayName] = useState('')
  const [notes, setNotes] = useState('')
  const [saving, setSaving] = useState(false)

  const selectedSpec = catalog.find(spec => spec.adapter_type === adapterType)
  const ADAPTER_OPTIONS = implemented.map(spec => ({
    value: spec.adapter_type,
    label: spec.display_name,
  }))

  async function save() {
    const name = displayName.trim() || selectedSpec?.display_name || ''
    if (!name) { toast.error('Display name required'); return }
    if (selectedSpec?.implementation_status !== 'implemented') { toast.error('Planned adapters are not executable yet'); return }
    if (!canCreate) { toast.error('Select an operational space before adding a runtime adapter'); return }
    setSaving(true)
    try {
      await runtimeAdaptersApi.create({
        adapter_type: adapterType as any,
        name,
        notes: notes.trim() || undefined,
        health_status: 'unknown',
        quota_status: 'unknown',
        enabled: true,
      })
      toast.success('Runtime adapter added')
      setDisplayName('')
      setNotes('')
      onAdded()
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="border rounded-lg p-4 space-y-3 bg-muted/30">
      <p className="text-sm font-medium">Add runtime adapter</p>
      <div className="flex gap-2">
        <Select
          className="w-36"
          value={adapterType}
          options={ADAPTER_OPTIONS}
          onChange={v => {
            const next = v as RuntimeAdapterType
            setAdapterType(next)
            const spec = catalog.find(item => item.adapter_type === next)
            setDisplayName(spec?.display_name ?? '')
          }}
          dropUp
        />
        <Input
          className="flex-1"
          placeholder={selectedSpec?.display_name ?? 'Display name'}
          value={displayName}
          onChange={e => setDisplayName(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && save()}
        />
      </div>
      <Input
        placeholder="Notes (optional)"
        value={notes}
        onChange={e => setNotes(e.target.value)}
      />
      {selectedSpec?.implementation_status !== 'implemented' && (
        <p className="text-xs text-muted-foreground">This adapter is planned and cannot be enabled yet.</p>
      )}
      <Button size="sm" onClick={save} disabled={saving || !canCreate || selectedSpec?.implementation_status !== 'implemented'}>
        {saving ? 'Saving…' : 'Add'}
      </Button>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────

export default function RuntimeAdaptersPage() {
  const { activeSpaceId, activeSpaceName } = useSpace()
  const [detection, setDetection] = useState<RuntimeAdapterStatus[]>([])
  const [configs, setConfigs]     = useState<RuntimeAdapter[]>([])
  const [catalog, setCatalog] = useState<RuntimeAdapterSpec[]>([])
  const [usageById, setUsageById] = useState<Record<string, Record<string, unknown>>>({})
  const [statusById, setStatusById] = useState<Record<string, RuntimeAdapterStatus>>({})
  const [detecting, setDetecting] = useState(false)
  const [loadingConfigs, setLoadingConfigs] = useState(true)

  async function loadCatalog() {
    try {
      setCatalog(await runtimeAdaptersApi.catalog())
    } catch (e) {
      toast.error(errMsg(e))
    }
  }

  async function loadConfigs() {
    if (!activeSpaceId) {
      setConfigs([])
      setLoadingConfigs(false)
      return
    }
    setLoadingConfigs(true)
    try {
      const data = await runtimeAdaptersApi.list()
      setConfigs(data)
      const statusEntries = await Promise.all(data.map(async config => {
        try {
          return [config.id, await runtimeAdaptersApi.status(config.id)] as const
        } catch {
          return null
        }
      }))
      setStatusById(Object.fromEntries(statusEntries.filter(Boolean) as Array<readonly [string, RuntimeAdapterStatus]>))
      const usageEntries = await Promise.all(data.map(async config => {
        try {
          return [config.id, await runtimeAdaptersApi.usage(config.id)] as const
        } catch {
          return null
        }
      }))
      setUsageById(Object.fromEntries(usageEntries.filter(Boolean) as Array<readonly [string, Record<string, unknown>]>))
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setLoadingConfigs(false)
    }
  }

  async function runDetection() {
    setDetecting(true)
    try {
      const data = await runtimeAdaptersApi.detectAll()
      setDetection(data)
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setDetecting(false)
    }
  }

  useEffect(() => { loadConfigs() }, [activeSpaceId])
  useEffect(() => { loadCatalog() }, [])

  async function handleQuotaChange(id: string, status: string) {
    if (!activeSpaceId) {
      toast.error('Select an operational space before updating usage status')
      return
    }
    try {
      const updated = await runtimeAdaptersApi.update(id, { quota_status: status as any })
      setConfigs(prev => prev.map(c => c.id === id ? updated : c))
    } catch (e) {
      toast.error(errMsg(e))
    }
  }

  async function handleReadUsage(id: string) {
    try {
      const usage = await runtimeAdaptersApi.usage(id)
      setUsageById(prev => ({ ...prev, [id]: usage }))
    } catch (e) {
      toast.error(errMsg(e))
    }
  }

  async function handleProbe(id: string) {
    try {
      const status = await runtimeAdaptersApi.probe(id)
      setStatusById(prev => ({ ...prev, [id]: status }))
      toast.success('Probe complete')
    } catch (e) {
      toast.error(errMsg(e))
    }
  }

  async function handleToggle(id: string, enabled: boolean) {
    if (!activeSpaceId) {
      toast.error('Select an operational space before updating runtime adapters')
      return
    }
    try {
      const updated = await runtimeAdaptersApi.update(id, { enabled })
      setConfigs(prev => prev.map(c => c.id === id ? updated : c))
    } catch (e) {
      toast.error(errMsg(e))
    }
  }

  async function handleDelete(id: string) {
    if (!activeSpaceId) {
      toast.error('Select an operational space before removing runtime adapters')
      return
    }
    try {
      await runtimeAdaptersApi.delete(id)
      setConfigs(prev => prev.filter(c => c.id !== id))
      toast.success('Removed')
    } catch (e) {
      toast.error(errMsg(e))
    }
  }

  return (
    <div className="p-6 space-y-6">
      {/* Page header */}
      <div className="flex items-center gap-4 pb-4 border-b border-border">
        <div
          className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
          style={{
            background: 'color-mix(in oklch, var(--primary) 12%, transparent)',
            border: '1px solid color-mix(in oklch, var(--primary) 35%, transparent)',
          }}
        >
          <Terminal className="size-5 text-accent-foreground" />
        </div>
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Runtime Adapters</h1>
          <p className="text-sm text-muted-foreground">Detect installed runtimes, credential profiles, and usage status.</p>
          <p className="text-xs text-muted-foreground">
            Viewing: {activeSpaceName ?? activeSpaceId ?? 'No operational space selected'}
          </p>
        </div>
      </div>

      {/* Credential login panel */}
      {activeSpaceId ? (
        <CLILoginSection key={activeSpaceId} />
      ) : (
        <Card>
          <CardTitle>Runtime Credentials</CardTitle>
          <p className="text-sm text-muted-foreground mt-2">Select an operational space to manage runtime credentials.</p>
        </Card>
      )}

      {/* Detection panel */}
      <Card>
        <div className="flex items-center justify-between mb-4">
          <CardTitle>Host Detection</CardTitle>
          <Button size="sm" onClick={runDetection} disabled={detecting}>
            {detecting ? 'Detecting…' : 'Detect host'}
          </Button>
        </div>

        {detection.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Click <em>Detect host</em> to probe which runtime adapters are installed on this host.
          </p>
        ) : (
          <div className="space-y-2">
            {detection.map(s => <DetectionCard key={s.adapter_type} status={s} />)}
          </div>
        )}
      </Card>

      {/* Configured runtime instances */}
      <Card>
        <CardTitle className="mb-4">Configured Runtime Instances</CardTitle>

        {loadingConfigs ? (
          <div className="space-y-2">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        ) : configs.length === 0 ? (
          <p className="text-sm text-muted-foreground mb-4">
            {activeSpaceId
              ? 'No runtime adapters configured yet. Add one below.'
              : 'Select an operational space to manage configured runtime adapters.'}
          </p>
        ) : (
          <div className="mb-4">
            {configs.map(c => (
              <ConfigRow
                key={c.id}
                config={c}
                spec={catalog.find(spec => spec.adapter_type === c.adapter_type)}
                status={statusById[c.id]}
                usage={usageById[c.id]}
                onQuotaChange={handleQuotaChange}
                onReadUsage={handleReadUsage}
                onProbe={handleProbe}
                onToggle={handleToggle}
                onDelete={handleDelete}
              />
            ))}
          </div>
        )}

        <AddConfigForm onAdded={loadConfigs} canCreate={Boolean(activeSpaceId)} catalog={catalog} />
      </Card>

      <Card>
        <CardTitle className="mb-4">Catalog</CardTitle>
        <div className="grid gap-2 md:grid-cols-2">
          {catalog.filter(spec => spec.implementation_status !== 'implemented').map(spec => (
            <div key={spec.adapter_type} className="border rounded-md p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium">{spec.display_name}</span>
                <Badge variant="secondary">{spec.implementation_status}</Badge>
              </div>
              <p className="text-xs text-muted-foreground mt-1 font-mono">{spec.adapter_type}</p>
            </div>
          ))}
        </div>
      </Card>
    </div>
  )
}
