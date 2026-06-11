import { useCallback, useEffect, useState } from 'react'
import { ExternalLink, RefreshCw, Plus } from 'lucide-react'
import { providersApi, type ModelProviderOut } from '../../api/client'

interface ProviderSelectorProps {
  value: { provider_id: string; model: string } | null
  onChange: (value: { provider_id: string; model: string } | null) => void
  /** When true, a provider must be chosen (no "System default" option) and an empty
   *  state nudges the user to define one. */
  required?: boolean
}

/** Opens the Providers page in a new tab so the in-progress form is preserved. */
function ManageProvidersLink({ label = 'Manage providers' }: { label?: string }) {
  return (
    <a
      href="/providers"
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
    >
      <Plus className="size-3" /> {label} <ExternalLink className="size-3" />
    </a>
  )
}

export default function ProviderSelector({ value, onChange, required = false }: ProviderSelectorProps) {
  const [providers, setProviders] = useState<ModelProviderOut[]>([])
  const [models, setModels] = useState<string[]>([])
  const [loading, setLoading] = useState(true)

  const loadProviders = useCallback(() => {
    setLoading(true)
    providersApi.list()
      .then(list => setProviders(list.filter(p => p.enabled)))
      .catch(() => setProviders([]))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { loadProviders() }, [loadProviders])

  useEffect(() => {
    if (!value?.provider_id) { setModels([]); return }
    providersApi.models(value.provider_id)
      .then(r => setModels(r.models))
      .catch(() => {
        const p = providers.find(x => x.id === value.provider_id)
        setModels(p?.available_models ?? (p?.default_model ? [p.default_model] : []))
      })
  }, [value?.provider_id, providers])

  if (loading) {
    return <p className="text-sm text-muted-foreground">Loading providers…</p>
  }

  if (providers.length === 0) {
    return (
      <div className="space-y-2 p-3 rounded-md border border-dashed border-border text-sm">
        <p className="text-muted-foreground">
          No enabled model providers yet.{required ? ' One is required for this runtime.' : ''}
        </p>
        <div className="flex items-center gap-3">
          <a
            href="/providers"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 h-8 px-3 rounded-md bg-primary text-primary-foreground text-xs font-medium hover:opacity-90"
          >
            <Plus className="size-3.5" /> Define a provider <ExternalLink className="size-3" />
          </a>
          <button type="button" onClick={loadProviders} className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
            <RefreshCw className="size-3" /> Refresh
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Model provider</label>
          <div className="flex items-center gap-3">
            <button type="button" onClick={loadProviders} className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
              <RefreshCw className="size-3" /> Refresh
            </button>
            <ManageProvidersLink label="Add" />
          </div>
        </div>
        <select
          value={value?.provider_id ?? ''}
          onChange={e => {
            const id = e.target.value
            if (!id) { onChange(null); return }
            const p = providers.find(x => x.id === id)
            onChange({ provider_id: id, model: p?.default_model ?? '' })
          }}
          className="flex h-9 w-full rounded-md border border-border bg-input px-3 text-sm"
        >
          <option value="">{required ? 'Select a provider…' : 'System default'}</option>
          {providers.map(p => (
            <option key={p.id} value={p.id}>{p.name} ({p.provider_type})</option>
          ))}
        </select>
        {required && !value?.provider_id && (
          <p className="text-xs text-amber-600">This runtime requires a model provider. Not seeing the right one? <ManageProvidersLink label="Add a provider" /></p>
        )}
      </div>
      {value?.provider_id && (
        <div className="space-y-1.5">
          <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Model</label>
          {models.length > 0 ? (
            <select
              value={value.model}
              onChange={e => onChange({ ...value, model: e.target.value })}
              className="flex h-9 w-full rounded-md border border-border bg-input px-3 text-sm font-mono"
            >
              {models.map(m => <option key={m} value={m}>{m}</option>)}
            </select>
          ) : (
            <input
              value={value.model}
              onChange={e => onChange({ ...value, model: e.target.value })}
              placeholder="model name"
              className="flex h-9 w-full rounded-md border border-border bg-input px-3 text-sm font-mono"
            />
          )}
        </div>
      )}
    </div>
  )
}
