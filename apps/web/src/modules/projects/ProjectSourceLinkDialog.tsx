import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { projectsApi } from '../../api/client'
import { Button } from '../../components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '../../components/ui/dialog'
import { Label } from '../../components/ui/label'
import { Select } from '../../components/ui/select'
import { errMsg } from '../../lib/utils'
import { SourceMonitorDialogContent } from '../sources/SourceMonitorDialog'
import { useSourceSetupCatalog } from '../sources/useSourceSetupCatalog'
import type { ProjectSourceBinding, SourceChannel } from '../../types/api'

interface ProjectSourceLinkDialogProps {
  projectId: string
  open: boolean
  onOpenChange: (open: boolean) => void
  channels: SourceChannel[]
  bindings: ProjectSourceBinding[]
  onLinked: () => void | Promise<void>
  onSourceCreated?: (channel: SourceChannel) => void | Promise<void>
  onSaved?: () => void | Promise<void>
  allowCreate?: boolean
  defaultBackfillHistory?: boolean
}

/** Link an existing reusable Source monitor to a project without copying it. */
export function ProjectSourceLinkDialog({
  projectId,
  open,
  onOpenChange,
  channels,
  bindings,
  onLinked,
  onSourceCreated,
  onSaved,
  allowCreate = false,
  defaultBackfillHistory = true,
}: ProjectSourceLinkDialogProps) {
  const [requestedMode, setRequestedMode] = useState<'link' | 'create' | null>(null)
  const [channelId, setChannelId] = useState('')
  const [backfillHistory, setBackfillHistory] = useState(defaultBackfillHistory)
  const [linking, setLinking] = useState(false)
  const sourceOptions = useMemo(
    () => channels
      .filter(channel => !bindings.some(binding =>
        binding.source_channel_id === channel.id && binding.binding_key === 'default'
      ))
      .map(channel => ({
        value: channel.id,
        label: `${channel.name} · ${channel.provider.display_name ?? channel.provider.key ?? 'Provider'}`,
      })),
    [bindings, channels],
  )
  const mode = requestedMode ?? (allowCreate && sourceOptions.length === 0 ? 'create' : 'link')
  const { providers, categoryGroups, loading: catalogLoading, error: catalogError } = useSourceSetupCatalog(open && mode === 'create')

  useEffect(() => {
    if (!open) return
    setChannelId(sourceOptions[0]?.value ?? '')
    setBackfillHistory(defaultBackfillHistory)
  }, [allowCreate, defaultBackfillHistory, open, sourceOptions])

  useEffect(() => {
    if (catalogError) toast.error(errMsg(catalogError))
  }, [catalogError])

  async function submit() {
    if (!channelId) {
      toast.error('Select a source')
      return
    }
    setLinking(true)
    try {
      const binding = await projectsApi.createSourceBinding(projectId, {
        source_channel_id: channelId,
        backfill_history: backfillHistory,
      })
      if (binding.backfill_result) {
        toast.success(`Source linked; ${binding.backfill_result.created_links} project items added`)
      } else {
        toast.success('Source linked')
      }
      await onLinked()
      handleOpenChange(false)
    } catch (error) {
      toast.error(errMsg(error))
    } finally {
      setLinking(false)
    }
  }

  function createNewSource() {
    if (allowCreate) setRequestedMode('create')
  }

  function handleOpenChange(nextOpen: boolean) {
    if (!nextOpen) setRequestedMode(null)
    onOpenChange(nextOpen)
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className={mode === 'create' ? 'max-w-2xl overflow-visible' : undefined}>
        {mode === 'create' ? (
          catalogLoading || catalogError || providers.length === 0 ? (
            <>
              <DialogHeader>
                <DialogTitle>{catalogError ? 'Unable to add source' : 'Add source'}</DialogTitle>
                <DialogDescription>
                  {catalogError ?? (catalogLoading ? 'Loading the available source platforms…' : 'No source platforms are available.')}
                </DialogDescription>
              </DialogHeader>
              {!catalogLoading && (
                <DialogFooter>
                  <Button variant="outline" onClick={() => setRequestedMode('link')}>Back</Button>
                </DialogFooter>
              )}
            </>
          ) : (
            <SourceMonitorDialogContent
              open={open && mode === 'create'}
              mode="source"
              providers={providers}
              categoryGroups={categoryGroups}
              onOpenChange={handleOpenChange}
              onCreated={async channel => {
                await onSourceCreated?.(channel)
              }}
              onSaved={async () => { await onSaved?.() }}
            />
          )
        ) : (
          <>
            <DialogHeader>
              <DialogTitle>Use an existing source</DialogTitle>
              <DialogDescription>
                Link a reusable source monitor to this project, or create a new one if the source you need is not listed.
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-4 py-2">
              <div className="space-y-1.5">
                <Label>Available sources</Label>
                {channels.length === 0 ? (
                  <p className="text-xs text-muted-foreground">No sources are configured yet.</p>
                ) : sourceOptions.length === 0 ? (
                  <p className="text-xs text-muted-foreground">All available sources are already linked to this project.</p>
                ) : (
                  <Select value={channelId} options={sourceOptions} onChange={setChannelId} />
                )}
              </div>
              <label className="flex items-start gap-2 rounded-md border border-border px-3 py-2 text-xs">
                <input
                  type="checkbox"
                  className="mt-0.5 accent-primary"
                  checked={backfillHistory}
                  onChange={event => setBackfillHistory(event.target.checked)}
                />
                <span>
                  <span className="block font-medium text-foreground">Include historical evidence</span>
                  <span className="text-muted-foreground">Link already extracted source evidence into this project.</span>
                </span>
              </label>
            </div>
            <DialogFooter>
              <Button variant="ghost" onClick={() => handleOpenChange(false)}>Cancel</Button>
              {allowCreate && <Button variant="outline" onClick={createNewSource}>Create new source</Button>}
              <Button onClick={() => { void submit() }} disabled={linking || !channelId}>
                {linking ? 'Linking…' : 'Link source'}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
