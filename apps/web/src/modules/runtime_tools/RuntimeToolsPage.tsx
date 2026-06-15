import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Terminal } from 'lucide-react'
import { runtimeToolsApi } from '../../api/client'
import { useSpace } from '../../contexts/SpaceContext'
import type { RuntimeToolStatus } from '../../types/api'
import { Card, CardTitle } from '../../components/ui/card'
import { errMsg } from '../../lib/utils'
import CLILoginSection from './CLILoginSection'

export default function RuntimeToolsPage() {
  const { activeSpaceId, activeSpaceName } = useSpace()
  const [runtimeTools, setRuntimeTools] = useState<RuntimeToolStatus[]>([])
  const [toolVersions, setToolVersions] = useState<Record<string, string>>({})
  const [loadingTools, setLoadingTools] = useState(true)
  const [installingRuntime, setInstallingRuntime] = useState<string | null>(null)

  async function loadRuntimeTools() {
    setLoadingTools(true)
    try {
      setRuntimeTools(await runtimeToolsApi.list())
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setLoadingTools(false)
    }
  }

  useEffect(() => { loadRuntimeTools() }, [])

  async function handleInstallRuntimeTool(runtime: string) {
    setInstallingRuntime(runtime)
    try {
      const version = toolVersions[runtime]?.trim()
      await runtimeToolsApi.install(runtime, { version: version || undefined, activate: true, force: true })
      toast.success('Runtime tool installed')
      await loadRuntimeTools()
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setInstallingRuntime(null)
    }
  }

  const runtimeToolsByRuntime = Object.fromEntries(
    runtimeTools.map(tool => [tool.runtime, tool] as const),
  ) as Record<string, RuntimeToolStatus | undefined>

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
          <Terminal className="size-5 text-accent-foreground" />
        </div>
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Runtime Tools</h1>
          <p className="text-sm text-muted-foreground">
            Install, authenticate, and monitor usage for the available CLI runtimes.
          </p>
          <p className="text-xs text-muted-foreground">
            Viewing: {activeSpaceName ?? activeSpaceId ?? 'No operational space selected'}
          </p>
        </div>
      </div>

      {activeSpaceId ? (
        <CLILoginSection
          key={activeSpaceId}
          runtimeToolsByRuntime={runtimeToolsByRuntime}
          runtimeToolsLoading={loadingTools}
          installingRuntime={installingRuntime}
          onInstallTool={handleInstallRuntimeTool}
          versions={toolVersions}
          onVersionChange={(runtime, version) => setToolVersions(prev => ({ ...prev, [runtime]: version }))}
          onRefreshTools={loadRuntimeTools}
        />
      ) : (
        <Card>
          <CardTitle>CLI Runtimes</CardTitle>
          <p className="text-sm text-muted-foreground mt-2">Select an operational space to manage runtime credentials.</p>
        </Card>
      )}
    </div>
  )
}
