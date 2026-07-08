import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '../../components/ui/dialog'

const SHORTCUTS: { keys: string; action: string }[] = [
  { keys: '↑ / ↓', action: 'Move paragraph focus' },
  { keys: 'H', action: 'Highlight selection or focused paragraph' },
  { keys: 'N', action: 'Comment on selection or focused paragraph' },
  { keys: '[ / ]', action: 'Toggle inspector' },
  { keys: 'Esc', action: 'Clear selection and paragraph focus' },
  { keys: '?', action: 'Show this reference' },
]

interface ReaderShortcutsDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function ReaderShortcutsDialog({ open, onOpenChange }: ReaderShortcutsDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>Keyboard shortcuts</DialogTitle>
          <DialogDescription className="sr-only">
            Keyboard shortcuts available while reading and annotating an source item.
          </DialogDescription>
        </DialogHeader>
        <dl className="space-y-2 text-sm">
          {SHORTCUTS.map(({ keys, action }) => (
            <div key={keys} className="flex items-center justify-between gap-4">
              <dt>
                <kbd className="rounded border bg-muted px-1.5 py-0.5 font-mono text-xs">{keys}</kbd>
              </dt>
              <dd className="text-muted-foreground text-right">{action}</dd>
            </div>
          ))}
        </dl>
      </DialogContent>
    </Dialog>
  )
}
