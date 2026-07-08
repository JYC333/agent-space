import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { sourcesApi, sourceReaderApi } from '../../api/client'
import { SpaceLink as Link } from '../../core/spaceNav'
import { useSpace } from '../../contexts/SpaceContext'
import { errMsg, isNotFoundError } from '../../lib/utils'
import type {
  ReaderAnchorJson,
  ReaderAnnotation,
  ReaderAnnotationCreate,
  ReaderCommentThread,
  ReaderDocumentPayload,
  SourcePostProcessingBriefingDetail,
  SourcePostProcessingItemRelevance,
} from '../../types/api'
import {
  ReadOnlyTiptapReader,
  type ReadOnlyTiptapReaderHandle,
  type TextSelection,
} from '../../components/editor/ReadOnlyTiptapReader'
import { ReaderAnnotationLayer } from '../../components/reader/ReaderAnnotationLayer'
import { ReaderInspector } from '../../components/reader/ReaderInspector'
import { ReaderSelectionToolbar } from '../../components/reader/ReaderSelectionToolbar'
import { ReaderShortcutsDialog } from '../../components/reader/ReaderShortcutsDialog'
import { activeAnnotationsInDocumentOrder, type ReaderAnnotationType } from '../../components/reader/readerModel'
import { runPendingItemJob } from '../sources/sourceActions'
import { textExtractionActionLabel, textExtractionDisabledReason } from '../sources/sourcePageModel'
import { Skeleton } from '../../components/ui/skeleton'
import { EmptyState } from '../../components/ui/empty-state'
import { Button } from '../../components/ui/button'
import { ArrowLeft, ChevronLeft, ChevronRight, ExternalLink, FileText, PanelRight, RefreshCw } from 'lucide-react'

type Visibility = 'private' | 'space_shared'

/** Item order within a day matches LibraryDetailPage's own rendering order:
 *  relevant, then maybe, then not_relevant, each in the (already-recency-sorted)
 *  order the backend returned; first occurrence wins if an item was re-decided
 *  across more than one run that day. */
const RELEVANCE_ORDER: SourcePostProcessingItemRelevance[] = ['relevant', 'maybe', 'not_relevant']

function orderedItemIdsFromBriefing(briefing: SourcePostProcessingBriefingDetail): string[] {
  const seen = new Set<string>()
  const ids: string[] = []
  for (const relevance of RELEVANCE_ORDER) {
    for (const decision of briefing.item_decisions) {
      if (decision.relevance !== relevance || seen.has(decision.source_item_id)) continue
      seen.add(decision.source_item_id)
      ids.push(decision.source_item_id)
    }
  }
  return ids
}

export default function LibraryItemReaderPage() {
  const { itemId = '', connectionId, date } = useParams<{ itemId: string; connectionId?: string; date?: string }>()
  const { activeSpaceId } = useSpace()

  // Day context (only present on the /library/digests/:connectionId/:date/items/:itemId route):
  // powers the prev/next flow across that day's briefing items and the "back to day" link.
  const [briefing, setBriefing] = useState<SourcePostProcessingBriefingDetail | null>(null)

  useEffect(() => {
    if (!connectionId || !date) {
      setBriefing(null)
      return
    }
    let cancelled = false
    setBriefing(null)
    sourcesApi.briefing(connectionId, date)
      .then((result) => { if (!cancelled) setBriefing(result) })
      .catch(() => { if (!cancelled) setBriefing(null) }) // Degrade to no prev/next; the item itself loads independently below.
    return () => { cancelled = true }
  }, [connectionId, date])

  const dayItemIds = useMemo(() => briefing ? orderedItemIdsFromBriefing(briefing) : [], [briefing])
  const dayIndex = dayItemIds.indexOf(itemId)
  const prevItemId = dayIndex > 0 ? dayItemIds[dayIndex - 1] : null
  const nextItemId = dayIndex >= 0 && dayIndex < dayItemIds.length - 1 ? dayItemIds[dayIndex + 1] : null

  const [doc, setDoc] = useState<ReaderDocumentPayload | null>(null)
  const [annotations, setAnnotations] = useState<ReaderAnnotation[]>([])
  const [threads, setThreads] = useState<ReaderCommentThread[]>([])
  const [loading, setLoading] = useState(true)
  const [panelOpen, setPanelOpen] = useState(true)

  const [selection, setSelection] = useState<TextSelection | null>(null)
  const [selectedAnnotation, setSelectedAnnotation] = useState<ReaderAnnotation | null>(null)
  const [pendingAnnotationType, setPendingAnnotationType] = useState<ReaderAnnotationType | null>(null)
  const [createVisibility, setCreateVisibility] = useState<Visibility>('private')
  const [createLabel, setCreateLabel] = useState('')
  const [focusedBlockIndex, setFocusedBlockIndex] = useState<number | null>(null)
  const [shortcutsOpen, setShortcutsOpen] = useState(false)
  const [pendingCommentFocusAnnotationId, setPendingCommentFocusAnnotationId] = useState<string | null>(null)
  const [reextracting, setReextracting] = useState(false)

  const readerRef = useRef<HTMLDivElement>(null)
  const readerHandleRef = useRef<ReadOnlyTiptapReaderHandle>(null)
  const commentInputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (!itemId || !activeSpaceId) {
      setDoc(null)
      setAnnotations([])
      setThreads([])
      setSelection(null)
      setSelectedAnnotation(null)
      setFocusedBlockIndex(null)
      setPendingAnnotationType(null)
      setPendingCommentFocusAnnotationId(null)
      setLoading(false)
      return
    }
    let cancelled = false
    ;(async () => {
      setLoading(true)
      setSelection(null)
      setSelectedAnnotation(null)
      setThreads([])
      setFocusedBlockIndex(null)
      setPendingAnnotationType(null)
      setPendingCommentFocusAnnotationId(null)
      try {
        const [d, annRes] = await Promise.all([
          sourceReaderApi.getDocument('source_item', itemId),
          sourceReaderApi.listAnnotations('source_item', itemId),
        ])
        if (!cancelled) {
          setDoc(d)
          setAnnotations(annRes.items)
        }
      } catch (e) {
        if (!cancelled) {
          if (!isNotFoundError(e)) toast.error(errMsg(e))
          setDoc(null)
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [itemId, activeSpaceId])

  const activeAnnotations = useMemo(
    () => activeAnnotationsInDocumentOrder(annotations),
    [annotations],
  )

  useEffect(() => {
    if (!pendingCommentFocusAnnotationId || !panelOpen) return
    if (selectedAnnotation?.id !== pendingCommentFocusAnnotationId) return
    const input = commentInputRef.current
    if (!input) return
    input.focus()
    setPendingCommentFocusAnnotationId(null)
  }, [pendingCommentFocusAnnotationId, panelOpen, selectedAnnotation?.id])

  const handleTextSelected = useCallback((sel: TextSelection | null) => {
    setSelection(sel)
    if (sel) setSelectedAnnotation(null)
  }, [])

  const scrollToAnnotation = useCallback((ann: ReaderAnnotation) => {
    if (!ann.anchor_json.tiptap_range) return
    readerRef.current
      ?.querySelector(`[data-annotation-id="${CSS.escape(ann.id)}"]`)
      ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [])

  const selectAnnotation = useCallback((ann: ReaderAnnotation, opts?: { scroll?: boolean }) => {
    setSelectedAnnotation(ann)
    setSelection(null)
    setPanelOpen(true)
    if (opts?.scroll) scrollToAnnotation(ann)
    sourceReaderApi.listThreads(ann.id)
      .then((res) => setThreads(res.items))
      .catch((e) => toast.error(errMsg(e)))
  }, [scrollToAnnotation])

  const handleAnnotationClickById = useCallback((annotationId: string) => {
    const ann = annotations.find((a) => a.id === annotationId)
    if (ann) selectAnnotation(ann)
  }, [annotations, selectAnnotation])

  const createAnnotation = useCallback(async (type: ReaderAnnotationType, sel: TextSelection) => {
    if (!doc || pendingAnnotationType) return
    setPendingAnnotationType(type)
    try {
      const draft = sel.anchorDraft
      const anchor: ReaderAnchorJson = {
        schema_version: 1,
        normalizer: 'plain_text_v1',
        quote_text: draft.quote_text,
        text_range: draft.text_range,
        before_context: draft.before_context,
        after_context: draft.after_context,
        ...(draft.tiptap_range ? { tiptap_range: draft.tiptap_range } : {}),
        ...(draft.block_ref ? { block_ref: draft.block_ref } : {}),
        content_hash: doc.content_hash,
        document_ref: { document_type: doc.document_type, document_id: doc.document_id },
      }
      const body: ReaderAnnotationCreate = {
        annotation_type: type,
        quote_text: sel.quoteText,
        anchor_json: anchor,
        visibility: createVisibility,
        label: createLabel.trim() || undefined,
      }
      if (doc.document_type === 'source_item') body.source_item_id = doc.document_id
      else if (doc.document_type === 'artifact') body.artifact_id = doc.document_id
      else if (doc.document_type === 'source_snapshot') body.source_snapshot_id = doc.document_id

      const created = await sourceReaderApi.createAnnotation(body)
      setAnnotations((prev) => [...prev, created])
      setSelection(null)
      setSelectedAnnotation(created)
      setThreads([])
      setPanelOpen(true)
      setCreateLabel('')
      toast.success('Annotation saved')
      if (type === 'comment') {
        setPendingCommentFocusAnnotationId(created.id)
      }
    } catch (e) {
      // Keep the selection so the user can retry.
      toast.error(errMsg(e))
    } finally {
      setPendingAnnotationType(null)
    }
  }, [doc, pendingAnnotationType, createVisibility, createLabel])

  const createAnnotationFromSelection = useCallback((type: ReaderAnnotationType) => {
    if (selection) void createAnnotation(type, selection)
  }, [selection, createAnnotation])

  // Keyboard reading flow: arrows move a paragraph focus indicator; H/N annotate
  // the selection or the focused block; [ ] toggles the inspector.
  useEffect(() => {
    if (!doc) return
    function onKeyDown(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null
      if (target?.closest('input, textarea, select, [contenteditable="true"], [role="dialog"]')) return
      if (e.metaKey || e.ctrlKey || e.altKey) return

      const annotateFocused = (type: ReaderAnnotationType) => {
        if (selection) {
          void createAnnotation(type, selection)
          return
        }
        if (focusedBlockIndex == null) return
        const blockSel = readerHandleRef.current?.blockSelection(focusedBlockIndex)
        if (blockSel) {
          void createAnnotation(type, blockSel)
          return
        }
        toast.error('Focused block has no text to annotate')
      }

      switch (e.key) {
        case 'ArrowDown':
        case 'ArrowUp': {
          const count = readerHandleRef.current?.blockCount() ?? 0
          if (count === 0) return
          e.preventDefault()
          const delta = e.key === 'ArrowDown' ? 1 : -1
          const next = focusedBlockIndex == null
            ? (delta === 1 ? 0 : count - 1)
            : Math.min(count - 1, Math.max(0, focusedBlockIndex + delta))
          setFocusedBlockIndex(next)
          readerHandleRef.current?.scrollToBlock(next)
          break
        }
        case 'h':
        case 'H':
          annotateFocused('highlight')
          break
        case 'n':
        case 'N':
          annotateFocused('comment')
          break
        case '[':
        case ']':
          setPanelOpen((o) => !o)
          break
        case 'Escape':
          setSelection(null)
          setFocusedBlockIndex(null)
          break
        case '?':
          setShortcutsOpen(true)
          break
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [doc, selection, focusedBlockIndex, createAnnotation])

  const handleAnnotationArchived = useCallback((annId: string) => {
    setAnnotations((prev) => prev.filter((a) => a.id !== annId))
    setSelectedAnnotation(null)
    setThreads([])
  }, [])

  const handleInspectorClose = useCallback(() => {
    setPanelOpen(false)
  }, [])

  async function runQueuedItemJob(itemId: string, jobType: string, label: string) {
    const result = await runPendingItemJob(itemId, jobType)
    if (!result) {
      toast.success(`${label} queued`)
      return
    }
    toast.success(`${label} ${result.status}`)
  }

  async function reextractReaderDocument() {
    if (!doc || doc.document_type !== 'source_item' || !doc.content_state) return
    const disabledReason = textExtractionDisabledReason({
      content_state: doc.content_state,
      source_uri: doc.source_uri,
    })
    if (disabledReason) {
      toast.error(disabledReason)
      return
    }

    setReextracting(true)
    try {
      await sourcesApi.itemAction(doc.document_id, 'queue_content')
      await runQueuedItemJob(doc.document_id, 'extract_text', 'Text extraction')
      const [d, annRes] = await Promise.all([
        sourceReaderApi.getDocument('source_item', doc.document_id),
        sourceReaderApi.listAnnotations('source_item', doc.document_id),
      ])
      setDoc(d)
      setAnnotations(annRes.items)
      setSelection(null)
      setSelectedAnnotation(null)
      setThreads([])
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setReextracting(false)
    }
  }

  if (loading) {
    return (
      <div className="p-6 space-y-4 max-w-3xl">
        <Skeleton className="h-6 w-32" />
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-96 w-full" />
      </div>
    )
  }

  // Day-scoped route: back goes to the day's briefing and prev/next steps through
  // its items. Standalone readers return to the Library reading stream.
  const dayScoped = Boolean(connectionId && date)
  const backTo = dayScoped ? `/library/digests/${connectionId}/${date}` : '/library/items'
  const backLabel = dayScoped ? (briefing?.connection_name ?? 'Day') : 'Library'
  const itemPath = (id: string) => `/library/digests/${connectionId}/${date}/items/${id}`

  if (!doc) {
    return (
      <div className="p-6">
        <Button variant="ghost" size="sm" asChild>
          <Link to={backTo}><ArrowLeft className="size-4 mr-1" />{backLabel}</Link>
        </Button>
        <EmptyState
          title="Document not found"
          description="No readable content is available for this item. Try queueing content extraction first."
        />
      </div>
    )
  }

  const readerTextExtractionReason = doc.document_type === 'source_item' && doc.content_state
    ? textExtractionDisabledReason({ content_state: doc.content_state, source_uri: doc.source_uri })
    : 'Text extraction is only available for source items.'
  const readerTextExtractionLabel = doc.content_state
    ? textExtractionActionLabel({ content_state: doc.content_state })
    : 'Extract text'

  return (
    <div className="reader-workspace flex flex-col h-full">
      {/* Header */}
      <header className="flex items-center gap-3 px-4 py-2 border-b shrink-0">
        <Button variant="ghost" size="sm" asChild>
          <Link to={backTo}><ArrowLeft className="size-4 mr-1" />{backLabel}</Link>
        </Button>
        {dayScoped && (
          <div className="flex items-center gap-0.5 shrink-0">
            {prevItemId ? (
              <Button variant="ghost" size="icon" className="size-7" asChild>
                <Link to={itemPath(prevItemId)} aria-label="Previous item"><ChevronLeft className="size-4" /></Link>
              </Button>
            ) : (
              <Button variant="ghost" size="icon" className="size-7" disabled aria-label="Previous item">
                <ChevronLeft className="size-4" />
              </Button>
            )}
            {nextItemId ? (
              <Button variant="ghost" size="icon" className="size-7" asChild>
                <Link to={itemPath(nextItemId)} aria-label="Next item"><ChevronRight className="size-4" /></Link>
              </Button>
            ) : (
              <Button variant="ghost" size="icon" className="size-7" disabled aria-label="Next item">
                <ChevronRight className="size-4" />
              </Button>
            )}
          </div>
        )}
        <div className="min-w-0 flex-1">
          <h1 className="text-sm font-medium truncate">{doc.title}</h1>
          {doc.content_state && (
            <p className="text-xs text-muted-foreground truncate">
              {doc.document_type} · {doc.content_state}
            </p>
          )}
        </div>
        {doc.source_uri && (
          <Button variant="ghost" size="icon" className="size-7" asChild>
            <a href={doc.source_uri} target="_blank" rel="noreferrer" aria-label="Open source URL">
              <ExternalLink className="size-4" />
            </a>
          </Button>
        )}
        {doc.document_type === 'source_item' && (
          <Button
            variant="outline"
            size="sm"
            className="h-7 px-2 text-xs"
            disabled={reextracting || readerTextExtractionReason !== null}
            title={readerTextExtractionReason ?? undefined}
            onClick={reextractReaderDocument}
          >
            {doc.content_state === 'content_saved' ? <RefreshCw className="size-3.5" /> : <FileText className="size-3.5" />}
            {reextracting ? 'Extracting...' : readerTextExtractionLabel}
          </Button>
        )}
        <Button
          variant="ghost" size="icon" className="size-7"
          onClick={() => setPanelOpen((o) => !o)}
          aria-label={panelOpen ? 'Hide inspector' : 'Show inspector'}
        >
          <PanelRight className="size-4" />
        </Button>
      </header>

      {/* Body */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        <div className="reader-document-shell flex-1 overflow-y-auto relative" ref={readerRef}>
          <ReaderAnnotationLayer
            annotations={annotations}
            selectedAnnotationId={selectedAnnotation?.id ?? null}
            onSelect={selectAnnotation}
          />
          <div className="reader-column mx-auto px-6 py-10">
            <ReadOnlyTiptapReader
              ref={readerHandleRef}
              contentJson={doc.content_json}
              normalizedText={doc.normalized_text}
              onTextSelected={handleTextSelected}
              onBlockFocused={setFocusedBlockIndex}
              onAnnotationClick={handleAnnotationClickById}
              annotations={annotations}
              selectedAnnotationId={selectedAnnotation?.id ?? null}
              focusedBlockIndex={focusedBlockIndex}
            />
          </div>
        </div>

        {panelOpen && (
          <ReaderInspector
            annotations={activeAnnotations}
            selection={selection}
            selectedAnnotation={selectedAnnotation}
            threads={threads}
            createVisibility={createVisibility}
            onCreateVisibilityChange={setCreateVisibility}
            createLabel={createLabel}
            onCreateLabelChange={setCreateLabel}
            commentInputRef={commentInputRef}
            onSelectAnnotation={(ann) => selectAnnotation(ann, { scroll: true })}
            onAnnotationArchived={handleAnnotationArchived}
            onThreadsUpdated={setThreads}
            onClose={handleInspectorClose}
          />
        )}
      </div>

      {selection && (
        <ReaderSelectionToolbar
          selectionRect={selection.selectionRect}
          pending={pendingAnnotationType !== null}
          onAction={createAnnotationFromSelection}
        />
      )}

      <ReaderShortcutsDialog open={shortcutsOpen} onOpenChange={setShortcutsOpen} />
    </div>
  )
}
