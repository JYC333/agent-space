import { useEffect, useState } from 'react'
import { Terminal } from 'lucide-react'
import { toast } from 'sonner'
import { runtimeToolsApi } from '../../api/client'
import { useSpace } from '../../contexts/SpaceContext'
import type { RuntimeToolStatus, SpaceRuntimeToolPolicyOut } from '../../types/api'
import { errMsg } from '../../lib/utils'
import CLILoginSection from '../runtime_tools/CLILoginSection'

export default function CliProfilesPage() {
  const { personalSpaceId, preferredSpaceId } = useSpace()
  const credentialSpaceId = preferredSpaceId ?? personalSpaceId
  const [runtimeTools, setRuntimeTools] = useState<RuntimeToolStatus[]>([])
  const [runtimePolicies, setRuntimePolicies] = useState<SpaceRuntimeToolPolicyOut[]>([])
  const [loadingTools, setLoadingTools] = useState(true)

  async function loadRuntimeTools() {
    setLoadingTools(true)
    try {
      const [tools, policies] = await Promise.all([
        runtimeToolsApi.list(),
        runtimeToolsApi.spacePolicies().catch(() => [] as SpaceRuntimeToolPolicyOut[]),
      ])
      setRuntimeTools(tools)
      setRuntimePolicies(policies)
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setLoadingTools(false)
    }
  }

  useEffect(() => { loadRuntimeTools() }, [])

  const runtimeToolsByRuntime = Object.fromEntries(
    runtimeTools.map(tool => [tool.runtime, tool] as const),
  ) as Record<string, RuntimeToolStatus | undefined>
  const allowedRuntimes = runtimePolicies
    .filter(policy =>
      policy.policy_id &&
      policy.enabled &&
      policy.installed_versions.some(version => version.installed),
    )
    .map(policy => policy.runtime)

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
          <Terminal className="size-5 text-accent-foreground" />
        </div>
        <div>
          <h1 className="text-xl font-semibold tracking-tight">CLI Runtime Profiles</h1>
          <p className="text-sm text-muted-foreground">
            Manage your CLI login profiles and grant those profiles to spaces.
          </p>
        </div>
      </div>

      <CLILoginSection
        title="CLI runtime profiles"
        description="Create profiles, refresh login state, and grant profiles to spaces."
        spaceId={credentialSpaceId}
        allowedRuntimes={allowedRuntimes}
        runtimeToolsByRuntime={runtimeToolsByRuntime}
        runtimeToolsLoading={loadingTools}
        onRefreshTools={loadRuntimeTools}
      />
    </div>
  )
}
