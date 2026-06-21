import type { CondenserPresetPromptOut } from '../../types/api'
import type { SessionCondenserProfile } from './policyMap'

export default function CondenserPresetPromptPreview({
  profile,
  presets,
}: {
  profile: SessionCondenserProfile
  presets: CondenserPresetPromptOut[]
}) {
  const preset = presets.find(item => item.profile === profile)
  if (!preset) {
    return (
      <p className="text-xs text-muted-foreground">
        Built-in preset prompt is unavailable right now.
      </p>
    )
  }
  return (
    <div className="space-y-3 rounded-md border border-border bg-muted/20 p-3">
      <div>
        <p className="text-xs font-medium">Built-in preset prompt</p>
        <p className="mt-1 text-xs text-muted-foreground">
          This is the server-defined prompt used when no custom override is set.
        </p>
      </div>
      <PromptBlock label="System prompt (with shared guardrails)" value={preset.effective_system} />
      <PromptBlock label="Summary instructions" value={preset.instructions} />
    </div>
  )
}

function PromptBlock({ label, value }: { label: string; value: string }) {
  return (
    <div className="space-y-1.5">
      <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">{label}</p>
      <pre className="max-h-44 overflow-auto whitespace-pre-wrap rounded-md border border-border bg-background p-2 text-xs font-mono leading-relaxed">
        {value}
      </pre>
    </div>
  )
}
