import type { NoteCollection, NoteSummary } from '../../../types/api'

export interface CollectionNode extends NoteCollection {
  children: CollectionNode[]
}

export function buildCollectionTree(collections: NoteCollection[]): CollectionNode[] {
  const nodes = new Map<string, CollectionNode>()
  collections.forEach(collection => nodes.set(collection.id, { ...collection, children: [] }))

  const roots: CollectionNode[] = []
  nodes.forEach(node => {
    const parent = node.parent_id ? nodes.get(node.parent_id) : null
    if (parent) parent.children.push(node)
    else roots.push(node)
  })

  const sortNodes = (items: CollectionNode[]) => {
    items.sort((a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name))
    items.forEach(item => sortNodes(item.children))
  }
  sortNodes(roots)

  return roots
}

export function groupNotesByCollection(notes: NoteSummary[]) {
  const map = new Map<string, NoteSummary[]>()

  for (const note of notes) {
    if (!note.collection_id) continue
    const bucket = map.get(note.collection_id)
    if (bucket) bucket.push(note)
    else map.set(note.collection_id, [note])
  }

  for (const bucket of map.values()) {
    bucket.sort((a, b) => (b.updated_at ?? '').localeCompare(a.updated_at ?? ''))
  }

  return map
}

export function flattenVisibleNotes(
  nodes: CollectionNode[],
  notesByCollection: Map<string, NoteSummary[]>,
  collapsedCollectionIds: Set<string>,
) {
  const out: NoteSummary[] = []

  function visit(items: CollectionNode[]) {
    for (const node of items) {
      const childNotes = notesByCollection.get(node.id) ?? []
      const expanded = (node.children.length > 0 || childNotes.length > 0) && !collapsedCollectionIds.has(node.id)
      if (!expanded) continue
      visit(node.children)
      out.push(...childNotes)
    }
  }

  visit(nodes)
  return out
}

export function collectionPath(collection: NoteCollection, byId: Map<string, NoteCollection>) {
  const names = [collection.name]
  let current = collection
  const seen = new Set<string>([collection.id])

  while (current.parent_id) {
    const parent = byId.get(current.parent_id)
    if (!parent || seen.has(parent.id)) break
    names.unshift(parent.name)
    seen.add(parent.id)
    current = parent
  }

  return names.join(' / ')
}

export function isProtectedCollection(collection: NoteCollection) {
  return collection.is_system || collection.system_role !== 'normal'
}
