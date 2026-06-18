import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { SpaceLink as Link } from '../../core/spaceNav'
import { Loader2, MessageSquare, Ban, Power } from 'lucide-react'
import { toast } from 'sonner'
import { agentsApi, credentialsApi, runtimeToolsApi } from '../../api/client'
import type { AgentOut, AgentVersionOut, Run, Proposal, CliCredentialAvailableProfileOut, SpaceRuntimeToolPolicyOut } from '../../types/api'
import { Button } from '../../components/ui/button'
import { Card, CardTitle } from '../../components/ui/card'
import { Badge, StatusBadge } from '../../components/ui/badge'
import { Input } from '../../components/ui/input'
import { Textarea } from '../../components/ui/textarea'
import { EmptyState } from '../../components/ui/empty-state'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../../components/ui/tabs'
import { errMsg } from '../../lib/utils'
import { InputsView, OutputsView, ScheduleView, SafetyView } from './ConfigCards'
import { modelFields, scheduleSummary } from './policyMap'
import AssistantSettingsPanel from './AssistantSettingsPanel'
import ProviderSelector from '../providers/ProviderSelector'

export default function AgentDetailPage() {
  const { agentId } = useParams()
  const [agent, setAgent] = useState<AgentOut | null>(null)
  const [version, setVersion] = useState<AgentVersionOut | null>(null)
  const [versions, setVersions] = useState<AgentVersionOut[]>([])
  const [runs, setRuns] = useState<Run[]>([])
  const [proposals, setProposals] = useState<Proposal[]>([])
  const [loading, setLoading] = useState(true)
  const [statusBusy, setStatusBusy] = useState(false)

  const reload = useCallback(async () => {
    if (!agentId) return
    const [a, vs, rs] = await Promise.all([
      agentsApi.get(agentId),
      agentsApi.listVersions(agentId).catch(() => [] as AgentVersionOut[]),
      agentsApi.listRunsForAgent(agentId).catch(() => [] as Run[]),
    ])
    setAgent(a)
    setVersions(vs)
    setRuns(rs)
    setVersion(vs.find(v => v.id === a.current_version_id) ?? vs[0] ?? null)
    agentsApi.listProposals(agentId, 'pending').then(setProposals).catch(() => setProposals([]))
  }, [agentId])

  useEffect(() => {
    setLoading(true)
    reload().catch(err => toast.error(errMsg(err))).finally(() => setLoading(false))
  }, [reload])

  if (loading) return <div className="p-6 flex items-center gap-2 text-muted-foreground"><Loader2 className="size-4 animate-spin" /> Loading…</div>
  if (!agent) return <div className="p-6 text-muted-foreground">Agent not found.</div>

  const isAssistant = agent.agent_kind === 'system_assistant'
  const isActive = agent.status === 'active'

  const toggleStatus = async () => {
    const next = isActive ? 'disabled' : 'active'
    setStatusBusy(true)
    try {
      await agentsApi.update(agent.id, { status: next })
      toast.success(next === 'disabled' ? 'Agent disabled — new runs are blocked by policy' : 'Agent enabled')
      await reload()
    } catch (err) {
      toast.error(errMsg(err))
    } finally {
      setStatusBusy(false)
    }
  }

  return (
    <div className="p-6 max-w-3xl space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold flex items-center gap-2">
            {agent.name} <StatusBadge status={agent.status} />
            {isAssistant && <Badge variant="secondary">System-managed</Badge>}
          </h1>
          <p className="text-sm text-muted-foreground">{agent.description ?? 'No description'}</p>
        </div>
        <div className="flex gap-2 shrink-0">
          {/* Chat works for any agent: the chat turn runs the agent's current
              version through the same execution path (a disabled agent's turn
              is correctly blocked by policy). */}
          <Button asChild size="sm"><Link to={`/agents/${agent.id}/chat`}><MessageSquare className="size-3.5 mr-1" />Open chat</Link></Button>
          {!isAssistant && (
            <Button
              size="sm"
              variant={isActive ? 'destructive' : 'success'}
              disabled={statusBusy}
              onClick={toggleStatus}
              title={isActive ? 'Disable this agent — blocks new run execution' : 'Enable this agent'}
            >
              {statusBusy
                ? <Loader2 className="size-3.5 animate-spin" />
                : isActive
                  ? <><Ban className="size-3.5 mr-1" />Disable</>
                  : <><Power className="size-3.5 mr-1" />Enable</>}
            </Button>
          )}
          <Button asChild size="sm" variant="outline"><Link to="/agents">All agents</Link></Button>
        </div>
      </div>

      <Tabs defaultValue={isAssistant ? 'preferences' : 'overview'}>
        <TabsList className="w-full flex-wrap justify-start gap-1 h-auto">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          {isAssistant && <TabsTrigger value="preferences">Preferences</TabsTrigger>}
          <TabsTrigger value="inputs">Inputs</TabsTrigger>
          <TabsTrigger value="outputs">Outputs</TabsTrigger>
          <TabsTrigger value="schedule">Schedule</TabsTrigger>
          <TabsTrigger value="model">Model</TabsTrigger>
          <TabsTrigger value="safety">Review &amp; Safety</TabsTrigger>
          <TabsTrigger value="versions">Versions</TabsTrigger>
          <TabsTrigger value="runs">Runs</TabsTrigger>
        </TabsList>

        {isAssistant && (
          <TabsContent value="preferences">
            <AssistantSettingsPanel />
          </TabsContent>
        )}

        <TabsContent value="overview">
          <OverviewTab agent={agent} version={version} runs={runs} proposals={proposals} onSaved={reload} />
        </TabsContent>
        <TabsContent value="inputs">
          <Card className="space-y-4">{version ? <InputsView version={version} /> : <NoVersion />}</Card>
        </TabsContent>
        <TabsContent value="outputs">
          <Card>{version ? <OutputsView version={version} /> : <NoVersion />}</Card>
        </TabsContent>
        <TabsContent value="schedule">
          {version ? <ScheduleTab agentId={agent.id} version={version} onSaved={reload} /> : <Card><NoVersion /></Card>}
        </TabsContent>
        <TabsContent value="model">
          {version ? <ModelTab agentId={agent.id} version={version} onSaved={reload} /> : <Card><NoVersion /></Card>}
        </TabsContent>
        <TabsContent value="safety">
          <Card>{version ? <SafetyView version={version} /> : <NoVersion />}</Card>
        </TabsContent>
        <TabsContent value="versions">
          <VersionsTab agentId={agent.id} versions={versions} currentId={agent.current_version_id} onSaved={reload} />
        </TabsContent>
        <TabsContent value="runs">
          <RunsTab runs={runs} />
        </TabsContent>
      </Tabs>
    </div>
  )
}

function NoVersion() {
  return <p className="text-sm text-muted-foreground">This agent has no current version configured.</p>
}

// ── Overview ──────────────────────────────────────────────────────────────────

function OverviewTab({ agent, version, runs, proposals, onSaved }: {
  agent: AgentOut; version: AgentVersionOut | null; runs: Run[]; proposals: Proposal[]; onSaved: () => Promise<void>
}) {
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(agent.name)
  const [description, setDescription] = useState(agent.description ?? '')
  const [systemPrompt, setSystemPrompt] = useState(agent.system_prompt ?? '')
  const [saving, setSaving] = useState(false)
  const lastRun = runs[0]

  async function save() {
    setSaving(true)
    try {
      await agentsApi.updateConfig(agent.id, {
        name: name.trim(),
        description: description.trim() || null,
        system_prompt: systemPrompt.trim() || null,
      })
      toast.success('Agent updated (new version created)')
      setEditing(false)
      await onSaved()
    } catch (err) { toast.error(errMsg(err)) } finally { setSaving(false) }
  }

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex items-center justify-between">
          <CardTitle>Identity &amp; role</CardTitle>
          {!editing && <Button size="sm" variant="outline" onClick={() => setEditing(true)}>Edit</Button>}
        </div>
        {editing ? (
          <div className="mt-3 space-y-3">
            <Input value={name} onChange={e => setName(e.target.value)} placeholder="Name" />
            <Input value={description} onChange={e => setDescription(e.target.value)} placeholder="Description" />
            <Textarea value={systemPrompt} onChange={e => setSystemPrompt(e.target.value)} rows={4} placeholder="System prompt (role/identity)" />
            <p className="text-xs text-muted-foreground">Saving creates a new immutable agent version; the previous version is preserved.</p>
            <div className="flex gap-2">
              <Button size="sm" onClick={save} disabled={saving}>{saving ? <Loader2 className="size-4 animate-spin" /> : 'Save'}</Button>
              <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
            </div>
          </div>
        ) : (
          <div className="mt-2 space-y-2">
            {agent.system_prompt
              ? <pre className="text-sm whitespace-pre-wrap font-sans text-foreground">{agent.system_prompt}</pre>
              : <p className="text-sm text-muted-foreground">No system prompt set.</p>}
          </div>
        )}
      </Card>

      <Card>
        <CardTitle className="mb-2">Provenance</CardTitle>
        {agent.agent_kind === 'system_assistant' ? (
          <p className="text-sm text-muted-foreground">System-managed default assistant — the space's Chat identity. Its core prompt and safety policy are managed by the system; you can adjust preferences and configurable settings.</p>
        ) : agent.source_template_id ? (
          <div className="text-sm space-y-1">
            <p>Created from template <Link className="underline" to={`/agents/templates/${agent.source_template_id}`}>{agent.source_template_id}</Link></p>
            {agent.source_template_version_id && <p className="text-xs text-muted-foreground">Template version: <span className="font-mono">{agent.source_template_version_id}</span></p>}
            <p className="text-xs text-muted-foreground">Configuration is an independent snapshot — later template updates do not change this agent.</p>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">Created directly (not from a template).</p>
        )}
        <p className="text-xs text-muted-foreground mt-2">Current version: <span className="font-mono">{version?.version_label ?? '—'}</span></p>
      </Card>

      <div className="grid grid-cols-2 gap-4">
        <Card>
          <CardTitle className="mb-2">Last run</CardTitle>
          {lastRun
            ? <div className="text-sm flex items-center gap-2"><StatusBadge status={lastRun.status} /><span className="text-muted-foreground">{new Date(lastRun.created_at).toLocaleString()}</span></div>
            : <p className="text-sm text-muted-foreground">No runs yet.</p>}
          <p className="text-xs text-muted-foreground mt-2">Next run is scheduler-driven and not yet surfaced.</p>
        </Card>
        <Card>
          <CardTitle className="mb-2">Pending proposals</CardTitle>
          {proposals.length
            ? <p className="text-sm">{proposals.length} awaiting review <Badge variant="warning">review</Badge></p>
            : <p className="text-sm text-muted-foreground">None pending.</p>}
        </Card>
      </div>
    </div>
  )
}

// ── Schedule (editable) ─────────────────────────────────────────────────────────

function ScheduleTab({ agentId, version, onSaved }: { agentId: string; version: AgentVersionOut; onSaved: () => Promise<void> }) {
  const current = scheduleSummary(version)
  const [mode, setMode] = useState<'manual' | 'daily' | 'cron'>(current.kind === 'manual' ? 'manual' : current.kind === 'daily' ? 'daily' : 'cron')
  const [dailyHour, setDailyHour] = useState(() => {
    const m = /Daily at (\d{2})/.exec(current.label); return m ? m[1] : '08'
  })
  const [cron, setCron] = useState(current.cron ?? '0 8 * * *')
  const [enabled, setEnabled] = useState(current.enabled)
  const [saving, setSaving] = useState(false)

  async function save() {
    setSaving(true)
    try {
      let schedule: Record<string, unknown>
      if (mode === 'manual') schedule = { enabled: false, cron: null }
      else if (mode === 'daily') schedule = { enabled, cron: `0 ${Number(dailyHour)} * * *` }
      else schedule = { enabled, cron }
      await agentsApi.updateConfig(agentId, { schedule_config_json: schedule })
      toast.success('Schedule updated (new version created)')
      await onSaved()
    } catch (err) { toast.error(errMsg(err)) } finally { setSaving(false) }
  }

  return (
    <Card className="space-y-4">
      <ScheduleView version={version} />
      <div className="border-t border-border pt-4 space-y-3">
        <CardTitle>Edit schedule</CardTitle>
        <div className="space-y-1.5">
          <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Cadence</label>
          <select value={mode} onChange={e => setMode(e.target.value as typeof mode)} className="flex h-9 w-full rounded-md border border-border bg-input px-3 text-sm">
            <option value="manual">Manual only</option>
            <option value="daily">Daily</option>
            <option value="cron">Custom cron</option>
          </select>
        </div>
        {mode === 'daily' && (
          <div className="space-y-1.5">
            <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Hour (UTC)</label>
            <Input value={dailyHour} onChange={e => setDailyHour(e.target.value)} className="w-24" />
          </div>
        )}
        {mode === 'cron' && (
          <div className="space-y-1.5">
            <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Cron expression</label>
            <Input value={cron} onChange={e => setCron(e.target.value)} className="font-mono" />
          </div>
        )}
        {mode !== 'manual' && (
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} /> Enabled
          </label>
        )}
        <p className="text-xs text-muted-foreground">Stored on the agent version. Actual scheduled execution is wired separately and not driven from here.</p>
        <Button size="sm" onClick={save} disabled={saving}>{saving ? <Loader2 className="size-4 animate-spin" /> : 'Save schedule'}</Button>
      </div>
    </Card>
  )
}

// ── Model (editable) ──────────────────────────────────────────────────────────

function CliProfileSelector({
  runtime,
  profiles,
  value,
  onChange,
}: {
  runtime: string
  profiles: CliCredentialAvailableProfileOut[]
  value: string
  onChange: (value: string) => void
}) {
  const runtimeProfiles = profiles.filter(profile => profile.runtime === runtime)
  if (runtimeProfiles.length === 0) return null
  return (
    <div className="space-y-1.5">
      <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">CLI profile</label>
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        className="flex h-9 w-full rounded-md border border-border bg-input px-3 text-sm"
      >
        <option value="">Active-space default</option>
        {runtimeProfiles.map(profile => (
          <option key={profile.id} value={profile.id}>
            {profile.name}{profile.is_default ? ' (default)' : ''}{profile.manageable ? ' · mine' : ''}
          </option>
        ))}
      </select>
    </div>
  )
}

function RuntimeVersionSelector({
  runtime,
  policies,
  value,
  onChange,
}: {
  runtime: string
  policies: SpaceRuntimeToolPolicyOut[]
  value: string
  onChange: (value: string) => void
}) {
  const policy = policies.find(item => item.runtime === runtime)
  if (!policy) return null
  const versions = policy.installed_versions.filter(version => version.installed)
  return (
    <div className="space-y-1.5">
      <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">CLI runtime version</label>
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        className="flex h-9 w-full rounded-md border border-border bg-input px-3 text-sm"
      >
        <option value="">Space default ({policy.default_version ?? 'none'})</option>
        {versions.map(version => (
          <option key={version.version} value={version.version}>{version.version}</option>
        ))}
      </select>
    </div>
  )
}

function ModelTab({ agentId, version, onSaved }: { agentId: string; version: AgentVersionOut; onSaved: () => Promise<void> }) {
  const m = modelFields(version)
  const [model, setModel] = useState(m.model ?? version.model_name ?? '')
  const [temperature, setTemperature] = useState(m.temperature != null ? String(m.temperature) : '')
  const [maxTokens, setMaxTokens] = useState(m.max_tokens != null ? String(m.max_tokens) : '')
  const [providerSelection, setProviderSelection] = useState<{ provider_id: string; model: string } | null>(
    version.model_provider_id
      ? { provider_id: version.model_provider_id, model: version.model_name ?? m.model ?? '' }
      : null,
  )
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [saving, setSaving] = useState(false)
  const hasProvider = Boolean(version.model_provider_id)
  const runtimeConfig = version.runtime_config_json as Record<string, unknown>
  const runtimePolicy = version.runtime_policy_json as Record<string, unknown>
  const adapterType =
    (typeof runtimeConfig.adapter_type === 'string' && runtimeConfig.adapter_type) ||
    (typeof runtimePolicy.default_adapter_type === 'string' && runtimePolicy.default_adapter_type) ||
    'model_api'
  const supportsProviderSelection = adapterType === 'model_api' || adapterType === 'claude_code' || adapterType === 'codex_cli'
  const providerRequired = adapterType === 'model_api'
  const requireClaudeCompatible = adapterType === 'claude_code'
  const requireOpenAiCompatible = adapterType === 'codex_cli'
  const isCli = adapterType === 'claude_code' || adapterType === 'codex_cli'
  const [cliProfiles, setCliProfiles] = useState<CliCredentialAvailableProfileOut[]>([])
  const [runtimePolicies, setRuntimePolicies] = useState<SpaceRuntimeToolPolicyOut[]>([])
  const [credentialProfileId, setCredentialProfileId] = useState(
    typeof runtimeConfig.credential_profile_id === 'string' ? runtimeConfig.credential_profile_id : '',
  )
  const [runtimeToolVersion, setRuntimeToolVersion] = useState(
    typeof runtimeConfig.runtime_tool_version === 'string' ? runtimeConfig.runtime_tool_version : '',
  )

  useEffect(() => {
    setCredentialProfileId(
      typeof runtimeConfig.credential_profile_id === 'string' ? runtimeConfig.credential_profile_id : '',
    )
    setRuntimeToolVersion(
      typeof runtimeConfig.runtime_tool_version === 'string' ? runtimeConfig.runtime_tool_version : '',
    )
  }, [version.id, runtimeConfig.credential_profile_id, runtimeConfig.runtime_tool_version])

  useEffect(() => {
    if (!isCli) {
      setCliProfiles([])
      setRuntimePolicies([])
      return
    }
    Promise.all([
      credentialsApi.available(adapterType).catch(() => [] as CliCredentialAvailableProfileOut[]),
      runtimeToolsApi.spacePolicies().catch(() => [] as SpaceRuntimeToolPolicyOut[]),
    ])
      .then(([profiles, policies]) => {
        setCliProfiles(profiles.filter(profile => profile.logged_in))
        setRuntimePolicies(policies)
      })
      .catch(() => {
        setCliProfiles([])
        setRuntimePolicies([])
      })
  }, [adapterType, isCli])

  function changeProviderSelection(next: { provider_id: string; model: string } | null) {
    setProviderSelection(next)
    if (next?.model) setModel(next.model)
  }

  async function save() {
    setSaving(true)
    try {
      const cfg: Record<string, unknown> = { ...(version.model_config_json as Record<string, unknown>) }
      const selectedModel = providerSelection?.model || model.trim()
      cfg.model = selectedModel || undefined
      if (temperature.trim()) cfg.temperature = Number(temperature)
      else delete cfg.temperature
      if (maxTokens.trim()) cfg.max_tokens = Number(maxTokens)
      const nextRuntimeConfig: Record<string, unknown> = { ...runtimeConfig, adapter_type: adapterType }
      if (isCli && credentialProfileId) nextRuntimeConfig.credential_profile_id = credentialProfileId
      else delete nextRuntimeConfig.credential_profile_id
      if (isCli && runtimeToolVersion) nextRuntimeConfig.runtime_tool_version = runtimeToolVersion
      else delete nextRuntimeConfig.runtime_tool_version
      // Keep the provider's model binding consistent with the edited model name.
      const body = supportsProviderSelection
        ? {
            model_config_json: cfg,
            ...(isCli ? { runtime_config_json: nextRuntimeConfig } : {}),
            model_provider_id: providerSelection?.provider_id ?? null,
            model_name: providerSelection?.provider_id && selectedModel ? selectedModel : null,
          }
        : hasProvider && model.trim()
          ? { model_config_json: cfg, ...(isCli ? { runtime_config_json: nextRuntimeConfig } : {}), model_name: model.trim() }
          : { model_config_json: cfg, ...(isCli ? { runtime_config_json: nextRuntimeConfig } : {}) }
      await agentsApi.updateConfig(agentId, body)
      toast.success('Model updated (new version created)')
      await onSaved()
    } catch (err) { toast.error(errMsg(err)) } finally { setSaving(false) }
  }

  return (
    <Card className="space-y-4">
      <CardTitle>Model</CardTitle>
      {hasProvider && <p className="text-xs text-muted-foreground -mt-2">Bound to a configured provider. Resolved from the system default at creation.</p>}
      {supportsProviderSelection && (
        <ProviderSelector
          value={providerSelection}
          onChange={changeProviderSelection}
          required={providerRequired}
          requireClaudeCompatible={requireClaudeCompatible}
          requireOpenAiCompatible={requireOpenAiCompatible}
          emptyLabel={requireClaudeCompatible ? 'Claude Code default' : requireOpenAiCompatible ? 'Codex default' : undefined}
        />
      )}
      {isCli && (
        <>
          <CliProfileSelector
            runtime={adapterType}
            profiles={cliProfiles}
            value={credentialProfileId}
            onChange={setCredentialProfileId}
          />
          <RuntimeVersionSelector
            runtime={adapterType}
            policies={runtimePolicies}
            value={runtimeToolVersion}
            onChange={setRuntimeToolVersion}
          />
        </>
      )}
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Model</label>
        <Input value={model} onChange={e => setModel(e.target.value)} placeholder="claude-sonnet-4-6" className="font-mono" />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1.5">
          <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Temperature</label>
          <Input value={temperature} onChange={e => setTemperature(e.target.value)} placeholder="(default)" />
        </div>
        <div className="space-y-1.5">
          <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Max tokens</label>
          <Input value={maxTokens} onChange={e => setMaxTokens(e.target.value)} placeholder="8192" />
        </div>
      </div>
      <div>
        <button type="button" onClick={() => setShowAdvanced(s => !s)} className="text-xs text-muted-foreground underline">
          {showAdvanced ? 'Hide' : 'Show'} advanced (raw JSON)
        </button>
        {showAdvanced && (
          <pre className="mt-2 text-xs bg-muted rounded-md p-3 overflow-auto">{JSON.stringify(version.model_config_json, null, 2)}</pre>
        )}
      </div>
      <Button size="sm" onClick={save} disabled={saving}>{saving ? <Loader2 className="size-4 animate-spin" /> : 'Save model'}</Button>
    </Card>
  )
}

// ── Versions ────────────────────────────────────────────────────────────────────

function VersionsTab({ agentId, versions, currentId, onSaved }: {
  agentId: string; versions: AgentVersionOut[]; currentId: string | null; onSaved: () => Promise<void>
}) {
  const [busy, setBusy] = useState<string | null>(null)
  const [open, setOpen] = useState<string | null>(null)

  async function restore(versionId: string) {
    setBusy(versionId)
    try {
      await agentsApi.restoreVersion(agentId, versionId)
      toast.success('Restored as a new version')
      await onSaved()
    } catch (err) { toast.error(errMsg(err)) } finally { setBusy(null) }
  }

  if (versions.length === 0) return <Card><EmptyState title="No versions" /></Card>

  return (
    <div className="space-y-3">
      {versions.map(v => (
        <Card key={v.id}>
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-sm font-medium flex items-center gap-2">
                {v.version_label}
                {v.id === currentId && <Badge variant="success">current</Badge>}
                {v.source_proposal_id && <Badge variant="outline">from proposal</Badge>}
              </p>
              <p className="text-xs text-muted-foreground">{new Date(v.created_at).toLocaleString()}</p>
            </div>
            <div className="flex gap-2">
              <Button size="sm" variant="ghost" onClick={() => setOpen(open === v.id ? null : v.id)}>{open === v.id ? 'Hide' : 'View config'}</Button>
              {v.id !== currentId && (
                <Button size="sm" variant="outline" disabled={busy === v.id} onClick={() => restore(v.id)}>
                  {busy === v.id ? <Loader2 className="size-4 animate-spin" /> : 'Restore'}
                </Button>
              )}
            </div>
          </div>
          {open === v.id && (
            <pre className="mt-3 text-xs bg-muted rounded-md p-3 overflow-auto max-h-80">{JSON.stringify({
              system_prompt: v.system_prompt,
              model_config_json: v.model_config_json,
              context_policy_json: v.context_policy_json,
              memory_policy_json: v.memory_policy_json,
              output_policy_json: v.output_policy_json,
              schedule_config_json: v.schedule_config_json,
            }, null, 2)}</pre>
          )}
        </Card>
      ))}
      <p className="text-xs text-muted-foreground">Restoring copies the selected version's config into a new version — old versions are never mutated.</p>
    </div>
  )
}

// ── Runs ──────────────────────────────────────────────────────────────────────

function RunsTab({ runs }: { runs: Run[] }) {
  if (runs.length === 0) {
    return <Card><EmptyState title="No runs yet" description="This agent hasn't been run. Runs will appear here once it executes." /></Card>
  }
  return (
    <div className="space-y-2">
      {runs.map(r => (
        <Card key={r.id} className="flex items-center justify-between gap-3">
          <div>
            <p className="text-sm flex items-center gap-2"><StatusBadge status={r.status} /> <span className="text-muted-foreground">{r.trigger_origin} · {r.mode}</span></p>
            <p className="text-xs text-muted-foreground">{new Date(r.created_at).toLocaleString()}</p>
          </div>
          <Link to={`/runs/${r.id}`} className="text-xs underline text-muted-foreground">View run</Link>
        </Card>
      ))}
    </div>
  )
}
