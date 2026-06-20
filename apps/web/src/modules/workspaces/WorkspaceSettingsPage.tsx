import { useState, useEffect, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { History, ArrowLeft, ShieldAlert, Folder } from 'lucide-react'
import { toast } from 'sonner'
import { workspacesApi, spacesApi } from '../../api/client'
import { useSpace } from '../../contexts/SpaceContext'
import { errMsg } from '../../lib/utils'
import type { MemberRole, Workspace, SpaceSnapshotDefaults } from '../../types/api'
import { Card, CardTitle } from '../../components/ui/card'
import { Button } from '../../components/ui/button'
import { Input } from '../../components/ui/input'
import { Badge } from '../../components/ui/badge'
import { SpaceLink as Link } from '../../core/spaceNav'

const BUILTIN_RETENTION_DAYS = 7
const BUILTIN_MAX_COUNT = 20

function canManageSpace(role: MemberRole | undefined): boolean {
  return role === 'owner' || role === 'admin'
}

function fmt(dt: string) {
  return new Date(dt).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

export default function WorkspaceSettingsPage() {
  const { id } = useParams<{ id: string }>()
  const { activeSpaceId, spaces } = useSpace()
  const activeSpace = spaces.find(s => s.id === activeSpaceId)
  const manageable = canManageSpace(activeSpace?.role)

  const [workspace, setWorkspace] = useState<Workspace | null>(null)
  const [spaceDefaults, setSpaceDefaults] = useState<SpaceSnapshotDefaults | null>(null)
  const [loading, setLoading] = useState(true)
  const [retentionDays, setRetentionDays] = useState('')
  const [maxCount, setMaxCount] = useState('')
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    if (!id || !activeSpaceId) return
    setLoading(true)
    try {
      const [ws, defaults] = await Promise.all([
        workspacesApi.get(id),
        manageable ? spacesApi.getSnapshotDefaults(activeSpaceId) : Promise.resolve(null),
      ])
      setWorkspace(ws)
      setSpaceDefaults(defaults)
      setRetentionDays(ws.snapshot_retention_days !== null ? String(ws.snapshot_retention_days) : '')
      setMaxCount(ws.snapshot_max_count !== null ? String(ws.snapshot_max_count) : '')
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setLoading(false)
    }
  }, [id, activeSpaceId, manageable])

  useEffect(() => { void load() }, [load])

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    if (!id) return
    const days = retentionDays.trim() ? parseInt(retentionDays, 10) : null
    const count = maxCount.trim() ? parseInt(maxCount, 10) : null
    if (days !== null && (isNaN(days) || days < 1)) { toast.error('Retention days must be a positive integer'); return }
    if (count !== null && (isNaN(count) || count < 1)) { toast.error('Max count must be a positive integer'); return }
    setSaving(true)
    try {
      await workspacesApi.update(id, { snapshot_retention_days: days, snapshot_max_count: count })
      toast.success('Snapshot settings saved')
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setSaving(false)
    }
  }

  const effectiveRetention = spaceDefaults?.snapshot_retention_days_default ?? BUILTIN_RETENTION_DAYS
  const effectiveMax = spaceDefaults?.snapshot_max_count_default ?? BUILTIN_MAX_COUNT

  return (
    <div className="p-6 space-y-4 max-w-2xl">
      {/* Back + header */}
      <div className="flex items-center gap-3 pb-4 border-b border-border">
        <Link
          to="/workspaces"
          className="text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft className="size-4" />
        </Link>
        <div
          className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
          style={{
            background: 'color-mix(in oklch, var(--primary) 12%, transparent)',
            border: '1px solid color-mix(in oklch, var(--primary) 35%, transparent)',
          }}
        >
          <Folder className="size-4 text-accent-foreground" />
        </div>
        <div className="min-w-0">
          <h1 className="text-lg font-semibold tracking-tight truncate">
            {loading ? 'Loading…' : (workspace?.name ?? 'Workspace not found')}
          </h1>
          <p className="text-xs text-muted-foreground">Workspace settings</p>
        </div>
      </div>

      {!loading && workspace && (
        <>
          {/* Info */}
          <Card>
            <CardTitle>Info</CardTitle>
            <div className="space-y-1.5 text-sm">
              <div className="flex items-center gap-2">
                <span className="text-muted-foreground w-24 shrink-0">Status</span>
                <Badge variant={workspace.status === 'active' ? 'default' : 'muted'} className="text-[10px] px-1.5 py-0">
                  {workspace.status}
                </Badge>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-muted-foreground w-24 shrink-0">Type</span>
                <Badge variant="muted" className="text-[10px] px-1.5 py-0">{workspace.workspace_type}</Badge>
                <Badge variant="muted" className="text-[10px] px-1.5 py-0">{workspace.kind}</Badge>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-muted-foreground w-24 shrink-0">Created</span>
                <span className="text-foreground">{fmt(workspace.created_at)}</span>
              </div>
              <div className="flex items-start gap-2">
                <span className="text-muted-foreground w-24 shrink-0 mt-0.5">ID</span>
                <span className="font-mono text-xs text-muted-foreground break-all">{workspace.id}</span>
              </div>
              {workspace.root_path && (
                <div className="flex items-start gap-2">
                  <span className="text-muted-foreground w-24 shrink-0 mt-0.5">Path</span>
                  <span className="font-mono text-xs text-muted-foreground break-all">{workspace.root_path}</span>
                </div>
              )}
            </div>
          </Card>

          {/* Snapshot settings */}
          <Card>
            <CardTitle className="flex items-center gap-2">
              <History className="size-3.5" /> Snapshot settings
            </CardTitle>
            {!manageable ? (
              <div className="flex items-start gap-2 text-sm text-muted-foreground">
                <ShieldAlert className="size-4 shrink-0 mt-0.5 text-muted-foreground" />
                <span>Only space owners and admins can configure snapshot settings.</span>
              </div>
            ) : (
              <form onSubmit={handleSave} className="space-y-4">
                <p className="text-sm text-muted-foreground">
                  Leave blank to use the space default ({effectiveRetention} days · {effectiveMax} max snapshots).
                </p>
                <div className="flex items-end gap-4">
                  <div className="flex flex-col gap-1">
                    <label className="text-[10px] text-muted-foreground font-medium uppercase tracking-wide">
                      Retention (days)
                    </label>
                    <Input
                      type="number"
                      min={1}
                      placeholder={String(effectiveRetention)}
                      value={retentionDays}
                      onChange={e => setRetentionDays(e.target.value)}
                      className="h-8 w-28 text-sm"
                    />
                  </div>
                  <div className="flex flex-col gap-1">
                    <label className="text-[10px] text-muted-foreground font-medium uppercase tracking-wide">
                      Max snapshots
                    </label>
                    <Input
                      type="number"
                      min={1}
                      placeholder={String(effectiveMax)}
                      value={maxCount}
                      onChange={e => setMaxCount(e.target.value)}
                      className="h-8 w-28 text-sm"
                    />
                  </div>
                  <Button type="submit" size="sm" disabled={saving}>
                    {saving ? 'Saving…' : 'Save'}
                  </Button>
                </div>
              </form>
            )}
          </Card>
        </>
      )}
    </div>
  )
}
