import { useRef, useState } from 'react'
import { History, Save, Undo2 } from 'lucide-react'
import { toast } from 'sonner'
import { projectResearchApi } from '../../../api/client'
import type { ResearchNotebookRevision, ResearchNotebookSection } from '../../../types/api'
import type { RichTextEditorHandle } from '../../../components/editor/types'
import { RichTextEditor } from '../../../components/editor/RichTextEditor'
import { Badge } from '../../../components/ui/badge'
import { Button } from '../../../components/ui/button'
import { Card } from '../../../components/ui/card'
import { errMsg } from '../../../lib/utils'
import { SpaceLink as Link } from '../../../core/spaceNav'
import { SECTION_LABELS } from './constants'

const SOURCE_LABELS: Record<ResearchNotebookRevision['source'], string> = {
  user_edit: 'You',
  ai_monitoring: 'AI · monitoring',
  ai_adhoc: 'AI · assistant',
  seed: 'Report seed',
  rollback: 'Rollback',
}

/** Plain text of one top-level Tiptap block, list items on `- ` lines. */
function blockText(block: unknown): string {
  const node = (block ?? {}) as Record<string, unknown>
  const inline = (value: unknown): string => {
    const record = (value ?? {}) as Record<string, unknown>
    if (typeof record.text === 'string') return record.text
    return Array.isArray(record.content) ? record.content.map(inline).join('') : ''
  }
  if (node.type === 'bulletList' || node.type === 'orderedList') {
    const items = Array.isArray(node.content) ? node.content : []
    return items.map((item, index) => {
      const text = inline(item).trim()
      return text ? `${node.type === 'orderedList' ? `${index + 1}.` : '-'} ${text}` : ''
    }).filter(Boolean).join('\n')
  }
  return inline(node).trim()
}

function docBlocks(doc: Record<string, unknown> | undefined): string[] {
  return Array.isArray(doc?.content) ? doc.content.map(blockText) : []
}

function RevisionDiff({ revision, previous }: { revision: ResearchNotebookRevision; previous?: ResearchNotebookRevision }) {
  const ops = revision.diff_json?.ops
  if (revision.diff_json?.rolled_back_to_version) {
    return <p className="text-xs text-muted-foreground">Restored the content of version {revision.diff_json.rolled_back_to_version}.</p>
  }
  if (!ops?.length) return <p className="text-xs text-muted-foreground">Manual edit — open this version below or restore it to inspect.</p>
  const base = docBlocks(previous?.content_json)
  return (
    <div className="space-y-1.5">
      {revision.diff_json?.conflict && <p className="text-xs font-medium text-warning">The section had changed under the AI; its update was appended instead of merged.</p>}
      {ops.map((op, index) => (
        <div key={index} className="space-y-1 text-xs">
          {(op.op === 'replace' || op.op === 'delete') && base.slice(op.index, op.index + op.count).map((text, i) => (
            <pre key={`del-${i}`} className="whitespace-pre-wrap rounded border border-destructive/30 bg-destructive/10 p-2 font-sans text-destructive line-through">{text || '(empty block)'}</pre>
          ))}
          {op.op !== 'delete' && (
            <pre className="whitespace-pre-wrap rounded border border-success/40 bg-success/10 p-2 font-sans">{op.markdown}</pre>
          )}
        </div>
      ))}
    </div>
  )
}

export function NotebookSectionCard({
  projectId,
  section,
  onSaved,
}: {
  projectId: string
  section: ResearchNotebookSection
  onSaved: (value: ResearchNotebookSection) => void
}) {
  const editor = useRef<RichTextEditorHandle>(null)
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(false)
  const [revisions, setRevisions] = useState<ResearchNotebookRevision[] | null>(null)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [expandedDiff, setExpandedDiff] = useState<number | null>(null)

  const latestIsAi = Boolean(section.updated_by_run_id)

  async function save() {
    const content = editor.current?.getSnapshot().content_json
    if (!content) return
    setBusy(true)
    try {
      const next = await projectResearchApi.updateNotebookSection(
        projectId,
        section.section_key,
        { base_version: section.version, content_json: content },
      )
      onSaved(next)
      setDirty(false)
      setRevisions(null)
      toast.success('Notebook section saved')
    } catch (error) {
      toast.error(errMsg(error))
    } finally {
      setBusy(false)
    }
  }

  async function loadHistory(open = true) {
    setHistoryOpen(open)
    if (!open) return
    try {
      setRevisions(await projectResearchApi.notebookRevisions(projectId, section.section_key))
    } catch (error) {
      toast.error(errMsg(error))
    }
  }

  async function rollback(toVersion: number) {
    setBusy(true)
    try {
      const next = await projectResearchApi.rollbackNotebookSection(projectId, section.section_key, toVersion)
      onSaved(next)
      setDirty(false)
      setRevisions(null)
      setHistoryOpen(false)
      toast.success(`Restored version ${toVersion} as version ${next.version}`)
    } catch (error) {
      toast.error(errMsg(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="space-y-3 p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="font-semibold">{SECTION_LABELS[section.section_key]}</h2>
          <p className="text-xs text-muted-foreground">
            Version {section.version} · updated {new Date(section.updated_at).toLocaleString()}
            {section.updated_by_run_id
              ? <> by <Link className="hover:underline" to={`/runs/${section.updated_by_run_id}`}>AI</Link></>
              : section.updated_by_user_id ? ' by a researcher' : ''}
          </p>
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="ghost" onClick={() => void loadHistory(!historyOpen)}>
            <History className="size-3.5" />History
          </Button>
          <Button size="sm" onClick={() => void save()} disabled={!dirty || busy}>
            <Save className="size-3.5" />
            {busy ? 'Saving…' : 'Save'}
          </Button>
        </div>
      </div>
      {latestIsAi && section.version > 1 && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded border border-primary/40 bg-primary/5 p-2.5 text-xs">
          <span className="font-medium">AI edited this section (<Link className="underline" to={`/runs/${section.updated_by_run_id}`}>run</Link>). Review the change or roll it back.</span>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={() => void loadHistory(true)}>View change</Button>
            <Button size="sm" variant="outline" disabled={busy} onClick={() => void rollback(section.version - 1)}>
              <Undo2 className="size-3.5" />Undo AI change
            </Button>
          </div>
        </div>
      )}
      <RichTextEditor
        ref={editor}
        key={`${section.id}:${section.version}`}
        initialContent={section.content_json}
        variant="notes"
        onChange={() => setDirty(true)}
      />
      {historyOpen && (
        <div className="space-y-2 rounded border border-border/70 bg-muted/30 p-3">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Version history</h3>
          {!revisions && <p className="text-xs text-muted-foreground">Loading…</p>}
          {revisions?.map((revision, index) => (
            <div key={revision.id} className="rounded border border-border/60 bg-background p-2.5">
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="font-medium">v{revision.version}</span>
                <Badge variant={revision.source.startsWith('ai_') ? 'default' : 'outline'}>{SOURCE_LABELS[revision.source]}</Badge>
                <span className="text-muted-foreground">{new Date(revision.created_at).toLocaleString()}</span>
                {revision.created_by_run_id && <Link className="text-muted-foreground hover:underline" to={`/runs/${revision.created_by_run_id}`}>run</Link>}
                <span className="ml-auto flex gap-2">
                  <Button size="sm" variant="ghost" onClick={() => setExpandedDiff(expandedDiff === revision.version ? null : revision.version)}>
                    {expandedDiff === revision.version ? 'Hide' : 'Changes'}
                  </Button>
                  {revision.version !== section.version && (
                    <Button size="sm" variant="outline" disabled={busy} onClick={() => void rollback(revision.version)}>Restore</Button>
                  )}
                </span>
              </div>
              {expandedDiff === revision.version && (
                <div className="mt-2"><RevisionDiff revision={revision} previous={revisions[index + 1]} /></div>
              )}
            </div>
          ))}
          {revisions && revisions.length === 0 && <p className="text-xs text-muted-foreground">No history yet.</p>}
        </div>
      )}
    </Card>
  )
}
