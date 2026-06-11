import type {
  KnowledgeContentFormat,
  KnowledgeItemStatus,
  KnowledgeItemType,
  KnowledgeRelationStatus,
  KnowledgeRelationType,
  KnowledgeVisibility,
} from '../../types/api'

export const KNOWLEDGE_ITEM_TYPES: KnowledgeItemType[] = [
  'concept',
  'claim',
  'lesson',
  'procedure',
  'decision',
  'question',
  'answer',
  'summary',
]

export const KNOWLEDGE_STATUSES: KnowledgeItemStatus[] = ['draft', 'active', 'superseded', 'archived']
export const KNOWLEDGE_VISIBILITIES: KnowledgeVisibility[] = ['private', 'space_shared', 'workspace_shared', 'restricted']
export const KNOWLEDGE_FORMATS: KnowledgeContentFormat[] = ['markdown', 'plain']

export const KNOWLEDGE_RELATION_TYPES: KnowledgeRelationType[] = [
  'related_to',
  'explains',
  'depends_on',
  'prerequisite_of',
  'part_of',
  'example_of',
  'applies_to',
  'supports',
  'contradicts',
  'derived_from',
  'summarizes',
  'updates',
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

// ── Knowledge section navigation ───────────────────────────────────────────
/**
 * Sub-areas of the first-level Knowledge module. `home` is the optional overview
 * hub; the other four are the working workspaces. `/knowledge` opens the last-used
 * *workspace* (never `home`, which stays an intentional destination) and defaults
 * to `notes` on a fresh client. See KnowledgeModule / KnowledgeSectionHeader.
 */
export type KnowledgeSection = 'home' | 'notes' | 'wiki' | 'sources' | 'cards'

/** Sections eligible to be remembered as the `/knowledge` redirect target. */
export const KNOWLEDGE_WORKSPACE_SECTIONS: Exclude<KnowledgeSection, 'home'>[] = [
  'notes',
  'wiki',
  'sources',
  'cards',
]

export const DEFAULT_KNOWLEDGE_SECTION: KnowledgeSection = 'notes'

const LAST_SECTION_KEY = 'agent-space:knowledge-section'

function isWorkspaceSection(value: string): value is Exclude<KnowledgeSection, 'home'> {
  return (KNOWLEDGE_WORKSPACE_SECTIONS as string[]).includes(value)
}

/** The section `/knowledge` should redirect to: last-used workspace, else Notes. */
export function readLastKnowledgeSection(): Exclude<KnowledgeSection, 'home'> {
  try {
    const v = localStorage.getItem(LAST_SECTION_KEY)
    if (v && isWorkspaceSection(v)) return v
  } catch {
    /* ignore */
  }
  return DEFAULT_KNOWLEDGE_SECTION as Exclude<KnowledgeSection, 'home'>
}

/**
 * Remember the active workspace so `/knowledge` reopens it next time. `home` is
 * intentionally not persisted — the overview must never become the default landing.
 */
export function rememberKnowledgeSection(section: KnowledgeSection): void {
  if (!isWorkspaceSection(section)) return
  try {
    localStorage.setItem(LAST_SECTION_KEY, section)
  } catch {
    /* ignore */
  }
}
