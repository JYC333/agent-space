import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { Terminal } from 'lucide-react'
import { cliAdaptersApi } from '../../api/client'
import type { CLIStatus, CLIAdapterConfig } from '../../types/api'
import { Card, CardTitle } from '../../components/ui/card'
import { Button } from '../../components/ui/button'
import { Badge } from '../../components/ui/badge'
import { Skeleton } from '../../components/ui/skeleton'
import { Select } from '../../components/ui/select'
import { Input } from '../../components/ui/input'
import { errMsg } from '../../lib/utils'
import CLILoginSection from './CLILoginSection'
import ClaudeUsageCard, { type ClaudeUsageCardHandle } from './ClaudeUsageCard'

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

// ── Single detected adapter card ──────────────────────────────────────────

function DetectionCard({ status }: { status: CLIStatus }) {
  const caps = status.capabilities

  return (
    <Card className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="font-medium">{status.adapter_id}</span>
          {status.version && (
            <span className="text-xs text-muted-foreground font-mono">{status.version}</span>
          )}
        </div>
        <Badge variant={status.available ? 'default' : 'secondary'}>
          {status.available ? 'available' : 'not found'}
        </Badge>
      </div>

      {status.status_message && (
        <p className="text-xs text-muted-foreground">{status.status_message}</p>
      )}

      {status.executable_path && (
        <p className="text-xs font-mono text-muted-foreground">{status.executable_path}</p>
      )}

      {caps && status.available && (
        <div className="flex flex-wrap gap-1 pt-1">
          {caps.supportsHeadlessRun     && <span className="text-xs bg-muted px-2 py-0.5 rounded">headless</span>}
          {caps.supportsInteractiveRun  && <span className="text-xs bg-muted px-2 py-0.5 rounded">interactive</span>}
          {caps.supportsModelOverride   && <span className="text-xs bg-muted px-2 py-0.5 rounded">model-override</span>}
          {caps.supportsPatchOutput     && <span className="text-xs bg-muted px-2 py-0.5 rounded">patch-output</span>}
          <span className="text-xs bg-muted px-2 py-0.5 rounded">ctx: {caps.contextFileType}</span>
        </div>
      )}
    </Card>
  )
}

// ── Per-space config row ──────────────────────────────────────────────────

function ConfigRow({
  config,
  onQuotaChange,
  onToggle,
  onDelete,
}: {
  config: CLIAdapterConfig
  onQuotaChange: (id: string, status: string) => void
  onToggle: (id: string, enabled: boolean) => void
  onDelete: (id: string) => void
}) {
  return (
    <div className="flex items-center gap-3 py-2 border-b last:border-0">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-medium text-sm truncate">{config.display_name}</span>
          <span className="text-xs text-muted-foreground font-mono">{config.adapter_id}</span>
          {!config.enabled && <Badge variant="secondary">disabled</Badge>}
        </div>
        {config.notes && (
          <p className="text-xs text-muted-foreground truncate mt-0.5">{config.notes}</p>
        )}
      </div>

      <div className="flex items-center gap-2 shrink-0">
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
          onClick={() => onToggle(config.id, !config.enabled)}
          className="text-xs h-7"
        >
          {config.enabled ? 'disable' : 'enable'}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onDelete(config.id)}
          className="text-xs h-7 text-destructive"
        >
          remove
        </Button>
      </div>
    </div>
  )
}

// ── Add config form ───────────────────────────────────────────────────────

function AddConfigForm({ onAdded }: { onAdded: () => void }) {
  const [adapterId, setAdapterId] = useState('claude_code')
  const [displayName, setDisplayName] = useState('')
  const [notes, setNotes] = useState('')
  const [saving, setSaving] = useState(false)

  const ADAPTER_OPTIONS = [
    { value: 'claude_code', label: 'Claude Code' },
    { value: 'codex_cli',   label: 'Codex CLI' },
    { value: 'opencode',    label: 'OpenCode' },
    { value: 'gemini_cli',  label: 'Gemini CLI' },
    { value: 'echo',        label: 'Echo (test)' },
    { value: 'custom',      label: 'Custom' },
  ]

  async function save() {
    if (!displayName.trim()) { toast.error('Display name required'); return }
    setSaving(true)
    try {
      await cliAdaptersApi.createConfig({
        adapter_id: adapterId as any,
        display_name: displayName.trim(),
        notes: notes.trim() || undefined,
        quota_status: 'unknown',
        enabled: true,
      })
      toast.success('CLI tool added')
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
      <p className="text-sm font-medium">Add CLI tool</p>
      <div className="flex gap-2">
        <Select
          className="w-36"
          value={adapterId}
          options={ADAPTER_OPTIONS}
          onChange={v => setAdapterId(v)}
          dropUp
        />
        <Input
          className="flex-1"
          placeholder="Display name (e.g. My Claude Code)"
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
      <Button size="sm" onClick={save} disabled={saving || !displayName.trim()}>
        {saving ? 'Saving…' : 'Add'}
      </Button>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────

export default function CLIStatusPage() {
  const [detection, setDetection] = useState<CLIStatus[]>([])
  const [configs, setConfigs]     = useState<CLIAdapterConfig[]>([])
  const [detecting, setDetecting] = useState(false)
  const [loadingConfigs, setLoadingConfigs] = useState(true)
  const usageCardRef = useRef<ClaudeUsageCardHandle>(null)

  async function loadConfigs() {
    try {
      const data = await cliAdaptersApi.listConfigs()
      setConfigs(data)
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setLoadingConfigs(false)
    }
  }

  async function runDetection() {
    setDetecting(true)
    try {
      const data = await cliAdaptersApi.detectAll()
      setDetection(data)
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setDetecting(false)
    }
  }

  useEffect(() => { loadConfigs() }, [])

  async function handleQuotaChange(id: string, status: string) {
    try {
      const updated = await cliAdaptersApi.updateConfig(id, { quota_status: status as any })
      setConfigs(prev => prev.map(c => c.id === id ? updated : c))
    } catch (e) {
      toast.error(errMsg(e))
    }
  }

  async function handleToggle(id: string, enabled: boolean) {
    try {
      const updated = await cliAdaptersApi.updateConfig(id, { enabled })
      setConfigs(prev => prev.map(c => c.id === id ? updated : c))
    } catch (e) {
      toast.error(errMsg(e))
    }
  }

  async function handleDelete(id: string) {
    try {
      await cliAdaptersApi.deleteConfig(id)
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
          <h1 className="text-xl font-semibold tracking-tight">CLI Tools</h1>
          <p className="text-sm text-muted-foreground">Detect installed CLI adapters and manage monthly quota.</p>
        </div>
      </div>

      {/* Claude Code usage stats */}
      <ClaudeUsageCard ref={usageCardRef} />

      {/* Credential login panel — refreshes quota after successful login */}
      <CLILoginSection onLoginSuccess={() => usageCardRef.current?.refreshQuota()} />

      {/* Detection panel */}
      <Card>
        <div className="flex items-center justify-between mb-4">
          <CardTitle>CLI Tool Status</CardTitle>
          <Button size="sm" onClick={runDetection} disabled={detecting}>
            {detecting ? 'Detecting…' : 'Detect all'}
          </Button>
        </div>

        {detection.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Click <em>Detect all</em> to probe which CLI tools are installed on this host.
          </p>
        ) : (
          <div className="space-y-2">
            {detection.map(s => <DetectionCard key={s.adapter_id} status={s} />)}
          </div>
        )}
      </Card>

      {/* Per-space quota board */}
      <Card>
        <CardTitle className="mb-4">Monthly Quota Board</CardTitle>

        {loadingConfigs ? (
          <div className="space-y-2">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        ) : configs.length === 0 ? (
          <p className="text-sm text-muted-foreground mb-4">
            No CLI tools configured yet. Add one below.
          </p>
        ) : (
          <div className="mb-4">
            {configs.map(c => (
              <ConfigRow
                key={c.id}
                config={c}
                onQuotaChange={handleQuotaChange}
                onToggle={handleToggle}
                onDelete={handleDelete}
              />
            ))}
          </div>
        )}

        <AddConfigForm onAdded={loadConfigs} />
      </Card>
    </div>
  )
}
