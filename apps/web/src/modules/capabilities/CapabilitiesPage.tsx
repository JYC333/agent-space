import { useState, useEffect, useCallback } from 'react'
import { Zap } from 'lucide-react'
import { toast } from 'sonner'
import { capabilitiesApi } from '../../api/client'
import { useSpace } from '../../contexts/SpaceContext'
import { errMsg } from '../../lib/utils'
import type { Capability } from '../../types/api'
import { Card, CardTitle } from '../../components/ui/card'
import { Button } from '../../components/ui/button'
import { StatusBadge } from '../../components/ui/badge'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '../../components/ui/table'

function fmt(dt: string | null | undefined) { return dt ? new Date(dt).toLocaleString() : '—' }

export default function CapabilitiesPage() {
  const { activeSpaceId, activeSpaceName } = useSpace()
  const [caps, setCaps]           = useState<Capability[]>([])
  const [reloading, setReloading] = useState(false)
  const [selected, setSelected]   = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!activeSpaceId) {
      setCaps([])
      setSelected(null)
      return
    }
    try {
      const data = await capabilitiesApi.list()
      setCaps(data)
      if (data.length && !selected) setSelected(data[0].id)
    } catch (e) { toast.error(errMsg(e)) }
  }, [selected, activeSpaceId])

  useEffect(() => { load() }, [load])

  async function reload() {
    if (!activeSpaceId) {
      toast.error('Select an operational space before reloading capabilities')
      return
    }
    setReloading(true)
    try {
      const r = await capabilitiesApi.reload()
      toast[r.failed ? 'warning' : 'success'](`Loaded ${r.loaded}, failed ${r.failed}`)
      await load()
    } catch (e) { toast.error(errMsg(e)) }
    finally { setReloading(false) }
  }

  const selectedCap = caps.find(c => c.id === selected)

  return (
    <div className="p-6 space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between pb-4 border-b border-border">
        <div className="flex items-center gap-4">
          <div
            className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
            style={{
              background: 'color-mix(in oklch, var(--primary) 12%, transparent)',
              border: '1px solid color-mix(in oklch, var(--primary) 35%, transparent)',
            }}
          >
            <Zap className="size-5 text-accent-foreground" />
          </div>
          <div>
            <h1 className="text-xl font-semibold tracking-tight">Capabilities</h1>
            <p className="text-sm text-muted-foreground">Registered capability manifests available to agents.</p>
            <p className="text-xs text-muted-foreground">Viewing: {activeSpaceName ?? activeSpaceId ?? 'No operational space selected'}</p>
          </div>
        </div>
        <Button variant="ghost" size="sm" onClick={reload} disabled={reloading}>
          {reloading ? 'Reloading…' : '↻ Reload'}
        </Button>
      </div>

      {caps.length === 0
        ? <Card><p className="text-muted-foreground text-center py-10 text-sm">No capabilities loaded.</p></Card>
        : (
          <Card>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>ID</TableHead><TableHead>Name</TableHead>
                  <TableHead>Version</TableHead><TableHead>Description</TableHead>
                  <TableHead>Status</TableHead><TableHead>Updated</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {caps.map(c => (
                  <TableRow
                    key={c.id}
                    onClick={() => setSelected(c.id)}
                    className={`cursor-pointer ${selected === c.id ? 'bg-accent/50' : ''}`}
                  >
                    <TableCell className="font-mono text-xs">{c.id}</TableCell>
                    <TableCell>{c.name}</TableCell>
                    <TableCell className="text-muted-foreground">{c.version}</TableCell>
                    <TableCell className="max-w-[240px] truncate text-muted-foreground">{c.description ?? '—'}</TableCell>
                    <TableCell><StatusBadge status={c.enabled ? 'active' : 'archived'} /></TableCell>
                    <TableCell className="text-muted-foreground text-xs">{fmt(c.updated_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>
        )}

      {selectedCap && (
        <Card>
          <CardTitle>Manifest — {selectedCap.id}</CardTitle>
          <pre className="text-xs">{JSON.stringify(selectedCap.manifest_json, null, 2)}</pre>
        </Card>
      )}
    </div>
  )
}
