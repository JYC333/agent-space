import { forwardRef } from 'react'
import type { RichTextEditorHandle, RichTextEditorProps } from './types'
import { TiptapEditorAdapter } from './TiptapEditorAdapter'

export const RichTextEditor = forwardRef<RichTextEditorHandle, RichTextEditorProps>(
  function RichTextEditor(props, ref) {
    return <TiptapEditorAdapter {...props} ref={ref} />
  },
)
