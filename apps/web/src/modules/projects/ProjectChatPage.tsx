import { useCallback, useEffect, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { Loader2, MessageSquareText } from 'lucide-react'
import { toast } from 'sonner'
import { agentsApi, projectsApi } from '../../api/client'
import type { AgentOut, Project } from '../../types/api'
import { Button } from '../../components/ui/button'
import { SpaceLink as Link } from '../../core/spaceNav'
import { errMsg, isNotFoundError } from '../../lib/utils'
import ChatPanel from '../agents/ChatPanel'

export default function ProjectChatPage() {
  const { projectId = '' } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const [project, setProject] = useState<Project | null>(null)
  const [agent, setAgent] = useState<AgentOut | null>(null)
  const [loading, setLoading] = useState(true)
  const sessionId = searchParams.get('session')

  useEffect(() => {
    if (!projectId) return
    setLoading(true)
    Promise.all([projectsApi.get(projectId), agentsApi.getDefaultAssistant()])
      .then(([projectRow, assistant]) => {
        setProject(projectRow)
        setAgent(assistant)
      })
      .catch(error => {
        if (!isNotFoundError(error)) toast.error(errMsg(error))
        setProject(null)
      })
      .finally(() => setLoading(false))
  }, [projectId])

  const rememberSession = useCallback(
    (id: string) =>
      setSearchParams(
        previous => {
          const next = new URLSearchParams(previous)
          next.set('session', id)
          return next
        },
        { replace: true },
      ),
    [setSearchParams],
  )

  if (loading) {
    return (
      <div className="p-6 flex items-center gap-2 text-muted-foreground">
        <Loader2 className="size-4 animate-spin" />
        Loading project chat…
      </div>
    )
  }

  if (!project || !agent) {
    return <div className="p-6 text-muted-foreground">Project not found or unavailable.</div>
  }

  return (
    <div className="flex h-full w-full max-w-4xl mx-auto flex-col p-4 md:p-6">
      <header className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs text-muted-foreground">Project chat</p>
          <h1 className="text-xl font-semibold">{project.name}</h1>
          <p className="text-sm text-muted-foreground">
            Ask the assistant to plan source changes. Durable actions appear as proposals for review.
          </p>
        </div>
        <Button asChild variant="outline" size="sm">
          <Link to={`/projects/${project.id}`}>
            <MessageSquareText className="size-3.5" />
            Project
          </Link>
        </Button>
      </header>
      <div className="mt-4 min-h-0 flex-1">
        <ChatPanel agent={agent} projectId={project.id} initialSessionId={sessionId} onSessionChange={rememberSession} />
      </div>
    </div>
  )
}
