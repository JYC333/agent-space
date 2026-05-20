import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Bot, Loader2, Plus } from 'lucide-react'
import { toast } from 'sonner'
import { agentsApi } from '../../api/client'
import type { AgentOut } from '../../types/api'
import { useSpace } from '../../contexts/SpaceContext'
import { Button } from '../../components/ui/button'
import { Card, CardTitle } from '../../components/ui/card'
import { errMsg } from '../../lib/utils'

export default function AgentsPage() {
  const { activeOperationalSpaceId, activeOperationalSpaceName } = useSpace()
  const [agents, setAgents] = useState<AgentOut[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!activeOperationalSpaceId) {
      setAgents([])
      setLoading(false)
      return
    }
    setLoading(true)
    agentsApi.list()
      .then(setAgents)
      .catch(err => toast.error(errMsg(err)))
      .finally(() => setLoading(false))
  }, [activeOperationalSpaceId])

  return (
    <div className="p-6 space-y-6 max-w-3xl">
      <div className="flex items-center justify-between gap-4 pb-4 border-b border-border">
        <div className="flex items-center gap-4">
          <div className="w-11 h-11 rounded-xl flex items-center justify-center" style={{ background: 'color-mix(in oklch, var(--primary) 12%, transparent)' }}>
            <Bot className="size-5" />
          </div>
          <div>
            <h1 className="text-xl font-semibold">Agents</h1>
            <p className="text-sm text-muted-foreground">Viewing: {activeOperationalSpaceName ?? 'No space'}</p>
          </div>
        </div>
        <Button asChild size="sm" disabled={!activeOperationalSpaceId}>
          <Link to="/agents/new"><Plus className="size-3.5 mr-1" />New agent</Link>
        </Button>
      </div>

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
