import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { SpaceLink as Link } from '../../core/spaceNav'
import { ArrowLeft } from 'lucide-react'
import { toast } from 'sonner'
import { artifactsApi } from '../../api/client'
import { useSpace } from '../../contexts/SpaceContext'
import { errMsg } from '../../lib/utils'
import type { Artifact } from '../../types/api'
import { Card } from '../../components/ui/card'
import { Button } from '../../components/ui/button'
import { Badge } from '../../components/ui/badge'
import { Skeleton } from '../../components/ui/skeleton'
import { PreviewBadge } from '../../components/PreviewBadge'
import { ScopeBadge } from '../../components/ScopeBadge'
import { ArtifactInlineRenderer } from './ArtifactRendererRegistry'

function fmt(dt: string | null | undefined) {
  return dt ? new Date(dt).toLocaleString() : '—'
}

export default function ArtifactDetailPage() {
  const { artifactId = '' } = useParams()
  const { activeSpaceId, activeSpaceName } = useSpace()
  const [a, setA] = useState<Artifact | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!artifactId) return
    if (!activeSpaceId) {
      setA(null)
      setLoading(false)
      return
    }
    let cancelled = false
    ;(async () => {
      setLoading(true)
      try {
        const r = await artifactsApi.get(artifactId)
        if (!cancelled) setA(r)
      } catch (e) {
        if (!cancelled) {
          toast.error(errMsg(e))
          setA(null)
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [artifactId, activeSpaceId])

  async function exportArt() {
    if (!a) return
    try {
      await artifactsApi.export(a.id)
      toast.success('Download started')
    } catch (e) {
      toast.error(errMsg(e))
    }
  }

  return (
    <div className="p-6 space-y-6 max-w-3xl">
      <Button variant="ghost" size="sm" asChild>
        <Link to="/artifacts"><ArrowLeft className="size-4 mr-1" />Artifacts</Link>
      </Button>

      {loading && <Skeleton className="h-40 w-full" />}

      {!loading && !a && (
        <Card className="p-8 text-center text-sm text-muted-foreground">
          {activeSpaceId ? 'Artifact not found.' : 'Select an operational space to inspect this artifact.'}
        </Card>
      )}

      {!loading && a && (
        <Card className="p-5 space-y-4">
          <div className="flex flex-wrap justify-between gap-3">
            <h1 className="text-lg font-semibold tracking-tight">{a.title}</h1>
            <Button size="sm" variant="outline" onClick={exportArt}>Export</Button>
          </div>
          <p className="text-xs text-muted-foreground">Viewing: {activeSpaceName ?? activeSpaceId ?? 'No operational space selected'}</p>
          <div className="flex flex-wrap gap-1.5 items-center text-xs text-muted-foreground">
            <Badge variant="secondary">{a.artifact_type}</Badge>
            <ScopeBadge visibility={a.visibility} />
            {a.preview && <PreviewBadge />}
            <span>{fmt(a.created_at)}</span>
            {a.run_id && (
              <Link to={`/runs/${a.run_id}`} className="text-accent-foreground hover:underline ml-2">
                Open run
              </Link>
            )}
          </div>
          <ArtifactInlineRenderer artifact={a} />
        </Card>
      )}
    </div>
  )
}
