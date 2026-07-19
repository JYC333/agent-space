import { useEffect } from 'react'
import { toast } from 'sonner'
import { Button } from '../../components/ui/button'
import { errMsg } from '../../lib/utils'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '../../components/ui/dialog'
import { SourceMonitorDialogContent } from './SourceMonitorDialog'
import { useSourceSetupCatalog } from './useSourceSetupCatalog'
import type { SourceChannel } from '../../types/api'

interface SourceSetupDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onChannelCreated?: (channel: SourceChannel) => Promise<void> | void
  onSaved?: () => Promise<void> | void
}

/** Loads source catalog metadata for any surface that needs the shared setup dialog. */
export function SourceSetupDialog({ open, onOpenChange, onChannelCreated, onSaved }: SourceSetupDialogProps) {
  const { providers, categoryGroups, loading, error: loadError } = useSourceSetupCatalog(open)

  useEffect(() => {
    if (loadError) toast.error(errMsg(loadError))
  }, [loadError])

  if (!open) return null

  const ready = !loading && !loadError && providers.length > 0

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={ready ? 'max-w-2xl overflow-visible' : 'max-w-md'}>
        {!ready ? (
          <>
            <DialogHeader>
              <DialogTitle>{loadError ? 'Unable to add source' : 'Add source'}</DialogTitle>
              <DialogDescription>
                {loadError ?? (loading ? 'Loading the available source platforms…' : 'No source platforms are available.')}
              </DialogDescription>
            </DialogHeader>
            {!loading && (
              <DialogFooter>
                <Button variant="outline" onClick={() => onOpenChange(false)}>Close</Button>
              </DialogFooter>
            )}
          </>
        ) : (
          <SourceMonitorDialogContent
            open={open}
            mode="source"
            providers={providers}
            categoryGroups={categoryGroups}
            onOpenChange={onOpenChange}
            onCreated={onChannelCreated}
            onSaved={async () => { await onSaved?.() }}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}
