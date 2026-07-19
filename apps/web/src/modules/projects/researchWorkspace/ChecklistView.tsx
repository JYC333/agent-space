import { useState } from 'react'
import { CheckCircle2, GripVertical, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { projectResearchApi } from '../../../api/client'
import type { ResearchChecklistItem } from '../../../types/api'
import { Badge } from '../../../components/ui/badge'
import { Button } from '../../../components/ui/button'
import { Card } from '../../../components/ui/card'
import { EmptyState } from '../../../components/ui/empty-state'
import { Input } from '../../../components/ui/input'
import { errMsg } from '../../../lib/utils'
import { SpaceLink as Link } from '../../../core/spaceNav'

export function ChecklistView({
  projectId,
  items,
  onChange,
}: {
  projectId: string
  items: ResearchChecklistItem[]
  onChange: (items: ResearchChecklistItem[]) => void
}) {
  const [text, setText] = useState('')
  const [draggedId, setDraggedId] = useState<string | null>(null)

  async function add() {
    if (!text.trim()) return
    try {
      const item = await projectResearchApi.createChecklistItem(projectId, text)
      onChange([...items, item])
      setText('')
    } catch (error) {
      toast.error(errMsg(error))
    }
  }

  async function setStatus(item: ResearchChecklistItem, status: ResearchChecklistItem['status']) {
    try {
      const next = await projectResearchApi.updateChecklistItem(projectId, item.id, { status })
      onChange(items.map((value) => value.id === next.id ? next : value))
    } catch (error) {
      toast.error(errMsg(error))
    }
  }

  async function remove(id: string) {
    try {
      await projectResearchApi.deleteChecklistItem(projectId, id)
      onChange(items.filter((value) => value.id !== id))
    } catch (error) {
      toast.error(errMsg(error))
    }
  }

  async function dropBefore(targetId: string) {
    if (!draggedId || draggedId === targetId) return
    const reordered = [...items]
    const from = reordered.findIndex((item) => item.id === draggedId)
    const to = reordered.findIndex((item) => item.id === targetId)
    if (from < 0 || to < 0) return
    const [dragged] = reordered.splice(from, 1)
    reordered.splice(to, 0, dragged)
    onChange(reordered)
    setDraggedId(null)
    try {
      await Promise.all(reordered.map((item, sortOrder) => projectResearchApi.updateChecklistItem(projectId, item.id, { sort_order: sortOrder })))
    } catch (error) {
      toast.error(errMsg(error))
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <Input value={text} onChange={(event) => setText(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') void add() }} placeholder="Add a research task" />
        <Button onClick={() => void add()}><Plus className="size-4" />Add</Button>
      </div>
      {items.length === 0 ? (
        <EmptyState title="Checklist is empty" description="Track research gaps, follow-ups, and experiments here." />
      ) : items.map((item) => (
        <Card
          key={item.id}
          draggable
          onDragStart={() => setDraggedId(item.id)}
          onDragOver={(event) => event.preventDefault()}
          onDrop={() => void dropBefore(item.id)}
          className="flex items-center gap-3 p-3"
        >
          <GripVertical className="size-4 cursor-grab text-muted-foreground" />
          <button onClick={() => void setStatus(item, item.status === 'done' ? 'open' : 'done')} className={item.status === 'done' ? 'text-success' : 'text-muted-foreground'}>
            <CheckCircle2 className="size-5" />
          </button>
          <span className={`flex-1 ${item.status === 'done' ? 'line-through text-muted-foreground' : ''}`}>{item.text}</span>
          {item.origin === 'agent' && <Badge variant="outline">AI suggestion</Badge>}
          {item.origin_run_id && <Link className="text-xs text-muted-foreground hover:underline" to={`/runs/${item.origin_run_id}`}>source</Link>}
          <Button size="icon" variant="ghost" onClick={() => void remove(item.id)}><Trash2 className="size-4" /></Button>
        </Card>
      ))}
    </div>
  )
}
