import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { agentsApi } from '../../api/client'
import type { AgentOut } from '../../types/api'
import { Button } from '../../components/ui/button'
import { Card, CardTitle } from '../../components/ui/card'
import { errMsg } from '../../lib/utils'

export default function AgentDetailPage() {
  const { agentId } = useParams()
  const [agent, setAgent] = useState<AgentOut | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!agentId) return
    agentsApi.get(agentId)
      .then(setAgent)
      .catch(err => toast.error(errMsg(err)))
      .finally(() => setLoading(false))
  }, [agentId])

  if (loading) {
    return <div className="p-6 flex items-center gap-2 text-muted-foreground"><Loader2 className="size-4 animate-spin" /> Loading…</div>
  }
  if (!agent) {
    return <div className="p-6 text-muted-foreground">Agent not found.</div>
  }

  return (
    <div className="p-6 max-w-xl space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">{agent.name}</h1>
          <p className="text-sm text-muted-foreground">{agent.description ?? 'No description'}</p>
        </div>
        <Button asChild size="sm" variant="outline"><Link to={`/agents/${agent.id}/edit`}>Edit</Link></Button>
      </div>
      <Card>
        <CardTitle className="mb-2">Model</CardTitle>
        {agent.model?.provider_name ? (
          <div className="text-sm space-y-1">
            <p>Provider: <span className="font-mono">{agent.model.provider_name}</span> ({agent.model.provider_type})</p>
            <p>Model: <span className="font-mono">{agent.model.model ?? '—'}</span></p>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">This agent will use the system default model unless you choose one.</p>
        )}
      </Card>
    </div>
  )
}
