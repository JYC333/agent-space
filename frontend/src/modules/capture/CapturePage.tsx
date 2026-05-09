import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, Send } from 'lucide-react'
import { toast } from 'sonner'
import { sessionsApi } from '../../api/client'
import { useSpace } from '../../contexts/SpaceContext'
import { errMsg } from '../../lib/utils'
import { Button } from '../../components/ui/button'
import { Textarea } from '../../components/ui/textarea'

export default function CapturePage() {
  const { spaceId } = useSpace()
  const navigate = useNavigate()
  const [text, setText] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function handleCapture(e: React.FormEvent) {
    e.preventDefault()
    if (!text.trim()) return
    setSubmitting(true)
    try {
      const session = await sessionsApi.create({ title: text.slice(0, 80) })
      await sessionsApi.addMessage(session.id, { role: 'user', content: text })
      toast.success('Captured — opening session')
      navigate('/sessions')
    } catch (err) {
      toast.error(errMsg(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="p-6 space-y-6 max-w-2xl">
      <div className="flex items-center gap-4 pb-4 border-b border-border">
        <div
          className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
          style={{
            background: 'color-mix(in oklch, var(--primary) 12%, transparent)',
            border: '1px solid color-mix(in oklch, var(--primary) 35%, transparent)',
          }}
        >
          <Plus className="size-5 text-accent-foreground" />
        </div>
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Capture</h1>
          <p className="text-sm text-muted-foreground">Quickly save thoughts, ideas, notes, and external content.</p>
        </div>
      </div>

      <form onSubmit={handleCapture} className="space-y-3">
        <Textarea
          value={text}
          onChange={e => setText(e.target.value)}
          placeholder="Capture a thought, paste a link, or drop a snippet. Nothing commits without review."
          rows={6}
          className="resize-none"
          autoFocus
        />
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-muted-foreground" style={{ fontFamily: 'var(--font-mono)' }}>
            {text.length} chars · space: {spaceId}
          </span>
          <Button type="submit" size="sm" disabled={!text.trim() || submitting}>
            <Send className="size-3.5 mr-1.5" />
            {submitting ? 'Capturing…' : 'Capture'}
          </Button>
        </div>
      </form>
    </div>
  )
}
