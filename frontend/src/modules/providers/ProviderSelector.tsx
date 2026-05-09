import { useState, useEffect } from 'react'
import { ChevronDown } from 'lucide-react'
import { providersApi } from '../../api/client'

interface ProviderOption {
  id: string
  name: string
  provider: string
  models: string[]
}

interface ProviderSelectorProps {
  value: { provider_id: string; model: string } | null
  onChange: (value: { provider_id: string; model: string } | null) => void
  className?: string
}

export function ProviderSelector({ value, onChange, className }: ProviderSelectorProps) {
  const [providers, setProviders] = useState<ProviderOption[]>([])
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    providersApi.list().then(setProviders).catch(() => setProviders([])).finally(() => setLoading(false))
  }, [])

  const selected = providers.find(p => p.id === value?.provider_id)

  return (
    <div className={`relative ${className ?? ''}`}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-2 h-8 px-3 rounded-md border border-border bg-background text-[13px] text-left hover:bg-accent transition-colors w-full"
      >
        {loading ? (
          <span className="text-muted-foreground">Loading…</span>
        ) : selected ? (
          <>
            <span className="font-medium">{selected.name}</span>
            <span className="text-muted-foreground">·</span>
            <span className="font-mono text-[11px] text-muted-foreground">{value?.model}</span>
          </>
        ) : (
          <span className="text-muted-foreground">Select provider…</span>
        )}
        <ChevronDown className="size-3.5 ml-auto text-muted-foreground" />
      </button>

      {open && (
        <div className="absolute top-[calc(100%+4px)] left-0 w-64 bg-card border border-border rounded-lg shadow-lg z-50 py-1 max-h-64 overflow-y-auto">
          {providers.length === 0 ? (
            <div className="px-3 py-2 text-xs text-muted-foreground">
              No providers configured.{' '}
              <a href="/providers" className="text-primary hover:underline">Add one</a>
            </div>
          ) : (
            providers.map(p => (
              <div key={p.id}>
                <div className="px-3 py-1.5 text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
                  {p.name}
                </div>
                {p.models.map(m => (
                  <button
                    key={m}
                    type="button"
                    onClick={() => {
                      onChange({ provider_id: p.id, model: m })
                      setOpen(false)
                    }}
                    className={`w-full text-left px-3 py-1.5 text-[13px] hover:bg-accent transition-colors ${
                      value?.provider_id === p.id && value?.model === m
                        ? 'text-foreground font-medium'
                        : 'text-muted-foreground'
                    }`}
                  >
                    <span className="font-mono">{m}</span>
                  </button>
                ))}
              </div>
            ))
          )}
        </div>
      )}

      {open && (
        <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
      )}
    </div>
  )
}
