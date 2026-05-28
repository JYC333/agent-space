import type {
  KnowledgeContentFormat,
  KnowledgeItemStatus,
  KnowledgeItemType,
  KnowledgeRelationStatus,
  KnowledgeRelationType,
  KnowledgeVisibility,
} from '../../types/api'

export const KNOWLEDGE_ITEM_TYPES: KnowledgeItemType[] = [
  'knowledge',
  'experience',
  'lesson',
  'procedure',
  'decision',
  'reflection',
  'source',
  'question',
  'answer',
  'summary',
]

export const KNOWLEDGE_STATUSES: KnowledgeItemStatus[] = ['draft', 'active', 'superseded', 'archived']
export const KNOWLEDGE_VISIBILITIES: KnowledgeVisibility[] = ['private', 'space_shared', 'workspace_shared', 'restricted']
export const KNOWLEDGE_FORMATS: KnowledgeContentFormat[] = ['markdown', 'plain']

export const KNOWLEDGE_RELATION_TYPES: KnowledgeRelationType[] = [
  'related',
  'derived_from',
  'example_of',
  'supports',
  'contradicts',
  'part_of',
  'prerequisite_of',
  'applies_to',
  'answers',
]

export const KNOWLEDGE_RELATION_STATUSES: Extract<KnowledgeRelationStatus, 'candidate' | 'active'>[] = ['candidate', 'active']

export function fmt(dt: string | null | undefined): string {
  return dt ? new Date(dt).toLocaleString() : '-'
}

export function parseTags(value: string): string[] {
  return value.split(',').map(t => t.trim()).filter(Boolean)
}

export function parseOptionalConfidence(value: string): number | null {
  if (!value.trim()) return null
  const n = Number(value)
  return Number.isFinite(n) ? n : Number.NaN
}

export function validateConfidence(value: number | null): boolean {
  return !Number.isNaN(value) && (value === null || (value >= 0 && value <= 1))
}

export function parseSourceRefs(value: string): Record<string, unknown>[] {
  if (!value.trim()) return []
  const parsed: unknown = JSON.parse(value)
  if (!Array.isArray(parsed) || !parsed.every(isObjectRecord)) {
    throw new Error('source_refs must be a JSON array of objects')
  }
  return parsed
}

function isObjectRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
