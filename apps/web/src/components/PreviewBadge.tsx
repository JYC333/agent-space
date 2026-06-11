import { Badge } from './ui/badge'

/** Neutral preview marker for artifacts, proposals, and dry-run context. */
export function PreviewBadge({ className }: { className?: string }) {
  return (
    <Badge variant="outline" className={className} title="Preview — not applied to live data">
      PREVIEW
    </Badge>
  )
}

export function DryRunBanner() {
  return (
    <div
      className="rounded-lg border border-border bg-muted/50 px-4 py-2.5 text-sm text-muted-foreground"
      role="status"
    >
      Dry-run preview — no changes are applied.
    </div>
  )
}

export function UrgencyBadge({ urgency, className }: { urgency: string; className?: string }) {
  const v =
    urgency === 'critical' ? 'destructive'
      : urgency === 'high' ? 'warning'
        : urgency === 'low' ? 'muted'
          : 'secondary'
  return <Badge variant={v} className={className}>{urgency}</Badge>
}
