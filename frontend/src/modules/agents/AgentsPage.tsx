import { useEffect, useState } from 'react'
import { useSpaceNavigate as useNavigate, SpaceLink as Link } from '../../core/spaceNav'
import { Bot, Loader2, Plus, LayoutTemplate, MessageSquare } from 'lucide-react'
import { toast } from 'sonner'
import { agentsApi } from '../../api/client'
import type { AgentOut } from '../../types/api'
import { useSpace } from '../../contexts/SpaceContext'
import { Button } from '../../components/ui/button'
import { Card, CardTitle } from '../../components/ui/card'
import { Badge } from '../../components/ui/badge'
import { errMsg } from '../../lib/utils'

/**
 * The default Assistant is the space's system-managed Personal Assistant identity — backed
 * by a real Agent (agent_kind=system_assistant) and its own AgentVersion, never a raw chat
 * box and never a user-created template instance. This is the single entry for it on this
 * page; "Open chat" goes to its dedicated chat page, while its configuration (incl.
 * preferences) lives separately on its detail page.
 */
function PersonalAssistantCard() {
  const navigate = useNavigate()
  const [assistant, setAssistant] = useState<AgentOut | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    // Resolve the existing assistant for its real name (404 until first created).
    agentsApi.getDefaultAssistant().then(setAssistant).catch(() => setAssistant(null))
  }, [])

  async function openAssistant() {
    setBusy(true)
    try {
      const agent = assistant ?? await agentsApi.ensureDefaultAssistant()
      navigate(`/agents/${agent.id}/chat`)
    } catch (err) {
      toast.error(errMsg(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="border-primary/30">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <div className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0" style={{ background: 'color-mix(in oklch, var(--primary) 12%, transparent)' }}>
            <MessageSquare className="size-4" />
          </div>
          <div>
            <CardTitle className="flex items-center gap-2">{assistant?.name ?? 'Personal Assistant'} <Badge variant="secondary">System-managed</Badge></CardTitle>
            <p className="text-sm text-muted-foreground mt-1">
              Your space's default contextual chat assistant. Open chat to talk to it; its context,
              model, allowed outputs, and preferences are configured separately on its detail page.
            </p>
          </div>
        </div>
        <Button size="sm" disabled={busy} onClick={openAssistant}>
          {busy ? <Loader2 className="size-4 animate-spin" /> : 'Open chat'}
        </Button>
      </div>
    </Card>
  )
}

export default function AgentsPage() {
  const { activeSpaceId, activeSpaceName } = useSpace()
  const [agents, setAgents] = useState<AgentOut[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!activeSpaceId) {
      setAgents([])
      setLoading(false)
      return
    }
    setLoading(true)
    agentsApi.list()
      // The system-managed default Assistant is represented by the card above —
      // exclude it from the agent list so it is not listed twice.
      .then(list => setAgents(list.filter(a => a.agent_kind !== 'system_assistant')))
      .catch(err => toast.error(errMsg(err)))
      .finally(() => setLoading(false))
  }, [activeSpaceId])

  return (
    <div className="p-6 space-y-6 max-w-3xl">
      <div className="flex items-center justify-between gap-4 pb-4 border-b border-border">
        <div className="flex items-center gap-4">
          <div className="w-11 h-11 rounded-xl flex items-center justify-center" style={{ background: 'color-mix(in oklch, var(--primary) 12%, transparent)' }}>
            <Bot className="size-5" />
          </div>
          <div>
            <h1 className="text-xl font-semibold">Agents</h1>
            <p className="text-sm text-muted-foreground">Viewing: {activeSpaceName ?? 'No space'}</p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button asChild size="sm" variant="outline" disabled={!activeSpaceId}>
            <Link to="/agents/templates"><LayoutTemplate className="size-3.5 mr-1" />Templates</Link>
          </Button>
          <Button asChild size="sm" disabled={!activeSpaceId}>
            <Link to="/agents/new"><Plus className="size-3.5 mr-1" />New agent</Link>
          </Button>
        </div>
      </div>

      {activeSpaceId && <PersonalAssistantCard />}

      {loading ? (
        <div className="flex items-center gap-2 text-muted-foreground"><Loader2 className="size-4 animate-spin" /> Loading…</div>
      ) : agents.length === 0 ? (
        <Card><p className="text-sm text-muted-foreground p-4">No agents yet. Create one to configure model and runtime defaults.</p></Card>
      ) : (
        <div className="space-y-3">
          {agents.map(a => (
            <Link key={a.id} to={`/agents/${a.id}`} className="block">
              <Card className="hover:bg-accent/40 transition-colors">
                <CardTitle>{a.name}</CardTitle>
                <p className="text-sm text-muted-foreground mt-1">{a.description ?? 'No description'}</p>
                {a.model?.provider_name ? (
                  <p className="text-xs font-mono mt-2">{a.model.provider_name} · {a.model.model ?? 'default model'}</p>
                ) : (
                  <p className="text-xs text-muted-foreground mt-2">Uses system default model</p>
                )}
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
