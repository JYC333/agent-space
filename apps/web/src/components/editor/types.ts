export const RICH_TEXT_CONTENT_FORMAT = 'prosemirror_json' as const
export const RICH_TEXT_SCHEMA_VERSION = 1 as const

export type RichTextContentFormat = typeof RICH_TEXT_CONTENT_FORMAT
export type RichTextSchemaVersion = typeof RICH_TEXT_SCHEMA_VERSION
export type RichTextDocument = Record<string, unknown>

export interface RichTextSnapshot {
  content_json: RichTextDocument
  content_format: RichTextContentFormat
  content_schema_version: RichTextSchemaVersion
}

export interface RichTextEditorHandle {
  getSnapshot: () => RichTextSnapshot
  focus: () => void
}

export interface RichTextEditorProps {
  initialContent: RichTextDocument
  /**
   * `default`/`notes` render the editor as a bordered field. `page` renders it
   * borderless and full-bleed for a document-style surface (no card box), with a
   * sticky formatting toolbar — used by the open-note editor.
   */
  variant?: 'default' | 'notes' | 'page'
  className?: string
  /** Fired on user-driven content edits (not when content is set programmatically). */
  onChange?: () => void
}
