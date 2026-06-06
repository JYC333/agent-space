import { useState, useEffect, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { SpaceLink as Link } from '../../core/spaceNav'
import { Package, FolderKanban, X } from 'lucide-react'
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
import { ScopeBadge } from '../../components/ScopeBadge'

function fmt(dt: string | null | undefined) {
  return dt ? new Date(dt).toLocaleString() : '—'
}

export default function ArtifactsPage() {
  const { activeSpaceId, activeSpaceName } = useSpace()
  const [searchParams, setSearchParams] = useSearchParams()
  const projectFilter = searchParams.get('project_id') ?? ''

  const [items, setItems] = useState<Artifact[]>([])
  const [loading, setLoading] = useState(true)
  const [fType, setFType] = useState('')

  const load = useCallback(async () => {
    if (!activeSpaceId) {
      setItems([])
      setLoading(false)
      return
    }
    setLoading(true)
    try {
      const p = await artifactsApi.list({
        limit: 100,
        artifact_type: fType.trim() || undefined,
        project_id: projectFilter || undefined,
      })
      setItems(p.items)
    } catch (e) {
      toast.error(errMsg(e))
      setItems([])
    } finally {
      setLoading(false)
    }
  }, [fType, projectFilter, activeSpaceId])

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
          <p className="text-xs text-muted-foreground">Viewing: {activeSpaceName ?? activeSpaceId ?? 'No operational space selected'}</p>
          {projectFilter && (
            <span className="inline-flex items-center gap-1 mt-0.5 px-2 py-0.5 rounded-full bg-accent/40 text-xs text-accent-foreground">
              <FolderKanban className="size-3" />
              Filtered by project
              <button onClick={() => setSearchParams(p => { p.delete('project_id'); return p })} className="ml-0.5 hover:text-foreground" aria-label="Clear project filter">
                <X className="size-3" />
              </button>
            </span>
          )}
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
        <Card className="p-10 text-center text-sm text-muted-foreground">
          {activeSpaceId ? 'No artifacts.' : 'Select an operational space to browse artifacts.'}
        </Card>
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
                  <ScopeBadge visibility={a.visibility} omitShared />
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
