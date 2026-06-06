import { useState, useEffect, useId } from 'react'
import { Clock, Plus, Loader2, Play, Pause, Archive, ShieldCheck } from 'lucide-react'
import { toast } from 'sonner'
import { automationsApi, agentsApi } from '../../api/client'
import type { AutomationOut, AutomationTriggerType, AgentOut } from '../../types/api'
import { useSpace } from '../../contexts/SpaceContext'
import { Card, CardTitle } from '../../components/ui/card'
import { Button } from '../../components/ui/button'
import { Input } from '../../components/ui/input'
import { Badge } from '../../components/ui/badge'
import { errMsg } from '../../lib/utils'

const BROWSER_TZ = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'

const CRON_PRESETS: { label: string; expr: string }[] = [
  { label: 'Every 15 min', expr: '*/15 * * * *' },
  { label: 'Hourly', expr: '0 * * * *' },
  { label: 'Daily 9am', expr: '0 9 * * *' },
  { label: 'Weekdays 9am', expr: '0 9 * * 1-5' },
]

const fieldLabel = 'text-[11px] font-medium text-muted-foreground uppercase tracking-wider'
const selectCls = 'flex h-9 w-full rounded-md border border-border bg-input px-3 text-sm'

function fmt(dt: string | null): string {
  if (!dt) return '—'
  try { return new Date(dt).toLocaleString() } catch { return dt }
}

function cfgString(cfg: Record<string, unknown> | null, key: string): string {
  const v = cfg?.[key]
  return typeof v === 'string' ? v : ''
}

function AddAutomationForm({ agents, onAdded, canCreate }: {
  agents: AgentOut[]
  onAdded: () => void
  canCreate: boolean
}) {
  const [expanded, setExpanded] = useState(false)
  const [name, setName] = useState('')
  const [agentId, setAgentId] = useState('')
  const [triggerType, setTriggerType] = useState<AutomationTriggerType>('schedule')
  const [cron, setCron] = useState('0 9 * * *')
  const [timezone, setTimezone] = useState(BROWSER_TZ)
  const [prompt, setPrompt] = useState('')
  const [saving, setSaving] = useState(false)

  function reset() {
    setName(''); setAgentId(''); setTriggerType('schedule')
    setCron('0 9 * * *'); setTimezone(BROWSER_TZ); setPrompt(''); setExpanded(false)
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!canCreate) { toast.error('Select an operational space first'); return }
    if (!agentId) { toast.error('Pick an agent for this automation'); return }
    if (triggerType === 'schedule' && !cron.trim()) { toast.error('A cron expression is required'); return }

    const config: Record<string, unknown> = {}
    if (triggerType === 'schedule') { config.cron = cron.trim(); config.timezone = timezone.trim() || 'UTC' }
    if (prompt.trim()) config.prompt = prompt.trim()

    setSaving(true)
    try {
      await automationsApi.create({
        name: name.trim() || 'Automation',
        agent_id: agentId,
        trigger_type: triggerType,
        config_json: Object.keys(config).length ? config : undefined,
      })
      toast.success('Automation created')
      reset()
      onAdded()
    } catch (err) {
      toast.error(errMsg(err))
    } finally {
      setSaving(false)
    }
  }

  if (!expanded) {
    return (
      <Button variant="outline" size="sm" onClick={() => setExpanded(true)} disabled={!canCreate}>
        <Plus className="size-3.5 mr-1.5" />
        New automation
      </Button>
    )
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3 p-4 border border-border rounded-lg bg-accent/30">
      <div className="space-y-1.5">
        <label className={fieldLabel}>Agent</label>
        <select value={agentId} onChange={e => setAgentId(e.target.value)} className={selectCls}>
          <option value="">Select an agent…</option>
          {agents.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select>
        {agents.length === 0 && (
          <p className="text-xs text-muted-foreground">No agents yet — create one on the Agents page first.</p>
        )}
      </div>

      <div className="space-y-1.5">
        <label className={fieldLabel}>Name</label>
        <Input value={name} onChange={e => setName(e.target.value)} placeholder="Daily summary" className="text-sm" />
      </div>

      <div className="space-y-1.5">
        <label className={fieldLabel}>Trigger</label>
        <select value={triggerType} onChange={e => setTriggerType(e.target.value as AutomationTriggerType)} className={selectCls}>
          <option value="schedule">Schedule (cron)</option>
          <option value="manual">Manual only</option>
        </select>
      </div>

      {triggerType === 'schedule' && (
        <>
          <div className="space-y-1.5">
            <label className={fieldLabel}>Cron expression</label>
            <Input value={cron} onChange={e => setCron(e.target.value)} placeholder="0 9 * * *" className="font-mono text-sm" />
            <div className="flex flex-wrap gap-1.5">
              {CRON_PRESETS.map(p => (
                <button key={p.expr} type="button" onClick={() => setCron(p.expr)}
                  className="text-[11px] px-2 py-0.5 rounded border border-border hover:bg-accent">
                  {p.label}
                </button>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">min hour day month weekday — e.g. <span className="font-mono">0 9 * * 1-5</span></p>
          </div>
          <div className="space-y-1.5">
            <label className={fieldLabel}>Timezone</label>
            <Input value={timezone} onChange={e => setTimezone(e.target.value)} placeholder="UTC" className="font-mono text-sm" />
          </div>
          <div className="flex items-start gap-2 text-xs text-muted-foreground p-2 rounded-md bg-amber-500/10">
            <ShieldCheck className="size-3.5 mt-0.5 shrink-0 text-amber-600" />
            <span>Creating a schedule pre-authorizes this automation to run unattended with the agent's configured credentials. Archiving it revokes that authorization.</span>
          </div>
        </>
      )}

      <div className="space-y-1.5">
        <label className={fieldLabel}>Prompt (optional)</label>
        <textarea value={prompt} onChange={e => setPrompt(e.target.value)} rows={3}
          placeholder="What should the agent do on each run?"
          className="flex w-full rounded-md border border-border bg-input px-3 py-2 text-sm" />
      </div>

      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={saving}>{saving ? <Loader2 className="size-3.5 animate-spin" /> : 'Create'}</Button>
        <Button type="button" size="sm" variant="outline" onClick={reset}>Cancel</Button>
      </div>
    </form>
  )
}

function AutomationCard({ auto, agentName, onChanged }: {
  auto: AutomationOut
  agentName: string
  onChanged: () => void
}) {
  const [busy, setBusy] = useState(false)
  const isSchedule = auto.trigger_type === 'schedule'
  const archived = auto.status === 'archived'

  async function act(fn: () => Promise<unknown>, ok: string) {
    setBusy(true)
    try { await fn(); toast.success(ok); onChanged() }
    catch (err) { toast.error(errMsg(err)) }
    finally { setBusy(false) }
  }

  return (
    <Card>
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2 flex-wrap">
          <CardTitle>{auto.name}</CardTitle>
          <Badge variant={isSchedule ? 'default' : 'muted'} className="text-[10px]">{auto.trigger_type}</Badge>
          {auto.status === 'active' && <Badge variant="muted" className="text-[10px]">active</Badge>}
          {auto.status === 'paused' && <Badge variant="muted" className="text-[10px]">paused</Badge>}
          {archived && <Badge variant="muted" className="text-[10px]">archived</Badge>}
        </div>
        <span className="text-[10px] font-mono text-muted-foreground">{agentName}</span>
      </div>

      {isSchedule && (
        <div className="text-xs text-muted-foreground space-y-0.5 mb-3">
          <p>Cron: <span className="font-mono text-foreground">{cfgString(auto.config_json, 'cron') || '—'}</span> <span className="font-mono">({cfgString(auto.config_json, 'timezone') || 'UTC'})</span></p>
          <p>Next run: <span className="text-foreground">{fmt(auto.next_run_at)}</span></p>
          <p>Last fired: {fmt(auto.last_fired_at)}</p>
        </div>
      )}
      {cfgString(auto.config_json, 'prompt') && (
        <p className="text-xs mb-3 line-clamp-2"><span className="text-muted-foreground">Prompt: </span>{cfgString(auto.config_json, 'prompt')}</p>
      )}

      {!archived && (
        <div className="flex gap-2">
          <Button size="sm" variant="outline" disabled={busy}
            onClick={() => act(() => automationsApi.fire(auto.id, { prompt: cfgString(auto.config_json, 'prompt') || undefined }), 'Run queued')}>
            <Play className="size-3.5 mr-1" /> Run now
          </Button>
          {auto.status === 'active' ? (
            <Button size="sm" variant="outline" disabled={busy}
              onClick={() => act(() => automationsApi.update(auto.id, { status: 'paused' }), 'Paused')}>
              <Pause className="size-3.5 mr-1" /> Pause
            </Button>
          ) : (
            <Button size="sm" variant="outline" disabled={busy}
              onClick={() => act(() => automationsApi.update(auto.id, { status: 'active' }), 'Resumed')}>
              <Play className="size-3.5 mr-1" /> Resume
            </Button>
          )}
          <Button size="sm" variant="outline" disabled={busy} className="text-red-500"
            onClick={() => act(() => automationsApi.update(auto.id, { status: 'archived' }), 'Archived')}>
            <Archive className="size-3.5" />
          </Button>
        </div>
      )}
    </Card>
  )
}

export default function AutomationsPage() {
  const { activeSpaceId, activeSpaceName } = useSpace()
  const [autos, setAutos] = useState<AutomationOut[]>([])
  const [agents, setAgents] = useState<AgentOut[]>([])
  const [loading, setLoading] = useState(true)
  const headingId = useId()

  useEffect(() => { loadAll() }, [activeSpaceId])

  async function loadAll() {
    setLoading(true)
    try {
      if (!activeSpaceId) { setAutos([]); setAgents([]); return }
      const [a, ag] = await Promise.all([automationsApi.list(), agentsApi.list()])
      setAutos(a)
      setAgents(ag)
    } catch (err) {
      toast.error(errMsg(err))
    } finally {
      setLoading(false)
    }
  }

  const agentName = (id: string) => agents.find(a => a.id === id)?.name ?? id.slice(0, 8)
  const visible = autos.filter(a => a.status !== 'archived')

  return (
    <div className="p-6 space-y-6 max-w-2xl" id={headingId}>
      <div className="flex items-center gap-4 pb-4 border-b border-border">
        <div className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0" style={{ background: 'color-mix(in oklch, var(--primary) 12%, transparent)', border: '1px solid color-mix(in oklch, var(--primary) 35%, transparent)' }}>
          <Clock className="size-5 text-accent-foreground" />
        </div>
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Automations</h1>
          <p className="text-sm text-muted-foreground">Schedule an agent to run on a cron, or keep it manual-only.</p>
          <p className="text-xs text-muted-foreground">Viewing: {activeSpaceName ?? activeSpaceId ?? 'No operational space selected'}</p>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-12 text-muted-foreground">
          <Loader2 className="size-5 animate-spin mr-2" /> Loading…
        </div>
      ) : (
        <div className="space-y-4">
          <AddAutomationForm agents={agents} onAdded={loadAll} canCreate={Boolean(activeSpaceId)} />
          {visible.length === 0 ? (
            <Card>
              <p className="text-sm text-muted-foreground p-4">
                {activeSpaceId
                  ? 'No automations yet. Create one to run an agent on a schedule.'
                  : 'Select an operational space to manage automations.'}
              </p>
            </Card>
          ) : (
            visible.map(a => (
              <AutomationCard key={a.id} auto={a} agentName={agentName(a.agent_id)} onChanged={loadAll} />
            ))
          )}
        </div>
      )}
    </div>
  )
}
