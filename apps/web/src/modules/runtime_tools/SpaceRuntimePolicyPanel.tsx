import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { ChevronDown, ChevronRight, Loader2, Plus } from 'lucide-react'
import { runtimeToolsApi } from '../../api/client'
import { useSpace } from '../../contexts/SpaceContext'
import type { RuntimeToolInstalledVersion, SpaceRuntimeToolPolicyOut } from '../../types/api'
import { errMsg } from '../../lib/utils'
import { Card, CardTitle } from '../../components/ui/card'
import { Button } from '../../components/ui/button'
import { Badge } from '../../components/ui/badge'

function installedVersions(policy: SpaceRuntimeToolPolicyOut): RuntimeToolInstalledVersion[] {
  return policy.installed_versions.filter(version => version.installed)
}

function defaultInstalledVersion(policy: SpaceRuntimeToolPolicyOut): string | null {
  const installed = installedVersions(policy)
  return policy.default_version ?? policy.active_version ?? installed[0]?.version ?? null
}

export function SpaceRuntimePolicyPanel() {
  const { activeSpaceId, spaces, preferredSpaceId } = useSpace()
  const policySpaceId = activeSpaceId ?? preferredSpaceId
  const activeSpace = spaces.find(space => space.id === policySpaceId) ?? null
  const canManage = activeSpace?.role === 'owner' || activeSpace?.role === 'admin'
  const [policies, setPolicies] = useState<SpaceRuntimeToolPolicyOut[]>([])
  const [open, setOpen] = useState(false)
  const [addRuntime, setAddRuntime] = useState('')
  const [savingRuntime, setSavingRuntime] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  async function load() {
    setLoading(true)
    try {
      setPolicies(await runtimeToolsApi.spacePolicies())
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [policySpaceId])

  async function update(policy: SpaceRuntimeToolPolicyOut, patch: Partial<SpaceRuntimeToolPolicyOut>) {
    setSavingRuntime(policy.runtime)
    try {
      const next = await runtimeToolsApi.updateSpacePolicy(policy.runtime, {
        enabled: patch.enabled ?? policy.enabled,
        default_version: patch.default_version === undefined ? policy.default_version : patch.default_version,
        allowed_versions: patch.allowed_versions ?? policy.allowed_versions,
      })
      setPolicies(prev => prev.map(item => item.runtime === next.runtime ? next : item))
      toast.success('Runtime policy updated')
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setSavingRuntime(null)
    }
  }

  const selectedPolicies = policies.filter(policy => Boolean(policy.policy_id && policy.enabled))
  const addCandidates = policies.filter(policy =>
    installedVersions(policy).length > 0 &&
    (!policy.policy_id || !policy.enabled),
  )

  useEffect(() => {
    if (addRuntime && addCandidates.some(policy => policy.runtime === addRuntime)) return
    setAddRuntime(addCandidates[0]?.runtime ?? '')
  }, [addRuntime, addCandidates])

  async function addSelectedRuntime() {
    const policy = policies.find(item => item.runtime === addRuntime)
    if (!policy) return
    await update(policy, {
      enabled: true,
      default_version: defaultInstalledVersion(policy),
      allowed_versions: [],
    })
  }

  return (
    <Card>
      <button
        type="button"
        className="flex w-full items-start justify-between gap-3 text-left"
        onClick={() => setOpen(value => !value)}
      >
        <div>
          <CardTitle className="flex items-center gap-2">
            {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
            Runtime Policy
          </CardTitle>
          <p className="mt-1 text-sm text-muted-foreground">
            Select which installed CLI runtimes this space can use.
          </p>
        </div>
        <Badge variant="muted" className="shrink-0">{selectedPolicies.length} enabled</Badge>
      </button>

      {open && (
        <div className="mt-4 space-y-3">
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs text-muted-foreground">
              Space: {activeSpace?.name ?? 'No active space'}
            </p>
            <Button size="sm" variant="ghost" onClick={load} disabled={loading}>Refresh</Button>
          </div>
          {!canManage && (
            <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
              Updating runtime policy requires space owner or admin role.
            </p>
          )}

          <div className="rounded-lg border p-3 space-y-2">
            <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Add CLI runtime</div>
            <div className="flex flex-col gap-2 sm:flex-row">
              <select
                value={addRuntime}
                onChange={e => setAddRuntime(e.target.value)}
                className="flex h-9 flex-1 rounded-md border border-border bg-input px-3 text-sm"
                disabled={!canManage || loading || addCandidates.length === 0}
              >
                {addCandidates.length === 0 ? (
                  <option value="">No installed CLI runtime available</option>
                ) : addCandidates.map(policy => (
                  <option key={policy.runtime} value={policy.runtime}>
                    {policy.label} · {defaultInstalledVersion(policy) ?? 'installed'}
                  </option>
                ))}
              </select>
              <Button
                size="sm"
                onClick={addSelectedRuntime}
                disabled={!canManage || !addRuntime || Boolean(savingRuntime)}
              >
                {savingRuntime === addRuntime ? <Loader2 className="size-3.5 animate-spin" /> : <Plus className="size-3.5" />}
                Add CLI
              </Button>
            </div>
            {addCandidates.length === 0 && (
              <p className="text-xs text-muted-foreground">
                Install CLI runtimes from Instance Settings before adding them to this space.
              </p>
            )}
          </div>

          {loading ? (
            <p className="text-sm text-muted-foreground">Loading runtime policy…</p>
          ) : selectedPolicies.length === 0 ? (
            <p className="rounded-lg border p-3 text-sm text-muted-foreground">
              No CLI runtimes have been added to this space.
            </p>
          ) : (
            selectedPolicies.map(policy => {
              const versions = installedVersions(policy)
              return (
                <div key={policy.runtime} className="rounded-lg border p-3 space-y-2">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="font-medium">{policy.label}</div>
                      <div className="text-xs font-mono text-muted-foreground">{policy.runtime}</div>
                    </div>
                    <Badge variant="success">enabled</Badge>
                  </div>
                  <div className="grid gap-2 sm:grid-cols-[1fr_auto]">
                    <select
                      className="flex h-9 w-full rounded-md border border-border bg-input px-3 text-sm"
                      value={policy.default_version ?? ''}
                      disabled={!canManage || savingRuntime === policy.runtime || versions.length === 0}
                      onChange={e => update(policy, { default_version: e.target.value || null })}
                    >
                      <option value="">No default version</option>
                      {versions.map(version => (
                        <option key={version.version} value={version.version}>{version.version}</option>
                      ))}
                    </select>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={!canManage || savingRuntime === policy.runtime}
                      onClick={() => update(policy, { enabled: false })}
                    >
                      {savingRuntime === policy.runtime ? <Loader2 className="size-3.5 animate-spin" /> : 'Remove'}
                    </Button>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Installed versions: {versions.length > 0 ? versions.map(version => version.version).join(', ') : 'none'}
                  </p>
                </div>
              )
            })
          )}
        </div>
      )}
    </Card>
  )
}
