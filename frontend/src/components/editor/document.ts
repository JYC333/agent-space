import type { Note } from '../../types/api'
import {
  RICH_TEXT_CONTENT_FORMAT,
  RICH_TEXT_SCHEMA_VERSION,
  type RichTextDocument,
  type RichTextSnapshot,
} from './types'

export function emptyRichTextDocument(): RichTextDocument {
  return {
    type: 'doc',
    content: [{ type: 'paragraph' }],
  }
}

export function plainTextToRichTextDocument(text: string | null | undefined): RichTextDocument {
  const trimmed = text?.trim()
  if (!trimmed) return emptyRichTextDocument()

  const paragraphs = trimmed.split(/\n{2,}/).map(part => part.trim()).filter(Boolean)
  return {
    type: 'doc',
    content: paragraphs.map(part => ({
      type: 'paragraph',
      content: [{ type: 'text', text: part }],
    })),
  }
}

export function isRichTextDocument(value: unknown): value is RichTextDocument {
  if (!isRecord(value) || value.type !== 'doc') return false
  const content = value.content
  return content === undefined || Array.isArray(content)
}

export function normalizeRichTextDocument(
  contentJson: unknown,
  fallbackPlainText?: string | null,
): RichTextDocument {
  if (isRichTextDocument(contentJson)) {
    const content = contentJson.content
    if (Array.isArray(content) && content.length === 0) return emptyRichTextDocument()
    return contentJson
  }
  return plainTextToRichTextDocument(fallbackPlainText)
}

export function normalizeNoteDocument(note: Pick<Note, 'content_json' | 'plain_text'>): RichTextDocument {
  return normalizeRichTextDocument(note.content_json, note.plain_text)
}

export function richTextSnapshotFromDocument(contentJson: RichTextDocument): RichTextSnapshot {
  return {
    content_json: contentJson,
    content_format: RICH_TEXT_CONTENT_FORMAT,
    content_schema_version: RICH_TEXT_SCHEMA_VERSION,
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
