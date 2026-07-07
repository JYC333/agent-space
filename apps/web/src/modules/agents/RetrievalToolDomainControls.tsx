import { Database, FolderKanban, Inbox } from 'lucide-react'
import { Badge } from '../../components/ui/badge'

export interface RetrievalToolDomainState {
  memory: boolean
  project_public_summary: boolean
  intake: boolean
}

export function readRetrievalToolDomains(config: Record<string, unknown> | null | undefined): RetrievalToolDomainState {
  const record = isRecord(config) ? config : {}
  const retrievalTools = isRecord(record.retrieval_tools) ? record.retrieval_tools : {}
  const domains = new Set(
    Array.isArray(retrievalTools.domains)
      ? retrievalTools.domains.filter((item): item is string => typeof item === 'string')
      : [],
  )
  const memory = isRecord(retrievalTools.memory) ? retrievalTools.memory : {}
  const project = isRecord(retrievalTools.project_public_summary) ? retrievalTools.project_public_summary : {}
  const intake = isRecord(retrievalTools.intake) ? retrievalTools.intake : {}
  return {
    memory:
      domains.has('memory') ||
      domains.has('memory_entry') ||
      record.memory_retrieval_tools_enabled === true ||
      retrievalTools.memory === true ||
      memory.enabled === true,
    project_public_summary:
      domains.has('project_public_summary') ||
      domains.has('project') ||
      domains.has('projects') ||
      record.project_public_summary_retrieval_tools_enabled === true ||
      retrievalTools.project_public_summary === true ||
      project.enabled === true,
    intake:
      domains.has('intake') ||
      domains.has('intake_item') ||
      domains.has('extracted_evidence') ||
      record.intake_retrieval_tools_enabled === true ||
      retrievalTools.intake === true ||
      intake.enabled === true,
  }
}

export function mergeRetrievalToolDomains(
  config: Record<string, unknown>,
  domains: RetrievalToolDomainState,
): Record<string, unknown> {
  const currentTools = isRecord(config.retrieval_tools) ? config.retrieval_tools : {}
  const nextDomains = [
    ...(domains.memory ? ['memory'] : []),
    ...(domains.project_public_summary ? ['project_public_summary'] : []),
    ...(domains.intake ? ['intake'] : []),
  ]
  return {
    ...config,
    retrieval_tools: {
      ...currentTools,
      domains: nextDomains,
      memory: {
        ...(isRecord(currentTools.memory) ? currentTools.memory : {}),
        enabled: domains.memory,
      },
      project_public_summary: {
        ...(isRecord(currentTools.project_public_summary) ? currentTools.project_public_summary : {}),
        enabled: domains.project_public_summary,
      },
      intake: {
        ...(isRecord(currentTools.intake) ? currentTools.intake : {}),
        enabled: domains.intake,
      },
    },
  }
}

export function RetrievalToolDomainControls({
  value,
  onChange,
  compact = false,
}: {
  value: RetrievalToolDomainState
  onChange: (value: RetrievalToolDomainState) => void
  compact?: boolean
}) {
  const set = (key: keyof RetrievalToolDomainState, checked: boolean) =>
    onChange({ ...value, [key]: checked })

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-sm font-medium">Domain retrieval tools</span>
        <Badge variant="muted">opt-in</Badge>
      </div>
      {!compact && (
        <p className="text-xs text-muted-foreground">
          Knowledge tools use the space retrieval mode. Memory, Project, and Intake tools are separately exposed only when enabled here.
        </p>
      )}
      <div className="grid gap-2 sm:grid-cols-3">
        <label className="flex items-start gap-2 rounded-md border border-border p-3 text-sm">
          <input
            type="checkbox"
            checked={value.memory}
            onChange={event => set('memory', event.target.checked)}
            className="mt-1"
          />
          <span>
            <span className="flex items-center gap-1.5 font-medium">
              <Database className="size-3.5" />
              Memory
            </span>
            <span className="block text-xs text-muted-foreground">
              Enables memory.retrieval.search and memory.retrieval.brief under the instructing user's visibility.
            </span>
          </span>
        </label>
        <label className="flex items-start gap-2 rounded-md border border-border p-3 text-sm">
          <input
            type="checkbox"
            checked={value.project_public_summary}
            onChange={event => set('project_public_summary', event.target.checked)}
            className="mt-1"
          />
          <span>
            <span className="flex items-center gap-1.5 font-medium">
              <FolderKanban className="size-3.5" />
              Project summaries
            </span>
            <span className="block text-xs text-muted-foreground">
              Enables project_public_summary.search and project_public_summary.brief over approved public summaries.
            </span>
          </span>
        </label>
        <label className="flex items-start gap-2 rounded-md border border-border p-3 text-sm">
          <input
            type="checkbox"
            checked={value.intake}
            onChange={event => set('intake', event.target.checked)}
            className="mt-1"
          />
          <span>
            <span className="flex items-center gap-1.5 font-medium">
              <Inbox className="size-3.5" />
              Intake
            </span>
            <span className="block text-xs text-muted-foreground">
              Enables intake.retrieval.search and intake.retrieval.brief over indexed intake items and evidence.
            </span>
          </span>
        </label>
      </div>
    </div>
  )
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}
