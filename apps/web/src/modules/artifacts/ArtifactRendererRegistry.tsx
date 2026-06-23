import type { ReactNode } from 'react'
import { SpaceLink as Link } from '../../core/spaceNav'
import type { Artifact } from '../../types/api'
import { Badge } from '../../components/ui/badge'

interface ArtifactRendererProps {
  artifact: Artifact
}

type ArtifactRenderer = (props: ArtifactRendererProps) => ReactNode

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

function numberValue(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
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

function EvalReportRenderer({ artifact }: ArtifactRendererProps) {
  const parsed = parseJsonContent(artifact)
  if (!isRecord(parsed)) return <InlineTextArtifact artifact={artifact} />

  const suite = firstString(parsed, ['report_label', 'suite', 'source'])
  const metrics = isRecord(parsed.metrics) ? parsed.metrics : {}
  const counts = isRecord(parsed.counts) ? parsed.counts : {}
  const primaryMetrics = omitPrefix(metrics, 'trend.')
  const trendMetrics = pickPrefix(metrics, 'trend.')
  const primaryCounts = omitPrefix(counts, 'trend.')
  const trendCounts = pickPrefix(counts, 'trend.')
  const diagnostics = arrayValue(parsed.diagnostic_codes)
  const cases = arrayValue(parsed.cases)
  const attribution = isRecord(parsed.rank_attribution) ? parsed.rank_attribution : {}

  return (
    <div className="space-y-4">
      {suite && <h2 className="text-base font-semibold tracking-tight">{suite}</h2>}
      <KeyValueGrid title="Metrics" values={primaryMetrics} />
      <KeyValueGrid title="Trend deltas" values={trendMetrics} />
      <KeyValueGrid title="Counts" values={primaryCounts} />
      <KeyValueGrid title="Trend sample" values={trendCounts} />
      {diagnostics.length > 0 && (
        <div className="space-y-1.5">
          <div className="text-[11px] font-medium uppercase text-muted-foreground">Diagnostics</div>
          <div className="flex flex-wrap gap-1.5">
            {diagnostics.map((code, index) => {
              const label = stringValue(code)
              return label ? <Badge key={`${label}-${index}`} variant="outline">{label}</Badge> : null
            })}
          </div>
        </div>
      )}
      {cases.length > 0 && (
        <div className="overflow-x-auto rounded-md border border-border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50">
              <tr className="text-left text-xs text-muted-foreground">
                <th className="p-2 font-medium">Case</th>
                <th className="p-2 font-medium">Mode</th>
                <th className="p-2 font-medium">Recall</th>
                <th className="p-2 font-medium">First hit</th>
                <th className="p-2 font-medium">Diagnostics</th>
              </tr>
            </thead>
            <tbody>
              {cases.map((item, index) => {
                const record = isRecord(item) ? item : {}
                const label = firstString(record, ['case_label']) ?? `Case ${index + 1}`
                const metricsRecord = isRecord(record.metrics) ? record.metrics : {}
                const recall = stringValue(metricsRecord.recall)
                const mode = firstString(record, ['mode'])
                const firstRank = stringValue(record.first_relevant_rank)
                const codes = arrayValue(record.diagnostic_codes).map(stringValue).filter(Boolean)
                return (
                  <tr key={`${label}-${index}`} className="border-t border-border align-top">
                    <td className="p-2 font-medium">{label}</td>
                    <td className="p-2 text-muted-foreground">{mode ?? '—'}</td>
                    <td className="p-2">{recall ?? '—'}</td>
                    <td className="p-2">{firstRank ?? '—'}</td>
                    <td className="p-2 text-muted-foreground">{codes.length ? codes.join(', ') : '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      <KeyValueGrid title="Evidence kinds" values={isRecord(attribution.evidence_kind_counts) ? attribution.evidence_kind_counts : {}} />
      <KeyValueGrid title="Matched fields" values={isRecord(attribution.matched_field_counts) ? attribution.matched_field_counts : {}} />
    </div>
  )
}

function CalibrationDecisionRenderer({ artifact }: ArtifactRendererProps) {
  const parsed = parseJsonContent(artifact)
  if (!isRecord(parsed)) return <InlineTextArtifact artifact={artifact} />

  const decisions = pickArray(parsed, ['decisions'])
  const evidence = pickArray(parsed, ['evidence_artifacts'])
  const summary = isRecord(parsed.decision_summary) ? parsed.decision_summary : {}
  const safety = isRecord(parsed.access_safety) ? parsed.access_safety : {}
  const label = firstString(parsed, ['report_label', 'suite'])
  const reviewScope = firstString(parsed, ['review_scope'])
  const visibility = firstString(parsed, ['visibility'])

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge variant="secondary">retrieval calibration</Badge>
        {label && <Badge variant="outline">{label}</Badge>}
        {reviewScope && <Badge variant="muted">{reviewScope}</Badge>}
        {visibility && <Badge variant="muted">{visibility}</Badge>}
      </div>
      <KeyValueGrid title="Decision summary" values={summary} />
      {decisions.length === 0 ? (
        <p className="text-sm text-muted-foreground">No calibration decisions.</p>
      ) : (
        <div className="space-y-2">
          <div className="text-[11px] font-medium uppercase text-muted-foreground">Decisions</div>
          {decisions.map((decision, index) => {
            const record = isRecord(decision) ? decision : {}
            const mechanic = firstString(record, ['mechanic']) ?? `mechanic_${index + 1}`
            const outcome = firstString(record, ['decision'])
            const proof = firstString(record, ['access_safety_proof'])
            const rationale = firstString(record, ['rationale'])
            const guardrails = arrayValue(record.guardrails).map(stringValue).filter(Boolean)
            const evalDelta = isRecord(record.eval_delta) ? record.eval_delta : {}
            return (
              <div key={`${mechanic}-${index}`} className="rounded-md border border-border p-3 space-y-3">
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge variant="secondary">{mechanic}</Badge>
                  {outcome && <Badge variant={calibrationDecisionVariant(outcome)}>{outcome}</Badge>}
                </div>
                {proof && (
                  <div>
                    <div className="text-[11px] font-medium uppercase text-muted-foreground">Access-safety proof</div>
                    <p className="mt-1 text-sm whitespace-pre-wrap">{proof}</p>
                  </div>
                )}
                {rationale && (
                  <div>
                    <div className="text-[11px] font-medium uppercase text-muted-foreground">Rationale</div>
                    <p className="mt-1 text-sm text-muted-foreground whitespace-pre-wrap">{rationale}</p>
                  </div>
                )}
                <KeyValueGrid title="Eval delta" values={evalDelta} />
                {guardrails.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {guardrails.map((guardrail, guardrailIndex) => (
                      <Badge key={`${guardrail}-${guardrailIndex}`} variant="outline">{guardrail}</Badge>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
      {evidence.length > 0 && (
        <div className="space-y-1.5">
          <div className="text-[11px] font-medium uppercase text-muted-foreground">Evidence artifacts</div>
          <div className="space-y-1.5">
            {evidence.map((item, index) => {
              const record = isRecord(item) ? item : {}
              const id = firstString(record, ['artifact_id'])
              const type = firstString(record, ['artifact_type'])
              const itemVisibility = firstString(record, ['visibility'])
              return (
                <div key={`${id ?? index}`} className="flex flex-wrap items-center gap-1.5 rounded-md border border-border px-3 py-2 text-sm">
                  {type && <Badge variant="muted">{type}</Badge>}
                  {itemVisibility && <Badge variant="outline">{itemVisibility}</Badge>}
                  {id ? (
                    <Link to={`/artifacts/${id}`} className="font-mono text-xs text-accent-foreground hover:underline">
                      {id}
                    </Link>
                  ) : (
                    <span className="text-muted-foreground">missing artifact id</span>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}
      <KeyValueGrid title="Access safety" values={safety} />
    </div>
  )
}

function RetrievalExplainRenderer({ artifact }: ArtifactRendererProps) {
  const parsed = parseJsonContent(artifact)
  if (!isRecord(parsed)) return <InlineTextArtifact artifact={artifact} />

  const target = isRecord(parsed.target) ? parsed.target : {}
  const match = isRecord(parsed.match) ? parsed.match : {}
  const trace = isRecord(parsed.trace) ? parsed.trace : {}
  const safety = isRecord(parsed.access_safety) ? parsed.access_safety : {}
  const diagnostics = arrayValue(parsed.diagnostic_codes)
  const objectType = firstString(target, ['object_type'])
  const objectId = firstString(target, ['object_id'])
  const title = firstString(target, ['title']) ?? 'Retrieval target'
  const returned = target.returned === true
  const matchedFields = arrayValue(match.matched_fields).map(stringValue).filter(Boolean).join(', ')

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-1.5">
        {objectType && <Badge variant="secondary">{objectType}</Badge>}
        <Badge variant={returned ? 'success' : 'warning'}>{returned ? 'returned' : 'missed'}</Badge>
        {stringValue(target.score_bucket) && <Badge variant="outline">{stringValue(target.score_bucket)}</Badge>}
        {stringValue(parsed.mode) && <Badge variant="muted">{stringValue(parsed.mode)}</Badge>}
      </div>
      <div className="rounded-md border border-border p-3">
        <div className="text-[11px] font-medium uppercase text-muted-foreground mb-1">Target</div>
        {objectType && objectId ? (
          <Link to={objectPath(objectType, objectId)} className="text-sm font-medium text-accent-foreground hover:underline">
            {title}
          </Link>
        ) : (
          <p className="text-sm font-medium">{title}</p>
        )}
        <div className="mt-1 flex flex-wrap gap-2 text-xs text-muted-foreground">
          {objectId && <span className="font-mono">{objectId}</span>}
          {stringValue(target.rank) && <span>rank {stringValue(target.rank)}</span>}
          {stringValue(target.score) && <span>score {stringValue(target.score)}</span>}
        </div>
      </div>
      <KeyValueGrid
        title="Match"
        values={compactRecord({
          matched_fields: matchedFields,
          evidence_kind: match.evidence_kind,
          evidence_field: match.evidence_field,
          evidence_source: match.evidence_source,
          evidence_confidence: match.evidence_confidence,
          create_safety: match.create_safety,
        })}
      />
      <KeyValueGrid title="Trace arms" values={isRecord(trace.arms) ? trace.arms : {}} />
      <KeyValueGrid title="Dropped reasons" values={isRecord(trace.dropped_reasons) ? trace.dropped_reasons : {}} />
      <KeyValueGrid
        title="Trace summary"
        values={compactRecord({
          dropped: trace.dropped,
          mode: trace.mode,
          intent: trace.intent,
        })}
      />
      {diagnostics.length > 0 && (
        <div className="space-y-1.5">
          <div className="text-[11px] font-medium uppercase text-muted-foreground">Diagnostics</div>
          <div className="flex flex-wrap gap-1.5">
            {diagnostics.map((code, index) => {
              const label = stringValue(code)
              return label ? <Badge key={`${label}-${index}`} variant="outline">{label}</Badge> : null
            })}
          </div>
        </div>
      )}
      <KeyValueGrid title="Access safety" values={safety} />
    </div>
  )
}

function RetrievalBriefRenderer({ artifact }: ArtifactRendererProps) {
  const parsed = parseJsonContent(artifact)
  if (!isRecord(parsed)) return <InlineTextArtifact artifact={artifact} />

  const query = firstString(parsed, ['query'])
  const answer = firstString(parsed, ['answer'])
  const surface = firstString(parsed, ['surface'])
  const sourceCount = stringValue(parsed.source_count)
  const itemRefs = pickArray(parsed, ['item_refs', 'items'])
  const citations = pickArray(parsed, ['citations'])
  const gap = isRecord(parsed.gap_analysis) ? parsed.gap_analysis : {}

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-1.5">
        {surface && <Badge variant="outline">{surface}</Badge>}
        <Badge variant={parsed.synthesized === true ? 'success' : 'muted'}>
          {parsed.synthesized === true ? 'synthesized' : 'deterministic'}
        </Badge>
        {sourceCount && <Badge variant="secondary">{sourceCount} sources</Badge>}
      </div>
      {query && (
        <div className="rounded-md border border-border bg-muted/30 p-3">
          <div className="text-[11px] font-medium uppercase text-muted-foreground mb-1">Query</div>
          <p className="text-sm whitespace-pre-wrap">{query}</p>
        </div>
      )}
      <div className="rounded-md border border-border p-3">
        <div className="text-[11px] font-medium uppercase text-muted-foreground mb-1">Answer</div>
        {answer ? (
          <p className="text-sm whitespace-pre-wrap">{answer}</p>
        ) : (
          <p className="text-sm text-muted-foreground">No synthesized answer. Sources and gap analysis were still persisted.</p>
        )}
      </div>
      {citations.length > 0 && <BriefCitationList citations={citations} />}
      <BriefGapAnalysis gap={gap} />
      {itemRefs.length > 0 && <BriefSourceRefs items={itemRefs} />}
    </div>
  )
}

function MaintenanceReportRenderer({ artifact }: ArtifactRendererProps) {
  const parsed = parseJsonContent(artifact)
  if (!isRecord(parsed)) return <InlineTextArtifact artifact={artifact} />

  const findings = pickArray(parsed, ['findings'])
  const counts = isRecord(parsed.counts) ? parsed.counts : {}
  const source = firstString(parsed, ['source'])
  const scanned = stringValue(parsed.scanned)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-1.5">
        {source && <Badge variant="outline">{source}</Badge>}
        {scanned && <Badge variant="secondary">{scanned} scanned</Badge>}
        {parsed.truncated === true && <Badge variant="warning">truncated</Badge>}
      </div>
      <KeyValueGrid title="Finding counts" values={counts} />
      {findings.length === 0 ? (
        <p className="text-sm text-muted-foreground">No maintenance findings.</p>
      ) : (
        <div className="space-y-2">
          <div className="text-[11px] font-medium uppercase text-muted-foreground">Findings</div>
          {findings.map((finding, index) => {
            const record = isRecord(finding) ? finding : {}
            const kind = firstString(record, ['kind']) ?? `finding_${index + 1}`
            const reason = firstString(record, ['reason'])
            const objects = pickArray(record, ['objects'])
            const action = isRecord(record.proposed_action) ? record.proposed_action : null
            const actionType = action ? firstString(action, ['proposal_type']) : null
            return (
              <div key={`${kind}-${index}`} className="rounded-md border border-border p-3 space-y-2">
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge variant="secondary">{kind}</Badge>
                  {actionType && <Badge variant="outline">{actionType}</Badge>}
                </div>
                {reason && <p className="text-sm whitespace-pre-wrap">{reason}</p>}
                {objects.length > 0 && (
                  <div className="space-y-1">
                    {objects.map((object, objectIndex) => {
                      const objectRecord = isRecord(object) ? object : {}
                      const title = firstString(objectRecord, ['title']) ?? `Object ${objectIndex + 1}`
                      const type = firstString(objectRecord, ['object_type'])
                      const id = firstString(objectRecord, ['object_id'])
                      return (
                        <div key={`${title}-${objectIndex}`} className="flex flex-wrap items-center gap-1.5 text-xs">
                          {type && <Badge variant="muted">{type}</Badge>}
                          <span>{title}</span>
                          {id && <span className="font-mono text-muted-foreground">{id.slice(0, 10)}…</span>}
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function ClaimCandidatePacketRenderer({ artifact }: ArtifactRendererProps) {
  const parsed = parseJsonContent(artifact)
  if (!isRecord(parsed)) return <InlineTextArtifact artifact={artifact} />

  const candidates = pickArray(parsed, ['candidates'])
  const sources = pickArray(parsed, ['source_artifacts'])
  const accessSafety = isRecord(parsed.access_safety) ? parsed.access_safety : {}
  const reviewScope = firstString(parsed, ['review_scope'])
  const visibility = firstString(parsed, ['visibility'])

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge variant="secondary">Claim Candidate Packet</Badge>
        {reviewScope && <Badge variant="outline">{reviewScope}</Badge>}
        {visibility && <Badge variant="muted">{visibility}</Badge>}
        <Badge variant="outline">{candidates.length} candidates</Badge>
        <Badge variant={accessSafety.canonical_write_performed === true ? 'warning' : 'success'}>
          canonical write: {accessSafety.canonical_write_performed === true ? 'yes' : 'no'}
        </Badge>
      </div>
      <KeyValueGrid
        title="Packet"
        values={compactRecord({
          candidate_count: parsed.candidate_count ?? candidates.length,
          source_artifact_count: sources.length,
          generated_at: parsed.generated_at,
          review_scope: reviewScope,
        })}
      />
      {sources.length > 0 && (
        <div className="space-y-1.5">
          <div className="text-[11px] font-medium uppercase text-muted-foreground">Source artifacts</div>
          <div className="space-y-1.5">
            {sources.map((source, index) => {
              const record = isRecord(source) ? source : {}
              const id = firstString(record, ['artifact_id'])
              const type = firstString(record, ['artifact_type'])
              const title = firstString(record, ['title']) ?? `Artifact ${index + 1}`
              return (
                <div key={`${id ?? title}-${index}`} className="flex flex-wrap items-center gap-1.5 rounded-md border border-border px-3 py-2 text-sm">
                  {type && <Badge variant="muted">{type}</Badge>}
                  {id ? (
                    <Link to={`/artifacts/${id}`} className="text-accent-foreground hover:underline">
                      {title}
                    </Link>
                  ) : (
                    <span>{title}</span>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}
      {candidates.length === 0 ? (
        <p className="text-sm text-muted-foreground">No claim candidates.</p>
      ) : (
        <div className="space-y-2">
          <div className="text-[11px] font-medium uppercase text-muted-foreground">Candidates</div>
          {candidates.map((candidate, index) => {
            const record = isRecord(candidate) ? candidate : {}
            const title = firstString(record, ['title']) ?? `Candidate ${index + 1}`
            const kind = firstString(record, ['kind'])
            const reason = firstString(record, ['reason'])
            const action = isRecord(record.proposed_action) ? record.proposed_action : null
            const proposalType = action ? firstString(action, ['proposal_type']) : null
            const confidence = stringValue(record.confidence)
            const origin = isRecord(record.origin) ? record.origin : {}
            const section = firstString(origin, ['source_section'])
            const markers = Object.entries(isRecord(record.markers) ? record.markers : {})
              .filter(([, value]) => value === true || typeof value === 'string' || typeof value === 'number')
              .slice(0, 8)
            return (
              <div key={`${title}-${index}`} className="rounded-md border border-border p-3 space-y-2">
                <div className="flex flex-wrap items-center gap-1.5">
                  {kind && <Badge variant="secondary">{kind}</Badge>}
                  {proposalType ? <Badge variant="outline">{proposalType}</Badge> : <Badge variant="muted">review_note</Badge>}
                  {confidence && <Badge variant="outline">confidence {confidence}</Badge>}
                  {section && <Badge variant="muted">{section}</Badge>}
                </div>
                <div className="text-sm font-medium">{title}</div>
                {reason && <p className="text-sm text-muted-foreground whitespace-pre-wrap">{reason}</p>}
                {markers.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {markers.map(([key, value]) => (
                      <Badge key={key} variant="outline">{key}: {value === true ? 'yes' : String(value)}</Badge>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function ClaimContradictionReportRenderer({ artifact }: ArtifactRendererProps) {
  const parsed = parseJsonContent(artifact)
  if (!isRecord(parsed)) return <InlineTextArtifact artifact={artifact} />

  const findings = pickArray(parsed, ['findings'])
  const counts = isRecord(parsed.counts) ? parsed.counts : {}
  const scanned = stringValue(parsed.scanned ?? parsed.candidates_examined)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge variant="secondary">Claim Contradiction Report</Badge>
        {scanned && <Badge variant="outline">{scanned} claims examined</Badge>}
        {parsed.truncated === true && <Badge variant="warning">truncated</Badge>}
      </div>
      <KeyValueGrid title="Finding counts" values={counts} />
      {findings.length === 0 ? (
        <p className="text-sm text-muted-foreground">No contradiction findings.</p>
      ) : (
        <div className="space-y-2">
          <div className="text-[11px] font-medium uppercase text-muted-foreground">Findings</div>
          {findings.map((finding, index) => {
            const record = isRecord(finding) ? finding : {}
            const signal = firstString(record, ['signal']) ?? `finding_${index + 1}`
            const tier = firstString(record, ['confidence_tier'])
            const reason = firstString(record, ['reason'])
            const from = isRecord(record.from_claim) ? record.from_claim : {}
            const to = isRecord(record.to_claim) ? record.to_claim : {}
            const action = isRecord(record.proposed_action) ? record.proposed_action : null
            return (
              <div key={`${signal}-${index}`} className="rounded-md border border-border p-3 space-y-2">
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge variant="secondary">{signal}</Badge>
                  {tier && <Badge variant={tier === 'high' ? 'warning' : 'outline'}>{tier}</Badge>}
                  {action && <Badge variant="outline">claim_relation_create · contradicts</Badge>}
                </div>
                <div className="flex flex-wrap items-center gap-1.5 text-sm">
                  <span className="font-medium">{firstString(from, ['title']) ?? 'claim'}</span>
                  <span className="text-muted-foreground">⇄</span>
                  <span className="font-medium">{firstString(to, ['title']) ?? 'claim'}</span>
                </div>
                {reason && <p className="text-sm text-muted-foreground whitespace-pre-wrap">{reason}</p>}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function RelationDiscoveryReportRenderer({ artifact }: ArtifactRendererProps) {
  const parsed = parseJsonContent(artifact)
  if (!isRecord(parsed)) return <InlineTextArtifact artifact={artifact} />

  const candidates = pickArray(parsed, ['candidates'])
  const counts = isRecord(parsed.counts) ? parsed.counts : {}
  const sourcesScanned = stringValue(parsed.sources_scanned)
  const linksExtracted = stringValue(parsed.links_extracted)
  const proposalReady = numberValue(parsed.proposal_candidate_count)
    ?? numberValue(counts.proposal_candidate)
    ?? candidates.filter((candidate) => isRecord(candidate) && isRecord(candidate.proposed_action)).length
  const reviewOnly = numberValue(parsed.review_only_candidate_count)
    ?? numberValue(counts.review_only_candidate)
    ?? candidates.filter((candidate) => !isRecord(candidate) || !isRecord(candidate.proposed_action)).length

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge variant="secondary">Relation Discovery Report</Badge>
        {sourcesScanned && <Badge variant="outline">{sourcesScanned} sources</Badge>}
        {linksExtracted && <Badge variant="outline">{linksExtracted} links</Badge>}
        <Badge variant="success">{proposalReady} proposal-ready</Badge>
        {reviewOnly > 0 && <Badge variant="muted">{reviewOnly} review-only</Badge>}
        {parsed.truncated === true && <Badge variant="warning">truncated</Badge>}
      </div>
      <KeyValueGrid title="Candidate counts" values={counts} />
      {candidates.length === 0 ? (
        <p className="text-sm text-muted-foreground">No discovery candidates.</p>
      ) : (
        <div className="space-y-2">
          <div className="text-[11px] font-medium uppercase text-muted-foreground">Candidates</div>
          {candidates.map((candidate, index) => {
            const record = isRecord(candidate) ? candidate : {}
            const title = firstString(record, ['title']) ?? `Candidate ${index + 1}`
            const kind = firstString(record, ['kind'])
            const tier = firstString(record, ['confidence_tier'])
            const reason = firstString(record, ['reason'])
            const action = isRecord(record.proposed_action) ? record.proposed_action : null
            const proposalType = action ? firstString(action, ['proposal_type']) : null
            const reviewOnlyCandidate = !proposalType
            return (
              <div key={`${title}-${index}`} className="rounded-md border border-border p-3 space-y-2">
                <div className="flex flex-wrap items-center gap-1.5">
                  {kind && <Badge variant="secondary">{kind}</Badge>}
                  {proposalType ? <Badge variant="outline">{proposalType}</Badge> : <Badge variant="muted">review-only</Badge>}
                  {tier && <Badge variant={tier === 'high' ? 'warning' : 'muted'}>{tier}</Badge>}
                </div>
                <div className="text-sm font-medium">{title}</div>
                {reason && <p className="text-sm text-muted-foreground whitespace-pre-wrap">{reason}</p>}
                {reviewOnlyCandidate && (
                  <p className="text-xs text-muted-foreground">
                    Review-only evidence; accepting the packet will not generate a child proposal for this candidate.
                  </p>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function BriefCitationList({ citations }: { citations: unknown[] }) {
  return (
    <div className="space-y-1.5">
      <div className="text-[11px] font-medium uppercase text-muted-foreground">Citations</div>
      <div className="space-y-1.5">
        {citations.map((citation, index) => {
          const record = isRecord(citation) ? citation : {}
          const sourceIndex = stringValue(record.source_index)
          const title = firstString(record, ['title']) ?? `Citation ${index + 1}`
          const objectType = firstString(record, ['object_type'])
          const objectId = firstString(record, ['object_id'])
          const quote = firstString(record, ['quote'])
          return (
            <div key={`${title}-${index}`} className="rounded-md border border-border px-3 py-2 text-sm">
              <div className="flex flex-wrap items-center gap-1.5">
                {sourceIndex && <Badge variant="outline">[{sourceIndex}]</Badge>}
                {objectType && <Badge variant="muted">{objectType}</Badge>}
                {objectId && (
                  <Link to={objectPath(objectType, objectId)} className="text-accent-foreground hover:underline">
                    {title}
                  </Link>
                )}
                {!objectId && <span>{title}</span>}
              </div>
              {quote && <p className="mt-1 text-xs text-muted-foreground whitespace-pre-wrap">{quote}</p>}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function BriefGapAnalysis({ gap }: { gap: Record<string, unknown> }) {
  const stale = pickArray(gap, ['stale'])
  const thin = pickArray(gap, ['thin'])
  const uncited = pickArray(gap, ['uncited_claims'])
  const contradictions = pickArray(gap, ['contradictions'])
  const missing = pickArray(gap, ['missing_topics'])
  const hasAny = gap.low_coverage === true || stale.length || thin.length || uncited.length || contradictions.length || missing.length
  if (!hasAny) return null
  return (
    <div className="space-y-2">
      <div className="text-[11px] font-medium uppercase text-muted-foreground">Gap analysis</div>
      <div className="grid gap-2 md:grid-cols-2">
        {gap.low_coverage === true && <GapCard title="Low coverage" items={['The brief had fewer sources than expected.']} />}
        <GapCard title="Stale refs" items={stale} />
        <GapCard title="Thin refs" items={thin} />
        <GapCard title="Uncited claims" items={uncited} />
        <GapCard title="Contradictions" items={contradictions} />
        <GapCard title="Missing topics" items={missing} />
      </div>
    </div>
  )
}

function GapCard({ title, items }: { title: string; items: unknown[] }) {
  if (items.length === 0) return null
  return (
    <div className="rounded-md border border-border p-3">
      <div className="text-xs font-medium mb-1">{title}</div>
      <ul className="space-y-1 text-xs text-muted-foreground">
        {items.slice(0, 8).map((item, index) => {
          const text = textFromItem(item, ['title', 'reason', 'text', 'claim', 'topic']) ?? JSON.stringify(item)
          return <li key={`${text}-${index}`} className="whitespace-pre-wrap">{text}</li>
        })}
      </ul>
    </div>
  )
}

function BriefSourceRefs({ items }: { items: unknown[] }) {
  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <table className="w-full text-sm">
        <thead className="bg-muted/50">
          <tr className="text-left text-xs text-muted-foreground">
            <th className="p-2 font-medium">Source</th>
            <th className="p-2 font-medium">Type</th>
            <th className="p-2 font-medium">Score</th>
            <th className="p-2 font-medium">Matched fields</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, index) => {
            const record = isRecord(item) ? item : {}
            const title = firstString(record, ['title']) ?? `Source ${index + 1}`
            const objectType = firstString(record, ['object_type'])
            const objectId = firstString(record, ['object_id'])
            const fields = arrayValue(record.matched_fields).map(stringValue).filter(Boolean).join(', ')
            return (
              <tr key={`${title}-${index}`} className="border-t border-border align-top">
                <td className="p-2">
                  {objectType && objectId ? (
                    <Link to={objectPath(objectType, objectId)} className="text-accent-foreground hover:underline">
                      {title}
                    </Link>
                  ) : title}
                </td>
                <td className="p-2 text-muted-foreground">{objectType ?? '—'}</td>
                <td className="p-2">{stringValue(record.score) ?? '—'}</td>
                <td className="p-2 text-muted-foreground">{fields || '—'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function objectPath(objectType: string | null | undefined, objectId: string): string {
  if (objectType === 'knowledge_item') return `/knowledge/wiki/${objectId}`
  if (objectType === 'note') return `/knowledge/notes/${objectId}`
  if (objectType === 'source') return '/knowledge/sources'
  if (objectType === 'claim') return '/knowledge/wiki'
  if (objectType === 'memory_entry') return `/memory/${objectId}`
  if (objectType === 'project_public_summary') return '/projects'
  return '/artifacts'
}

function pickPrefix(values: Record<string, unknown>, prefix: string): Record<string, unknown> {
  return Object.fromEntries(Object.entries(values).filter(([key]) => key.startsWith(prefix)))
}

function omitPrefix(values: Record<string, unknown>, prefix: string): Record<string, unknown> {
  return Object.fromEntries(Object.entries(values).filter(([key]) => !key.startsWith(prefix)))
}

function compactRecord(values: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(values).filter(([, value]) => value !== undefined && value !== null && value !== ''),
  )
}

function calibrationDecisionVariant(decision: string): 'success' | 'warning' | 'destructive' | 'muted' {
  if (decision === 'adopt') return 'success'
  if (decision === 'defer') return 'warning'
  if (decision === 'reject') return 'destructive'
  return 'muted'
}

function KeyValueGrid({ title, values }: { title: string; values: Record<string, unknown> }) {
  const entries = Object.entries(values)
  if (entries.length === 0) return null
  return (
    <div className="space-y-1.5">
      <div className="text-[11px] font-medium uppercase text-muted-foreground">{title}</div>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {entries.map(([key, value]) => (
          <div key={key} className="rounded-md border border-border px-3 py-2">
            <div className="text-xs text-muted-foreground">{key}</div>
            <div className="text-sm font-medium">{stringValue(value) ?? '—'}</div>
          </div>
        ))}
      </div>
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

function ObjectSchemaSuggestionReportRenderer({ artifact }: ArtifactRendererProps) {
  const parsed = parseJsonContent(artifact)
  if (!isRecord(parsed)) return <InlineTextArtifact artifact={artifact} />
  const findings = pickArray(parsed, ['findings'])
  const counts = isRecord(parsed.counts) ? parsed.counts : {}
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <Badge variant="outline">findings: {findings.length}</Badge>
        <Badge variant="outline">missing: {numberValue(counts.missing_object_kind) ?? 0}</Badge>
        <Badge variant="outline">deprecated usage: {numberValue(counts.deprecated_kind_usage) ?? 0}</Badge>
        <Badge variant="outline">unused active: {numberValue(counts.unused_active_kind) ?? 0}</Badge>
      </div>
      <div className="space-y-2">
        {findings.map((item, index) => {
          const finding = isRecord(item) ? item : {}
          const title = firstString(finding, ['title']) ?? `Finding ${index + 1}`
          const reason = firstString(finding, ['reason'])
          const kind = firstString(finding, ['kind'])
          const base = firstString(finding, ['base_object_type'])
          const objectKind = firstString(finding, ['object_kind'])
          const usage = numberValue(finding.visible_usage_count)
          return (
            <div key={index} className="rounded-md border border-border p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium">{title}</span>
                {kind && <Badge variant="secondary">{kind}</Badge>}
                {base && <Badge variant="outline">{base}</Badge>}
                {objectKind && <Badge variant="outline">{objectKind}</Badge>}
                {usage !== null && <Badge variant="outline">visible usage: {usage}</Badge>}
              </div>
              {reason && <p className="mt-1 text-sm text-muted-foreground">{reason}</p>}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function BrainThinkSessionRenderer({ artifact }: ArtifactRendererProps) {
  const parsed = parseJsonContent(artifact)
  if (!isRecord(parsed)) return <InlineTextArtifact artifact={artifact} />

  const query = firstString(parsed, ['query'])
  const domains = pickArray(parsed, ['requested_domains'])
  const briefRefs = pickArray(parsed, ['brief_artifact_refs'])
  const provenance = pickArray(parsed, ['provenance'])
  const combinedAnswer = firstString(parsed, ['combined_answer'])
  const gap = isRecord(parsed.gap_summary) ? parsed.gap_summary : {}
  const gapEntries = Object.entries(gap).filter(([, value]) => typeof value === 'number' && value > 0)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-1.5">
        <Badge variant={parsed.synthesized === true ? 'success' : 'muted'}>
          {parsed.synthesized === true ? 'synthesized' : 'deterministic'}
        </Badge>
        {domains.map((domain, i) => (
          <Badge key={i} variant="outline">{String(domain)}</Badge>
        ))}
      </div>
      {query && (
        <div className="rounded-md border border-border bg-muted/30 p-3">
          <div className="mb-1 text-[11px] font-medium uppercase text-muted-foreground">Question</div>
          <p className="whitespace-pre-wrap text-sm">{query}</p>
        </div>
      )}
      {combinedAnswer && (
        <div className="rounded-md border border-border p-3">
          <div className="mb-1 text-[11px] font-medium uppercase text-muted-foreground">Combined answer</div>
          <p className="whitespace-pre-wrap text-sm">{combinedAnswer}</p>
        </div>
      )}
      {gapEntries.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {gapEntries.map(([key, value]) => (
            <Badge key={key} variant="secondary">{key}: {String(value)}</Badge>
          ))}
        </div>
      )}
      {briefRefs.length > 0 && (
        <div className="rounded-md border border-border p-3">
          <div className="mb-2 text-[11px] font-medium uppercase text-muted-foreground">Domain briefs</div>
          <div className="space-y-1">
            {briefRefs.map((ref, i) => {
              const record = isRecord(ref) ? ref : {}
              const id = stringValue(record.artifact_id)
              const domain = stringValue(record.domain)
              if (!id) return null
              return (
                <Link key={i} to={`/artifacts/${id}`} className="block text-sm hover:text-foreground">
                  {domain ?? 'brief'} brief →
                </Link>
              )
            })}
          </div>
        </div>
      )}
      {provenance.length > 0 && (
        <div>
          <div className="mb-1 text-[11px] font-medium uppercase text-muted-foreground">Provenance ({provenance.length})</div>
          <div className="flex flex-wrap gap-1.5">
            {provenance.map((item, i) => {
              const record = isRecord(item) ? item : {}
              const title = stringValue(record.title)
              return title ? <Badge key={i} variant="outline" className="max-w-[18rem] truncate">{title}</Badge> : null
            })}
          </div>
        </div>
      )}
    </div>
  )
}

const REGISTRY: Record<string, ArtifactRenderer> = {
  'research_brief.v1': ResearchBriefRenderer,
  'brain_think_session': BrainThinkSessionRenderer,
  'research_source_table.v1': SourceTableRenderer,
  'research_idea_candidates.v1': IdeaCandidatesRenderer,
  'retrieval_brief': RetrievalBriefRenderer,
  'retrieval_maintenance_report': MaintenanceReportRenderer,
  'memory_maintenance_report': MaintenanceReportRenderer,
  'claim_candidate_packet': ClaimCandidatePacketRenderer,
  'claim_contradiction_report': ClaimContradictionReportRenderer,
  'relation_discovery_report': RelationDiscoveryReportRenderer,
  'object_schema_suggestion_report': ObjectSchemaSuggestionReportRenderer,
  'retrieval_eval_report': EvalReportRenderer,
  'retrieval_calibration_decision': CalibrationDecisionRenderer,
  'retrieval_explain_report': RetrievalExplainRenderer,
}

export function ArtifactInlineRenderer({ artifact }: ArtifactRendererProps) {
  const Renderer = REGISTRY[artifact.artifact_type]
  return <>{(Renderer ?? InlineTextArtifact)({ artifact })}</>
}
