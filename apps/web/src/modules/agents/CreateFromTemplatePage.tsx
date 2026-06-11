import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useSpaceNavigate as useNavigate, SpaceLink as Link } from '../../core/spaceNav'
import { ChevronDown, ChevronRight, Loader2, Plus } from 'lucide-react'
import { toast } from 'sonner'
import { agentTemplatesApi, providersApi, type ModelProviderOut } from '../../api/client'
import type { AgentTemplateOut, AgentTemplateVersionOut, CreateAgentFromTemplateBody } from '../../types/api'
import { useSpace } from '../../contexts/SpaceContext'
import { Button } from '../../components/ui/button'
import { Input } from '../../components/ui/input'
import { Textarea } from '../../components/ui/textarea'
import { Card, CardTitle } from '../../components/ui/card'
import { Badge } from '../../components/ui/badge'
import { errMsg } from '../../lib/utils'
import { SafetyView } from './ConfigCards'
import {
  allowedInputContexts, defaultInputContexts, inputContextLabel,
  allowedOutputTypes, outputTypeLabel, isMemoryOutput,
  buildContextPolicy, buildOutputPolicy,
} from './policyMap'

const CREATE_NOTE: Record<string, string> = {
  activity_reflector: 'This agent processes captures / activity records into typed proposals and a reflection summary for review.',
}

function Toggle({ checked, onChange, label, note }: { checked: boolean; onChange: (v: boolean) => void; label: string; note?: string }) {
  return (
    <label className="flex items-center justify-between gap-2 py-1.5 text-sm cursor-pointer">
      <span>{label}{note && <span className="text-xs text-muted-foreground ml-2">{note}</span>}</span>
      <input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} />
    </label>
  )
}

export default function CreateFromTemplatePage() {
  const { templateId } = useParams()
  const navigate = useNavigate()
  const { activeSpaceId } = useSpace()
  const [template, setTemplate] = useState<AgentTemplateOut | null>(null)
  const [version, setVersion] = useState<AgentTemplateVersionOut | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [advancedOpen, setAdvancedOpen] = useState(false)

  // Normal parameters.
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [systemPrompt, setSystemPrompt] = useState('')
  const [scheduleMode, setScheduleMode] = useState<'manual' | 'daily' | 'cron'>('manual')
  const [dailyHour, setDailyHour] = useState('08')
  const [cron, setCron] = useState('0 8 * * *')
  const [scheduleEnabled, setScheduleEnabled] = useState(false)
  const [defaultProvider, setDefaultProvider] = useState<ModelProviderOut | null>(null)

  // Advanced (configurable) parameters — initialised from the template defaults.
  // Both are keyed by the template's product-level context / output ids.
  const [inputs, setInputs] = useState<Record<string, boolean>>({})
  const [outputs, setOutputs] = useState<Record<string, boolean>>({})
  const [maxTokens, setMaxTokens] = useState('')
  const [temperature, setTemperature] = useState('')

  useEffect(() => {
    if (!templateId) return
    setLoading(true)
    providersApi.list()
      .then(list => setDefaultProvider(list.find(p => p.is_default && p.enabled) ?? null))
      .catch(() => setDefaultProvider(null))
    agentTemplatesApi.get(templateId)
      .then(async t => {
        setTemplate(t)
        setName(t.name)
        setDescription(t.description ?? '')
        if (t.current_version_id) {
          const v = await agentTemplatesApi.getVersion(t.id, t.current_version_id)
          setVersion(v)
          setSystemPrompt(v.system_prompt ?? '')
          const enabledCtx = new Set(defaultInputContexts(v))
          setInputs(Object.fromEntries(allowedInputContexts(v).map(id => [id, enabledCtx.has(id)])))
          setOutputs(Object.fromEntries(allowedOutputTypes(v).map(id => [id, true])))
          const mc = v.model_config_json as Record<string, unknown>
          setMaxTokens(typeof mc.max_tokens === 'number' ? String(mc.max_tokens) : '')
          setTemperature(typeof mc.temperature === 'number' ? String(mc.temperature) : '')
          // Schedule defaults.
          const sd = v.schedule_defaults_json as Record<string, unknown>
          const cronStr = typeof sd.cron === 'string' ? sd.cron : ''
          setScheduleEnabled(sd.enabled === true)
          const daily = /^0 (\d{1,2}) \* \* \*$/.exec(cronStr)
          if (daily) { setScheduleMode('daily'); setDailyHour(daily[1].padStart(2, '0')); setCron(cronStr) }
          else if (cronStr) { setScheduleMode('cron'); setCron(cronStr) }
          else setScheduleMode('manual')
        }
      })
      .catch(err => toast.error(errMsg(err)))
      .finally(() => setLoading(false))
  }, [templateId])

  const hasDefaultModel = Boolean(defaultProvider?.default_model)

  function buildScheduleConfig(): Record<string, unknown> {
    if (scheduleMode === 'manual') return { enabled: false, cron: null }
    if (scheduleMode === 'daily') return { enabled: scheduleEnabled, cron: `0 ${Number(dailyHour)} * * *` }
    return { enabled: scheduleEnabled, cron }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!templateId || !version) return
    if (!activeSpaceId) { toast.error('Select an operational space'); return }
    if (!hasDefaultModel) { toast.error('Set a default model provider before creating an agent'); return }
    setSaving(true)
    try {
      const baseModel = version.model_config_json as Record<string, unknown>
      const cfg: Record<string, unknown> = { ...baseModel }
      delete cfg.model // model stays "system default" — resolved server-side
      if (maxTokens.trim()) cfg.max_tokens = Number(maxTokens)
      if (temperature.trim()) cfg.temperature = Number(temperature)
      else delete cfg.temperature

      const enabledInputs = Object.entries(inputs).filter(([, on]) => on).map(([k]) => k)
      const enabledOutputs = Object.entries(outputs).filter(([, on]) => on).map(([k]) => k)
      const body: CreateAgentFromTemplateBody = {
        name: name.trim() || undefined,
        description: description.trim() || null,
        model_config_json: cfg,
        schedule_config_json: buildScheduleConfig(),
        context_policy_json: buildContextPolicy(version.context_policy_json as Record<string, unknown>, enabledInputs),
        output_policy_json: buildOutputPolicy(version.output_policy_json as Record<string, unknown>, enabledOutputs),
      }
      if (systemPrompt.trim() && systemPrompt.trim() !== (version.system_prompt ?? '')) {
        body.system_prompt = systemPrompt.trim()
      }
      const created = await agentTemplatesApi.createAgent(templateId, body)
      toast.success('Agent created from template')
      navigate(`/agents/${created.id}`)
    } catch (err) {
      toast.error(errMsg(err))
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <div className="p-6 flex items-center gap-2 text-muted-foreground"><Loader2 className="size-4 animate-spin" /> Loading…</div>
  if (!template) return <div className="p-6 text-muted-foreground">Template not found.</div>

  // Live safety preview reflecting current edits (memory/tool stay locked server-side).
  const previewVersion = version && {
    context_policy_json: buildContextPolicy(
      version.context_policy_json as Record<string, unknown>,
      Object.entries(inputs).filter(([, on]) => on).map(([k]) => k),
    ),
    output_policy_json: buildOutputPolicy(
      version.output_policy_json as Record<string, unknown>,
      Object.entries(outputs).filter(([, on]) => on).map(([k]) => k),
    ),
    memory_policy_json: version.memory_policy_json,
    tool_policy_json: version.tool_policy_json,
  }

  return (
    <div className="p-6 max-w-2xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Use template: {template.name}</h1>
        <p className="text-sm text-muted-foreground">
          Creates an independent agent by copying this template. Defaults below come from the template;
          tweak them as needed. Later template updates won't change this agent.
        </p>
        {template.key && CREATE_NOTE[template.key] && (
          <p className="mt-2 text-sm rounded-md border border-border bg-accent/30 px-3 py-2">{CREATE_NOTE[template.key]}</p>
        )}
      </div>

      <form onSubmit={handleSubmit} className="space-y-6">
        <Card className="p-4 space-y-4">
          <CardTitle>Agent</CardTitle>
          <div className="space-y-1.5">
            <label className="text-[11px] font-medium text-muted-foreground uppercase">Name</label>
            <Input value={name} onChange={e => setName(e.target.value)} required />
          </div>
          <div className="space-y-1.5">
            <label className="text-[11px] font-medium text-muted-foreground uppercase">Description</label>
            <Input value={description} onChange={e => setDescription(e.target.value)} />
          </div>
          {version?.system_prompt != null && (
            <div className="space-y-1.5">
              <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">System prompt</label>
              <Textarea value={systemPrompt} onChange={e => setSystemPrompt(e.target.value)} rows={3} />
            </div>
          )}
          <div className="space-y-1.5">
            <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Model</label>
            {hasDefaultModel ? (
              <p className="text-sm">
                <span className="font-mono">{defaultProvider?.default_model}</span>{' '}
                <span className="text-muted-foreground">· system default ({defaultProvider?.name})</span>
              </p>
            ) : (
              <div className="space-y-2 p-3 rounded-md border border-dashed border-border text-sm">
                <p className="text-muted-foreground">
                  No system default model is set. Set a default provider (and mark it default) before creating an agent.
                </p>
                <Button asChild size="sm" type="button">
                  <Link to="/providers"><Plus className="size-3.5 mr-1" /> Set default model</Link>
                </Button>
              </div>
            )}
          </div>
        </Card>

        {/* Schedule — a normal operating parameter, not advanced. */}
        <Card className="p-4 space-y-3">
          <CardTitle>Schedule</CardTitle>
          <div className="space-y-1.5">
            <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Cadence</label>
            <select value={scheduleMode} onChange={e => setScheduleMode(e.target.value as typeof scheduleMode)} className="flex h-9 w-full rounded-md border border-border bg-input px-3 text-sm">
              <option value="manual">Manual only</option>
              <option value="daily">Daily</option>
              <option value="cron">Custom cron</option>
            </select>
          </div>
          {scheduleMode === 'daily' && (
            <div className="space-y-1.5">
              <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Hour (UTC)</label>
              <Input value={dailyHour} onChange={e => setDailyHour(e.target.value)} className="w-24" />
            </div>
          )}
          {scheduleMode === 'cron' && (
            <div className="space-y-1.5">
              <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Cron expression</label>
              <Input value={cron} onChange={e => setCron(e.target.value)} className="font-mono" />
            </div>
          )}
          {scheduleMode !== 'manual' && (
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={scheduleEnabled} onChange={e => setScheduleEnabled(e.target.checked)} /> Enabled
            </label>
          )}
        </Card>

        {/* Advanced settings — configurable, collapsed by default. */}
        <Card className="p-4">
          <button type="button" onClick={() => setAdvancedOpen(o => !o)} className="flex w-full items-center gap-2 text-sm font-medium">
            {advancedOpen ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
            Advanced settings
            <span className="text-xs font-normal text-muted-foreground">inputs, outputs &amp; limits — defaults from the template</span>
          </button>
          {advancedOpen && version && (
            <div className="mt-4 space-y-5">
              <div>
                <p className="text-sm font-medium mb-1">Inputs (within the template's allowed contexts)</p>
                <div className="divide-y divide-border">
                  {allowedInputContexts(version).map(id => (
                    <Toggle key={id} label={inputContextLabel(id)} checked={Boolean(inputs[id])} onChange={v => setInputs(s => ({ ...s, [id]: v }))} />
                  ))}
                </div>
              </div>

              <div>
                <p className="text-sm font-medium mb-1">Allowed outputs (this agent can create)</p>
                <div className="divide-y divide-border">
                  {allowedOutputTypes(version).map(id => (
                    <Toggle
                      key={id}
                      label={outputTypeLabel(id)}
                      note={isMemoryOutput(id) ? 'always review' : undefined}
                      checked={Boolean(outputs[id])}
                      onChange={v => setOutputs(s => ({ ...s, [id]: v }))}
                    />
                  ))}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Max tokens</label>
                  <Input value={maxTokens} onChange={e => setMaxTokens(e.target.value)} placeholder="8192" />
                </div>
                <div className="space-y-1.5">
                  <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Temperature</label>
                  <Input value={temperature} onChange={e => setTemperature(e.target.value)} placeholder="(default)" />
                </div>
              </div>

              {previewVersion && (
                <div className="border-t border-border pt-4">
                  <SafetyView version={previewVersion} />
                  <p className="mt-2 text-xs text-muted-foreground">
                    <Badge variant="muted">locked</Badge>{' '}
                    Direct memory write, proposal-only outputs, and tool/shell access stay as the template defines them.
                  </p>
                </div>
              )}
            </div>
          )}
        </Card>

        <div className="flex gap-2">
          <Button type="submit" disabled={saving || !hasDefaultModel}>{saving ? <Loader2 className="size-4 animate-spin" /> : 'Create agent'}</Button>
          <Button type="button" variant="outline" asChild><Link to="/agents/templates">Cancel</Link></Button>
        </div>
      </form>
    </div>
  )
}
