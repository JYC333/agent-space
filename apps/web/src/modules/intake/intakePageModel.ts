import type { EvidenceLink, ExtractedEvidence, IntakeItem } from '../../types/api'

export type ItemFilter = 'open' | 'new' | 'triaged' | 'selected' | 'ignored'
export type EvidenceFilter = 'candidate' | 'active' | 'all'

export interface IntakeSummaryResult {
  run_id: string
  artifact_id: string
  preview: string
  proposal_ids: string[]
}

export const CAPTURE_POLICIES = [
  { value: 'metadata_only', label: 'Metadata' },
  { value: 'excerpt_only', label: 'Excerpt' },
  { value: 'auto_extract_relevant', label: 'Extract relevant' },
  { value: 'auto_extract_all_text', label: 'Extract text' },
  { value: 'archive_all_snapshots', label: 'Archive snapshots' },
]

export const FREQUENCIES = [
  { value: 'manual', label: 'Manual' },
  { value: 'hourly', label: 'Hourly' },
  { value: 'daily', label: 'Daily' },
  { value: 'weekly', label: 'Weekly' },
]

export function minimumRetentionForCapturePolicy(capturePolicy: string) {
  if (capturePolicy === 'archive_all_snapshots') return 'full_snapshot'
  if (capturePolicy === 'auto_extract_relevant' || capturePolicy === 'auto_extract_all_text') return 'full_text'
  if (capturePolicy === 'excerpt_only') return 'summary_only'
  return 'metadata_only'
}

const RETENTION_RANK = ['metadata_only', 'summary_only', 'full_text', 'full_snapshot', 'archived']

export function retentionAtLeast(current: string, minimum: string) {
  const currentRank = RETENTION_RANK.indexOf(current)
  const minimumRank = RETENTION_RANK.indexOf(minimum)
  if (currentRank < 0) return minimum
  if (minimumRank < 0) return current
  return currentRank < minimumRank ? minimum : current
}

const TEXT_EXTRACTION_READY_STATES = new Set(['metadata_only', 'excerpt_saved', 'content_saved', 'extraction_failed'])

export function textExtractionDisabledReason(item: Pick<IntakeItem, 'content_state' | 'source_uri'>) {
  if (!item.source_uri) return 'This item has no source URL to fetch.'
  if (TEXT_EXTRACTION_READY_STATES.has(item.content_state)) return null
  if (item.content_state === 'content_queued') return 'Text extraction is already queued.'
  if (item.content_state === 'snapshot_queued') return 'Snapshot capture is already queued.'
  if (item.content_state === 'snapshot_saved') return 'A source snapshot is already saved.'
  return `Text extraction is not available for ${item.content_state}.`
}

export function canQueueTextExtraction(item: Pick<IntakeItem, 'content_state' | 'source_uri'>) {
  return textExtractionDisabledReason(item) === null
}

export function textExtractionActionLabel(item: Pick<IntakeItem, 'content_state'>) {
  return item.content_state === 'content_saved' ? 'Re-extract' : 'Extract text'
}

export function fmt(dt: string | null) {
  return dt ? new Date(dt).toLocaleString() : 'never'
}

export function short(id: string | null | undefined) {
  return id ? `${id.slice(0, 8)}...` : ''
}

export function preview(text: string | null | undefined, fallback = 'No excerpt') {
  const raw = (text || '').trim()
  if (!raw) return fallback
  return raw.length > 280 ? `${raw.slice(0, 280)}...` : raw
}

export function evidenceLinked(row: ExtractedEvidence, links: EvidenceLink[]) {
  return links.some(l => l.evidence_id === row.id && l.status === 'active' && l.target_type === 'space')
}
