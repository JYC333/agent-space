import {
  Activity, BookOpen, CheckCircle, Edit2, FileText, Network, Plus, RefreshCw, Rss, Search, Target,
} from 'lucide-react'
import { SpaceLink as Link } from '../../core/spaceNav'
import type {
  ExtractedEvidence, Project, ProjectResearchArtifactLink, ProjectResearchCheckpoint,
  ProjectResearchLiteratureMatrixItem, ProjectResearchProfile, ProjectResearchScreeningCriteria,
  ProjectResearchWorkflow, ProjectSourceBinding, ReaderAnnotation, SourceItem,
  SourcePostProcessingItemDecision,
} from '../../types/api'
import { Badge, StatusBadge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'

export function activeResearchWorkflowFrom(workflows: ProjectResearchWorkflow[]): ProjectResearchWorkflow | null {
  return workflows.find(workflow => workflow.status === 'active') ?? null
}

function academicGraphHref(projectId: string): string {
  return `/graph?${new URLSearchParams({ project_id: projectId, lens_id: 'academic_citation_v1' })}`
}

function arxivSourcePresetHref(projectId: string): string {
  return `/sources/source-presets?${new URLSearchParams({ project_id: projectId, preset: 'arxiv' })}`
}

function stageState(workflow: ProjectResearchWorkflow | null, stageKey: string): Record<string, unknown> | null {
  if (!workflow) return null
  const stages = workflow.state_json.stages
  if (!stages || typeof stages !== 'object' || Array.isArray(stages)) return null
  const value = (stages as Record<string, unknown>)[stageKey]
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null
}

function stageToneClass(status: string): string {
  switch (status) {
    case 'complete':
      return 'border-success/35 bg-success/5'
    case 'active':
      return 'border-warning/40 bg-warning/5'
    case 'warning':
      return 'border-destructive/35 bg-destructive/5'
    default:
      return 'border-border bg-muted/20'
  }
}

function stageBadgeVariant(status: string): 'success' | 'warning' | 'destructive' | 'muted' {
  switch (status) {
    case 'complete':
      return 'success'
    case 'active':
      return 'warning'
    case 'warning':
      return 'destructive'
    default:
      return 'muted'
  }
}

function hasScreeningCriteria(criteria: ProjectResearchScreeningCriteria | null): boolean {
  if (!criteria) return false
  return [
    criteria.include_keywords,
    criteria.exclude_keywords,
    criteria.methods,
    criteria.venues,
    criteria.required_evidence_fields,
  ].some(values => values.length > 0) || Boolean(criteria.date_range_start || criteria.date_range_end)
}

function profileNeedsSync(project: Project, profile: ProjectResearchProfile | null): boolean {
  const focus = project.current_focus?.trim()
  if (!focus || !profile?.research_question) return false
  return focus !== profile.research_question.trim()
}

export interface AcademicResearchWorkbenchProps {
  project: Project
  sourceBindings: ProjectSourceBinding[]
  recentSourceItems: SourceItem[]
  recentEvidence: ExtractedEvidence[]
  sourceRecommendations: SourcePostProcessingItemDecision[]
  readerAnnotations: ReaderAnnotation[]
  researchProfile: ProjectResearchProfile | null
  researchWorkflows: ProjectResearchWorkflow[]
  researchCheckpoints: ProjectResearchCheckpoint[]
  literatureMatrix: ProjectResearchLiteratureMatrixItem[]
  synthesisArtifacts: ProjectResearchArtifactLink[]
  screeningCriteria: ProjectResearchScreeningCriteria | null
  researchActionBusy: string | null
  onPrepareProfile: () => void
  onStartWorkflow: () => void
  onRebuildMatrix: () => void
  onRunIntegrity: () => void
  onEditQuestion: () => void
}

export function AcademicResearchWorkbench({
  project,
  sourceBindings,
  recentSourceItems,
  recentEvidence,
  sourceRecommendations,
  readerAnnotations,
  researchProfile,
  researchWorkflows,
  researchCheckpoints,
  literatureMatrix,
  synthesisArtifacts,
  screeningCriteria,
  researchActionBusy,
  onPrepareProfile,
  onStartWorkflow,
  onRebuildMatrix,
  onRunIntegrity,
  onEditQuestion,
}: AcademicResearchWorkbenchProps) {
  const sourceHref = `/projects/${project.id}/sources`
  const activeWorkflow = activeResearchWorkflowFrom(researchWorkflows)
  const setupRecorded = Boolean(stageState(activeWorkflow, 'research_profile'))
  const matrixRecorded = Boolean(stageState(activeWorkflow, 'screening_matrix'))
  const profileApproved = researchProfile?.status === 'approved'
  const syncNeeded = profileNeedsSync(project, researchProfile)
  const projectQuestion = project.current_focus?.trim() ?? ''
  const criteriaReady = hasScreeningCriteria(screeningCriteria)
  const pendingCheckpoints = researchCheckpoints.filter(checkpoint => checkpoint.status === 'pending')
  const integrityCheckpoint = researchCheckpoints.find(checkpoint => checkpoint.checkpoint_type === 'integrity_gate')
  const evidenceSignalCount = recentEvidence.length + readerAnnotations.length
  const matrixEvidenceCount = literatureMatrix.reduce((total, row) => total + row.evidence_count + row.annotation_count, 0)
  const canAct = project.status === 'active'
  const stageRows = [
    {
      key: 'research_profile',
      label: 'Research profile',
      icon: <Target className="size-4" />,
      status: profileApproved && !syncNeeded ? 'complete' : projectQuestion ? 'active' : 'waiting',
      badge: profileApproved && !syncNeeded ? 'Approved' : projectQuestion ? 'Review' : 'Missing',
      meta: projectQuestion || 'Set a research question to unlock the workflow.',
    },
    {
      key: 'literature_monitoring',
      label: 'Literature intake',
      icon: <Rss className="size-4" />,
      status: sourceBindings.length > 0 ? 'complete' : 'waiting',
      badge: `${sourceBindings.length} sources`,
      meta: sourceBindings.length > 0
        ? `${recentSourceItems.length} recent papers or source items collected.`
        : 'Connect arXiv, RSS, PDFs, or manual URLs to feed the corpus.',
    },
    {
      key: 'screening_matrix',
      label: 'Screening matrix',
      icon: <Search className="size-4" />,
      status: literatureMatrix.length > 0 || matrixRecorded ? 'complete' : recentSourceItems.length > 0 || sourceRecommendations.length > 0 ? 'active' : 'waiting',
      badge: `${literatureMatrix.length} rows`,
      meta: criteriaReady
        ? 'Screening criteria are configured for triage.'
        : `${sourceRecommendations.length} source recommendations ready for review.`,
    },
    {
      key: 'synthesis',
      label: 'Synthesis',
      icon: <FileText className="size-4" />,
      status: synthesisArtifacts.length > 0 ? 'complete' : activeWorkflow?.current_stage === 'synthesis' ? 'active' : 'waiting',
      badge: `${synthesisArtifacts.length} reports`,
      meta: synthesisArtifacts[0]?.artifact.title ?? 'Build synthesis after the matrix has included papers.',
    },
    {
      key: 'integrity_gate',
      label: 'Integrity gate',
      icon: <CheckCircle className="size-4" />,
      status: integrityCheckpoint?.status === 'approved' || integrityCheckpoint?.status === 'waived'
        ? 'complete'
        : integrityCheckpoint?.status === 'rejected'
          ? 'warning'
          : integrityCheckpoint?.status === 'pending'
            ? 'active'
            : 'waiting',
      badge: integrityCheckpoint?.status ?? 'Not run',
      meta: pendingCheckpoints.length > 0
        ? `${pendingCheckpoints.length} checkpoint${pendingCheckpoints.length === 1 ? '' : 's'} waiting for review.`
        : `${matrixEvidenceCount || evidenceSignalCount} evidence and annotation signals in scope.`,
    },
  ]
  const nextAction = !projectQuestion
    ? 'Set the research question before starting auto research.'
    : !profileApproved || syncNeeded
      ? 'Approve the project research profile.'
      : !activeWorkflow
        ? 'Start the literature review workflow.'
        : literatureMatrix.length === 0 && recentSourceItems.length > 0
          ? 'Rebuild the literature matrix from the project corpus.'
          : 'Run the integrity gate before using synthesis or draft outputs.'

  return (
    <section className="rounded-lg border border-border bg-card overflow-hidden">
      <div className="border-b border-border p-4 lg:p-5 flex items-start justify-between gap-4 flex-wrap">
        <div className="space-y-1.5 min-w-0">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            <BookOpen className="size-4 text-accent-foreground" />
            Academic research
            <Badge variant="secondary">Auto research</Badge>
          </div>
          <h2 className="text-lg font-semibold tracking-tight">Auto research workflow</h2>
          <p className="text-sm text-muted-foreground max-w-3xl">
            Research question to literature intake to screening matrix to synthesis to integrity gate.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {!projectQuestion && (
            <Button size="sm" variant="secondary" onClick={onEditQuestion}>
              <Edit2 className="size-3.5" />
              Set research question
            </Button>
          )}
          <Button
            size="sm"
            onClick={onStartWorkflow}
            disabled={!canAct || !projectQuestion || researchActionBusy !== null}
          >
            <Activity className="size-3.5" />
            {researchActionBusy === 'start-workflow' ? 'Starting...' : 'Start auto research'}
          </Button>
          <Button size="sm" variant="outline" asChild>
            <Link to={arxivSourcePresetHref(project.id)}>
              <Plus className="size-3.5" />
              Add arXiv source
            </Link>
          </Button>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(280px,0.85fr)] p-4 lg:p-5">
        <div className="space-y-4 min-w-0">
          <div className="grid gap-3 md:grid-cols-5">
            {stageRows.map(stage => (
              <div key={stage.key} className={`rounded-md border p-3 min-h-[148px] ${stageToneClass(stage.status)}`}>
                <div className="flex items-start justify-between gap-2">
                  <div className="h-8 w-8 rounded-md bg-background border border-border flex items-center justify-center text-accent-foreground">
                    {stage.icon}
                  </div>
                  <Badge variant={stageBadgeVariant(stage.status)}>{stage.badge}</Badge>
                </div>
                <p className="mt-3 text-sm font-semibold">{stage.label}</p>
                <p className="mt-1 text-xs text-muted-foreground line-clamp-3">{stage.meta}</p>
              </div>
            ))}
          </div>

          <div className="rounded-md border border-border p-4">
            <div className="flex items-start justify-between gap-3 flex-wrap">
              <div className="space-y-1">
                <h3 className="text-sm font-semibold">Next research action</h3>
                <p className="text-sm text-muted-foreground">{nextAction}</p>
              </div>
              {activeWorkflow ? (
                <StatusBadge status={activeWorkflow.status} />
              ) : (
                <Badge variant="muted">No workflow</Badge>
              )}
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              <Button
                size="sm"
                variant={profileApproved && !syncNeeded ? 'outline' : 'secondary'}
                onClick={onPrepareProfile}
                disabled={!canAct || !projectQuestion || researchActionBusy !== null}
              >
                <CheckCircle className="size-3.5" />
                {researchActionBusy === 'prepare-profile'
                  ? 'Approving...'
                  : profileApproved && !syncNeeded
                    ? 'Profile approved'
                    : 'Approve profile'}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={onRebuildMatrix}
                disabled={!canAct || researchActionBusy !== null}
              >
                <RefreshCw className="size-3.5" />
                {researchActionBusy === 'rebuild-matrix' ? 'Rebuilding...' : 'Rebuild matrix'}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={onRunIntegrity}
                disabled={!canAct || !activeWorkflow || researchActionBusy !== null}
              >
                <CheckCircle className="size-3.5" />
                {researchActionBusy === 'run-integrity' ? 'Checking...' : 'Run integrity'}
              </Button>
              <Button size="sm" variant="outline" asChild>
                <Link to={academicGraphHref(project.id)}>
                  <Network className="size-3.5" />
                  Citation graph
                </Link>
              </Button>
              <Button size="sm" variant="outline" asChild>
                <Link to={sourceHref}>
                  <Search className="size-3.5" />
                  Review corpus
                </Link>
              </Button>
            </div>
          </div>

          <div className="rounded-md border border-border p-4">
            <div className="flex items-center justify-between gap-3 mb-3">
              <h3 className="text-sm font-semibold">Literature matrix preview</h3>
              <Badge variant="muted">{literatureMatrix.length} papers</Badge>
            </div>
            {literatureMatrix.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No included or maybe papers are in the matrix yet. Review source recommendations or rebuild after adding sources.
              </p>
            ) : (
              <div className="space-y-2">
                {literatureMatrix.slice(0, 4).map(row => (
                  <div key={row.corpus_item_id} className="flex items-start justify-between gap-3 min-w-0">
                    <div className="min-w-0">
                      <p className="text-sm font-medium truncate">{row.title ?? row.object_id ?? row.corpus_item_id}</p>
                      <p className="text-xs text-muted-foreground truncate">
                        {row.academic?.venue ?? row.academic?.arxiv_id ?? row.summary ?? 'Project corpus item'}
                      </p>
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <Badge variant={row.triage_status === 'included' ? 'success' : 'outline'}>{row.triage_status}</Badge>
                      <Badge variant="muted">{row.evidence_count + row.annotation_count} signals</Badge>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="space-y-3 min-w-0">
          <div className="rounded-md border border-border p-4">
            <div className="flex items-center justify-between gap-2 mb-3">
              <h3 className="text-sm font-semibold">Research profile</h3>
              <StatusBadge status={researchProfile?.status ?? 'not_started'} />
            </div>
            <dl className="space-y-2 text-sm">
              <div>
                <dt className="text-xs text-muted-foreground uppercase tracking-wide">Question</dt>
                <dd className="mt-1 line-clamp-3">{researchProfile?.research_question ?? project.current_focus ?? 'Not set'}</dd>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <dt className="text-xs text-muted-foreground uppercase tracking-wide">Output</dt>
                  <dd className="mt-1">{researchProfile?.output_type ?? 'paper'}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground uppercase tracking-wide">Mode</dt>
                  <dd className="mt-1">{activeWorkflow?.mode ?? 'agent_assisted'}</dd>
                </div>
              </div>
              {syncNeeded && (
                <div className="rounded-md border border-warning/35 bg-warning/5 p-2 text-xs text-warning">
                  Project question changed after profile approval.
                </div>
              )}
            </dl>
          </div>

          <div className="rounded-md border border-border p-4">
            <div className="flex items-center justify-between gap-2 mb-3">
              <h3 className="text-sm font-semibold">Workflow state</h3>
              <Badge variant="outline">{researchWorkflows.length} total</Badge>
            </div>
            <div className="grid grid-cols-2 gap-2 text-sm">
              <div className="rounded-md bg-muted/30 p-2">
                <p className="text-xs text-muted-foreground uppercase tracking-wide">Current stage</p>
                <p className="mt-1 font-medium truncate">{activeWorkflow?.current_stage ?? (setupRecorded ? 'research_profile' : 'Not started')}</p>
              </div>
              <div className="rounded-md bg-muted/30 p-2">
                <p className="text-xs text-muted-foreground uppercase tracking-wide">Checkpoints</p>
                <p className="mt-1 font-medium">{pendingCheckpoints.length} pending</p>
              </div>
              <div className="rounded-md bg-muted/30 p-2">
                <p className="text-xs text-muted-foreground uppercase tracking-wide">Evidence</p>
                <p className="mt-1 font-medium">{evidenceSignalCount} signals</p>
              </div>
              <div className="rounded-md bg-muted/30 p-2">
                <p className="text-xs text-muted-foreground uppercase tracking-wide">Criteria</p>
                <p className="mt-1 font-medium">{criteriaReady ? 'Set' : 'Open'}</p>
              </div>
            </div>
          </div>

          <div className="rounded-md border border-border p-4">
            <h3 className="text-sm font-semibold mb-3">Permission boundary</h3>
            <div className="space-y-2 text-xs text-muted-foreground">
              <p>Uses this project's research profile, source bindings, corpus, workflow artifacts, and checkpoints.</p>
              <p>Reader annotations link back to Library; this page does not create or delete annotations.</p>
              <p>Integrity checks read visible project claims and evidence, then write a project artifact and checkpoint.</p>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
