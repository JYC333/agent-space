import type { ReaderAnnotation } from '../../types/api'

interface ReaderAnnotationLayerProps {
  annotations: ReaderAnnotation[]
  selectedAnnotationId: string | null
  onSelect: (annotation: ReaderAnnotation) => void
}

// Renders an accessibility list for keyboard/screen-reader access.
// Visual highlights are rendered inside ReadOnlyTiptapReader via its annotations prop.
export function ReaderAnnotationLayer({
  annotations,
  onSelect,
}: ReaderAnnotationLayerProps) {
  const active = annotations.filter((a) => a.status === 'active')

  return (
    <div className="sr-only" aria-label="Annotations">
      {active.map((ann) => (
        <button
          key={ann.id}
          onClick={() => onSelect(ann)}
          aria-label={`${ann.annotation_type}: ${ann.quote_text}`}
        >
          {ann.quote_text}
        </button>
      ))}
    </div>
  )
}
