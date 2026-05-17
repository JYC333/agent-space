import { useState, useEffect, useId, useRef } from 'react'
import { KeyRound, CheckCircle, AlertCircle, Loader2, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { providersApi } from '../../api/client'
import { useSpace } from '../../contexts/SpaceContext'
import { Card, CardTitle } from '../../components/ui/card'
import { Button } from '../../components/ui/button'
import { Input } from '../../components/ui/input'
import { Badge } from '../../components/ui/badge'
import { errMsg } from '../../lib/utils'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ProviderConfig {
  id: string
  space_id: string
  name: string
  provider: string
  models: string[]
  api_base: string | null
  is_default: boolean
  status: string
  created_at: string
  updated_at: string
}

interface CatalogInfo {
  id: string
  name: string
  description: string
  model_hint: string
}

// ---------------------------------------------------------------------------
// Provider Selector with autocomplete
// ---------------------------------------------------------------------------

const PROVIDER_SUGGESTIONS: Record<string, { model_placeholder: string; api_base_placeholder: string }> = {
  openai:       { model_placeholder: 'gpt-4o', api_base_placeholder: 'https://api.openai.com/v1' },
  anthropic:    { model_placeholder: 'claude-3-5-sonnet-20241022', api_base_placeholder: '' },
  azure:        { model_placeholder: 'gpt-4o', api_base_placeholder: 'https://YOUR_RESOURCE.openai.azure.com/v1' },
  vertex_ai:    { model_placeholder: 'gemini-2.0-flash', api_base_placeholder: '' },
  gemini:       { model_placeholder: 'gemini-2.0-flash', api_base_placeholder: 'https://generativelanguage.googleapis.com/v1' },
  deepseek:     { model_placeholder: 'deepseek-chat', api_base_placeholder: 'https://api.deepseek.com/v1' },
  together_ai:  { model_placeholder: 'meta-llama/Llama-3-70b-chat-hf', api_base_placeholder: '' },
  openrouter:   { model_placeholder: 'anthropic/claude-3.5-sonnet', api_base_placeholder: '' },
  groq:         { model_placeholder: 'llama-3.3-70b-versatile', api_base_placeholder: '' },
  mistral:      { model_placeholder: 'mistral-large-latest', api_base_placeholder: 'https://api.mistral.ai/v1' },
  cerebras:     { model_placeholder: 'llama-3.3-70b', api_base_placeholder: 'https://api.cerebras.ai/v1' },
  fireworks_ai: { model_placeholder: 'accounts/fireworks/models/llama-3.3-70b-instruct', api_base_placeholder: '' },
  'v0':         { model_placeholder: 'v0', api_base_placeholder: '' },
  zai:          { model_placeholder: 'glm-4-flash', api_base_placeholder: 'https://open.bigmodel.cn/api/paas/v4' },
  databricks:   { model_placeholder: 'databricks-meta-llama-3-70b-instruct', api_base_placeholder: '' },
  bedrock:      { model_placeholder: 'anthropic.claude-3-5-sonnet-20241022', api_base_placeholder: '' },
}

function ProviderSelector({
  value,
  onChange,
}: {
  value: string
  onChange: (provider: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState(value)
  const [providers, setProviders] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    setQuery(value)
  }, [value])

  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  useEffect(() => {
    setLoading(true)
    providersApi.litellmProviders().then(list => {
      setProviders(list)
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [])

  const filtered = query
    ? providers.filter(p => p.toLowerCase().includes(query.toLowerCase()))
    : providers.slice(0, 30)

  function handleInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const v = e.target.value
    setQuery(v)
    onChange(v)
    setOpen(true)
  }

  function select(p: string) {
    onChange(p)
    setQuery(p)
    setOpen(false)
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      setOpen(false)
    }
  }

  return (
    <div className="relative" ref={ref}>
      <div className="flex items-center gap-1.5">
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={handleInputChange}
          onFocus={() => setOpen(true)}
          onKeyDown={handleKeyDown}
          placeholder="Search or type provider…"
          className="flex-1 h-9 rounded-md border border-border bg-input px-3 text-sm font-mono text-foreground placeholder:text-muted-foreground hover:bg-accent focus:outline-none focus:ring-1 focus:ring-ring transition-colors"
        />
        <button
          type="button"
          onClick={() => { setOpen(o => !o); inputRef.current?.focus() }}
          className="shrink-0 h-9 px-2 rounded-md border border-border hover:bg-accent transition-colors flex items-center justify-center"
        >
          <ChevronDown size={13} className="text-muted-foreground" />
        </button>
      </div>

      {open && (
        <div className="absolute z-50 w-full mt-1 border border-border bg-card rounded-lg shadow-md overflow-hidden">
          <div className="max-h-60 overflow-y-auto">
            {loading && (
              <div className="px-3 py-2 text-xs text-muted-foreground">Loading providers…</div>
            )}
            {!loading && filtered.length === 0 && query && (
              <div className="px-3 py-2 text-xs text-muted-foreground">No match — type to add custom</div>
            )}
            {!loading && filtered.map(p => (
              <button
                key={p}
                type="button"
                onClick={() => select(p)}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-left text-sm transition-colors hover:bg-accent"
              >
                <span className="flex-1 truncate font-mono text-xs">{p}</span>
                {p === value && <Check size={11} className="shrink-0 text-accent-foreground" />}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function ChevronDown({ size, className }: { size: number; className?: string }) {
  const s = String(size)
  return <svg xmlns="http://www.w3.org/2000/svg" width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><path d="m6 9 6 6 6-6"/></svg>
}
function Check({ size, className }: { size: number; className?: string }) {
  const s = String(size)
  return <svg xmlns="http://www.w3.org/2000/svg" width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><path d="M20 6 9 17l-5-5"/></svg>
}

// ---------------------------------------------------------------------------
// Add Provider Form
// ---------------------------------------------------------------------------

function AddProviderForm({ onAdded, canCreate }: { onAdded: () => void; canCreate: boolean }) {
  const [name, setName] = useState('')
  const [provider, setProvider] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [models, setModels] = useState('')
  const [apiBase, setApiBase] = useState('')
  const [isDefault, setIsDefault] = useState(false)
  const [saving, setSaving] = useState(false)
  const [expanded, setExpanded] = useState(false)

  // Auto-fill model placeholder and api_base when provider changes
  useEffect(() => {
    if (!provider) return
    const hint = PROVIDER_SUGGESTIONS[provider]
    if (hint) {
      if (hint.api_base_placeholder && !apiBase) setApiBase(hint.api_base_placeholder)
    }
  }, [provider])

  function reset() {
    setName('')
    setProvider('')
    setApiKey('')
    setModels('')
    setApiBase('')
    setIsDefault(false)
    setExpanded(false)
  }

  function handleProviderChange(p: string) {
    setProvider(p)
    // Auto-fill model placeholder
    const hint = PROVIDER_SUGGESTIONS[p]
    if (hint && !models) setModels(hint.model_placeholder)
    // Auto-fill api_base for known providers
    if (hint?.api_base_placeholder && !apiBase) setApiBase(hint.api_base_placeholder)
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!provider.trim() || !apiKey.trim()) return
    if (!canCreate) {
      toast.error('Select an operational space before adding a provider')
      return
    }

    setSaving(true)
    try {
      const modelList = models
        ? models.split(',').map(m => m.trim()).filter(Boolean)
        : []
      await providersApi.create({
        name: name || provider,
        provider: provider.trim(),
        api_key: apiKey.trim(),
        models: modelList,
        api_base: apiBase.trim() || undefined,
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
        <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Provider</label>
        <ProviderSelector value={provider} onChange={handleProviderChange} />
        <p className="text-xs text-muted-foreground">
          选择 provider 后 Models 和 API Base 会自动填充
        </p>
      </div>

      <div className="space-y-1.5">
        <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Display name</label>
        <Input
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder="My OpenAI"
          className="text-sm"
        />
      </div>

      <div className="space-y-1.5">
        <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
          API Key <span className="text-warning">*</span>
        </label>
        <Input
          type="password"
          value={apiKey}
          onChange={e => setApiKey(e.target.value)}
          placeholder="sk-…"
          className="font-mono text-sm"
        />
      </div>

      <div className="space-y-1.5">
        <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Models</label>
        <Input
          value={models}
          onChange={e => setModels(e.target.value)}
          placeholder={provider && PROVIDER_SUGGESTIONS[provider]
            ? PROVIDER_SUGGESTIONS[provider].model_placeholder
            : 'e.g. gpt-4o, gpt-4o-mini'}
          className="text-sm font-mono"
        />
        <p className="text-xs text-muted-foreground">Comma-separated model names</p>
      </div>

      <div className="space-y-1.5">
        <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">API Base <span className="text-muted-foreground">(optional)</span></label>
        <Input
          value={apiBase}
          onChange={e => setApiBase(e.target.value)}
          placeholder={provider && PROVIDER_SUGGESTIONS[provider]?.api_base_placeholder
            ? PROVIDER_SUGGESTIONS[provider].api_base_placeholder
            : 'https://…'}
          className="text-sm font-mono"
        />
      </div>

      <div className="flex items-center gap-2">
        <input
          type="checkbox"
          id="is-default"
          checked={isDefault}
          onChange={e => setIsDefault(e.target.checked)}
          className="accent-primary"
        />
        <label htmlFor="is-default" className="text-[13px]">Set as default provider</label>
      </div>

      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={!canCreate || !provider.trim() || !apiKey.trim() || saving}>
          {saving ? <Loader2 className="size-3.5 animate-spin" /> : 'Add provider'}
        </Button>
        <Button type="button" size="sm" variant="outline" onClick={reset}>Cancel</Button>
      </div>
    </form>
  )
}

// ---------------------------------------------------------------------------
// Provider Card
// ---------------------------------------------------------------------------

function ProviderCard({
  config,
  onDelete,
  onTest,
  onUpdate,
}: {
  config: ProviderConfig
  onDelete: (id: string) => void
  onTest: (id: string) => Promise<{ success: boolean; message: string }>
  onUpdate: (id: string, data: { name: string; models: string[]; api_base: string }) => Promise<void>
}) {
  const [deleting, setDeleting] = useState(false)
  const [testing, setTesting] = useState(false)
  const [editing, setEditing] = useState(false)
  const [editName, setEditName] = useState(config.name)
  const [editModels, setEditModels] = useState(config.models.join(', '))
  const [editApiBase, setEditApiBase] = useState(config.api_base ?? '')
  const [saving, setSaving] = useState(false)
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null)

  function startEdit() {
    setEditName(config.name)
    setEditModels(config.models.join(', '))
    setEditApiBase(config.api_base ?? '')
    setEditing(true)
  }

  function cancelEdit() {
    setEditing(false)
  }

  async function handleSave() {
    setSaving(true)
    try {
      const modelList = editModels.split(',').map(m => m.trim()).filter(Boolean)
      await onUpdate(config.id, {
        name: editName,
        models: modelList,
        api_base: editApiBase,
      })
      setEditing(false)
    } catch (err) {
      toast.error(errMsg(err))
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete() {
    setDeleting(true)
    try {
      await onDelete(config.id)
    } finally {
      setDeleting(false)
    }
  }

  async function handleTest() {
    setTesting(true)
    setTestResult(null)
    try {
      const result = await onTest(config.id)
      setTestResult(result)
    } finally {
      setTesting(false)
    }
  }

  if (editing) {
    return (
      <Card>
        <div className="space-y-3 p-4">
          <div className="space-y-1.5">
            <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Display name</label>
            <Input
              value={editName}
              onChange={e => setEditName(e.target.value)}
              placeholder="My ZAI"
              className="text-sm"
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Models</label>
            <Input
              value={editModels}
              onChange={e => setEditModels(e.target.value)}
              placeholder="glm-4.7-flash"
              className="text-sm font-mono"
            />
            <p className="text-xs text-muted-foreground">Comma-separated model names</p>
          </div>
          <div className="space-y-1.5">
            <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">API Base <span className="text-muted-foreground">(optional)</span></label>
            <Input
              value={editApiBase}
              onChange={e => setEditApiBase(e.target.value)}
              placeholder="https://api.zai.com/v1"
              className="text-sm font-mono"
            />
          </div>
          <div className="flex gap-2">
            <Button size="sm" onClick={handleSave} disabled={saving}>
              {saving ? <Loader2 className="size-3.5 animate-spin" /> : 'Save'}
            </Button>
            <Button size="sm" variant="outline" onClick={cancelEdit}>Cancel</Button>
          </div>
        </div>
      </Card>
    )
  }

  return (
    <Card>
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2">
          <CardTitle>{config.name}</CardTitle>
          {config.is_default && (
            <Badge variant="default" className="text-[10px] gap-1">
              Default
            </Badge>
          )}
          {config.status !== 'active' && (
            <Badge variant="muted" className="text-[10px]">{config.status}</Badge>
          )}
        </div>
        <span className="text-[10px] font-mono text-muted-foreground">{config.provider}</span>
      </div>

      <div className="flex flex-wrap gap-1 mb-3">
        {config.models.map(m => (
          <Badge key={m} variant="muted" className="text-[10px] font-mono">{m}</Badge>
        ))}
        {config.models.length === 0 && (
          <span className="text-[10px] text-muted-foreground">No models</span>
        )}
      </div>

      {testResult && (
        <div className={`text-xs mb-3 p-2 rounded-md ${testResult.success ? 'bg-green-500/10 text-green-600' : 'bg-red-500/10 text-red-500'}`}>
          {testResult.success ? <CheckCircle className="size-3 inline mr-1" /> : <AlertCircle className="size-3 inline mr-1" />}
          {testResult.message}
        </div>
      )}

      <div className="flex gap-2">
        <Button size="sm" variant="outline" onClick={handleTest} disabled={testing}>
          {testing ? <Loader2 className="size-3.5 animate-spin" /> : 'Test'}
        </Button>
        <Button size="sm" variant="outline" onClick={startEdit}>
          Edit
        </Button>
        <Button size="sm" variant="outline" onClick={handleDelete} disabled={deleting} className="text-red-500 hover:text-red-600">
          {deleting ? <Loader2 className="size-3.5 animate-spin" /> : <Trash2 className="size-3.5" />}
        </Button>
      </div>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function ModelProvidersPage() {
  const { activeOperationalSpaceId, activeOperationalSpaceName } = useSpace()
  const [configs, setConfigs] = useState<ProviderConfig[]>([])
  const [catalog, setCatalog] = useState<CatalogInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState<'configured' | 'catalog'>('configured')

  const headingId = useId()

  useEffect(() => {
    loadAll()
  }, [activeOperationalSpaceId])

  async function loadAll() {
    setLoading(true)
    try {
      if (!activeOperationalSpaceId) {
        const cat = await providersApi.catalog()
        setConfigs([])
        setCatalog(cat as CatalogInfo)
        return
      }
      const [cfg, cat] = await Promise.all([
        providersApi.list(),
        providersApi.catalog(),
      ])
      setConfigs(cfg)
      setCatalog(cat as CatalogInfo)
    } catch (err) {
      toast.error(errMsg(err))
    } finally {
      setLoading(false)
    }
  }

  async function handleDelete(id: string) {
    await providersApi.delete(id)
    setConfigs(prev => prev.filter(c => c.id !== id))
    toast.success('Provider removed')
  }

  async function handleTest(id: string) {
    return await providersApi.test(id)
  }

  async function handleUpdate(id: string, data: { name: string; models: string[]; api_base: string }) {
    const updated = await providersApi.update(id, {
      name: data.name,
      models: data.models,
      api_base: data.api_base || undefined,
    })
    setConfigs(prev => prev.map(c => c.id === id ? { ...c, ...updated } : c))
    toast.success('Provider updated')
  }

  return (
    <div className="p-6 space-y-6 max-w-2xl" id={headingId}>
      {/* Page header */}
      <div className="flex items-center gap-4 pb-4 border-b border-border">
        <div
          className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
          style={{
            background: 'color-mix(in oklch, var(--primary) 12%, transparent)',
            border: '1px solid color-mix(in oklch, var(--primary) 35%, transparent)',
          }}
        >
          <KeyRound className="size-5 text-accent-foreground" />
        </div>
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Model Providers</h1>
          <p className="text-sm text-muted-foreground">
            Configure LLM providers via LiteLLM — any model name LiteLLM supports works.
          </p>
          <p className="text-xs text-muted-foreground">
            Viewing: {activeOperationalSpaceName ?? activeOperationalSpaceId ?? 'No operational space selected'}
          </p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-border">
        {(['configured', 'catalog'] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-3 py-2 text-[13px] font-medium border-b-2 -mb-px transition-colors ${
              tab === t
                ? 'border-primary text-foreground'
                : 'border-transparent text-muted-foreground hover:text-foreground'
            }`}
          >
            {t === 'configured' ? `Configured (${configs.length})` : 'About'}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-12 text-muted-foreground">
          <Loader2 className="size-5 animate-spin mr-2" />
          <span>Loading…</span>
        </div>
      ) : tab === 'configured' ? (
        <div className="space-y-4">
          <AddProviderForm onAdded={loadAll} canCreate={Boolean(activeOperationalSpaceId)} />

          {configs.length === 0 ? (
            <Card>
              <p className="text-sm text-muted-foreground">
                {activeOperationalSpaceId
                  ? 'No providers configured yet. Add one to get started.'
                  : 'Select an operational space to configure providers.'}
              </p>
            </Card>
          ) : (
            configs.map(cfg => (
              <ProviderCard
                key={cfg.id}
                config={cfg}
                onDelete={handleDelete}
                onTest={handleTest}
                onUpdate={handleUpdate}
              />
            ))
          )}
        </div>
      ) : (
        <Card>
          <CardTitle>{catalog?.name ?? 'LiteLLM'}</CardTitle>
          <p className="text-sm text-muted-foreground mt-2">{catalog?.description}</p>
          {catalog?.model_hint && (
            <p className="text-xs text-muted-foreground mt-1 font-mono">{catalog.model_hint}</p>
          )}
        </Card>
      )}
    </div>
  )
}
