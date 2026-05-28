import type { SpaceWithMembership } from '../../types/api'

export function getKnowledgeDisplayName(space: Pick<SpaceWithMembership, 'type'> | null | undefined): string {
  if (space?.type === 'personal') return 'Second Brain'
  if (space?.type === 'household') return 'Family Knowledge'
  if (space?.type === 'team') return 'Knowledge Hub'
  return 'Knowledge'
}
