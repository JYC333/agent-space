import { useEffect, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { SpaceLink as Link } from '../../core/spaceNav'
import { Loader2, Settings2, AlertTriangle } from 'lucide-react'
import { toast } from 'sonner'
import { agentsApi, providersApi } from '../../api/client'
import type { AgentOut } from '../../types/api'
import { Button } from '../../components/ui/button'
import { Badge, StatusBadge } from '../../components/ui/badge'
import { errMsg } from '../../lib/utils'
import ChatPanel from './ChatPanel'

/**
 * Dedicated, full-height chat surface for an agent (typically the space's Personal
 * Assistant). Chat is a primary daily activity, so it is its own page — intentionally
 * separate from the agent's configuration, which lives on AgentDetailPage. A draft
 * carried from Home (?draft=) is captured once and auto-sent on arrival.
 *
 * The assistant resolves to the space's default ModelProvider at run time (the
 * personal-assistant template binds no provider of its own). If no default provider
 * is configured the assistant cannot answer, so we check up-front and replace the
 * chat with a clear "configure a provider" notice rather than letting the user type
 * a message that can only fail. (The check is best-effort and fails open on a fetch
 * error; ChatPanel still surfaces the same error reactively as a safety net.)
 */
export default function AssistantChatPage() {
  const { agentId } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  // Captured once so the Chat auto-sends it; the URL param is then cleared so a
  // refresh won't resend the same message.
  const [initialDraft] = useState(() => searchParams.get('draft'))
  const [agent, setAgent] = useState<AgentOut | null>(null)
  // null = unknown (not loaded yet, or the providers check failed → fail open).
  const [hasDefaultProvider, setHasDefaultProvider] = useState<boolean | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!agentId) return
    setLoading(true)
    Promise.all([
      agentsApi.get(agentId),
      // A "default model provider" is one marked default and enabled — the same
      // condition the backend uses to resolve a provider for the run. Fail open
      // (null) on error so a transient providers hiccup never blocks a working chat.
      providersApi.list().then(
        ps => ps.some(p => p.is_default && p.enabled),
        () => null,
      ),
    ])
      .then(([a, ready]) => { setAgent(a); setHasDefaultProvider(ready) })
      .catch(err => toast.error(errMsg(err)))
      .finally(() => setLoading(false))
  }, [agentId])

  // Clear the carried ?draft= once (already captured into initialDraft above).
  useEffect(() => {
    if (searchParams.get('draft')) {
      setSearchParams(p => { p.delete('draft'); return p }, { replace: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (loading) return <div className="p-6 flex items-center gap-2 text-muted-foreground"><Loader2 className="size-4 animate-spin" /> Loading…</div>
  if (!agent) return <div className="p-6 text-muted-foreground">Assistant not found.</div>

  const isAssistant = agent.agent_kind === 'system_assistant'
  const providerMissing = hasDefaultProvider === false

  return (
    <div className="flex flex-col h-full w-full max-w-3xl mx-auto p-4 md:p-6">
      <header className="flex items-start justify-between gap-4 shrink-0">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold flex items-center gap-2 truncate">
            {agent.name} <StatusBadge status={agent.status} />
            {isAssistant && <Badge variant="secondary">System-managed</Badge>}
          </h1>
          {agent.description && <p className="text-sm text-muted-foreground truncate">{agent.description}</p>}
        </div>
        <div className="flex gap-2 shrink-0">
          <Button asChild size="sm" variant="outline">
            <Link to={`/agents/${agent.id}`}><Settings2 className="size-3.5 mr-1" />Settings</Link>
          </Button>
        </div>
      </header>

      <div className="flex-1 min-h-0 mt-4">
        {providerMissing
          ? <NoProviderNotice />
          : <ChatPanel agent={agent} initialDraft={initialDraft} />}
      </div>
    </div>
  )
}

/**
 * Blocking notice shown when the space has no default model provider. The assistant
 * cannot answer without one, so this replaces the chat and points the user at /providers.
 */
function NoProviderNotice() {
  return (
    <div className="rounded-lg border border-warning/30 bg-warning/5 p-5 max-w-xl space-y-3">
      <div className="flex items-start gap-2.5">
        <AlertTriangle className="size-5 text-warning shrink-0 mt-0.5" />
        <div className="space-y-1">
          <h2 className="text-[15px] font-semibold tracking-tight">Assistant unavailable — no model provider configured</h2>
          <p className="text-sm text-muted-foreground">
            This assistant answers using your space's default model provider. None is configured yet,
            so it can't be used. Add a provider and mark it as the default (with an API key if the
            provider needs one) to enable chat.
          </p>
        </div>
      </div>
      <Button asChild size="sm">
        <Link to="/providers"><Settings2 className="size-3.5 mr-1" />Configure a provider</Link>
      </Button>
    </div>
  )
}
