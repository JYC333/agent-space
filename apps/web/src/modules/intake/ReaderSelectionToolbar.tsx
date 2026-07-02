import type { CSSProperties } from 'react'
import { Bookmark, Highlighter, MessageSquare, Quote } from 'lucide-react'
import { Button } from '../../components/ui/button'
import { cn } from '../../lib/utils'
import type { SelectionRect } from '../../components/editor/ReadOnlyTiptapReader'
import type { ReaderAnnotationType } from './readerModel'

interface ReaderSelectionToolbarProps {
  selectionRect: SelectionRect | null
  pending: boolean
  onAction: (type: ReaderAnnotationType) => void
}

const ACTIONS: { type: ReaderAnnotationType; label: string; Icon: typeof Highlighter }[] = [
  { type: 'highlight', label: 'Highlight', Icon: Highlighter },
  { type: 'comment', label: 'Comment', Icon: MessageSquare },
  { type: 'excerpt', label: 'Excerpt', Icon: Quote },
  { type: 'bookmark', label: 'Bookmark', Icon: Bookmark },
]

const TOOLBAR_WIDTH = 168
const TOOLBAR_HEIGHT = 40
const EDGE_GAP = 8

function hasUsableRect(rect: SelectionRect | null): rect is SelectionRect {
  return rect != null && (rect.width > 0 || rect.height > 0)
}

/** Above the selection when there is room, below it otherwise, clamped to the viewport. */
function floatingStyle(rect: SelectionRect): CSSProperties {
  const above = rect.top - TOOLBAR_HEIGHT - EDGE_GAP
  const top = above >= EDGE_GAP
    ? above
    : Math.min(rect.bottom + EDGE_GAP, window.innerHeight - TOOLBAR_HEIGHT - EDGE_GAP)
  const center = rect.left + rect.width / 2
  const maxLeft = Math.max(EDGE_GAP, window.innerWidth - TOOLBAR_WIDTH - EDGE_GAP)
  const left = Math.min(Math.max(center - TOOLBAR_WIDTH / 2, EDGE_GAP), maxLeft)
  return { top, left }
}

export function ReaderSelectionToolbar({
  selectionRect,
  pending,
  onAction,
}: ReaderSelectionToolbarProps) {
  const floating = hasUsableRect(selectionRect)
  return (
    <div
      role="toolbar"
      aria-label="Annotate selection"
      className={cn(
        'reader-selection-toolbar',
        floating ? 'reader-selection-toolbar-floating' : 'reader-selection-toolbar-docked',
      )}
      style={floating ? floatingStyle(selectionRect) : undefined}
      // Keep the browser selection alive while clicking toolbar buttons.
      onMouseDown={(e) => e.preventDefault()}
    >
      {ACTIONS.map(({ type, label, Icon }) => (
        <Button
          key={type}
          variant="ghost"
          size="icon"
          className="size-8"
          disabled={pending}
          aria-label={label}
          title={label}
          onClick={() => onAction(type)}
        >
          <Icon className="size-4" />
        </Button>
      ))}
    </div>
  )
}
