import { useLocation } from 'react-router-dom'
import { Send } from 'lucide-react'
import { useSpace } from '../contexts/SpaceContext'
import { Badge } from './ui/badge'
import { routeScopeForPath } from '../core/navigation'

function writeTargetLabel(name: string, isPersonal: boolean) {
  return isPersonal ? 'Personal Space' : name
}

/**
 * Resolves the write destination for the current route:
 *  - space routes write to the active Space (the workspace you're in);
 *  - Home writes go to the explicit write target (default Personal Space) — handled by the
 *    floating Quick Capture, which has its own picker.
 */
export function useWriteTarget() {
  const { spaces, writeTargetSpaceId, activeSpaceId } = useSpace()
  const { pathname } = useLocation()
  const scope = routeScopeForPath(pathname)
  const targetId = scope === 'home' ? writeTargetSpaceId : activeSpaceId
  const target = spaces.find(s => s.id === targetId) ?? null
  return {
    writeTargetSpaceId: targetId,
    writeTargetSpace: target,
    hasWriteTarget: Boolean(targetId && target),
    label: target ? writeTargetLabel(target.name, target.type === 'personal') : null,
  }
}

/**
 * Read-only target indicator for space-scoped forms. On a Space page the destination is the
 * active Space (no selector needed); the label is always shown so writes are never silent.
 */
export function WriteTargetPicker({ compact = false }: { compact?: boolean }) {
  const { label, hasWriteTarget } = useWriteTarget()

  if (!hasWriteTarget) {
    return (
      <Badge variant="warning" className="gap-1">
        <Send className="size-3" /> No write target
      </Badge>
    )
  }

  if (compact) {
    return (
      <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <Send className="size-3" />
        <span>Write to:</span>
        <span className="text-foreground font-medium">{label}</span>
      </div>
    )
  }

  return (
    <div className="rounded-md border border-border bg-muted/20 p-2.5">
      <div className="flex items-center gap-1.5 text-[11px] font-semibold text-muted-foreground">
        <Send className="size-3" />
        Write to: <span className="text-foreground">{label}</span>
      </div>
    </div>
  )
}
