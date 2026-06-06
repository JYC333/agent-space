import { useCallback, useEffect, useRef, useState } from 'react'
import { Send, Loader2, Sparkles, AlertTriangle } from 'lucide-react'
import { toast } from 'sonner'
import { SpaceLink as Link } from '../../core/spaceNav'
import { agentsApi } from '../../api/client'
import type { AgentOut } from '../../types/api'
import { Button } from '../../components/ui/button'
import { Textarea } from '../../components/ui/textarea'
import { EmptyState } from '../../components/ui/empty-state'
import { errMsg } from '../../lib/utils'

interface ChatMessage { role: 'user' | 'assistant'; content: string; error?: boolean }

/**
 * Synchronous chat surface for the space's Personal Assistant. Each turn calls
 * POST /agents/{id}/chat, which runs the no-tools model_api path server-side and
 * returns the reply. The conversation is held in component state for the session;
 * a model-provider-missing failure renders an inline hint rather than a fake reply.
 */
export default function ChatPanel({ agent, initialDraft }: { agent: AgentOut; initialDraft?: string | null }) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [sessionId, setSessionId] = useState<string | undefined>(undefined)
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const autoSentRef = useRef(false)

  const send = useCallback(async (text: string) => {
    const message = text.trim()
    if (!message || sending) return
    setInput('')
    setMessages(m => [...m, { role: 'user', content: message }])
    setSending(true)
    try {
      const res = await agentsApi.chat(agent.id, { message, session_id: sessionId }, { spaceId: agent.space_id })
      setSessionId(res.session_id)
      if (res.ok) {
        setMessages(m => [...m, { role: 'assistant', content: res.reply ?? '' }])
      } else {
        const note = res.error_code === 'model_provider_required'
          ? 'No model provider is configured for this space yet. Add one to enable chat.'
          : (res.error ?? 'The assistant could not complete this turn.')
        setMessages(m => [...m, { role: 'assistant', content: note, error: true }])
      }
    } catch (e) {
      toast.error(errMsg(e))
      setMessages(m => [...m, { role: 'assistant', content: errMsg(e), error: true }])
    } finally {
      setSending(false)
    }
  }, [agent.id, agent.space_id, sessionId, sending])

  // Auto-send a draft carried from Home's assistant entry (the user already hit "Open").
  useEffect(() => {
    if (initialDraft && initialDraft.trim() && !autoSentRef.current) {
      autoSentRef.current = true
      void send(initialDraft)
    }
  }, [initialDraft, send])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, sending])

  const providerMissing = messages.some(m => m.error && m.content.includes('model provider'))

  return (
    <div className="flex flex-col h-full min-h-0">
      <div ref={scrollRef} className="flex-1 overflow-y-auto rounded-lg border border-border bg-card p-4">
        {messages.length === 0 && !sending ? (
          <EmptyState
            title="Ask your assistant"
            description="It is aware of your space — memory, projects, captures, runs, and proposals. Long-term changes are always proposals you approve."
          />
        ) : (
          <ul className="m-0 p-0 list-none flex flex-col gap-3">
            {messages.map((m, i) => (
              <li key={i} className={m.role === 'user' ? 'flex justify-end' : 'flex justify-start'}>
                <div
                  className="max-w-[85%] rounded-lg px-3 py-2 text-[13px] whitespace-pre-wrap break-words"
                  style={
                    m.role === 'user'
                      ? { background: 'var(--primary)', color: 'var(--primary-foreground)' }
                      : m.error
                        ? { background: 'color-mix(in oklch, var(--warning) 14%, transparent)', border: '1px solid color-mix(in oklch, var(--warning) 35%, transparent)', color: 'var(--foreground)' }
                        : { background: 'var(--muted)', color: 'var(--foreground)' }
                  }
                >
                  {m.role === 'assistant' && (
                    <span className="flex items-center gap-1.5 mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">
                      {m.error ? <AlertTriangle className="size-3" /> : <Sparkles className="size-3" />}
                      {m.error ? 'Could not complete' : 'Assistant'}
                    </span>
                  )}
                  {m.content}
                  {m.error && providerMissing && m.content.includes('model provider') && (
                    <div className="mt-1.5">
                      <Link to="/providers" className="text-[12px] underline text-accent-foreground">Configure a provider →</Link>
                    </div>
                  )}
                </div>
              </li>
            ))}
            {sending && (
              <li className="flex justify-start">
                <div className="rounded-lg px-3 py-2 text-[13px] flex items-center gap-2 text-muted-foreground" style={{ background: 'var(--muted)' }}>
                  <Loader2 className="size-3.5 animate-spin" /> Thinking…
                </div>
              </li>
            )}
          </ul>
        )}
      </div>

      <form
        className="mt-3 flex items-end gap-2"
        onSubmit={(e) => { e.preventDefault(); void send(input) }}
      >
        <Textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void send(input) }
          }}
          placeholder="Ask your assistant… (Enter to send, Shift+Enter for newline)"
          rows={2}
          className="resize-none flex-1"
        />
        <Button type="submit" disabled={sending || !input.trim()}>
          {sending ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}
        </Button>
      </form>
    </div>
  )
}
