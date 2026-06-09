import { useEffect, useMemo, useState, type KeyboardEvent, type MouseEvent } from 'react'
import {
  ChevronRight, EyeOff, FileText, Folder, FolderPlus, MoreHorizontal, Pencil, Trash2,
} from 'lucide-react'
import type { NoteCollection, NoteSummary } from '../../../types/api'
import { cn } from '../../../lib/utils'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger,
} from '../../../components/ui/dropdown-menu'
import { TreeContextMenu, type TreeContextMenuPosition } from './TreeContextMenu'
import {
  buildCollectionTree, flattenVisibleNotes, groupNotesByCollection, isProtectedCollection, type CollectionNode,
} from './model'

/**
 * Notes tree wrapper boundary.
 *
 * Keep tree-specific rendering and interactions in this module: folder rows,
 * note rows, keyboard handlers, context menus, drag/drop, and any future
 * third-party tree renderer such as Wunderbaum. The page that renders this
 * component should continue to own APIs, routing, toasts/confirms, tabs, and
 * collection dialogs, passing those behaviors in through callbacks.
 */
export interface NotesTreeProps {
  collections: NoteCollection[]
  notes: NoteSummary[]
  selectedCollectionId: string | null
  activeNoteId?: string
  collapsedCollectionIds: Set<string>
  resolveNoteTitle: (id: string) => string
  onToggleCollection: (id: string) => void
  onSelectCollection: (id: string) => void
  onSelectNoteCollection?: (id: string) => void
  onOpenNote: (id: string) => void
  onArchiveNote: (note: Pick<NoteSummary, 'id' | 'title'>) => void
  onArchiveNotes?: (notes: Array<Pick<NoteSummary, 'id' | 'title'>>) => void
  onDeleteNote: (note: Pick<NoteSummary, 'id' | 'title'>) => void
  onDeleteNotes?: (notes: Array<Pick<NoteSummary, 'id' | 'title'>>) => void
  onCreateChild: (collection: NoteCollection) => void
  onRename: (collection: NoteCollection) => void
  onMove: (collection: NoteCollection) => void
  onHide: (collection: NoteCollection) => void
  onDeleteCollection: (collection: NoteCollection) => void
}

export default function NotesTree({
  collections, notes, selectedCollectionId, activeNoteId, collapsedCollectionIds,
  resolveNoteTitle, onToggleCollection, onSelectCollection, onSelectNoteCollection,
  onOpenNote, onArchiveNote, onArchiveNotes, onDeleteNote, onDeleteNotes,
  onCreateChild, onRename, onMove, onHide, onDeleteCollection,
}: NotesTreeProps) {
  const collectionTree = useMemo(() => buildCollectionTree(collections), [collections])
  const visibleTreeNotes = useMemo(
    () => notes.filter(note => note.status !== 'archived' && note.status !== 'deleted'),
    [notes],
  )
  const notesByCollection = useMemo(() => groupNotesByCollection(visibleTreeNotes), [visibleTreeNotes])
  const visibleNotes = useMemo(
    () => flattenVisibleNotes(collectionTree, notesByCollection, collapsedCollectionIds),
    [collectionTree, collapsedCollectionIds, notesByCollection],
  )
  const visibleNoteIds = useMemo(() => visibleNotes.map(note => note.id), [visibleNotes])
  const visibleNotesById = useMemo(() => new Map(visibleNotes.map(note => [note.id, note])), [visibleNotes])
  const [selectedNoteIds, setSelectedNoteIds] = useState<Set<string>>(() => new Set())
  const [selectionAnchorId, setSelectionAnchorId] = useState<string | null>(null)
  const [contextMenu, setContextMenu] = useState<(TreeContextMenuPosition & { noteId: string }) | null>(null)

  useEffect(() => {
    setSelectedNoteIds(prev => {
      const visible = new Set(visibleNoteIds)
      const next = new Set([...prev].filter(id => visible.has(id)))
      return next.size === prev.size ? prev : next
    })
    setSelectionAnchorId(prev => (prev && visibleNotesById.has(prev) ? prev : null))
  }, [visibleNoteIds, visibleNotesById])

  const contextMenuNotes = useMemo(() => {
    if (!contextMenu) return []
    const target = visibleNotesById.get(contextMenu.noteId)
    if (!target) return []
    const actionIds = selectedNoteIds.has(target.id) && selectedNoteIds.size > 1
      ? selectedNoteIds
      : new Set([target.id])
    return visibleNotes.filter(note => actionIds.has(note.id))
  }, [contextMenu, selectedNoteIds, visibleNotes, visibleNotesById])

  function notesForAction(note: NoteSummary) {
    if (selectedNoteIds.has(note.id) && selectedNoteIds.size > 1) {
      return visibleNotes.filter(item => selectedNoteIds.has(item.id))
    }
    return [note]
  }

  function selectRange(toId: string) {
    const fromId = selectionAnchorId ?? toId
    const from = visibleNoteIds.indexOf(fromId)
    const to = visibleNoteIds.indexOf(toId)
    if (from === -1 || to === -1) {
      setSelectedNoteIds(new Set([toId]))
      setSelectionAnchorId(toId)
      return
    }
    const [start, end] = from < to ? [from, to] : [to, from]
    setSelectedNoteIds(new Set(visibleNoteIds.slice(start, end + 1)))
  }

  function toggleSelected(noteId: string) {
    setSelectedNoteIds(prev => {
      const next = new Set(prev)
      if (next.has(noteId)) next.delete(noteId)
      else next.add(noteId)
      return next
    })
    setSelectionAnchorId(noteId)
  }

  function selectSingle(noteId: string) {
    setSelectedNoteIds(new Set([noteId]))
    setSelectionAnchorId(noteId)
  }

  function syncNoteCollection(note: NoteSummary) {
    if (note.collection_id) onSelectNoteCollection?.(note.collection_id)
  }

  function handleCollectionSelect(id: string) {
    setSelectedNoteIds(new Set())
    setSelectionAnchorId(null)
    setContextMenu(null)
    onSelectCollection(id)
  }

  function handleNoteClick(note: NoteSummary, event: MouseEvent<HTMLButtonElement>) {
    syncNoteCollection(note)
    if (event.shiftKey) {
      selectRange(note.id)
      return
    }
    if (event.metaKey || event.ctrlKey) {
      toggleSelected(note.id)
      return
    }
    selectSingle(note.id)
    onOpenNote(note.id)
  }

  function handleNoteContextMenu(note: NoteSummary, event: MouseEvent<HTMLButtonElement>) {
    event.preventDefault()
    syncNoteCollection(note)
    if (!selectedNoteIds.has(note.id)) selectSingle(note.id)
    setContextMenu({ x: event.clientX, y: event.clientY, noteId: note.id })
  }

  function requestDeleteNotes(targetNotes: NoteSummary[]) {
    setContextMenu(null)
    const uniqueNotes = [...new Map(targetNotes.map(note => [note.id, note])).values()]
    if (uniqueNotes.length === 0) return
    if (uniqueNotes.length === 1 || !onDeleteNotes) {
      uniqueNotes.forEach(note => onDeleteNote(note))
      return
    }
    onDeleteNotes(uniqueNotes)
  }

  function requestArchiveNotes(targetNotes: NoteSummary[]) {
    setContextMenu(null)
    const uniqueNotes = [...new Map(targetNotes.map(note => [note.id, note])).values()]
    if (uniqueNotes.length === 0) return
    if (uniqueNotes.length === 1 || !onArchiveNotes) {
      uniqueNotes.forEach(note => onArchiveNote(note))
      return
    }
    onArchiveNotes(uniqueNotes)
  }

  return (
    <>
      <CollectionTree
        nodes={collectionTree}
        notesByCollection={notesByCollection}
        selectedId={selectedCollectionId}
        activeNoteId={activeNoteId}
        selectedNoteIds={selectedNoteIds}
        collapsed={collapsedCollectionIds}
        onToggle={onToggleCollection}
        onSelect={handleCollectionSelect}
        onNoteClick={handleNoteClick}
        onNoteContextMenu={handleNoteContextMenu}
        onDeleteNotes={note => requestDeleteNotes(notesForAction(note))}
        titleFor={resolveNoteTitle}
        onCreateChild={onCreateChild}
        onRename={onRename}
        onMove={onMove}
        onHide={onHide}
        onDelete={onDeleteCollection}
      />
      <TreeContextMenu
        label={contextMenuNotes.length > 1 ? 'Selected notes' : contextMenuNotes[0]?.title ?? 'Note'}
        archiveLabel={contextMenuNotes.length > 1 ? `Archive ${contextMenuNotes.length} notes` : 'Archive'}
        deleteLabel={contextMenuNotes.length > 1 ? `Delete ${contextMenuNotes.length} notes` : 'Delete'}
        position={contextMenu}
        onClose={() => setContextMenu(null)}
        onArchive={() => requestArchiveNotes(contextMenuNotes)}
        onDelete={() => requestDeleteNotes(contextMenuNotes)}
      />
    </>
  )
}

interface CollectionTreeProps {
  nodes: CollectionNode[]
  notesByCollection: Map<string, NoteSummary[]>
  selectedId: string | null
  activeNoteId: string | undefined
  selectedNoteIds: Set<string>
  collapsed: Set<string>
  onToggle: (id: string) => void
  onSelect: (id: string) => void
  onNoteClick: (note: NoteSummary, event: MouseEvent<HTMLButtonElement>) => void
  onNoteContextMenu: (note: NoteSummary, event: MouseEvent<HTMLButtonElement>) => void
  onDeleteNotes: (note: NoteSummary) => void
  titleFor: (id: string) => string
  onCreateChild: (collection: NoteCollection) => void
  onRename: (collection: NoteCollection) => void
  onMove: (collection: NoteCollection) => void
  onHide: (collection: NoteCollection) => void
  onDelete: (collection: NoteCollection) => void
  depth?: number
}

function CollectionTree({
  nodes, notesByCollection, selectedId, activeNoteId, selectedNoteIds, collapsed,
  onToggle, onSelect, onNoteClick, onNoteContextMenu, onDeleteNotes, titleFor,
  onCreateChild, onRename, onMove, onHide, onDelete, depth = 0,
}: CollectionTreeProps) {
  return (
    <div className="space-y-0.5">
      {nodes.map(node => {
        const active = node.id === selectedId
        const visualDepth = Math.min(depth, 2)
        const indent = 8 + visualDepth * 14
        const protectedCollection = isProtectedCollection(node)
        const childNotes = notesByCollection.get(node.id) ?? []
        const hasChildren = node.children.length > 0 || childNotes.length > 0
        const expanded = hasChildren && !collapsed.has(node.id)

        return (
          <div key={node.id}>
            <div
              className={cn(
                'group flex items-center gap-1 rounded-md pr-1 text-[13px] transition-colors',
                active
                  ? 'bg-primary/10 text-accent-foreground font-medium'
                  : 'text-muted-foreground hover:text-foreground hover:bg-accent',
              )}
              style={{ paddingLeft: indent }}
            >
              {hasChildren ? (
                <button
                  type="button"
                  onClick={() => onToggle(node.id)}
                  aria-label={expanded ? `Collapse ${node.name}` : `Expand ${node.name}`}
                  className="flex size-5 shrink-0 items-center justify-center rounded text-muted-foreground hover:text-foreground"
                >
                  <ChevronRight className={cn('size-3.5 transition-transform', expanded && 'rotate-90')} />
                </button>
              ) : (
                <span className="size-5 shrink-0" aria-hidden />
              )}
              <button
                type="button"
                onClick={() => onSelect(node.id)}
                className="min-w-0 flex-1 flex items-center gap-2 py-1.5 text-left"
                title={node.name}
              >
                <Folder className="size-4 shrink-0" />
                <span className="truncate">{node.name}</span>
              </button>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    type="button"
                    aria-label={`Folder actions for ${node.name}`}
                    className="shrink-0 rounded p-1 opacity-0 group-hover:opacity-100 focus:opacity-100 hover:bg-background/80"
                  >
                    <MoreHorizontal className="size-3.5" />
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onSelect={() => onCreateChild(node)}>
                    <FolderPlus className="size-4" /> New child folder
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => onRename(node)}>
                    <Pencil className="size-4" /> Rename
                  </DropdownMenuItem>
                  {!protectedCollection && (
                    <DropdownMenuItem onSelect={() => onMove(node)}>
                      <Folder className="size-4" /> Move
                    </DropdownMenuItem>
                  )}
                  {!protectedCollection && <DropdownMenuSeparator />}
                  {!protectedCollection && (
                    <DropdownMenuItem onSelect={() => onHide(node)}>
                      <EyeOff className="size-4" /> Hide
                    </DropdownMenuItem>
                  )}
                  {!protectedCollection && (
                    <DropdownMenuItem onSelect={() => onDelete(node)} className="text-destructive">
                      <Trash2 className="size-4" /> Delete
                    </DropdownMenuItem>
                  )}
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
            {expanded && (
              <div className="mt-1 space-y-1">
                {node.children.length > 0 && (
                  <CollectionTree
                    nodes={node.children}
                    notesByCollection={notesByCollection}
                    selectedId={selectedId}
                    activeNoteId={activeNoteId}
                    selectedNoteIds={selectedNoteIds}
                    collapsed={collapsed}
                    onToggle={onToggle}
                    onSelect={onSelect}
                    onNoteClick={onNoteClick}
                    onNoteContextMenu={onNoteContextMenu}
                    onDeleteNotes={onDeleteNotes}
                    titleFor={titleFor}
                    onCreateChild={onCreateChild}
                    onRename={onRename}
                    onMove={onMove}
                    onHide={onHide}
                    onDelete={onDelete}
                    depth={depth + 1}
                  />
                )}
                {childNotes.map(note => (
                  <NoteTreeItem
                    key={note.id}
                    title={titleFor(note.id)}
                    active={note.id === activeNoteId}
                    selected={selectedNoteIds.has(note.id)}
                    muted={note.status === 'archived'}
                    onClick={event => onNoteClick(note, event)}
                    onContextMenu={event => onNoteContextMenu(note, event)}
                    onDelete={() => onDeleteNotes(note)}
                    indent={indent + 26}
                  />
                ))}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

function NoteTreeItem({
  title, active, selected, muted, onClick, onContextMenu, onDelete, indent,
}: {
  title: string
  active: boolean
  selected: boolean
  muted: boolean
  onClick: (event: MouseEvent<HTMLButtonElement>) => void
  onContextMenu: (event: MouseEvent<HTMLButtonElement>) => void
  onDelete: () => void
  indent: number
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onClick}
      onContextMenu={onContextMenu}
      onKeyDown={(event: KeyboardEvent<HTMLButtonElement>) => {
        if (event.key !== 'Delete') return
        event.preventDefault()
        onDelete()
      }}
      title={title}
      style={{ paddingLeft: indent }}
      className={cn(
        'mx-1 flex w-[calc(100%-0.5rem)] items-center gap-2 rounded-md py-1 pr-2 text-[13px] transition-colors',
        active
          ? 'bg-primary/10 text-accent-foreground font-medium'
          : selected
            ? 'bg-accent text-foreground'
            : 'text-muted-foreground hover:text-foreground hover:bg-accent',
        muted && !active && 'opacity-60',
      )}
    >
      <FileText className="size-3.5 shrink-0 opacity-70" />
      <span className="truncate">{title}</span>
    </button>
  )
}
