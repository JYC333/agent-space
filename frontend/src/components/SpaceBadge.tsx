import { Home, Heart, Users } from 'lucide-react'
import { useSpace } from '../contexts/SpaceContext'
import { Badge } from './ui/badge'
import { cn } from '../lib/utils'
import type { SpaceType } from '../types/api'

const TYPE_ICON: Record<SpaceType, typeof Home> = {
  personal: Home,
  household: Heart,
  team: Users,
}

/**
 * Consistent provenance badge for cross-space items shown on user-scoped surfaces (Home).
 * Resolves the space name/type from context; renders nothing when the space is unknown.
 */
export function SpaceBadge({ spaceId, className }: { spaceId: string | null | undefined; className?: string }) {
  const { spaces } = useSpace()
  if (!spaceId) return null
  const space = spaces.find(s => s.id === spaceId)
  const Icon = space ? (TYPE_ICON[space.type] ?? Users) : Users
  return (
    <Badge variant="outline" className={cn('gap-1', className)} title={space ? `Space: ${space.name}` : 'Space'}>
      <Icon className="size-3" />
      {space?.name ?? 'Unknown space'}
    </Badge>
  )
}
