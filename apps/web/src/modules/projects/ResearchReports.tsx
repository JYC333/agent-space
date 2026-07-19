import { ArrowRight, FileText } from 'lucide-react'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { SpaceLink as Link } from '../../core/spaceNav'
import type { ProjectResearchReport, ProjectResearchWorkflow } from '../../types/api'
import { researchReportViews } from './researchReports'

interface ResearchReportsProps {
  reports: ProjectResearchReport[]
  workflows: ProjectResearchWorkflow[]
  currentQuestion: string
}

function generatedLabel(value: string): string {
  const timestamp = Date.parse(value)
  if (!Number.isFinite(timestamp)) return 'Generation time unavailable'
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(timestamp))
}

export function ResearchReports({ reports: reportRows, workflows, currentQuestion }: ResearchReportsProps) {
  const reports = researchReportViews(reportRows, workflows, currentQuestion)
  if (reports.length === 0) return null
  const latest = reports[0]!

  return (
    <section id="research-reports" aria-labelledby="research-reports-title" className="rounded-lg border border-border bg-card p-4 lg:p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <FileText className="size-4 text-accent-foreground" />
            <h2 id="research-reports-title" className="text-sm font-semibold">Research reports</h2>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">Open the generated outputs and see which research question each one answered.</p>
        </div>
        <Badge variant="muted">{reports.length} report{reports.length === 1 ? '' : 's'}</Badge>
      </div>

      <div className="mt-4 rounded-md border border-border bg-muted/15 p-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="secondary">Latest</Badge>
              <Badge variant="outline">{latest.kindLabel}</Badge>
              {latest.stale && <Badge variant="warning">Generated for a previous question</Badge>}
            </div>
            <h3 className="mt-2 font-semibold">{latest.title}</h3>
            {latest.summary && <p className="mt-1 line-clamp-3 text-sm text-muted-foreground">{latest.summary}</p>}
            <p className="mt-2 text-xs text-muted-foreground">Generated {generatedLabel(latest.generatedAt)}</p>
            <p className="mt-1 text-xs text-muted-foreground">Question: {latest.question ?? 'Question provenance unavailable'}</p>
          </div>
          <Button size="sm" asChild>
            <Link to={`/projects/${latest.link.project_id}/research/reports/${latest.link.id}`}>Open report <ArrowRight className="size-3.5" /></Link>
          </Button>
        </div>
      </div>

      {reports.length > 1 && (
        <div className="mt-3 divide-y divide-border rounded-md border border-border">
          {reports.slice(1).map(report => (
            <div key={report.link.id} className="flex flex-col gap-3 p-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="truncate text-sm font-medium">{report.title}</p>
                  <Badge variant="outline">{report.kindLabel}</Badge>
                  {report.stale && <Badge variant="warning">Previous question</Badge>}
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{generatedLabel(report.generatedAt)} · Question: {report.question ?? 'Unavailable'}</p>
              </div>
              <Button size="sm" variant="ghost" asChild>
                <Link to={`/projects/${report.link.project_id}/research/reports/${report.link.id}`}>Open <ArrowRight className="size-3.5" /></Link>
              </Button>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
