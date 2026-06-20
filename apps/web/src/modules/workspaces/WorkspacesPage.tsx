import { useState, useEffect, useCallback, useRef } from 'react'
import { Folder, Plus, Settings } from 'lucide-react'
import { toast } from 'sonner'
import { workspacesApi } from '../../api/client'
import { useSpace } from '../../contexts/SpaceContext'
import { errMsg } from '../../lib/utils'
import type { Workspace } from '../../types/api'
import { Card, CardTitle } from '../../components/ui/card'
import { Button } from '../../components/ui/button'
import { Input } from '../../components/ui/input'
import { Badge } from '../../components/ui/badge'
import { EmptyState } from '../../components/ui/empty-state'
import { SpaceLink as Link } from '../../core/spaceNav'

function fmt(dt: string) {
  return new Date(dt).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

export default function WorkspacesPage() {
  const { activeSpaceId, activeSpaceName } = useSpace()
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [newName, setNewName]       = useState('')
  const [creating, setCreating]     = useState(false)

  const load = useCallback(async () => {
    if (!activeSpaceId) {
      setWorkspaces([])
      return
    }
    try { setWorkspaces((await workspacesApi.list()).items) }
    catch (e) { toast.error(errMsg(e)) }
  }, [activeSpaceId])

  // scanned ref persists across React StrictMode's intentional double-mount so
  // the scan endpoint is only called once per real page visit, not twice.
  const scanned = useRef(false)

  useEffect(() => {
    if (!activeSpaceId) { load(); return }
    if (scanned.current) { load(); return }
    scanned.current = true

    workspacesApi.scan()
      .then(({ created, deleted }) => {
        if (created.length > 0)
          toast.info(`Discovered ${created.length} new workspace${created.length > 1 ? 's' : ''}: ${created.map(w => w.name).join(', ')}`)
        if (deleted.length > 0)
          toast.info(`Removed ${deleted.length} workspace${deleted.length > 1 ? 's' : ''} whose folder was deleted: ${deleted.join(', ')}`)
      })
      .catch(() => {/* non-fatal */})
      .finally(() => load())
  }, [load, activeSpaceId])

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    if (!newName.trim()) return
    if (!activeSpaceId) {
      toast.error('Select an operational space before creating a workspace')
      return
    }
    setCreating(true)
    try {
      await workspacesApi.create({ name: newName.trim(), workspace_type: 'project', kind: 'project' })
      toast.success('Workspace created')
      setNewName('')
      await load()
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="p-6 space-y-4">
      {/* Page header */}
      <div className="flex items-center gap-4 pb-4 border-b border-border">
        <div
          className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
          style={{
            background: 'color-mix(in oklch, var(--primary) 12%, transparent)',
            border: '1px solid color-mix(in oklch, var(--primary) 35%, transparent)',
          }}
        >
          <Folder className="size-5 text-accent-foreground" />
        </div>
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Workspaces</h1>
          <p className="text-sm text-muted-foreground">Projects and knowledge areas within this space.</p>
          <p className="text-xs text-muted-foreground">Viewing: {activeSpaceName ?? activeSpaceId ?? 'No operational space selected'}</p>
        </div>
      </div>

      {/* Create */}
      <Card>
        <CardTitle>New workspace</CardTitle>
        <form onSubmit={handleCreate} className="flex gap-2">
          <Input
            value={newName}
            onChange={e => setNewName(e.target.value)}
            placeholder="Workspace name…"
            className="flex-1"
          />
          <Button type="submit" size="sm" disabled={!newName.trim() || creating || !activeSpaceId}>
            <Plus className="size-3.5 mr-1" />
            {creating ? 'Creating…' : 'Create'}
          </Button>
        </form>
      </Card>

      {/* List */}
      <Card>
        <CardTitle>Workspaces · {workspaces.length}</CardTitle>
        {workspaces.length === 0 ? (
          <EmptyState
            title={activeSpaceId ? 'No workspaces yet' : 'No operational space selected'}
            description={activeSpaceId ? 'Create one above.' : 'Select an operational space to browse workspaces.'}
          />
        ) : (
          <div className="divide-y divide-border">
            {workspaces.map(ws => (
              <div key={ws.id} className="flex items-center gap-3 py-3 group">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <Link
                      to={`/workspace-console?workspace=${ws.id}`}
                      className="text-sm font-medium text-foreground hover:underline"
                    >{ws.name}</Link>
                    <Badge variant={ws.status === 'active' ? 'default' : 'muted'} className="text-[10px] px-1.5 py-0">
                      {ws.status}
                    </Badge>
                    <Badge variant="muted" className="text-[10px] px-1.5 py-0">{ws.workspace_type}</Badge>
                  </div>
                  {ws.description && (
                    <p className="text-xs text-muted-foreground truncate mt-0.5">{ws.description}</p>
                  )}
                  <p className="text-[10px] text-muted-foreground mt-0.5" style={{ fontFamily: 'var(--font-mono)' }}>
                    {ws.id} · {ws.kind} · created {fmt(ws.created_at)}
                  </p>
                </div>
                <Link
                  to={`/workspaces/${ws.id}`}
                  className="opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-foreground p-1.5 rounded-md hover:bg-muted"
                  title="Workspace settings"
                >
                  <Settings className="size-3.5" />
                </Link>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}
