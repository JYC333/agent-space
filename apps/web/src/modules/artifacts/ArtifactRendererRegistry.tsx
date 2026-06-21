import type { ReactNode } from 'react'
import type { Artifact } from '../../types/api'
import { Badge } from '../../components/ui/badge'

interface ArtifactRendererProps {
  artifact: Artifact
}

type ArtifactRenderer = (props: ArtifactRendererProps) => ReactNode

const RESEARCH_TYPES = new Set([
  'research_brief.v1',
  'research_source_table.v1',
  'research_idea_candidates.v1',
])

function InlineTextArtifact({ artifact }: ArtifactRendererProps) {
  if (artifact.has_inline_content && (artifact.content ?? '') !== '') {
    return (
      <pre className="text-sm whitespace-pre-wrap bg-muted/40 rounded-md p-3 max-h-[480px] overflow-auto border border-border">
        {artifact.content}
      </pre>
    )
  }
  return <p className="text-sm text-muted-foreground">No inline preview. Use Export to download.</p>
}

function parseJsonContent(artifact: Artifact): unknown | null {
  const raw = artifact.content?.trim()
  if (!raw) return null
  if (!raw.startsWith('{') && !raw.startsWith('[')) return null
  try {
    return JSON.parse(raw)
  } catch {
    return null
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}

function stringValue(value: unknown): string | null {
  if (typeof value === 'string' && value.trim().length > 0) return value
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  return null
}

function firstString(record: Record<string, unknown>, keys: string[]): string | null {
  for (const key of keys) {
    const value = stringValue(record[key])
    if (value) return value
  }
  return null
}

function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function pickArray(record: Record<string, unknown>, keys: string[]): unknown[] {
  for (const key of keys) {
    const value = arrayValue(record[key])
    if (value.length > 0) return value
  }
  return []
}

function textFromItem(item: unknown, keys: string[]): string | null {
  if (typeof item === 'string') return item
  if (!isRecord(item)) return null
  return firstString(item, keys)
}

function sourceHref(value: unknown): string | null {
  const text = stringValue(value)
  if (!text) return null
  if (text.startsWith('http://') || text.startsWith('https://')) return text
  return null
}

function ResearchBriefRenderer({ artifact }: ArtifactRendererProps) {
  const parsed = parseJsonContent(artifact)
  if (!isRecord(parsed)) return <InlineTextArtifact artifact={artifact} />

  const title = firstString(parsed, ['title', 'question', 'query'])
  const summary = firstString(parsed, ['summary', 'abstract', 'answer', 'brief'])
  const findings = pickArray(parsed, ['findings', 'key_findings', 'claims', 'takeaways'])
  const limitations = pickArray(parsed, ['limitations', 'caveats', 'open_questions'])
  const citations = pickArray(parsed, ['citations', 'sources', 'references'])

  return (
    <div className="space-y-4">
      {title && <h2 className="text-base font-semibold tracking-tight">{title}</h2>}
      {summary && (
        <div className="rounded-md border border-border bg-muted/30 p-3">
          <div className="text-[11px] font-medium uppercase text-muted-foreground mb-1">Summary</div>
          <p className="text-sm whitespace-pre-wrap">{summary}</p>
        </div>
      )}
      {findings.length > 0 && (
        <div className="space-y-2">
          <div className="text-[11px] font-medium uppercase text-muted-foreground">Findings</div>
          <div className="space-y-2">
            {findings.map((finding, index) => {
              const text = textFromItem(finding, ['finding', 'claim', 'summary', 'text', 'content'])
              if (!text) return null
              const confidence = isRecord(finding) ? firstString(finding, ['confidence', 'certainty']) : null
              return (
                <div key={`${text}-${index}`} className="rounded-md border border-border p-3">
                  <div className="flex gap-2 items-start">
                    <span className="text-xs text-muted-foreground font-mono pt-0.5">{index + 1}</span>
                    <p className="text-sm whitespace-pre-wrap flex-1">{text}</p>
                    {confidence && <Badge variant="outline">{confidence}</Badge>}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}
      {limitations.length > 0 && (
        <div className="space-y-1.5">
          <div className="text-[11px] font-medium uppercase text-muted-foreground">Limitations</div>
          <ul className="list-disc pl-5 text-sm space-y-1">
            {limitations.map((item, index) => {
              const text = textFromItem(item, ['limitation', 'caveat', 'question', 'text'])
              return text ? <li key={`${text}-${index}`}>{text}</li> : null
            })}
          </ul>
        </div>
      )}
      {citations.length > 0 && <CitationList citations={citations} />}
    </div>
  )
}

function SourceTableRenderer({ artifact }: ArtifactRendererProps) {
  const parsed = parseJsonContent(artifact)
  const rows = Array.isArray(parsed)
    ? parsed
    : isRecord(parsed)
      ? pickArray(parsed, ['sources', 'rows', 'items', 'source_table'])
      : []
  if (rows.length === 0) return <InlineTextArtifact artifact={artifact} />

  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <table className="w-full text-sm">
        <thead className="bg-muted/50">
          <tr className="text-left text-xs text-muted-foreground">
            <th className="p-2 font-medium">Source</th>
            <th className="p-2 font-medium">Publisher</th>
            <th className="p-2 font-medium">Date</th>
            <th className="p-2 font-medium">Use</th>
            <th className="p-2 font-medium">Notes</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => {
            const record = isRecord(row) ? row : {}
            const title = firstString(record, ['title', 'name', 'source', 'url']) ?? `Source ${index + 1}`
            const url = sourceHref(record.url ?? record.href)
            const publisher = firstString(record, ['publisher', 'site', 'author', 'organization'])
            const date = firstString(record, ['date', 'published_at', 'accessed_at'])
            const use = firstString(record, ['relevance', 'use', 'credibility', 'confidence'])
            const notes = firstString(record, ['summary', 'notes', 'evidence', 'claim'])
            return (
              <tr key={`${title}-${index}`} className="border-t border-border align-top">
                <td className="p-2 min-w-[220px]">
                  {url ? (
                    <a className="text-accent-foreground hover:underline break-words" href={url} target="_blank" rel="noreferrer">
                      {title}
                    </a>
                  ) : (
                    <span>{title}</span>
                  )}
                </td>
                <td className="p-2 text-muted-foreground">{publisher ?? '—'}</td>
                <td className="p-2 text-muted-foreground">{date ?? '—'}</td>
                <td className="p-2">{use ? <Badge variant="outline">{use}</Badge> : <span className="text-muted-foreground">—</span>}</td>
                <td className="p-2 max-w-[360px] whitespace-pre-wrap">{notes ?? <span className="text-muted-foreground">—</span>}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function IdeaCandidatesRenderer({ artifact }: ArtifactRendererProps) {
  const parsed = parseJsonContent(artifact)
  const ideas = Array.isArray(parsed)
    ? parsed
    : isRecord(parsed)
      ? pickArray(parsed, ['ideas', 'candidates', 'items'])
      : []
  if (ideas.length === 0) return <InlineTextArtifact artifact={artifact} />

  return (
    <div className="space-y-2">
      {ideas.map((idea, index) => {
        const record = isRecord(idea) ? idea : {}
        const title = firstString(record, ['title', 'name', 'idea']) ?? textFromItem(idea, ['text']) ?? `Candidate ${index + 1}`
        const rationale = firstString(record, ['rationale', 'reason', 'summary', 'description'])
        const evidence = firstString(record, ['evidence', 'supporting_evidence', 'source'])
        const confidence = firstString(record, ['confidence', 'score', 'priority'])
        const nextStep = firstString(record, ['next_step', 'next_steps', 'follow_up'])
        return (
          <div key={`${title}-${index}`} className="rounded-md border border-border p-3 space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium text-sm">{title}</span>
              {confidence && <Badge variant="outline">{confidence}</Badge>}
            </div>
            {rationale && <p className="text-sm text-muted-foreground whitespace-pre-wrap">{rationale}</p>}
            <div className="grid gap-2 md:grid-cols-2">
              {evidence && (
                <div>
                  <div className="text-[11px] font-medium uppercase text-muted-foreground">Evidence</div>
                  <p className="text-xs whitespace-pre-wrap">{evidence}</p>
                </div>
              )}
              {nextStep && (
                <div>
                  <div className="text-[11px] font-medium uppercase text-muted-foreground">Next step</div>
                  <p className="text-xs whitespace-pre-wrap">{nextStep}</p>
                </div>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function CitationList({ citations }: { citations: unknown[] }) {
  return (
    <div className="space-y-1.5">
      <div className="text-[11px] font-medium uppercase text-muted-foreground">Sources</div>
      <div className="space-y-1.5">
        {citations.map((citation, index) => {
          const record = isRecord(citation) ? citation : {}
          const label = firstString(record, ['title', 'name', 'source', 'url']) ?? textFromItem(citation, ['text']) ?? `Source ${index + 1}`
          const url = sourceHref(record.url ?? record.href)
          return (
            <div key={`${label}-${index}`} className="text-sm rounded-md border border-border px-3 py-2">
              {url ? (
                <a href={url} target="_blank" rel="noreferrer" className="text-accent-foreground hover:underline">
                  {label}
                </a>
              ) : (
                <span>{label}</span>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

const REGISTRY: Record<string, ArtifactRenderer> = {
  'research_brief.v1': ResearchBriefRenderer,
  'research_source_table.v1': SourceTableRenderer,
  'research_idea_candidates.v1': IdeaCandidatesRenderer,
}

export function ArtifactInlineRenderer({ artifact }: ArtifactRendererProps) {
  const Renderer = RESEARCH_TYPES.has(artifact.artifact_type)
    ? REGISTRY[artifact.artifact_type]
    : undefined
  return <>{(Renderer ?? InlineTextArtifact)({ artifact })}</>
}
