import { useState, useEffect, useRef, useCallback } from 'react'
import { History, ShieldAlert } from 'lucide-react'
import { toast } from 'sonner'
import { useSearchParams } from 'react-router-dom'
import { workspacesApi, spacesApi } from '../../api/client'
import { useSpace } from '../../contexts/SpaceContext'
import { errMsg } from '../../lib/utils'
import type { MemberRole, Workspace } from '../../types/api'
import { Card, CardTitle } from '../../components/ui/card'
import { Button } from '../../components/ui/button'
import { Input } from '../../components/ui/input'

const BUILTIN_RETENTION_DAYS = 7
const BUILTIN_MAX_COUNT = 20

function canManageSpace(role: MemberRole | undefined): boolean {
  return role === 'owner' || role === 'admin'
}

interface WorkspaceRowState {
  retentionDays: string
  maxCount: string
  saving: boolean
}

export default function WorkspaceSnapshotSettingsPage() {
  const { activeSpaceId, spaces } = useSpace()
  const activeSpace = spaces.find(s => s.id === activeSpaceId)
  const manageable = canManageSpace(activeSpace?.role)

  // Space defaults
  const [defaultDays, setDefaultDays] = useState('')
  const [defaultCount, setDefaultCount] = useState('')
  const [savingDefaults, setSavingDefaults] = useState(false)

  // Per-workspace overrides
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [loading, setLoading] = useState(false)
  const [rowState, setRowState] = useState<Record<string, WorkspaceRowState>>({})
  const [searchParams] = useSearchParams()
  const highlightId = searchParams.get('workspace')
  const highlightRef = useRef<HTMLDivElement | null>(null)

  const loadDefaults = useCallback(async () => {
    if (!activeSpaceId || !manageable) return
    try {
      const d = await spacesApi.getSnapshotDefaults(activeSpaceId)
      setDefaultDays(d.snapshot_retention_days_default !== null ? String(d.snapshot_retention_days_default) : '')
      setDefaultCount(d.snapshot_max_count_default !== null ? String(d.snapshot_max_count_default) : '')
    } catch { /* non-fatal */ }
  }, [activeSpaceId, manageable])

  const load = useCallback(async () => {
    if (!activeSpaceId || !manageable) return
    setLoading(true)
    try {
      const { items } = await workspacesApi.list()
      setWorkspaces(items)
      const initial: Record<string, WorkspaceRowState> = {}
      for (const ws of items) {
        initial[ws.id] = {
          retentionDays: String(ws.snapshot_retention_days ?? BUILTIN_RETENTION_DAYS),
          maxCount: String(ws.snapshot_max_count ?? BUILTIN_MAX_COUNT),
          saving: false,
        }
      }
      setRowState(initial)
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setLoading(false)
    }
  }, [activeSpaceId, manageable])

  useEffect(() => { void loadDefaults(); void load() }, [loadDefaults, load])

  useEffect(() => {
    if (highlightRef.current) {
      highlightRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }, [workspaces, highlightId])

  async function handleSaveDefaults() {
    if (!activeSpaceId) return
    const days = defaultDays.trim() ? parseInt(defaultDays, 10) : null
    const count = defaultCount.trim() ? parseInt(defaultCount, 10) : null
    if (days !== null && (isNaN(days) || days < 1)) { toast.error('Retention days must be a positive integer'); return }
    if (count !== null && (isNaN(count) || count < 1)) { toast.error('Max count must be a positive integer'); return }
    setSavingDefaults(true)
    try {
      await spacesApi.updateSnapshotDefaults(activeSpaceId, {
        snapshot_retention_days_default: days,
        snapshot_max_count_default: count,
      })
      toast.success('Space default snapshot settings saved')
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setSavingDefaults(false)
    }
  }

  async function handleSave(ws: Workspace) {
    const state = rowState[ws.id]
    if (!state) return
    const days = parseInt(state.retentionDays, 10)
    const count = parseInt(state.maxCount, 10)
    if (isNaN(days) || days < 1) { toast.error('Retention days must be a positive integer'); return }
    if (isNaN(count) || count < 1) { toast.error('Max count must be a positive integer'); return }
    setRowState(prev => ({ ...prev, [ws.id]: { ...prev[ws.id], saving: true } }))
    try {
      await workspacesApi.update(ws.id, {
        snapshot_retention_days: days,
        snapshot_max_count: count,
      })
      toast.success(`Snapshot settings saved for "${ws.name}"`)
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setRowState(prev => ({ ...prev, [ws.id]: { ...prev[ws.id], saving: false } }))
    }
  }

  function patchRow(id: string, patch: Partial<Omit<WorkspaceRowState, 'saving'>>) {
    setRowState(prev => ({ ...prev, [id]: { ...prev[id], ...patch } }))
  }

  return (
    <div className="p-6 space-y-6 max-w-4xl">
      <div className="flex items-center gap-4 pb-4 border-b border-border">
        <div
          className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
          style={{
            background: 'color-mix(in oklch, var(--primary) 12%, transparent)',
            border: '1px solid color-mix(in oklch, var(--primary) 35%, transparent)',
          }}
        >
          <History className="size-5 text-accent-foreground" />
        </div>
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Snapshot Rollback Settings</h1>
          <p className="text-sm text-muted-foreground">
            Configure code-patch rollback snapshot retention for this space and its workspaces.
          </p>
        </div>
      </div>

      {!manageable ? (
        <Card>
          <CardTitle className="flex items-center gap-2">
            <ShieldAlert className="size-3.5" /> Space admin required
          </CardTitle>
          <p className="text-sm text-muted-foreground">
            Only this space's owner or admins can configure snapshot settings.
          </p>
        </Card>
      ) : (
        <>
          {/* Space-level defaults — editable */}
          <Card>
            <CardTitle className="flex items-center gap-2">
              <History className="size-3.5" /> Space defaults
            </CardTitle>
            <p className="text-sm text-muted-foreground mb-4">
              Workspaces without an explicit override use these defaults.
              Leave blank to fall back to the built-in policy ({BUILTIN_RETENTION_DAYS} days · {BUILTIN_MAX_COUNT} max snapshots).
            </p>
            <div className="flex items-end gap-3">
              <div className="flex flex-col gap-1">
                <label className="text-[10px] text-muted-foreground font-medium uppercase tracking-wide">
                  Retention (days)
                </label>
                <Input
                  type="number"
                  min={1}
                  placeholder={String(BUILTIN_RETENTION_DAYS)}
                  value={defaultDays}
                  onChange={e => setDefaultDays(e.target.value)}
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
                  placeholder={String(BUILTIN_MAX_COUNT)}
                  value={defaultCount}
                  onChange={e => setDefaultCount(e.target.value)}
                  className="h-8 w-28 text-sm"
                />
              </div>
              <Button
                size="sm"
                variant="outline"
                className="h-8"
                disabled={savingDefaults}
                onClick={handleSaveDefaults}
              >
                {savingDefaults ? 'Saving…' : 'Save defaults'}
              </Button>
            </div>
            <p className="text-xs text-muted-foreground mt-3">
              Snapshots are captured automatically before each accepted code-patch proposal
              and pruned when the limit is reached or the retention period expires.
            </p>
          </Card>

          {/* Per-workspace overrides */}
          {loading ? (
            <Card>
              <p className="text-sm text-muted-foreground">Loading workspaces…</p>
            </Card>
          ) : workspaces.length === 0 ? (
            <Card>
              <CardTitle>Per-workspace overrides</CardTitle>
              <p className="text-sm text-muted-foreground">
                No workspaces in this space yet. Once workspaces are created they can be
                configured individually here.
              </p>
            </Card>
          ) : (
            <Card>
              <CardTitle>Per-workspace overrides · {workspaces.length}</CardTitle>
              <p className="text-xs text-muted-foreground mb-4">
                Workspace-level settings take precedence over the space defaults above.
              </p>
              <div className="divide-y divide-border">
                {workspaces.map(ws => {
                  const state = rowState[ws.id]
                  const isHighlight = ws.id === highlightId
                  const hasOverride = ws.snapshot_retention_days !== null || ws.snapshot_max_count !== null
                  return (
                    <div
                      key={ws.id}
                      ref={isHighlight ? highlightRef : undefined}
                      className={`py-4 transition-colors ${isHighlight ? 'bg-primary/5 -mx-4 px-4 rounded' : ''}`}
                    >
                      <div className="flex items-start gap-4">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-medium text-foreground truncate">{ws.name}</span>
                            {hasOverride && (
                              <span className="text-[10px] px-1.5 py-0 rounded bg-primary/10 text-primary font-medium">
                                custom
                              </span>
                            )}
                          </div>
                          <div
                            className="text-[10px] text-muted-foreground mt-0.5"
                            style={{ fontFamily: 'var(--font-mono)' }}
                          >
                            {ws.id}
                          </div>
                        </div>

                        <div className="flex items-center gap-3 shrink-0">
                          <div className="flex flex-col gap-1">
                            <label className="text-[10px] text-muted-foreground font-medium uppercase tracking-wide">
                              Retention (days)
                            </label>
                            <Input
                              type="number"
                              min={1}
                              placeholder={defaultDays || String(BUILTIN_RETENTION_DAYS)}
                              value={state?.retentionDays ?? ''}
                              onChange={e => patchRow(ws.id, { retentionDays: e.target.value })}
                              className="h-7 w-24 text-sm"
                            />
                          </div>
                          <div className="flex flex-col gap-1">
                            <label className="text-[10px] text-muted-foreground font-medium uppercase tracking-wide">
                              Max snapshots
                            </label>
                            <Input
                              type="number"
                              min={1}
                              placeholder={defaultCount || String(BUILTIN_MAX_COUNT)}
                              value={state?.maxCount ?? ''}
                              onChange={e => patchRow(ws.id, { maxCount: e.target.value })}
                              className="h-7 w-24 text-sm"
                            />
                          </div>
                          <div className="flex flex-col gap-1">
                            <label className="text-[10px] text-muted-foreground font-medium uppercase tracking-wide opacity-0 select-none">
                              Save
                            </label>
                            <Button
                              size="sm"
                              variant="outline"
                              className="h-7"
                              disabled={state?.saving}
                              onClick={() => handleSave(ws)}
                            >
                              {state?.saving ? 'Saving…' : 'Save'}
                            </Button>
                          </div>
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            </Card>
          )}
        </>
      )}
    </div>
  )
}
