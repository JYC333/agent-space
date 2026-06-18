import { useState, useEffect, useId } from 'react'
import { KeyRound, CheckCircle, AlertCircle, Loader2, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { authApi, providersApi, type ModelProviderOut, type ProviderType } from '../../api/client'
import type { SpaceWithMembership } from '../../types/api'
import { useSpace } from '../../contexts/SpaceContext'
import { Card, CardTitle } from '../../components/ui/card'
import { Button } from '../../components/ui/button'
import { Input } from '../../components/ui/input'
import { Badge } from '../../components/ui/badge'
import { errMsg } from '../../lib/utils'
import NetworkProfileSelector from '../network_profiles/NetworkProfileSelector'

const PROVIDER_TYPES: { value: ProviderType; label: string }[] = [
  { value: 'openai', label: 'OpenAI-compatible' },
  { value: 'anthropic', label: 'Anthropic-compatible' },
  { value: 'openrouter', label: 'OpenRouter' },
  { value: 'ollama', label: 'Ollama' },
  { value: 'other', label: 'Other' },
]

const API_KEY_REQUIRED = new Set(['openai', 'anthropic', 'openrouter'])

type ProviderPresetId = 'custom' | 'minimax'

interface ProviderPreset {
  id: ProviderPresetId
  label: string
  name: string
  providerType: ProviderType
  baseUrl: string
  claudeCompatibleBaseUrl?: string
  openAiCompatibleBaseUrl?: string
  defaultModel?: string
  availableModels?: string[]
}

const PROVIDER_PRESETS: ProviderPreset[] = [
  {
    id: 'minimax',
    label: 'MiniMax',
    name: 'MiniMax',
    providerType: 'anthropic',
    baseUrl: 'https://api.minimaxi.com/anthropic',
    claudeCompatibleBaseUrl: 'https://api.minimaxi.com/anthropic',
    openAiCompatibleBaseUrl: 'https://api.minimaxi.com/v1',
    defaultModel: 'MiniMax-M3',
    availableModels: [
      'MiniMax-M3',
      'MiniMax-M2.7',
      'MiniMax-M2.7-highspeed',
      'MiniMax-M2.5',
      'MiniMax-M2.5-highspeed',
      'MiniMax-M2.1',
      'MiniMax-M2.1-highspeed',
      'MiniMax-M2',
    ],
  },
]

function defaultBaseUrl(providerType: ProviderType): string {
  if (providerType === 'openai') return 'https://api.openai.com/v1'
  if (providerType === 'anthropic') return 'https://api.anthropic.com'
  if (providerType === 'openrouter') return 'https://openrouter.ai/api/v1'
  if (providerType === 'ollama') return 'http://localhost:11434'
  return ''
}

function ProviderTypeSelect({ value, onChange }: { value: ProviderType; onChange: (v: ProviderType) => void }) {
  return (
    <select
      value={value}
      onChange={e => onChange(e.target.value as ProviderType)}
      className="flex h-9 w-full rounded-md border border-border bg-input px-3 text-sm"
    >
      {PROVIDER_TYPES.map(t => (
        <option key={t.value} value={t.value}>{t.label}</option>
      ))}
    </select>
  )
}

function AddProviderForm({ onAdded, canCreate, expanded, setExpanded }: {
  onAdded: () => void
  canCreate: boolean
  expanded: boolean
  setExpanded: (v: boolean) => void
}) {
  const [presetId, setPresetId] = useState<ProviderPresetId>('custom')
  const [name, setName] = useState('')
  const [providerType, setProviderType] = useState<ProviderType>('openai')
  const [apiKey, setApiKey] = useState('')
  const [defaultModel, setDefaultModel] = useState('')
  const [availableModels, setAvailableModels] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [claudeCompatibleBaseUrl, setClaudeCompatibleBaseUrl] = useState('')
  const [openAiCompatibleBaseUrl, setOpenAiCompatibleBaseUrl] = useState('')
  const [networkProfileId, setNetworkProfileId] = useState<string | null>(null)
  const [isDefault, setIsDefault] = useState(false)
  const [saving, setSaving] = useState(false)

  function reset() {
    setPresetId('custom')
    setName('')
    setProviderType('openai')
    setApiKey('')
    setDefaultModel('')
    setAvailableModels('')
    setBaseUrl('')
    setClaudeCompatibleBaseUrl('')
    setOpenAiCompatibleBaseUrl('')
    setNetworkProfileId(null)
    setIsDefault(false)
    setExpanded(false)
  }

  function applyPreset(nextPresetId: ProviderPresetId) {
    setPresetId(nextPresetId)
    if (nextPresetId === 'custom') return
    const preset = PROVIDER_PRESETS.find(p => p.id === nextPresetId)
    if (!preset) return
    setName(preset.name)
    setProviderType(preset.providerType)
    setBaseUrl(preset.baseUrl)
    setClaudeCompatibleBaseUrl(preset.claudeCompatibleBaseUrl ?? '')
    setOpenAiCompatibleBaseUrl(preset.openAiCompatibleBaseUrl ?? '')
    setDefaultModel(preset.defaultModel ?? '')
    setAvailableModels((preset.availableModels ?? []).join(', '))
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!canCreate) {
      toast.error('Select an operational space before adding a provider')
      return
    }
    if (API_KEY_REQUIRED.has(providerType) && !apiKey.trim()) {
      toast.error('API key is required for this provider type')
      return
    }
    if (!baseUrl.trim()) {
      toast.error('Base URL is required')
      return
    }

    setSaving(true)
    try {
      const models = availableModels
        ? availableModels.split(',').map(m => m.trim()).filter(Boolean)
        : defaultModel ? [defaultModel.trim()] : []
      await providersApi.create({
        name: name.trim() || providerType,
        provider_type: providerType,
        api_key: apiKey.trim() || undefined,
        default_model: defaultModel.trim() || undefined,
        available_models: models,
        base_url: baseUrl.trim(),
        network_profile_id: networkProfileId,
        claude_compatible_base_url: claudeCompatibleBaseUrl.trim() || undefined,
        openai_compatible_base_url: openAiCompatibleBaseUrl.trim() || undefined,
        is_default: isDefault,
      })
      toast.success('Provider added')
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
        Add provider
      </Button>
    )
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3 p-4 border border-border rounded-lg bg-accent/30">
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Preset</label>
        <select
          value={presetId}
          onChange={e => applyPreset(e.target.value as ProviderPresetId)}
          className="flex h-9 w-full rounded-md border border-border bg-input px-3 text-sm"
        >
          <option value="custom">Custom</option>
          {PROVIDER_PRESETS.map(p => (
            <option key={p.id} value={p.id}>{p.label}</option>
          ))}
        </select>
      </div>
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">API protocol</label>
        <ProviderTypeSelect value={providerType} onChange={v => { setPresetId('custom'); setProviderType(v) }} />
      </div>
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Display name</label>
        <Input value={name} onChange={e => setName(e.target.value)} placeholder="My OpenAI" className="text-sm" />
      </div>
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Base URL</label>
        <Input value={baseUrl} onChange={e => setBaseUrl(e.target.value)} placeholder={defaultBaseUrl(providerType) || 'https://gateway.example/v1'} className="font-mono text-sm" required />
      </div>
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Claude-compatible URL (optional)</label>
        <Input value={claudeCompatibleBaseUrl} onChange={e => setClaudeCompatibleBaseUrl(e.target.value)} placeholder="https://api.example.com/anthropic" className="font-mono text-sm" />
      </div>
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">OpenAI-compatible URL (optional)</label>
        <Input value={openAiCompatibleBaseUrl} onChange={e => setOpenAiCompatibleBaseUrl(e.target.value)} placeholder="https://api.example.com/v1" className="font-mono text-sm" />
      </div>
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Network</label>
        <NetworkProfileSelector value={networkProfileId} onChange={setNetworkProfileId} />
      </div>
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
          API Key {API_KEY_REQUIRED.has(providerType) ? '(required)' : '(optional)'}
        </label>
        <Input type="password" value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder="sk-…" className="font-mono text-sm" />
      </div>
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Default model</label>
        <Input value={defaultModel} onChange={e => setDefaultModel(e.target.value)} placeholder="gpt-4o" className="font-mono text-sm" />
      </div>
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Available models</label>
        <Input value={availableModels} onChange={e => setAvailableModels(e.target.value)} placeholder="gpt-4o, gpt-4o-mini" className="font-mono text-sm" />
        <p className="text-xs text-muted-foreground">Comma-separated</p>
      </div>
      <label className="flex items-center gap-2 text-[13px]">
        <input type="checkbox" checked={isDefault} onChange={e => setIsDefault(e.target.checked)} className="accent-primary" />
        Set as default provider
      </label>
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={saving}>{saving ? <Loader2 className="size-3.5 animate-spin" /> : 'Add provider'}</Button>
        <Button type="button" size="sm" variant="outline" onClick={reset}>Cancel</Button>
      </div>
    </form>
  )
}

function ProviderCard({
  config,
  onDelete,
  onTest,
  onPatched,
  spaces,
}: {
  config: ModelProviderOut
  onDelete: (id: string) => void
  onTest: (id: string) => Promise<{ success: boolean; message: string }>
  onPatched: (updated: ModelProviderOut) => void
  spaces: SpaceWithMembership[]
}) {
  const [deleting, setDeleting] = useState(false)
  const [testing, setTesting] = useState(false)
  const [editing, setEditing] = useState(false)
  const [editName, setEditName] = useState(config.name)
  const [editDefaultModel, setEditDefaultModel] = useState(config.default_model ?? '')
  const [editModels, setEditModels] = useState(config.available_models.join(', '))
  const [editBaseUrl, setEditBaseUrl] = useState(config.base_url ?? '')
  const [editClaudeCompatibleBaseUrl, setEditClaudeCompatibleBaseUrl] = useState(config.claude_compatible_base_url ?? '')
  const [editOpenAiCompatibleBaseUrl, setEditOpenAiCompatibleBaseUrl] = useState(config.openai_compatible_base_url ?? '')
  const [editNetworkProfileId, setEditNetworkProfileId] = useState<string | null>(config.network_profile_id ?? null)
  const [editApiKey, setEditApiKey] = useState('')
  const [editEnabled, setEditEnabled] = useState(config.enabled)
  const [saving, setSaving] = useState(false)
  const [grantSpaceId, setGrantSpaceId] = useState('')
  const [granting, setGranting] = useState(false)
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null)

  async function handleSave() {
    if (!editBaseUrl.trim()) {
      toast.error('Base URL is required')
      return
    }
    setSaving(true)
    try {
      const updated = await providersApi.patch(config.id, {
        name: editName,
        default_model: editDefaultModel || undefined,
        available_models: editModels.split(',').map(m => m.trim()).filter(Boolean),
        base_url: editBaseUrl.trim(),
        network_profile_id: editNetworkProfileId,
        claude_compatible_base_url: editClaudeCompatibleBaseUrl.trim() || null,
        openai_compatible_base_url: editOpenAiCompatibleBaseUrl.trim() || null,
        api_key: editApiKey.trim() || undefined,
        enabled: editEnabled,
      })
      onPatched(updated)
      setEditing(false)
      setEditApiKey('')
      toast.success('Provider updated')
    } catch (err) {
      toast.error(errMsg(err))
    } finally {
      setSaving(false)
    }
  }

  async function grantProvider() {
    if (!grantSpaceId) return
    setGranting(true)
    try {
      await providersApi.grant(config.id, { space_id: grantSpaceId, enabled: true })
      toast.success('Provider granted')
    } catch (err) {
      toast.error(errMsg(err))
    } finally {
      setGranting(false)
    }
  }

  if (editing) {
    return (
      <Card>
        <div className="space-y-3 p-4">
          <Input value={editName} onChange={e => setEditName(e.target.value)} placeholder="Name" />
          <Input value={editBaseUrl} onChange={e => setEditBaseUrl(e.target.value)} placeholder="Base URL" className="font-mono text-sm" />
          <Input value={editClaudeCompatibleBaseUrl} onChange={e => setEditClaudeCompatibleBaseUrl(e.target.value)} placeholder="Claude-compatible URL" className="font-mono text-sm" />
          <Input value={editOpenAiCompatibleBaseUrl} onChange={e => setEditOpenAiCompatibleBaseUrl(e.target.value)} placeholder="OpenAI-compatible URL" className="font-mono text-sm" />
          <div className="space-y-1.5">
            <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Network</label>
            <NetworkProfileSelector value={editNetworkProfileId} onChange={setEditNetworkProfileId} />
          </div>
          <Input type="password" value={editApiKey} onChange={e => setEditApiKey(e.target.value)} placeholder="Replace API key (optional)" className="font-mono text-sm" />
          <Input value={editDefaultModel} onChange={e => setEditDefaultModel(e.target.value)} placeholder="Default model" className="font-mono text-sm" />
          <Input value={editModels} onChange={e => setEditModels(e.target.value)} placeholder="Available models" className="font-mono text-sm" />
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={editEnabled} onChange={e => setEditEnabled(e.target.checked)} />
            Enabled
          </label>
          <div className="flex gap-2">
            <Button size="sm" onClick={handleSave} disabled={saving}>Save</Button>
            <Button size="sm" variant="outline" onClick={() => setEditing(false)}>Cancel</Button>
          </div>
        </div>
      </Card>
    )
  }

  return (
    <Card>
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2 flex-wrap">
          <CardTitle>{config.name}</CardTitle>
          {config.is_default && <Badge variant="default" className="text-[10px]">Default</Badge>}
          {config.manageable === false && <Badge variant="muted" className="text-[10px]">Granted</Badge>}
          {!config.enabled && <Badge variant="muted" className="text-[10px]">Disabled</Badge>}
          {config.has_api_key ? (
            <Badge variant="muted" className="text-[10px]">API key set</Badge>
          ) : (
            <Badge variant="muted" className="text-[10px]">No API key</Badge>
          )}
        </div>
        <span className="text-[10px] font-mono text-muted-foreground">{config.provider_type}</span>
      </div>
      {config.base_url && (
        <p className="text-xs font-mono text-muted-foreground mb-2 truncate">{config.base_url}</p>
      )}
      {config.claude_compatible_base_url && (
        <p className="text-xs font-mono text-muted-foreground mb-2 truncate">Claude: {config.claude_compatible_base_url}</p>
      )}
      {config.openai_compatible_base_url && (
        <p className="text-xs font-mono text-muted-foreground mb-2 truncate">OpenAI: {config.openai_compatible_base_url}</p>
      )}
      <p className="text-xs mb-2">
        Network: <span className="font-mono">{config.network_profile_id ? `profile:${config.network_profile_id.slice(0, 8)}` : 'direct'}</span>
      </p>
      {config.default_model && (
        <p className="text-xs mb-2">Default: <span className="font-mono">{config.default_model}</span></p>
      )}
      <div className="flex flex-wrap gap-1 mb-3">
        {config.available_models.map(m => (
          <Badge key={m} variant="muted" className="text-[10px] font-mono">{m}</Badge>
        ))}
      </div>
      {testResult && (
        <div className={`text-xs mb-3 p-2 rounded-md ${testResult.success ? 'bg-green-500/10 text-green-600' : 'bg-red-500/10 text-red-500'}`}>
          {testResult.success ? <CheckCircle className="size-3 inline mr-1" /> : <AlertCircle className="size-3 inline mr-1" />}
          {testResult.message}
        </div>
      )}
      <div className="flex gap-2">
        <Button size="sm" variant="outline" onClick={async () => { setTesting(true); try { setTestResult(await onTest(config.id)) } finally { setTesting(false) } }} disabled={testing}>
          {testing ? <Loader2 className="size-3.5 animate-spin" /> : 'Test'}
        </Button>
        {config.manageable !== false && (
          <>
            <Button size="sm" variant="outline" onClick={() => setEditing(true)}>Edit</Button>
            <Button size="sm" variant="outline" onClick={async () => { setDeleting(true); try { await onDelete(config.id) } finally { setDeleting(false) } }} disabled={deleting} className="text-red-500">
              {deleting ? <Loader2 className="size-3.5 animate-spin" /> : <Trash2 className="size-3.5" />}
            </Button>
          </>
        )}
      </div>
      {config.manageable !== false && spaces.length > 0 && (
        <div className="flex gap-2 pt-3 mt-3 border-t border-border">
          <select
            value={grantSpaceId}
            onChange={e => setGrantSpaceId(e.target.value)}
            className="flex h-8 flex-1 rounded-md border border-border bg-input px-2 text-xs"
          >
            <option value="">Grant to space…</option>
            {spaces.map(space => (
              <option key={space.id} value={space.id}>{space.name}</option>
            ))}
          </select>
          <Button size="sm" variant="outline" onClick={grantProvider} disabled={!grantSpaceId || granting}>
            {granting ? <Loader2 className="size-3.5 animate-spin" /> : 'Grant'}
          </Button>
        </div>
      )}
    </Card>
  )
}

export default function ModelProvidersPage() {
  const { activeSpaceId, activeSpaceName } = useSpace()
  const [configs, setConfigs] = useState<ModelProviderOut[]>([])
  const [spaces, setSpaces] = useState<SpaceWithMembership[]>([])
  const [loading, setLoading] = useState(true)
  // While the add form is open it takes over the view; the list/empty-state below
  // is hidden so we never show "no providers" (or the existing list) mid-add.
  const [adding, setAdding] = useState(false)
  const headingId = useId()
  const ownedConfigs = configs.filter(cfg => cfg.manageable !== false)
  const grantedConfigs = configs.filter(cfg => cfg.manageable === false)

  useEffect(() => { loadAll() }, [activeSpaceId])

  async function loadAll() {
    setLoading(true)
    try {
      if (!activeSpaceId) {
        setConfigs([])
        setSpaces([])
        return
      }
      const [providers, nextSpaces] = await Promise.all([
        providersApi.list(),
        authApi.mySpaces().catch(() => [] as SpaceWithMembership[]),
      ])
      setConfigs(providers)
      setSpaces(nextSpaces)
    } catch (err) {
      toast.error(errMsg(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="p-6 space-y-6 max-w-2xl" id={headingId}>
      <div className="flex items-center gap-4 pb-4 border-b border-border">
        <div className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0" style={{ background: 'color-mix(in oklch, var(--primary) 12%, transparent)', border: '1px solid color-mix(in oklch, var(--primary) 35%, transparent)' }}>
          <KeyRound className="size-5 text-accent-foreground" />
        </div>
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Model Providers</h1>
          <p className="text-sm text-muted-foreground">Configure OpenAI, Anthropic, OpenRouter, Ollama, or custom endpoints.</p>
          <p className="text-xs text-muted-foreground">Viewing: {activeSpaceName ?? activeSpaceId ?? 'No operational space selected'}</p>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-12 text-muted-foreground">
          <Loader2 className="size-5 animate-spin mr-2" /> Loading…
        </div>
      ) : (
        <div className="space-y-4">
          <AddProviderForm onAdded={loadAll} canCreate={Boolean(activeSpaceId)} expanded={adding} setExpanded={setAdding} />
          {!adding && (configs.length === 0 ? (
            <Card>
              <p className="text-sm text-muted-foreground p-4">
                {activeSpaceId
                  ? 'No model providers configured. Add OpenAI-compatible, Anthropic-compatible, OpenRouter, Ollama, or Other before running agents.'
                  : 'Select an operational space to configure providers.'}
              </p>
            </Card>
          ) : (
            <div className="space-y-5">
              {ownedConfigs.length > 0 && (
                <section className="space-y-3">
                  <h2 className="text-sm font-medium">Owned by me</h2>
                  {ownedConfigs.map(cfg => (
                    <ProviderCard
                      key={cfg.id}
                      config={cfg}
                      onDelete={async id => { await providersApi.delete(id); setConfigs(prev => prev.filter(c => c.id !== id)); toast.success('Provider disabled') }}
                      onTest={id => providersApi.test(id)}
                      onPatched={updated => setConfigs(prev => prev.map(c => c.id === updated.id ? updated : c))}
                      spaces={spaces}
                    />
                  ))}
                </section>
              )}
              {grantedConfigs.length > 0 && (
                <section className="space-y-3">
                  <h2 className="text-sm font-medium">Usable in this space</h2>
                  {grantedConfigs.map(cfg => (
                    <ProviderCard
                      key={cfg.id}
                      config={cfg}
                      onDelete={async id => { await providersApi.delete(id); setConfigs(prev => prev.filter(c => c.id !== id)); toast.success('Provider disabled') }}
                      onTest={id => providersApi.test(id)}
                      onPatched={updated => setConfigs(prev => prev.map(c => c.id === updated.id ? updated : c))}
                      spaces={spaces}
                    />
                  ))}
                </section>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
