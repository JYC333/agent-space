import { useMemo } from 'react'
import { Send } from 'lucide-react'
import { useSpace } from '../contexts/SpaceContext'
import { Select } from './ui/select'
import { Badge } from './ui/badge'

function writeTargetLabel(name: string, isPersonal: boolean) {
  return isPersonal ? 'Personal Space' : name
}

export function useWriteTarget() {
  const { spaces, personalSpaceId, activeWriteTargetSpaceId, perspective, spaceId } = useSpace()
  const targetId = activeWriteTargetSpaceId ?? (perspective === 'personal' ? personalSpaceId : spaceId)
  const target = spaces.find(s => s.id === targetId) ?? null
  return {
    writeTargetSpaceId: targetId,
    writeTargetSpace: target,
    hasWriteTarget: Boolean(targetId && target),
    label: target ? writeTargetLabel(target.name, target.type === 'personal') : null,
  }
}

export function WriteTargetPicker({ compact = false }: { compact?: boolean }) {
  const { spaces, activeWriteTargetSpaceId, setWriteTarget } = useSpace()
  const { writeTargetSpaceId, writeTargetSpace, label } = useWriteTarget()

  const options = useMemo(() => spaces.map(s => ({
    value: s.id,
    label: writeTargetLabel(s.name, s.type === 'personal'),
  })), [spaces])

  if (spaces.length === 0) {
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
        <Select
          value={activeWriteTargetSpaceId ?? writeTargetSpaceId ?? ''}
          options={options}
          onChange={setWriteTarget}
          className="h-7 min-w-[150px] text-xs"
        />
      </div>
    )
  }

  return (
    <div className="rounded-md border border-border bg-muted/20 p-2.5 space-y-1.5">
      <div className="flex items-center gap-1.5 text-[11px] font-semibold text-muted-foreground">
        <Send className="size-3" />
        Write to: <span className="text-foreground">{label ?? 'No write target'}</span>
      </div>
      <Select
        value={activeWriteTargetSpaceId ?? writeTargetSpaceId ?? ''}
        options={options}
        onChange={setWriteTarget}
      />
      {!writeTargetSpace && (
        <p className="text-xs text-warning">Choose a member space before creating content.</p>
      )}
    </div>
  )
}
