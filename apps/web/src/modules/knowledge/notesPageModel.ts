import type { EntityLink, NoteStatus, NoteSummary } from '../../types/api'

export const ROOT_PARENT = '__root__'

export function fmt(dt: string | null | undefined) {
  return dt ? new Date(dt).toLocaleString() : '—'
}

export function activeNoteIdFromPath(logicalPath: string): string | undefined {
  return logicalPath.match(/^\/knowledge\/notes\/([^/]+)$/)?.[1]
}

function tabsKey(spaceId: string | null) {
  return `agent-space:notes-tabs:${spaceId ?? 'none'}`
}

export function readTabs(spaceId: string | null): string[] {
  try {
    const v = JSON.parse(sessionStorage.getItem(tabsKey(spaceId)) ?? '[]')
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : []
  } catch {
    return []
  }
}

export function writeTabs(spaceId: string | null, ids: string[]) {
  try { sessionStorage.setItem(tabsKey(spaceId), JSON.stringify(ids)) } catch { /* ignore */ }
}

export function hideArchivedOrDeletedNotes(notes: NoteSummary[]) {
  return notes.filter(note => note.status !== 'archived' && note.status !== 'deleted')
}

export function isNoteToNoteLink(link: EntityLink) {
  return link.source_type === 'note' && link.target_type === 'note'
}

export function restoreStatus(status: NoteStatus | undefined) {
  return status && status !== 'archived' && status !== 'deleted' ? status : 'active'
}
