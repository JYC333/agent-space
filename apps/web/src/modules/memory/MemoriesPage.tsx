import { useState, useEffect, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { SpaceLink as Link } from '../../core/spaceNav'
import { Brain, FolderKanban, Search, X } from 'lucide-react'
import { toast } from 'sonner'
import { memoryApi } from '../../api/client'
import { useSpace } from '../../contexts/SpaceContext'
import { errMsg } from '../../lib/utils'
import type { Memory, MemoryType, MemoryScope } from '../../types/api'
import { Card, CardTitle } from '../../components/ui/card'
import { Button } from '../../components/ui/button'
import { Input } from '../../components/ui/input'
import { Label } from '../../components/ui/label'
import { Textarea } from '../../components/ui/textarea'
import { Select } from '../../components/ui/select'
import { Badge } from '../../components/ui/badge'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '../../components/ui/table'
import { ScopeBadge } from '../../components/ScopeBadge'

const TYPES:  MemoryType[]  = ['preference', 'semantic', 'episodic', 'procedural', 'project']
const SCOPES: MemoryScope[] = ['user', 'workspace', 'capability', 'agent', 'system']

function fmt(dt: string | null | undefined) { return dt ? new Date(dt).toLocaleString() : '—' }

interface MemoryForm {
  title: string
  content: string
  type: MemoryType
  scope: MemoryScope
  namespace: string
}

const EMPTY_FORM: MemoryForm = {
  title: '', content: '', type: 'semantic', scope: 'user', namespace: 'user.default',
}

export default function MemoriesPage() {
  const { activeSpaceId, activeSpaceName } = useSpace()
  const [searchParams, setSearchParams] = useSearchParams()
  const projectFilter = searchParams.get('project_id') ?? ''

  const [memories, setMemories] = useState<Memory[]>([])
  const [form, setForm]         = useState<MemoryForm>(EMPTY_FORM)
  const [query, setQuery]       = useState('')
  const [searchResults, setSearchResults] = useState<Memory[] | null>(null)
  const [searching, setSearching] = useState(false)

  const load = useCallback(async () => {
    if (!activeSpaceId) {
      setMemories([])
      return
    }
    try {
      setMemories((await memoryApi.list({
        status: 'active',
        project_id: projectFilter || undefined,
      })).items)
    }
    catch (e) { toast.error(errMsg(e)) }
  }, [projectFilter, activeSpaceId])

  useEffect(() => { load() }, [load])

  const displayedMemories = searchResults ?? memories
  const showingSearch = searchResults !== null

  function setField<K extends keyof MemoryForm>(k: K, v: MemoryForm[K]) {
    setForm(f => ({ ...f, [k]: v }))
  }

  async function runSearch() {
    const q = query.trim()
    if (!activeSpaceId) {
      toast.error('Select an operational space before searching memory')
      return
    }
    if (!q) {
      setSearchResults(null)
      return
    }
    setSearching(true)
    try {
      setSearchResults(await memoryApi.search({ query: q, limit: 50 }))
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setSearching(false)
    }
  }

  function clearSearch() {
    setQuery('')
    setSearchResults(null)
  }

  async function addMemory() {
    if (!activeSpaceId) {
      toast.error('Select an operational space before proposing memory')
      return
    }
    if (!form.title.trim() || !form.content.trim()) {
      toast.error('Title and content required'); return
    }
    try {
      await memoryApi.create(form)
      setForm(EMPTY_FORM)
      toast.success('Memory proposal submitted')
      await load()
    } catch (e) { toast.error(errMsg(e)) }
  }

  async function deleteMemory(id: string) {
    try {
      await memoryApi.delete(id)
      toast('Archive proposal submitted')
      await load()
    } catch (e) { toast.error(errMsg(e)) }
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
          <Brain className="size-5 text-accent-foreground" />
        </div>
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Memories</h1>
          <p className="text-sm text-muted-foreground">Review-gated long-term memories across scopes and namespaces.</p>
          <p className="text-xs text-muted-foreground">Viewing: {activeSpaceName ?? activeSpaceId ?? 'No operational space selected'}</p>
          {projectFilter && (
            <span className="inline-flex items-center gap-1 mt-0.5 px-2 py-0.5 rounded-full bg-accent/40 text-xs text-accent-foreground">
              <FolderKanban className="size-3" />
              Filtered by project
              <button onClick={() => setSearchParams(p => { p.delete('project_id'); return p })} className="ml-0.5 hover:text-foreground" aria-label="Clear project filter">
                <X className="size-3" />
              </button>
            </span>
          )}
        </div>
      </div>

      <Card>
        <CardTitle>Propose memory</CardTitle>
        <div className="grid grid-cols-2 gap-3 mb-3">
          <div>
            <Label>Title</Label>
            <Input value={form.title} onChange={e => setField('title', e.target.value)} placeholder="Short title…" />
          </div>
          <div>
            <Label>Type</Label>
            <Select
              value={form.type}
              options={TYPES.map(t => ({ value: t, label: t }))}
              onChange={v => setField('type', v as MemoryType)}
            />
          </div>
          <div>
            <Label>Scope</Label>
            <Select
              value={form.scope}
              options={SCOPES.map(s => ({ value: s, label: s }))}
              onChange={v => setField('scope', v as MemoryScope)}
            />
          </div>
          <div>
            <Label>Namespace</Label>
            <Input value={form.namespace} onChange={e => setField('namespace', e.target.value)} />
          </div>
        </div>
        <div className="mb-3">
          <Label>Content</Label>
          <Textarea value={form.content} onChange={e => setField('content', e.target.value)} placeholder="Memory content…" />
        </div>
        <Button onClick={addMemory} disabled={!activeSpaceId}>Submit proposal</Button>
      </Card>

      <Card>
        <div className="flex flex-col gap-3 mb-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <CardTitle>{showingSearch ? 'Search Results' : 'Active Memories'} ({displayedMemories.length})</CardTitle>
          </div>
          <form
            className="flex gap-2 w-full lg:w-auto"
            onSubmit={e => {
              e.preventDefault()
              void runSearch()
            }}
          >
            <Input
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Search memory…"
              className="min-w-0 lg:w-72"
            />
            <Button type="submit" variant="outline" disabled={!activeSpaceId || searching}>
              <Search className="size-4" /> Search
            </Button>
            {showingSearch && (
              <Button type="button" variant="ghost" onClick={clearSearch}>
                <X className="size-4" /> Clear
              </Button>
            )}
          </form>
        </div>
        {displayedMemories.length === 0
          ? <p className="text-muted-foreground text-center py-10 text-sm">
              {activeSpaceId
                ? showingSearch ? 'No memories matched this search.' : 'No active memories.'
                : 'Select an operational space to browse memories.'}
            </p>
          : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Title</TableHead><TableHead>Type</TableHead>
                  <TableHead>Scope</TableHead><TableHead>Visibility</TableHead><TableHead>Namespace</TableHead>
                  <TableHead>Imp.</TableHead><TableHead>Created</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {displayedMemories.map(m => (
                  <TableRow key={m.id}>
                    <TableCell className="max-w-[220px]">
                      <Link to={`/memory/${m.id}`} className="font-medium text-accent-foreground hover:underline">
                        {m.title || 'Untitled memory'}
                      </Link>
                      {m.content && <p className="text-xs text-muted-foreground truncate mt-0.5">{m.content}</p>}
                    </TableCell>
                    <TableCell><Badge variant="secondary">{m.type}</Badge></TableCell>
                    <TableCell className="text-muted-foreground">{m.scope}</TableCell>
                    <TableCell><ScopeBadge visibility={m.visibility} /></TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">{m.namespace ?? '—'}</TableCell>
                    <TableCell className="text-muted-foreground">{m.importance.toFixed(1)}</TableCell>
                    <TableCell className="text-muted-foreground text-xs">{fmt(m.created_at)}</TableCell>
                    <TableCell>
                      <Button variant="destructive" size="sm" onClick={() => deleteMemory(m.id)}>×</Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
      </Card>
    </div>
  )
}
