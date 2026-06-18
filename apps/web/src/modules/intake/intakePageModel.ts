import type { EvidenceLink, ExtractedEvidence } from '../../types/api'

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
