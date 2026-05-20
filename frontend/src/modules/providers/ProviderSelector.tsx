import { useEffect, useState } from 'react'
import { providersApi, type ModelProviderOut } from '../../api/client'

interface ProviderSelectorProps {
  value: { provider_id: string; model: string } | null
  onChange: (value: { provider_id: string; model: string } | null) => void
}

export default function ProviderSelector({ value, onChange }: ProviderSelectorProps) {
  const [providers, setProviders] = useState<ModelProviderOut[]>([])
  const [models, setModels] = useState<string[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    providersApi.list()
      .then(list => setProviders(list.filter(p => p.enabled)))
      .catch(() => setProviders([]))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (!value?.provider_id) {
      setModels([])
      return
    }
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
      <p className="text-sm text-muted-foreground">
        No enabled model providers.{' '}
        <a href="/providers" className="text-primary hover:underline">Configure one</a>
      </p>
    )
  }

  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Model provider</label>
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
          <option value="">System default</option>
          {providers.map(p => (
            <option key={p.id} value={p.id}>{p.name} ({p.provider_type})</option>
          ))}
        </select>
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
