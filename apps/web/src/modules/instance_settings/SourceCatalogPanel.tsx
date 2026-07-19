import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Card, CardHeader, CardTitle } from '../../components/ui/card'
import { sourcesApi } from '../../api/client'
import { errMsg } from '../../lib/utils'
import type { SourceCatalog } from '../../types/api'

/** Instance-admin controls for the published source catalog. Runtime code is never editable here. */
export function SourceCatalogPanel() {
  const [catalog, setCatalog] = useState<SourceCatalog | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setCatalog(await sourcesApi.sourceCatalog())
    } catch (error) {
      toast.error(errMsg(error))
    }
  }, [])

  useEffect(() => { void load() }, [load])

  async function update(key: string, action: () => Promise<unknown>) {
    setBusy(key)
    try {
      await action()
      await load()
    } catch (error) {
      toast.error(errMsg(error))
    } finally {
      setBusy(null)
    }
  }

  if (!catalog) {
    return <Card><CardHeader><CardTitle>Source Catalog</CardTitle></CardHeader><p className="px-6 pb-6 text-sm text-muted-foreground">Loading provider and connector catalog…</p></Card>
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Source Catalog</CardTitle>
        <p className="text-sm text-muted-foreground">Providers and transport implementations are published by the server. Admins can only enable, disable, and reprioritize them.</p>
      </CardHeader>
      <div className="px-6 pb-6 space-y-5">
        <section className="space-y-2">
          <h3 className="text-sm font-medium">Providers</h3>
          {catalog.providers.map(provider => (
            <div key={provider.id} className="flex items-center justify-between gap-3 rounded-md border px-3 py-2">
              <div className="min-w-0"><div className="flex items-center gap-2"><span className="font-medium">{provider.display_name}</span><Badge variant="muted">{provider.provider_key}</Badge><Badge variant="outline">{provider.status}</Badge></div><p className="text-xs text-muted-foreground">Default mapping: {provider.connector_mapping?.connector_key ?? 'unavailable'}</p></div>
              <Button size="sm" variant="outline" disabled={busy === `provider:${provider.id}`} onClick={() => void update(`provider:${provider.id}`, () => sourcesApi.updateCatalogProvider(provider.id, { status: provider.status === 'active' ? 'disabled' : 'active' }))}>{provider.status === 'active' ? 'Disable' : 'Enable'}</Button>
            </div>
          ))}
        </section>

        <section className="space-y-2">
          <h3 className="text-sm font-medium">Connectors</h3>
          {catalog.connectors.map(connector => (
            <div key={connector.id} className="flex items-center justify-between gap-3 rounded-md border px-3 py-2"><div><span className="font-medium">{connector.display_name}</span><span className="ml-2 text-xs text-muted-foreground">{connector.connector_key}</span></div><Button size="sm" variant="outline" disabled={busy === `connector:${connector.id}`} onClick={() => void update(`connector:${connector.id}`, () => sourcesApi.updateCatalogConnector(connector.id, { status: connector.status === 'active' ? 'disabled' : 'active' }))}>{connector.status === 'active' ? 'Disable' : 'Enable'}</Button></div>
          ))}
        </section>

        <section className="space-y-2">
          <h3 className="text-sm font-medium">Provider mappings</h3>
          {catalog.mappings.map(mapping => (
            <div key={mapping.id} className="flex items-center justify-between gap-3 rounded-md border px-3 py-2"><div><span className="font-medium">{mapping.provider_key} → {mapping.connector_key}</span><span className="ml-2 text-xs text-muted-foreground">priority {mapping.priority}</span><Badge className="ml-2" variant="outline">{mapping.status}</Badge></div><div className="flex gap-2"><Button size="sm" variant="outline" disabled={busy === `mapping:${mapping.id}`} onClick={() => void update(`mapping:${mapping.id}`, () => sourcesApi.updateCatalogMapping(mapping.id, { priority: mapping.priority === 0 ? 1 : 0 }))}>Swap priority</Button><Button size="sm" variant="outline" disabled={busy === `mapping:${mapping.id}`} onClick={() => void update(`mapping:${mapping.id}`, () => sourcesApi.updateCatalogMapping(mapping.id, { status: mapping.status === 'active' ? 'disabled' : 'active' }))}>{mapping.status === 'active' ? 'Disable' : 'Enable'}</Button></div></div>
          ))}
        </section>
      </div>
    </Card>
  )
}
