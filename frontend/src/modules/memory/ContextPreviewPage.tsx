import { useState } from 'react'
import { Layers } from 'lucide-react'
import { toast } from 'sonner'
import { contextApi } from '../../api/client'
import { errMsg } from '../../lib/utils'
import type { ContextPackage, Memory } from '../../types/api'
import { Card, CardTitle } from '../../components/ui/card'
import { Button } from '../../components/ui/button'
import { Input } from '../../components/ui/input'
import { Label } from '../../components/ui/label'

interface ContextForm {
  session_id: string
  capability_id: string
  query: string
}

const SUMMARY_ROWS: [string, keyof ContextPackage][] = [
  ['User Memory',       'user_memory'],
  ['Workspace Memory',  'workspace_memory'],
  ['Capability Memory', 'capability_memory'],
  ['Agent Memory',      'agent_memory'],
  ['System Policy',     'system_policy'],
  ['Episodes',          'relevant_episodes'],
  ['Session Summaries', 'recent_session_summary'],
]

export default function ContextPreviewPage() {
  const [form, setForm] = useState<ContextForm>({ session_id: '', capability_id: '', query: '' })
  const [pkg, setPkg]   = useState<ContextPackage | null>(null)
  const [loading, setLoading] = useState(false)

  function setField(k: keyof ContextForm, v: string) { setForm(f => ({ ...f, [k]: v })) }

  async function build() {
    setLoading(true)
    try {
      setPkg(await contextApi.build({
        session_id:    form.session_id.trim()    || null,
        capability_id: form.capability_id.trim() || null,
        query:         form.query.trim()          || null,
      }))
    } catch (e) { toast.error(errMsg(e)) }
    finally { setLoading(false) }
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
          <Layers className="size-5 text-accent-foreground" />
        </div>
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Context Preview</h1>
          <p className="text-sm text-muted-foreground">Build and inspect context packages assembled for agent runs.</p>
        </div>
      </div>

      <Card>
        <CardTitle>Build Context Package</CardTitle>
        <div className="grid grid-cols-2 gap-3 mb-3">
          <div>
            <Label>Session ID (optional)</Label>
            <Input value={form.session_id} onChange={e => setField('session_id', e.target.value)} placeholder="Paste session ID…" />
          </div>
          <div>
            <Label>Capability ID (optional)</Label>
            <Input value={form.capability_id} onChange={e => setField('capability_id', e.target.value)} placeholder="e.g. memory.reflect" />
          </div>
        </div>
        <div className="mb-3">
          <Label>Query (optional — relevance search)</Label>
          <Input value={form.query} onChange={e => setField('query', e.target.value)} placeholder="What are you building?" />
        </div>
        <Button onClick={build} disabled={loading}>{loading ? 'Building…' : 'Build Context'}</Button>
      </Card>

      {pkg && (
        <>
          <Card>
            <CardTitle>Summary</CardTitle>
            <div className="flex flex-wrap gap-3">
              {SUMMARY_ROWS.map(([label, key]) => {
                const arr = pkg[key] as Memory[]
                return (
                  <div key={label} className="bg-background border border-border rounded-md p-3 min-w-[110px]">
                    <div className="text-[11px] text-muted-foreground mb-1">{label}</div>
                    <div className={`text-2xl font-bold ${arr.length > 0 ? 'text-accent-foreground' : 'text-muted-foreground'}`}>
                      {arr.length}
                    </div>
                  </div>
                )
              })}
            </div>
          </Card>
          <Card>
            <CardTitle>Full Package JSON</CardTitle>
            <pre>{JSON.stringify(pkg, null, 2)}</pre>
          </Card>
        </>
      )}
    </div>
  )
}
