import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { Package } from 'lucide-react'
import { toast } from 'sonner'
import { artifactsApi } from '../../api/client'
import { useSpace } from '../../contexts/SpaceContext'
import { errMsg } from '../../lib/utils'
import type { Artifact } from '../../types/api'
import { Card } from '../../components/ui/card'
import { Button } from '../../components/ui/button'
import { Badge } from '../../components/ui/badge'
import { Label } from '../../components/ui/label'
import { Select } from '../../components/ui/select'
import { Skeleton } from '../../components/ui/skeleton'
import { PreviewBadge } from '../../components/PreviewBadge'

function fmt(dt: string | null | undefined) {
  return dt ? new Date(dt).toLocaleString() : '—'
}

export default function ArtifactsPage() {
  const { spaceId } = useSpace()
  const [items, setItems] = useState<Artifact[]>([])
  const [loading, setLoading] = useState(true)
  const [fType, setFType] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const q: Record<string, string> = { limit: '100' }
      if (fType.trim()) q.artifact_type = fType.trim()
      const p = await artifactsApi.list(q)
      setItems(p.items)
    } catch (e) {
      toast.error(errMsg(e))
      setItems([])
    } finally {
      setLoading(false)
    }
  }, [fType, spaceId])

  useEffect(() => { load() }, [load])

  const types = Array.from(new Set(items.map(a => a.artifact_type))).sort()

  async function dl(id: string) {
    try {
      await artifactsApi.export(id)
      toast.success('Download started')
    } catch (e) {
      toast.error(errMsg(e))
    }
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center gap-4 pb-4 border-b border-border">
        <div
          className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
          style={{
            background: 'color-mix(in oklch, var(--primary) 12%, transparent)',
            border: '1px solid color-mix(in oklch, var(--primary) 35%, transparent)',
          }}
        >
          <Package className="size-5 text-accent-foreground" />
        </div>
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Artifacts</h1>
          <p className="text-sm text-muted-foreground">Browse and export space-scoped artifacts.</p>
        </div>
      </div>

      <div className="flex flex-wrap gap-3 items-end">
        <div className="min-w-[180px]">
          <Label className="text-xs">artifact_type</Label>
          <Select
            value={fType}
            options={[
              { value: '', label: 'All (loaded page)' },
              ...types.map(t => ({ value: t, label: t })),
            ]}
            onChange={setFType}
          />
        </div>
        <Button variant="secondary" size="sm" onClick={load}>Refresh</Button>
      </div>

      {loading ? (
        <Card className="p-6"><Skeleton className="h-24 w-full" /></Card>
      ) : items.length === 0 ? (
        <Card className="p-10 text-center text-sm text-muted-foreground">No artifacts.</Card>
      ) : (
        <div className="space-y-3">
          {items.map(a => (
            <Card key={a.id} className="p-4 flex flex-wrap justify-between gap-3">
              <div className="min-w-0">
                <div className="font-medium text-sm truncate">
                  <Link to={`/artifacts/${a.id}`} className="text-accent-foreground hover:underline">
                    {a.title}
                  </Link>
                </div>
                <div className="flex flex-wrap gap-1.5 mt-1 items-center">
                  <Badge variant="secondary">{a.artifact_type}</Badge>
                  {a.preview && <PreviewBadge />}
                  <span className="text-xs text-muted-foreground">{fmt(a.created_at)}</span>
                </div>
                {a.run_id && (
                  <Link to={`/runs/${a.run_id}`} className="text-xs text-accent-foreground hover:underline mt-2 inline-block">
                    Run {a.run_id.slice(0, 10)}…
                  </Link>
                )}
              </div>
              <Button size="sm" variant="outline" onClick={() => dl(a.id)}>Export</Button>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
