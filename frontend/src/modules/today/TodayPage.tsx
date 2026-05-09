import { Sun } from 'lucide-react'

export default function TodayPage() {
  return (
    <div className="p-6 space-y-6 max-w-3xl">
      <div className="flex items-center gap-4 pb-4 border-b border-border">
        <div
          className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
          style={{
            background: 'color-mix(in oklch, var(--primary) 12%, transparent)',
            border: '1px solid color-mix(in oklch, var(--primary) 35%, transparent)',
          }}
        >
          <Sun className="size-5 text-accent-foreground" />
        </div>
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Today</h1>
          <p className="text-sm text-muted-foreground">Daily overview, active items, and suggested actions.</p>
        </div>
      </div>
      <div className="border border-dashed border-border rounded-lg p-12 text-center">
        <p className="text-sm text-muted-foreground">Daily overview is under development.</p>
        <p className="text-xs text-muted-foreground/60 mt-1">Check Proposals and Sessions in the meantime.</p>
      </div>
    </div>
  )
}
