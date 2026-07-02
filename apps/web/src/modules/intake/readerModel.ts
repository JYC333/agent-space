import type { ReaderAnnotation, ReaderCommentThread } from '../../types/api'

export type ReaderAnnotationType = ReaderAnnotation['annotation_type']

/** Document-order position: tiptap_range.from, then text_range.start, else end of list. */
function anchorSortKey(ann: ReaderAnnotation): number {
  return (
    ann.anchor_json.tiptap_range?.from ??
    ann.anchor_json.text_range?.start ??
    Number.POSITIVE_INFINITY
  )
}

export function activeAnnotationsInDocumentOrder(
  annotations: ReaderAnnotation[],
): ReaderAnnotation[] {
  return annotations
    .filter((ann) => ann.status === 'active')
    .sort((a, b) => {
      const diff = anchorSortKey(a) - anchorSortKey(b)
      if (diff !== 0) return diff
      return a.created_at.localeCompare(b.created_at)
    })
}

export function annotationCountsByType(
  annotations: ReaderAnnotation[],
): Record<ReaderAnnotationType, number> {
  const counts: Record<ReaderAnnotationType, number> = {
    highlight: 0,
    comment: 0,
    excerpt: 0,
    bookmark: 0,
  }
  for (const ann of annotations) counts[ann.annotation_type] += 1
  return counts
}

export function openThreadCount(threads: ReaderCommentThread[]): number {
  return threads.filter((t) => t.status === 'open').length
}
