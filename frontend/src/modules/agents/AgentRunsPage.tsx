import { useState, useEffect, useCallback } from 'react'
import { Bot } from 'lucide-react'
import { toast } from 'sonner'
import { tasksApi, agentsApi } from '../../api/client'
import { useSpace } from '../../contexts/SpaceContext'
import { useRun } from '../../hooks/useRun'
import { errMsg } from '../../lib/utils'
import { Card, CardTitle } from '../../components/ui/card'
import { Button } from '../../components/ui/button'
import { Label } from '../../components/ui/label'
import { Textarea } from '../../components/ui/textarea'
import { Select } from '../../components/ui/select'
import { StatusBadge, Badge } from '../../components/ui/badge'
import { Skeleton } from '../../components/ui/skeleton'
import type { AgentRun } from '../../types/api'

function fmt(dt: string | null | undefined) { return dt ? new Date(dt).toLocaleString() : '—' }

const ADAPTERS = [
  { value: 'echo',        label: 'Echo (test)' },
  { value: 'claude_code', label: 'Claude Code' },
  { value: 'codex_cli',   label: 'Codex CLI' },
  { value: 'opencode',    label: 'OpenCode' },
  { value: 'gemini_cli',  label: 'Gemini CLI' },
]

function RunCard({ run: initialRun }: { run: AgentRun }) {
  const { run: polledRun, loading } = useRun(
    initialRun.status === 'pending' || initialRun.status === 'running' ? initialRun.id : null
  )
  const run = polledRun ?? initialRun

  if (loading && !polledRun) {
    return (
      <Card>
        <div className="flex gap-3 items-center mb-3">
          <Skeleton className="h-5 w-16" />
          <Skeleton className="h-5 w-20" />
          <Skeleton className="h-5 w-32" />
        </div>
        <Skeleton className="h-20 w-full" />
      </Card>
    )
  }

  return (
    <Card>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <StatusBadge status={run.status} />
          <Badge variant="secondary">{run.adapter_type}</Badge>
          <span className="font-mono text-xs text-muted-foreground">{run.id.slice(0, 16)}…</span>
        </div>
        <span className="text-xs text-muted-foreground">{fmt(run.created_at)}</span>
      </div>
      {run.prompt && <p className="text-xs text-muted-foreground mb-2 truncate">{run.prompt}</p>}
      {run.output && <pre className="text-xs">{run.output}</pre>}
      {run.error  && <pre className="text-xs border-destructive text-destructive">{run.error}</pre>}
    </Card>
  )
}

export default function AgentRunsPage() {
  const { spaceId } = useSpace()
  const [prompt, setPrompt]         = useState('')
  const [adapter, setAdapter]       = useState('echo')
  const [runs, setRuns]             = useState<AgentRun[]>([])
  const [loadingRuns, setLoadingRuns] = useState(true)
  const [submitting, setSubmitting] = useState(false)

  const loadRuns = useCallback(async () => {
    try {
      const data = await agentsApi.listRuns()
      setRuns(data)
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setLoadingRuns(false)
    }
  }, [])

  useEffect(() => {
    setLoadingRuns(true)
    loadRuns()
  }, [loadRuns, spaceId])

  async function quickRun() {
    if (!prompt.trim()) { toast.error('Prompt required'); return }
    setSubmitting(true)
    try {
      const task = await tasksApi.create({ title: prompt.trim() })
      await tasksApi.run(task.id, adapter)
      toast.success('Run enqueued')
      setPrompt('')
      await loadRuns()
    } catch (e) { toast.error(errMsg(e)) }
    finally { setSubmitting(false) }
  }

  return (
    <div className="p-6 space-y-6">
      {/* Page header */}
      <div className="flex items-center gap-4 pb-4 border-b border-border">
        <div
          className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
          style={{
            background: 'color-mix(in oklch, var(--primary) 12%, transparent)',
            border: '1px solid color-mix(in oklch, var(--primary) 35%, transparent)',
          }}
        >
          <Bot className="size-5 text-accent-foreground" />
        </div>
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Agent Runs</h1>
          <p className="text-sm text-muted-foreground">Submit prompts and track agent execution across adapters.</p>
        </div>
      </div>

      <Card>
        <CardTitle>Quick Run</CardTitle>
        <div className="mb-3">
          <Label>Prompt</Label>
          <Textarea value={prompt} onChange={e => setPrompt(e.target.value)} placeholder="Enter a prompt…" />
        </div>
        <div className="flex items-end gap-3">
          <div className="flex-1">
            <Label>Adapter</Label>
            <Select
              value={adapter}
              options={ADAPTERS}
              onChange={v => setAdapter(v)}
            />
          </div>
          <Button onClick={quickRun} disabled={submitting || !prompt.trim()}>
            {submitting ? 'Submitting…' : 'Run Agent'}
          </Button>
        </div>
      </Card>

      {loadingRuns ? (
        <Card>
          <div className="space-y-3">
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-20 w-full" />
          </div>
        </Card>
      ) : runs.length === 0 ? (
        <Card><p className="text-muted-foreground text-center py-10 text-sm">No runs yet.</p></Card>
      ) : (
        runs.map(run => <RunCard key={run.id} run={run} />)
      )}
    </div>
  )
}
