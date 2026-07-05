import type { ReactNode } from 'react'
import { cn } from '../../lib/utils'

type MarkdownBlock =
  | { type: 'paragraph'; lines: string[] }
  | { type: 'heading'; level: number; text: string }
  | { type: 'unordered_list'; items: string[] }
  | { type: 'ordered_list'; items: string[] }
  | { type: 'code'; language: string | null; text: string }
  | { type: 'blockquote'; lines: string[] }
  | { type: 'table'; headers: string[]; rows: string[][] }
  | { type: 'rule' }

export function MarkdownMessage({ content, className }: { content: string; className?: string }) {
  const blocks = parseMarkdownBlocks(content)
  return (
    <div className={cn('space-y-2 break-words text-sm leading-relaxed', className)}>
      {blocks.map((block, index) => renderBlock(block, index))}
    </div>
  )
}

function parseMarkdownBlocks(content: string): MarkdownBlock[] {
  const lines = content.replace(/\r\n/g, '\n').split('\n')
  const blocks: MarkdownBlock[] = []
  let index = 0

  while (index < lines.length) {
    const line = lines[index] ?? ''
    const trimmed = line.trim()
    if (!trimmed) {
      index += 1
      continue
    }

    const fence = trimmed.match(/^```([A-Za-z0-9_-]+)?\s*$/)
    if (fence) {
      const codeLines: string[] = []
      index += 1
      while (index < lines.length && !(lines[index] ?? '').trim().startsWith('```')) {
        codeLines.push(lines[index] ?? '')
        index += 1
      }
      if (index < lines.length) index += 1
      blocks.push({ type: 'code', language: fence[1] ?? null, text: codeLines.join('\n') })
      continue
    }

    const heading = trimmed.match(/^(#{1,4})\s+(.+)$/)
    if (heading) {
      blocks.push({ type: 'heading', level: heading[1].length, text: heading[2].trim() })
      index += 1
      continue
    }

    if (/^[-*_]\s*[-*_]\s*[-*_]\s*$/.test(trimmed)) {
      blocks.push({ type: 'rule' })
      index += 1
      continue
    }

    if (isTableStart(lines, index)) {
      const headers = splitTableCells(lines[index] ?? '')
      index += 2
      const rows: string[][] = []
      while (index < lines.length && isTableRow(lines[index] ?? '')) {
        rows.push(splitTableCells(lines[index] ?? ''))
        index += 1
      }
      blocks.push({ type: 'table', headers, rows })
      continue
    }

    if (/^\s*[-*+]\s+/.test(line)) {
      const items: string[] = []
      while (index < lines.length && /^\s*[-*+]\s+/.test(lines[index] ?? '')) {
        items.push((lines[index] ?? '').replace(/^\s*[-*+]\s+/, '').trim())
        index += 1
      }
      blocks.push({ type: 'unordered_list', items })
      continue
    }

    if (/^\s*\d+[.)]\s+/.test(line)) {
      const items: string[] = []
      while (index < lines.length && /^\s*\d+[.)]\s+/.test(lines[index] ?? '')) {
        items.push((lines[index] ?? '').replace(/^\s*\d+[.)]\s+/, '').trim())
        index += 1
      }
      blocks.push({ type: 'ordered_list', items })
      continue
    }

    if (/^\s*>\s?/.test(line)) {
      const quoteLines: string[] = []
      while (index < lines.length && /^\s*>\s?/.test(lines[index] ?? '')) {
        quoteLines.push((lines[index] ?? '').replace(/^\s*>\s?/, '').trim())
        index += 1
      }
      blocks.push({ type: 'blockquote', lines: quoteLines })
      continue
    }

    const paragraphLines: string[] = []
    while (index < lines.length && !startsMarkdownBlock(lines, index)) {
      paragraphLines.push(lines[index] ?? '')
      index += 1
    }
    blocks.push({ type: 'paragraph', lines: paragraphLines })
  }

  return blocks.length > 0 ? blocks : [{ type: 'paragraph', lines: [''] }]
}

function startsMarkdownBlock(lines: string[], index: number) {
  const line = lines[index] ?? ''
  const trimmed = line.trim()
  if (!trimmed) return true
  return Boolean(
    trimmed.match(/^```/) ||
    trimmed.match(/^#{1,4}\s+/) ||
    trimmed.match(/^[-*_]\s*[-*_]\s*[-*_]\s*$/) ||
    /^\s*[-*+]\s+/.test(line) ||
    /^\s*\d+[.)]\s+/.test(line) ||
    /^\s*>\s?/.test(line) ||
    isTableStart(lines, index),
  )
}

function isTableStart(lines: string[], index: number) {
  const line = lines[index] ?? ''
  const next = lines[index + 1] ?? ''
  return isTableRow(line) && /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(next)
}

function isTableRow(line: string) {
  return line.includes('|') && line.trim().length > 0
}

function splitTableCells(line: string) {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map(cell => cell.trim())
}

function renderBlock(block: MarkdownBlock, index: number): ReactNode {
  switch (block.type) {
    case 'heading': {
      const className = headingClassName(block.level)
      if (block.level === 1) return <h1 key={index} className={className}>{renderInline(block.text, `${index}`)}</h1>
      if (block.level === 2) return <h2 key={index} className={className}>{renderInline(block.text, `${index}`)}</h2>
      if (block.level === 3) return <h3 key={index} className={className}>{renderInline(block.text, `${index}`)}</h3>
      return <h4 key={index} className={className}>{renderInline(block.text, `${index}`)}</h4>
    }
    case 'unordered_list':
      return (
        <ul key={index} className="ml-5 list-disc space-y-1">
          {block.items.map((item, itemIndex) => <li key={itemIndex}>{renderInline(item, `${index}-${itemIndex}`)}</li>)}
        </ul>
      )
    case 'ordered_list':
      return (
        <ol key={index} className="ml-5 list-decimal space-y-1">
          {block.items.map((item, itemIndex) => <li key={itemIndex}>{renderInline(item, `${index}-${itemIndex}`)}</li>)}
        </ol>
      )
    case 'code':
      return (
        <pre key={index} className="overflow-x-auto rounded-md border border-border bg-muted px-3 py-2 text-xs leading-relaxed">
          <code>{block.text}</code>
        </pre>
      )
    case 'blockquote':
      return (
        <blockquote key={index} className="border-l-2 border-border pl-3 text-muted-foreground">
          {renderLines(block.lines, `${index}`)}
        </blockquote>
      )
    case 'table':
      return (
        <div key={index} className="overflow-x-auto rounded-md border border-border">
          <table className="min-w-full border-collapse text-left text-xs">
            <thead className="bg-muted">
              <tr>
                {block.headers.map((header, cellIndex) => (
                  <th key={cellIndex} className="border-b border-border px-2 py-1.5 font-semibold">
                    {renderInline(header, `${index}-h-${cellIndex}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, rowIndex) => (
                <tr key={rowIndex} className="border-t border-border">
                  {normalizedTableRow(row, block.headers.length).map((cell, cellIndex) => (
                    <td key={cellIndex} className="px-2 py-1.5 align-top">
                      {renderInline(cell, `${index}-${rowIndex}-${cellIndex}`)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )
    case 'rule':
      return <hr key={index} className="border-border" />
    case 'paragraph':
    default:
      return <p key={index} className="whitespace-pre-wrap">{renderLines(block.lines, `${index}`)}</p>
  }
}

function headingClassName(level: number) {
  if (level === 1) return 'text-base font-semibold'
  if (level === 2) return 'text-sm font-semibold'
  return 'text-sm font-medium'
}

function renderLines(lines: string[], keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = []
  lines.forEach((line, index) => {
    if (index > 0) nodes.push(<br key={`${keyPrefix}-br-${index}`} />)
    nodes.push(...renderInline(line, `${keyPrefix}-line-${index}`))
  })
  return nodes
}

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = []
  let index = 0
  let key = 0

  while (index < text.length) {
    const codeEnd = text[index] === '`' ? text.indexOf('`', index + 1) : -1
    if (codeEnd > index + 1) {
      nodes.push(
        <code key={`${keyPrefix}-code-${key++}`} className="rounded bg-muted px-1 py-0.5 text-[0.92em]">
          {text.slice(index + 1, codeEnd)}
        </code>,
      )
      index = codeEnd + 1
      continue
    }

    if (text.startsWith('**', index)) {
      const end = text.indexOf('**', index + 2)
      if (end > index + 2) {
        nodes.push(<strong key={`${keyPrefix}-strong-${key++}`}>{renderInline(text.slice(index + 2, end), `${keyPrefix}-strong-${key}`)}</strong>)
        index = end + 2
        continue
      }
    }

    if (text[index] === '*') {
      const end = text.indexOf('*', index + 1)
      if (end > index + 1) {
        nodes.push(<em key={`${keyPrefix}-em-${key++}`}>{renderInline(text.slice(index + 1, end), `${keyPrefix}-em-${key}`)}</em>)
        index = end + 1
        continue
      }
    }

    if (text[index] === '[') {
      const labelEnd = text.indexOf('](', index)
      const urlEnd = labelEnd >= 0 ? text.indexOf(')', labelEnd + 2) : -1
      if (labelEnd > index && urlEnd > labelEnd + 2) {
        const label = text.slice(index + 1, labelEnd)
        const href = safeHref(text.slice(labelEnd + 2, urlEnd))
        if (href) {
          nodes.push(
            <a key={`${keyPrefix}-link-${key++}`} href={href} target="_blank" rel="noreferrer" className="text-primary underline underline-offset-2">
              {renderInline(label, `${keyPrefix}-link-${key}`)}
            </a>,
          )
          index = urlEnd + 1
          continue
        }
      }
    }

    const nextSpecial = nextInlineSpecialIndex(text, index + 1)
    nodes.push(text.slice(index, nextSpecial))
    index = nextSpecial
  }

  return nodes
}

function nextInlineSpecialIndex(text: string, start: number) {
  const indexes = ['`', '*', '[']
    .map(char => text.indexOf(char, start))
    .filter(item => item >= 0)
  return indexes.length > 0 ? Math.min(...indexes) : text.length
}

function safeHref(value: string) {
  const href = value.trim()
  if (/^(https?:|mailto:)/i.test(href)) return href
  return null
}

function normalizedTableRow(row: string[], expectedLength: number) {
  if (row.length >= expectedLength) return row.slice(0, expectedLength)
  return [...row, ...Array.from({ length: expectedLength - row.length }, () => '')]
}
