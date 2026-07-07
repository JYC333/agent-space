import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { Archive, ArrowLeft, Bot, CheckCircle2, Code2, Loader2, Pause, Play, Plus, RefreshCw, ShieldCheck, TestTube2 } from 'lucide-react'
import { agentsApi, intakeApi, projectsApi } from '../../api/client'
import { Badge, StatusBadge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Card, CardHeader, CardTitle } from '../../components/ui/card'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../../components/ui/dialog'
import { EmptyState } from '../../components/ui/empty-state'
import { Label } from '../../components/ui/label'
import { Select } from '../../components/ui/select'
import { Skeleton } from '../../components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../components/ui/tabs'
import { Textarea } from '../../components/ui/textarea'
import { SpaceLink as Link } from '../../core/spaceNav'
import { useSpace } from '../../contexts/SpaceContext'
import { errMsg, isNotFoundError } from '../../lib/utils'
import type {
  AgentOut,
  CustomSourceHandlerRun,
  CustomSourceHandlerSummary,
  CustomSourceHandlerVersion,
  ExtractedEvidence,
  ExtractionJob,
  IntakeItem,
  Project,
  SourceConnection,
  SourcePolicyEnvelope,
  SourcePostProcessingActions,
  SourcePostProcessingBacklog,
  SourcePostProcessingContentSource,
  SourcePostProcessingDeepAnalysisContentSource,
  SourcePostProcessingDeepAnalysisOutput,
  SourcePostProcessingDecisionReviewStatus,
  SourcePostProcessingItemDecision,
  SourcePostProcessingItemRelevance,
  SourcePostProcessingInputConfig,
  SourcePostProcessingRetrievalDomain,
  SourcePostProcessingRetrievalMode,
  SourcePostProcessingRule,
  SourcePostProcessingRuleCreate,
  SourcePostProcessingRuleUpdate,
  SourcePostProcessingRun,
  SourcePostProcessingStrategy,
  SourcePostProcessingTriggerType,
  SourceRecipeDryRunResult,
  SourceRecipeVersion,
  SourceRunSummary,
} from '../../types/api'
import {
  emptyScheduleFormValue,
  FREQUENCIES,
  fmt,
  isScheduleFormComplete,
  scheduleFormValueFromConnection,
  scheduleRuleFromForm,
  short,
  type ScheduleFormValue,
} from './intakePageModel'
import { ScheduleRuleFields } from './IntakePageSections'

const DEFAULT_FIXTURE = '<html><body><article><a href="/item">Title</a><p>Excerpt text.</p></article></body></html>'
const BROWSER_TZ = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
const POST_PROCESSING_ACTIONS: Array<{ key: keyof SourcePostProcessingActions; label: string }> = [
  { key: 'batch_digest', label: 'Batch digest' },
  { key: 'per_item_summary', label: 'Per-item summaries' },
  { key: 'extract_evidence', label: 'Extract evidence' },
  { key: 'create_proposals', label: 'Create proposals' },
  { key: 'mark_items', label: 'Mark relevance' },
]

type SourceDetailTab = 'overview' | 'plan' | 'preview' | 'items' | 'evidence' | 'runs' | 'post-processing' | 'advanced'

type PostProcessingOperation = {
  kind: 'run' | 'drain'
  ruleId: string
  ruleName: string
  status: 'running' | 'succeeded' | 'failed'
  message: string
  startedAt: string
  updatedAt: string
}

type PostProcessingFormState = {
  editingRuleId: string | null
  name: string
  agentId: string
  projectId: string
  triggerType: SourcePostProcessingTriggerType
  cron: string
  minNewItems: string
  cooldownSeconds: string
  window: SourcePostProcessingInputConfig['window']
  itemLimit: string
  maxBatchesPerEvent: string
  processingStrategy: SourcePostProcessingStrategy
  contentSource: SourcePostProcessingContentSource
  includeEvidence: boolean
  retrievalDomains: SourcePostProcessingRetrievalDomain[]
  retrievalQuery: string
  retrievalMaxResults: string
  retrievalMode: SourcePostProcessingRetrievalMode
  candidatePrefilterEnabled: boolean
  candidatePrefilterMode: SourcePostProcessingRetrievalMode
  candidatePrefilterMaxCandidates: string
  candidatePrefilterMinScore: string
  deepAnalysisEnabled: boolean
  deepAnalysisIncludeMaybe: boolean
  deepAnalysisMinConfidence: string
  deepAnalysisMaxCandidates: string
  deepAnalysisContentSource: SourcePostProcessingDeepAnalysisContentSource
  deepAnalysisOutput: SourcePostProcessingDeepAnalysisOutput
  actions: SourcePostProcessingActions
  relevanceEnabled: boolean
  relevanceObjective: string
  relevanceIncludeCriteria: string
  relevanceExcludeCriteria: string
}

function defaultPostProcessingForm(): PostProcessingFormState {
  return {
    editingRuleId: null,
    name: '',
    agentId: '',
    projectId: '',
    triggerType: 'items_materialized',
    cron: '0 9 * * *',
    minNewItems: '1',
    cooldownSeconds: '900',
    window: 'new_since_last_success',
    itemLimit: '10',
    maxBatchesPerEvent: '10',
    processingStrategy: 'batch_digest',
    contentSource: 'excerpt_only',
    includeEvidence: true,
    retrievalDomains: [],
    retrievalQuery: '',
    retrievalMaxResults: '6',
    retrievalMode: 'hybrid',
    candidatePrefilterEnabled: false,
    candidatePrefilterMode: 'hybrid',
    candidatePrefilterMaxCandidates: '20',
    candidatePrefilterMinScore: '',
    deepAnalysisEnabled: false,
    deepAnalysisIncludeMaybe: false,
    deepAnalysisMinConfidence: '0.7',
    deepAnalysisMaxCandidates: '5',
    deepAnalysisContentSource: 'prefer_extracted_text',
    deepAnalysisOutput: 'deep_report',
    actions: {
      batch_digest: true,
      per_item_summary: false,
      extract_evidence: false,
      create_proposals: false,
      mark_items: false,
    },
    relevanceEnabled: false,
    relevanceObjective: '',
    relevanceIncludeCriteria: '',
    relevanceExcludeCriteria: '',
  }
}

function linesToCriteria(value: string): string[] {
  return value
    .split('\n')
    .map(line => line.trim())
    .filter(Boolean)
}

export default function SourceConnectionDetailPage() {
  const { connectionId = '' } = useParams()
  const { activeSpaceId } = useSpace()
  const [connection, setConnection] = useState<SourceConnection | null>(null)
  const [summary, setSummary] = useState<CustomSourceHandlerSummary | null>(null)
  const [handlerVersions, setHandlerVersions] = useState<CustomSourceHandlerVersion[]>([])
  const [handlerRuns, setHandlerRuns] = useState<CustomSourceHandlerRun[]>([])
  const [recipeVersions, setRecipeVersions] = useState<SourceRecipeVersion[]>([])
  const [sourceRuns, setSourceRuns] = useState<SourceRunSummary[]>([])
  const [agents, setAgents] = useState<AgentOut[]>([])
  const [projects, setProjects] = useState<Project[]>([])
  const [postProcessingRules, setPostProcessingRules] = useState<SourcePostProcessingRule[]>([])
  const [postProcessingRuns, setPostProcessingRuns] = useState<SourcePostProcessingRun[]>([])
  const [postProcessingBacklog, setPostProcessingBacklog] = useState<SourcePostProcessingBacklog | null>(null)
  const [postProcessingDecisions, setPostProcessingDecisions] = useState<SourcePostProcessingItemDecision[]>([])
  const [items, setItems] = useState<IntakeItem[]>([])
  const [evidence, setEvidence] = useState<ExtractedEvidence[]>([])
  const [jobs, setJobs] = useState<ExtractionJob[]>([])
  const [fixtureHtml, setFixtureHtml] = useState(DEFAULT_FIXTURE)
  const [scheduleFrequency, setScheduleFrequency] = useState<SourceConnection['fetch_frequency']>('manual')
  const [scheduleForm, setScheduleForm] = useState<ScheduleFormValue>(() => emptyScheduleFormValue())
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<SourceDetailTab>('overview')
  const [postProcessingOperation, setPostProcessingOperation] = useState<PostProcessingOperation | null>(null)
  const [postProcessingReadModelRefreshedAt, setPostProcessingReadModelRefreshedAt] = useState<string | null>(null)

  const isCustomSource = connection?.handler_kind === 'generated_custom'
  const isRecipeSource = connection?.handler_kind === 'recipe'
  const activeRecipe = useMemo(
    () => recipeVersions.find(version => version.id === connection?.active_recipe_version_id)
      ?? recipeVersions.find(version => version.status === 'active')
      ?? recipeVersions[0]
      ?? null,
    [connection?.active_recipe_version_id, recipeVersions],
  )
  const latestRecipePreview = useMemo(() => {
    const activePreview = activeRecipe?.test_result_json as SourceRecipeDryRunResult | Record<string, unknown> | null | undefined
    if (activePreview) return activePreview as SourceRecipeDryRunResult
    return recipeVersions.find(version => version.test_result_json)?.test_result_json as SourceRecipeDryRunResult | null ?? null
  }, [activeRecipe, recipeVersions])
  const latestDraft = useMemo(
    () => handlerVersions.find(version => version.status === 'draft' || version.status === 'test_failed') ?? null,
    [handlerVersions],
  )

  const load = useCallback(async (options: { showSkeleton?: boolean } = {}) => {
    const showSkeleton = Boolean(options.showSkeleton)
    if (!activeSpaceId || !connectionId) {
      setConnection(null)
      setScheduleFrequency('manual')
      setScheduleForm(emptyScheduleFormValue())
      setAgents([])
      setProjects([])
      setPostProcessingRules([])
      setPostProcessingRuns([])
      setPostProcessingBacklog(null)
      setPostProcessingDecisions([])
      setLoading(false)
      return
    }
    if (showSkeleton) setLoading(true)
    try {
      const row = await intakeApi.getConnection(connectionId)
      setConnection(row)
      setScheduleFrequency(row.fetch_frequency)
      setScheduleForm(scheduleFormValueFromConnection(row))
      const [itemPage, jobPage, evidencePage, runPage, ruleRows, postRunPage, backlog, decisionsPage, agentRows, projectPage] = await Promise.all([
        intakeApi.items({ connection_id: connectionId, limit: 20 }),
        intakeApi.jobs({ connection_id: connectionId, limit: 20 }),
        intakeApi.evidence({ connection_id: connectionId, limit: 20 }),
        intakeApi.sourceRuns(connectionId, { limit: 30 }),
        intakeApi.postProcessingRules(connectionId),
        intakeApi.postProcessingRuns(connectionId, { limit: 20 }),
        intakeApi.postProcessingBacklog(connectionId),
        intakeApi.postProcessingConnectionDecisions(connectionId, { limit: 20 }),
        agentsApi.list({ status: 'active,disabled,inactive' }),
        projectsApi.list({ status: 'active' }),
      ])
      setItems(itemPage.items)
      setJobs(jobPage.items)
      setEvidence(evidencePage.items)
      setSourceRuns(runPage.items)
      setPostProcessingRules(ruleRows)
      setPostProcessingRuns(postRunPage.items)
      setPostProcessingBacklog(backlog)
      setPostProcessingDecisions(decisionsPage.items)
      setAgents(agentRows.filter(agent => agent.agent_kind !== 'system_assistant'))
      setProjects(projectPage.items)

      if (row.handler_kind === 'generated_custom') {
        const [handlerSummary, versionPage, rawRunPage] = await Promise.all([
          intakeApi.customSourceSummary(connectionId),
          intakeApi.customSourceVersions(connectionId, { limit: 20 }),
          intakeApi.customSourceRuns(connectionId, { limit: 20 }),
        ])
        setSummary(handlerSummary)
        setHandlerVersions(versionPage.items)
        setHandlerRuns(rawRunPage.items)
      } else {
        setSummary(null)
        setHandlerVersions([])
        setHandlerRuns([])
      }

      if (row.handler_kind === 'recipe') {
        const versionPage = await intakeApi.sourceRecipeVersions(connectionId, { limit: 20 })
        setRecipeVersions(versionPage.items)
      } else {
        setRecipeVersions([])
      }
    } catch (error) {
      if (!isNotFoundError(error)) toast.error(errMsg(error))
      if (showSkeleton) {
        setConnection(null)
        setScheduleFrequency('manual')
        setScheduleForm(emptyScheduleFormValue())
        setAgents([])
        setProjects([])
        setPostProcessingRules([])
        setPostProcessingRuns([])
        setPostProcessingBacklog(null)
        setPostProcessingDecisions([])
      }
    } finally {
      setLoading(false)
    }
  }, [activeSpaceId, connectionId])

  useEffect(() => {
    setActiveTab('overview')
    void load({ showSkeleton: true })
  }, [load])

  function upsertPostProcessingRule(rule: SourcePostProcessingRule) {
    setPostProcessingRules(current => {
      const existingIndex = current.findIndex(item => item.id === rule.id)
      if (existingIndex < 0) return [rule, ...current]
      return current.map(item => item.id === rule.id ? rule : item)
    })
  }

  function upsertPostProcessingDecision(decision: SourcePostProcessingItemDecision) {
    setPostProcessingDecisions(current => {
      const existingIndex = current.findIndex(item => item.id === decision.id)
      if (existingIndex < 0) return [decision, ...current].slice(0, 20)
      return current.map(item => item.id === decision.id ? decision : item)
    })
  }

  const refreshPostProcessingReadModels = useCallback(async (options: { includeRuns?: boolean; includeRules?: boolean } = {}) => {
    const currentConnectionId = connection?.id
    if (!currentConnectionId) return
    const [backlog, decisionsPage, runPage, ruleRows] = await Promise.all([
      intakeApi.postProcessingBacklog(currentConnectionId).catch(() => null),
      intakeApi.postProcessingConnectionDecisions(currentConnectionId, { limit: 20 }).catch(() => null),
      options.includeRuns ? intakeApi.postProcessingRuns(currentConnectionId, { limit: 20 }).catch(() => null) : Promise.resolve(null),
      options.includeRules ? intakeApi.postProcessingRules(currentConnectionId).catch(() => null) : Promise.resolve(null),
    ])
    if (backlog) setPostProcessingBacklog(backlog)
    if (decisionsPage) setPostProcessingDecisions(decisionsPage.items)
    if (runPage) setPostProcessingRuns(runPage.items)
    if (ruleRows) setPostProcessingRules(ruleRows)
    setPostProcessingReadModelRefreshedAt(new Date().toISOString())
  }, [connection?.id])

  useEffect(() => {
    if (!connection || postProcessingOperation?.status !== 'running') return
    let cancelled = false
    const refresh = async () => {
      if (cancelled) return
      await refreshPostProcessingReadModels({ includeRuns: true, includeRules: true })
    }
    void refresh()
    const timer = window.setInterval(() => { void refresh() }, 2000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [connection?.id, postProcessingOperation?.status, refreshPostProcessingReadModels])

  useEffect(() => {
    if (!postProcessingOperation || postProcessingOperation.status !== 'running') return
    const latestRun = postProcessingRuns.find(run => run.rule_id === postProcessingOperation.ruleId)
    if (!latestRun || latestRun.status === 'queued' || latestRun.status === 'running') return
    setPostProcessingOperation(current => {
      if (!current || current.ruleId !== latestRun.rule_id || current.status !== 'running') return current
      return {
        ...current,
        status: operationStatusFromRun(latestRun.status),
        message: operationMessageFromRun(latestRun.status),
        updatedAt: new Date().toISOString(),
      }
    })
  }, [postProcessingRuns, postProcessingOperation])

  async function generateHandler() {
    if (!connection) return
    setBusy('generate')
    try {
      const version = await intakeApi.generateCustomSourceHandler(connection.id)
      toast.success(`Handler v${version.version_number} generated`)
      await load()
    } catch (error) {
      toast.error(errMsg(error))
    } finally {
      setBusy(null)
    }
  }

  async function testHandler(version: CustomSourceHandlerVersion) {
    if (!connection) return
    setBusy(`test:${version.id}`)
    try {
      const outcome = await intakeApi.testCustomSourceHandler(connection.id, {
        handler_version_id: version.id,
        fixture_html: fixtureHtml,
      })
      toast.success(`Test ${outcome.run.status}`)
      await load()
    } catch (error) {
      toast.error(errMsg(error))
    } finally {
      setBusy(null)
    }
  }

  async function activateHandler(version: CustomSourceHandlerVersion) {
    if (!connection) return
    const scheduleRule = scheduleRuleFromForm(scheduleFrequency, scheduleForm)
    if (scheduleRule === undefined) {
      toast.error('Complete the schedule before activation')
      return
    }
    setBusy(`activate:${version.id}`)
    try {
      const result = await intakeApi.activateCustomSourceHandler(connection.id, {
        handler_version_id: version.id,
        schedule_rule: scheduleRule,
      })
      if (result.status === 'pending_approval') {
        toast.success(`Approval proposal created: ${short(result.proposal_id)}`)
      } else {
        toast.success(`Handler v${result.handler_version.version_number} activated`)
      }
      await load()
    } catch (error) {
      toast.error(errMsg(error))
    } finally {
      setBusy(null)
    }
  }

  async function runSourceNow() {
    if (!connection) return
    setBusy('source:scan')
    try {
      const job = await intakeApi.scanConnection(connection.id)
      toast.success('Scan queued')
      const result = await intakeApi.runJob(job.id)
      toast.success(`Scan ${result.status}: ${result.items_created ?? 0} new`)
      await load()
    } catch (error) {
      toast.error(errMsg(error))
    } finally {
      setBusy(null)
    }
  }

  async function saveNextRun() {
    if (!connection) return
    const scheduleRule = scheduleRuleFromForm(scheduleFrequency, scheduleForm)
    if (scheduleRule === undefined) {
      toast.error('Complete the schedule')
      return
    }
    setBusy('source:schedule')
    try {
      const row = await intakeApi.updateConnection(connection.id, {
        fetch_frequency: scheduleFrequency,
        schedule_rule: scheduleRule,
      })
      setConnection(row)
      setScheduleFrequency(row.fetch_frequency)
      setScheduleForm(scheduleFormValueFromConnection(row))
      toast.success('Schedule updated')
    } catch (error) {
      toast.error(errMsg(error))
    } finally {
      setBusy(null)
    }
  }

  async function allowExternalModelProcessing() {
    if (!connection) return
    setBusy('source:egress')
    try {
      const row = await intakeApi.updateConnection(connection.id, {
        consent: {
          ...connection.consent_json,
          allow_external_model_egress: true,
        },
        policy: {
          ...connection.policy_json,
          source_egress_class: 'external_provider_allowed',
        },
      })
      setConnection(row)
      toast.success('External model processing enabled for this source')
    } catch (error) {
      toast.error(errMsg(error))
    } finally {
      setBusy(null)
    }
  }

  async function createPostProcessingRule(body: SourcePostProcessingRuleCreate) {
    if (!connection) return
    setBusy('post-processing:create')
    try {
      const rule = await intakeApi.createPostProcessingRule(connection.id, body)
      upsertPostProcessingRule(rule)
      refreshPostProcessingReadModels()
      toast.success('Post-processing rule created')
    } catch (error) {
      toast.error(errMsg(error))
    } finally {
      setBusy(null)
    }
  }

  async function updatePostProcessingRule(rule: SourcePostProcessingRule, body: SourcePostProcessingRuleUpdate, ok: string) {
    if (!connection) return
    setBusy(`post-processing:update:${rule.id}`)
    try {
      const updated = await intakeApi.updatePostProcessingRule(connection.id, rule.id, body)
      upsertPostProcessingRule(updated)
      refreshPostProcessingReadModels()
      toast.success(ok)
    } catch (error) {
      toast.error(errMsg(error))
    } finally {
      setBusy(null)
    }
  }

  async function runPostProcessingRule(rule: SourcePostProcessingRule) {
    if (!connection) return
    setBusy(`post-processing:run:${rule.id}`)
    setPostProcessingOperation({
      kind: 'run',
      ruleId: rule.id,
      ruleName: rule.name,
      status: 'running',
      message: 'Running the next batch for this rule.',
      startedAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    })
    try {
      const run = await intakeApi.runPostProcessingRule(connection.id, rule.id)
      setPostProcessingRuns(current => [run, ...current.filter(item => item.id !== run.id)].slice(0, 20))
      void intakeApi.postProcessingRules(connection.id)
        .then(setPostProcessingRules)
        .catch(() => undefined)
      void refreshPostProcessingReadModels({ includeRuns: true, includeRules: true })
      setPostProcessingOperation(current => ({
        kind: 'run',
        ruleId: rule.id,
        ruleName: rule.name,
        status: operationStatusFromRun(run.status),
        message: operationMessageFromRun(run.status),
        startedAt: current?.ruleId === rule.id ? current.startedAt : new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      }))
      toast.success(`Post-processing ${run.status}`)
    } catch (error) {
      setPostProcessingOperation(current => ({
        kind: 'run',
        ruleId: rule.id,
        ruleName: rule.name,
        status: 'failed',
        message: errMsg(error),
        startedAt: current?.ruleId === rule.id ? current.startedAt : new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      }))
      toast.error(errMsg(error))
    } finally {
      setBusy(null)
    }
  }

  async function drainPostProcessingRule(rule: SourcePostProcessingRule) {
    if (!connection) return
    setBusy(`post-processing:drain:${rule.id}`)
    setPostProcessingOperation({
      kind: 'drain',
      ruleId: rule.id,
      ruleName: rule.name,
      status: 'running',
      message: 'Draining queued batches until the backlog is empty, capped, or a run fails.',
      startedAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    })
    try {
      const result = await intakeApi.drainPostProcessingRule(connection.id, rule.id)
      setPostProcessingRuns(current => [
        ...result.runs,
        ...current.filter(item => !result.runs.some(run => run.id === item.id)),
      ].slice(0, 20))
      void intakeApi.postProcessingRules(connection.id)
        .then(setPostProcessingRules)
        .catch(() => undefined)
      void refreshPostProcessingReadModels({ includeRuns: true, includeRules: true })
      const failedRun = result.runs.find(run => run.status === 'failed')
      setPostProcessingOperation(current => ({
        kind: 'drain',
        ruleId: rule.id,
        ruleName: rule.name,
        status: failedRun ? 'failed' : 'succeeded',
        message: failedRun
          ? 'Drain stopped after a failed run. Check Recent Runs for the error.'
          : `Drain ${result.stopped_reason}; ${result.pending_item_count} pending.`,
        startedAt: current?.ruleId === rule.id ? current.startedAt : new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      }))
      toast.success(`Drain ${result.stopped_reason}; ${result.pending_item_count} pending`)
    } catch (error) {
      setPostProcessingOperation(current => ({
        kind: 'drain',
        ruleId: rule.id,
        ruleName: rule.name,
        status: 'failed',
        message: errMsg(error),
        startedAt: current?.ruleId === rule.id ? current.startedAt : new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      }))
      toast.error(errMsg(error))
    } finally {
      setBusy(null)
    }
  }

  async function postProcessingDecisionAction(decision: SourcePostProcessingItemDecision, action: string) {
    setBusy(`post-processing:decision:${decision.id}:${action}`)
    try {
      const result = await intakeApi.postProcessingDecisionAction(decision.id, action)
      upsertPostProcessingDecision(result.decision)
      refreshPostProcessingReadModels()
      if (result.proposal_id) toast.success(`Proposal created: ${short(result.proposal_id)}`)
      else if (result.job_ids?.length) toast.success(`${result.job_ids.length} extraction job${result.job_ids.length === 1 ? '' : 's'} queued`)
      else if (result.run) toast.success(action === 'deep_analysis' ? `Deep analysis ${result.run.status}` : `Rerun ${result.run.status}`)
      else toast.success('Decision updated')
    } catch (error) {
      toast.error(errMsg(error))
    } finally {
      setBusy(null)
    }
  }

  if (loading) {
    return (
      <div className="p-6 space-y-4">
        <Skeleton className="h-6 w-32" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  if (!connection) {
    return (
      <div className="p-6 space-y-4">
        <Button variant="ghost" size="sm" asChild>
          <Link to="/intake"><ArrowLeft className="size-4" />Intake</Link>
        </Button>
        <EmptyState title="Source not found" description="This source does not exist or is not accessible." />
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-2 min-w-0">
          <Button variant="ghost" size="sm" asChild>
            <Link to="/intake"><ArrowLeft className="size-4" />Intake</Link>
          </Button>
          <div>
            <h1 className="text-xl font-semibold truncate">{connection.name}</h1>
            <p className="text-sm text-muted-foreground break-all">{connection.endpoint_url ?? connection.id}</p>
          </div>
          <div className="flex flex-wrap gap-1.5">
            <StatusBadge status={connection.status} />
            <Badge variant="outline">{sourceKindLabel(connection, activeRecipe)}</Badge>
            <Badge variant="muted">{connection.fetch_frequency}</Badge>
            <Badge variant="muted">{connection.capture_policy}</Badge>
            {connection.repair_status && <Badge variant="muted">{connection.repair_status}</Badge>}
          </div>
        </div>
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="secondary" onClick={runSourceNow} disabled={!canRunConnectionNow(connection) || Boolean(busy)}>
            <Play className="size-4" />
            Run now
          </Button>
          <Button variant="outline" onClick={() => { void load() }} disabled={loading || Boolean(busy)}>
            <RefreshCw className="size-4" />
            Refresh
          </Button>
        </div>
      </div>

      <Tabs value={activeTab} onValueChange={value => setActiveTab(value as SourceDetailTab)} className="space-y-4">
        <TabsList className="flex h-auto flex-wrap justify-start">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="plan">Plan</TabsTrigger>
          <TabsTrigger value="preview">Preview</TabsTrigger>
          <TabsTrigger value="items">Items</TabsTrigger>
          <TabsTrigger value="evidence">Evidence</TabsTrigger>
          <TabsTrigger value="runs">Runs</TabsTrigger>
          <TabsTrigger value="post-processing">Post-processing</TabsTrigger>
          <TabsTrigger value="advanced">Advanced</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-4">
          <OverviewPanel
            connection={connection}
            activeRecipe={activeRecipe}
            activeHandler={summary?.active_handler_version ?? null}
            scheduleFrequency={scheduleFrequency}
            scheduleForm={scheduleForm}
            busy={busy}
            onScheduleFrequencyChange={value => {
              setScheduleFrequency(value)
              setScheduleForm(emptyScheduleFormValue())
            }}
            onScheduleFormChange={setScheduleForm}
            onSaveNextRun={saveNextRun}
          />
        </TabsContent>

        <TabsContent value="plan" className="space-y-4">
          <PlanPanel connection={connection} activeRecipe={activeRecipe} activeHandler={summary?.active_handler_version ?? null} />
        </TabsContent>

        <TabsContent value="preview" className="space-y-4">
          <PreviewPanel connection={connection} recipePreview={latestRecipePreview} latestHandlerDraft={latestDraft} />
        </TabsContent>

        <TabsContent value="items" className="space-y-4">
          <SourceItemsTable items={items} />
        </TabsContent>

        <TabsContent value="evidence" className="space-y-4">
          <SourceEvidenceTable evidence={evidence} />
        </TabsContent>

        <TabsContent value="runs" className="space-y-4">
          <SourceRunsTable runs={sourceRuns} />
        </TabsContent>

        <TabsContent value="post-processing" className="space-y-4">
          <PostProcessingPanel
            connection={connection}
            agents={agents}
            projects={projects}
            rules={postProcessingRules}
            runs={postProcessingRuns}
            backlog={postProcessingBacklog}
            decisions={postProcessingDecisions}
            busy={busy}
            operation={postProcessingOperation}
            lastRefreshAt={postProcessingReadModelRefreshedAt}
            onCreate={createPostProcessingRule}
            onUpdate={updatePostProcessingRule}
            onRun={runPostProcessingRule}
            onDrain={drainPostProcessingRule}
            onDecisionAction={postProcessingDecisionAction}
            onAllowExternalModelProcessing={allowExternalModelProcessing}
          />
        </TabsContent>

        <TabsContent value="advanced" className="space-y-4">
          <AdvancedPanel
            connection={connection}
            isCustomSource={isCustomSource}
            isRecipeSource={isRecipeSource}
            summary={summary}
            handlerVersions={handlerVersions}
            handlerRuns={handlerRuns}
            recipeVersions={recipeVersions}
            jobs={jobs}
            fixtureHtml={fixtureHtml}
            setFixtureHtml={setFixtureHtml}
            busy={busy}
            latestDraft={latestDraft}
            onGenerate={generateHandler}
            onTest={testHandler}
            onActivate={activateHandler}
          />
        </TabsContent>
      </Tabs>
    </div>
  )
}

function OverviewPanel(props: {
  connection: SourceConnection
  activeRecipe: SourceRecipeVersion | null
  activeHandler: CustomSourceHandlerVersion | null
  scheduleFrequency: SourceConnection['fetch_frequency']
  scheduleForm: ScheduleFormValue
  busy: string | null
  onScheduleFrequencyChange: (value: SourceConnection['fetch_frequency']) => void
  onScheduleFormChange: (value: ScheduleFormValue) => void
  onSaveNextRun: () => void
}) {
  const implementationId = props.connection.handler_kind === 'recipe'
    ? (props.activeRecipe ? recipeVersionLabel(props.activeRecipe) : 'none')
    : props.connection.handler_kind === 'generated_custom'
      ? (props.activeHandler ? `handler v${props.activeHandler.version_number}` : 'none')
      : 'built-in'
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card className="space-y-3">
        <CardHeader>
          <CardTitle>Source</CardTitle>
        </CardHeader>
        <KeyValueGrid rows={[
          ['ID', props.connection.id],
          ['Owner', props.connection.owner_user_id],
          ['Implementation', sourceKindLabel(props.connection, props.activeRecipe)],
          ['Active version', implementationId],
          ['Trust', props.connection.trust_level],
        ]} />
      </Card>
      <Card className="space-y-3">
        <CardHeader>
          <CardTitle>Schedule</CardTitle>
        </CardHeader>
        <KeyValueGrid rows={[
          ['Status', props.connection.status],
          ['Last checked', fmt(props.connection.last_checked_at)],
          ['Next run', fmt(props.connection.next_check_at)],
          ['Capture', props.connection.capture_policy],
        ]} />
        <div className="space-y-3 border-t border-border pt-3">
          <div className="space-y-1.5">
            <Label>Frequency</Label>
            <Select
              options={FREQUENCIES}
              value={props.scheduleFrequency}
              onChange={value => props.onScheduleFrequencyChange(value as SourceConnection['fetch_frequency'])}
            />
          </div>
          <ScheduleRuleFields
            fetchFrequency={props.scheduleFrequency}
            value={props.scheduleForm}
            onChange={props.onScheduleFormChange}
          />
          <Button
            type="button"
            variant="secondary"
            onClick={props.onSaveNextRun}
            disabled={props.busy === 'source:schedule' || !isScheduleFormComplete(props.scheduleFrequency, props.scheduleForm)}
          >
            <CheckCircle2 className="size-4" />
            Save schedule
          </Button>
        </div>
      </Card>
      <Card className="space-y-3 lg:col-span-2">
        <CardHeader>
          <CardTitle>Policy</CardTitle>
        </CardHeader>
        <PolicySummary envelope={props.activeRecipe?.policy_envelope_json ?? props.activeHandler?.policy_envelope_json ?? null} />
      </Card>
    </div>
  )
}

function PlanPanel(props: {
  connection: SourceConnection
  activeRecipe: SourceRecipeVersion | null
  activeHandler: CustomSourceHandlerVersion | null
}) {
  if (props.connection.handler_kind === 'recipe') {
    if (!props.activeRecipe) return <EmptyState title="No active plan" description="Activate a version to see the source plan." />
    return <RecipePlanPanel version={props.activeRecipe} />
  }
  if (props.connection.handler_kind === 'generated_custom') {
    return (
      <Card className="space-y-3">
        <CardHeader>
          <CardTitle>Advanced Source Handler</CardTitle>
        </CardHeader>
        <p className="text-sm text-muted-foreground">
          This source uses the advanced handler fallback. Normal operation is visible in Runs and Items;
          handler versions, raw policy, logs, and artifacts are in Advanced.
        </p>
        {props.activeHandler && <HandlerVersionSummary version={props.activeHandler} />}
      </Card>
    )
  }
  return (
    <Card className="space-y-3">
      <CardHeader>
        <CardTitle>Built-In Source</CardTitle>
      </CardHeader>
      <p className="text-sm text-muted-foreground">
        This source uses the built-in connector path for scheduled scans and extraction.
      </p>
      <KeyValueGrid rows={[
        ['Endpoint', props.connection.endpoint_url ?? 'none'],
        ['Capture', props.connection.capture_policy],
        ['Frequency', props.connection.fetch_frequency],
      ]} />
    </Card>
  )
}

function RecipePlanPanel({ version }: { version: SourceRecipeVersion }) {
  const steps = Array.isArray(version.recipe_json.steps) ? version.recipe_json.steps : []
  return (
    <div className="space-y-4">
      <Card className="space-y-3">
        <CardHeader>
          <CardTitle>{recipePlanTitle(version)}</CardTitle>
        </CardHeader>
        <div className="flex flex-wrap gap-1.5">
          <Badge variant="outline">v{version.version_number}</Badge>
          <StatusBadge status={version.status} />
          {Object.entries(version.primitive_versions_json ?? {}).map(([name, primitiveVersion]) => (
            <Badge key={name} variant="muted">{primitiveLabel(name)} v{primitiveVersion}</Badge>
          ))}
        </div>
        <ol className="space-y-2 text-sm">
          {steps.map((step, index) => (
            <li key={`${String(step.type)}-${index}`} className="rounded-md border border-border bg-muted/20 p-3">
              <div className="font-medium">{index + 1}. {primitiveLabel(String(step.type))}</div>
              <p className="text-muted-foreground">{describeRecipeStep(step)}</p>
            </li>
          ))}
        </ol>
      </Card>
      <Card className="space-y-3">
        <CardHeader>
          <CardTitle>Output</CardTitle>
        </CardHeader>
        <KeyValueGrid rows={[
          ['Items variable', version.recipe_json.output.items_var],
          ['Created', fmt(version.created_at)],
          ['Activated', fmt(version.activated_at)],
        ]} />
      </Card>
    </div>
  )
}

function PreviewPanel(props: {
  connection: SourceConnection
  recipePreview: SourceRecipeDryRunResult | null
  latestHandlerDraft: CustomSourceHandlerVersion | null
}) {
  if (props.connection.handler_kind === 'recipe') {
    if (!props.recipePreview) return <EmptyState title="No preview yet" description="Run a preview before activation to store sample output." />
    return <RecipePreview preview={props.recipePreview} />
  }
  if (props.connection.handler_kind === 'generated_custom') {
    const draft = props.latestHandlerDraft
    const result = draft?.test_result_json
    if (!result) return <EmptyState title="No handler test yet" description="Run a fixture test in Advanced to capture preview diagnostics." />
    return <TestResultPanel title={`Latest fixture test v${draft.version_number}`} result={result} />
  }
  return <EmptyState title="No stored preview" description="Built-in source scans appear in Runs and Items after execution." />
}

function PostProcessingPanel(props: {
  connection: SourceConnection
  agents: AgentOut[]
  projects: Project[]
  rules: SourcePostProcessingRule[]
  runs: SourcePostProcessingRun[]
  backlog: SourcePostProcessingBacklog | null
  decisions: SourcePostProcessingItemDecision[]
  busy: string | null
  operation: PostProcessingOperation | null
  lastRefreshAt: string | null
  onCreate: (body: SourcePostProcessingRuleCreate) => Promise<void>
  onUpdate: (rule: SourcePostProcessingRule, body: SourcePostProcessingRuleUpdate, ok: string) => Promise<void>
  onRun: (rule: SourcePostProcessingRule) => Promise<void>
  onDrain: (rule: SourcePostProcessingRule) => Promise<void>
  onDecisionAction: (decision: SourcePostProcessingItemDecision, action: string) => Promise<void>
  onAllowExternalModelProcessing: () => Promise<void>
}) {
  const [form, setForm] = useState<PostProcessingFormState>(() => defaultPostProcessingForm())
  const agentName = (id: string) => props.agents.find(agent => agent.id === id)?.name ?? short(id)
  const projectName = (id: string | null) => (id ? props.projects.find(project => project.id === id)?.name ?? short(id) : null)

  function setAction(key: keyof SourcePostProcessingActions, value: boolean) {
    setForm(current => ({ ...current, actions: { ...current.actions, [key]: value } }))
  }

  function setRetrievalDomain(domain: SourcePostProcessingRetrievalDomain, enabled: boolean) {
    setForm(current => {
      const domains = enabled
        ? Array.from(new Set([...current.retrievalDomains, domain]))
        : current.retrievalDomains.filter(item => item !== domain)
      return { ...current, retrievalDomains: domains }
    })
  }

  function editRule(rule: SourcePostProcessingRule) {
    const input = rule.input_config_json
    const relevance = input.relevance_profile
    setForm({
      editingRuleId: rule.id,
      name: rule.name,
      agentId: rule.agent_id,
      projectId: rule.project_id ?? '',
      triggerType: rule.trigger_type,
      cron: rule.trigger_config_json.cron ?? '0 9 * * *',
      minNewItems: String(rule.trigger_config_json.min_new_items),
      cooldownSeconds: String(rule.trigger_config_json.cooldown_seconds),
      window: input.window,
      itemLimit: String(input.item_limit),
      maxBatchesPerEvent: String(input.max_batches_per_event ?? 10),
      processingStrategy: input.processing_strategy ?? 'batch_digest',
      contentSource: input.content_source ?? 'excerpt_only',
      includeEvidence: input.include_evidence,
      retrievalDomains: input.retrieval_context.enabled ? input.retrieval_context.domains : [],
      retrievalQuery: input.retrieval_context.query ?? '',
      retrievalMaxResults: String(input.retrieval_context.max_results_per_domain),
      retrievalMode: input.retrieval_context.mode,
      candidatePrefilterEnabled: input.candidate_prefilter?.enabled === true,
      candidatePrefilterMode: input.candidate_prefilter?.mode ?? 'hybrid',
      candidatePrefilterMaxCandidates: String(input.candidate_prefilter?.max_candidates ?? 20),
      candidatePrefilterMinScore: input.candidate_prefilter?.min_score === undefined ? '' : String(input.candidate_prefilter.min_score),
      deepAnalysisEnabled: input.deep_analysis?.enabled === true,
      deepAnalysisIncludeMaybe: input.deep_analysis?.trigger_relevance.includes('maybe') ?? false,
      deepAnalysisMinConfidence: String(input.deep_analysis?.min_confidence ?? 0.7),
      deepAnalysisMaxCandidates: String(input.deep_analysis?.max_candidates_per_run ?? 5),
      deepAnalysisContentSource: input.deep_analysis?.content_source ?? 'prefer_extracted_text',
      deepAnalysisOutput: input.deep_analysis?.output ?? 'deep_report',
      actions: rule.actions_json,
      relevanceEnabled: relevance?.enabled === true,
      relevanceObjective: relevance?.objective ?? '',
      relevanceIncludeCriteria: relevance?.include_criteria.join('\n') ?? '',
      relevanceExcludeCriteria: relevance?.exclude_criteria.join('\n') ?? '',
    })
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (!Object.values(form.actions).some(Boolean)) {
      toast.error('Select at least one action')
      return
    }
    if (form.triggerType === 'schedule' && !form.cron.trim()) {
      toast.error('Cron expression is required')
      return
    }
    const triggerConfig = {
      min_new_items: positiveInt(form.minNewItems, 1),
      cooldown_seconds: nonNegativeInt(form.cooldownSeconds, 900),
      timezone: BROWSER_TZ,
      skip_when_no_new_items: true,
      ...(form.triggerType === 'schedule' ? { cron: form.cron.trim() } : {}),
    }
    const relevanceObjective = form.relevanceObjective.trim()
    const relevanceInclude = linesToCriteria(form.relevanceIncludeCriteria)
    const relevanceExclude = linesToCriteria(form.relevanceExcludeCriteria)
    const retrievalDomains = selectedRetrievalDomains(form)
    if (form.relevanceEnabled && !relevanceObjective && relevanceInclude.length === 0) {
      toast.error('Relevance screening needs an objective or at least one include criterion')
      return
    }
    const body: SourcePostProcessingRuleCreate = {
      name: form.name.trim() || undefined,
      agent_id: form.agentId || undefined,
      project_id: form.projectId || undefined,
      trigger_type: form.triggerType,
      trigger_config_json: triggerConfig,
      input_config_json: {
        window: form.window,
        item_limit: positiveInt(form.itemLimit, 10),
        max_batches_per_event: positiveInt(form.maxBatchesPerEvent, 10),
        processing_strategy: form.processingStrategy,
        content_source: form.contentSource,
        include_excerpts: true,
        include_evidence: form.includeEvidence,
        timezone: BROWSER_TZ,
        retrieval_context: {
          enabled: retrievalDomains.length > 0,
          domains: retrievalDomains.length > 0 ? retrievalDomains : ['project'],
          ...(form.retrievalQuery.trim() ? { query: form.retrievalQuery.trim() } : {}),
          max_results_per_domain: positiveInt(form.retrievalMaxResults, 6),
          mode: form.retrievalMode,
        },
        candidate_prefilter: {
          enabled: form.candidatePrefilterEnabled,
          mode: form.candidatePrefilterMode,
          max_candidates: positiveInt(form.candidatePrefilterMaxCandidates, 20),
          ...(form.candidatePrefilterMinScore.trim()
            ? { min_score: decimalNumber(form.candidatePrefilterMinScore, 0) }
            : {}),
        },
        deep_analysis: {
          enabled: form.deepAnalysisEnabled,
          trigger_relevance: form.deepAnalysisIncludeMaybe ? ['relevant', 'maybe'] : ['relevant'],
          min_confidence: decimalNumber(form.deepAnalysisMinConfidence, 0.7),
          max_candidates_per_run: positiveInt(form.deepAnalysisMaxCandidates, 5),
          content_source: form.deepAnalysisContentSource,
          output: form.deepAnalysisOutput,
        },
        ...(form.relevanceEnabled
          ? {
              relevance_profile: {
                enabled: true,
                ...(relevanceObjective ? { objective: relevanceObjective } : {}),
                include_criteria: relevanceInclude,
                exclude_criteria: relevanceExclude,
                must_have: [],
                nice_to_have: [],
              },
            }
          : {}),
      },
      actions_json: form.actions,
    }
    if (form.editingRuleId) {
      const rule = props.rules.find(item => item.id === form.editingRuleId)
      if (!rule) {
        toast.error('Rule no longer exists')
        return
      }
      await props.onUpdate(rule, body, 'Rule updated')
    } else {
      await props.onCreate(body)
    }
    setForm(defaultPostProcessingForm())
  }

  return (
    <div className="space-y-4">
      <PostProcessingEgressCard
        connection={props.connection}
        busy={props.busy === 'source:egress'}
        onAllowExternalModelProcessing={props.onAllowExternalModelProcessing}
      />

      <PostProcessingOperationCard
        operation={props.operation}
        lastRefreshAt={props.lastRefreshAt}
      />

      <Card className="space-y-4">
        <CardHeader>
          <CardTitle>{form.editingRuleId ? 'Edit Rule' : 'New Rule'}</CardTitle>
        </CardHeader>
        <form onSubmit={submit} className="space-y-5">
          <div className="grid gap-3 lg:grid-cols-4">
            <label className="space-y-1.5 lg:col-span-2">
              <span className="text-xs font-medium text-muted-foreground">Rule name</span>
              <input
                value={form.name}
                onChange={event => setForm(current => ({ ...current, name: event.target.value }))}
                placeholder={`${props.connection.name} digest`}
                className="flex h-9 w-full rounded-md border border-border bg-input px-3 text-sm"
              />
              <p className="text-xs text-muted-foreground">Shown in the rule list and run history.</p>
            </label>
            <label className="space-y-1.5">
              <span className="text-xs font-medium text-muted-foreground">Project</span>
              <select
                value={form.projectId}
                onChange={event => {
                  const projectId = event.target.value
                  setForm(current => ({
                    ...current,
                    projectId,
                    retrievalDomains: projectId
                      ? current.retrievalDomains
                      : current.retrievalDomains.filter(domain => domain !== 'project'),
                  }))
                }}
                className="flex h-9 w-full rounded-md border border-border bg-input px-3 text-sm"
              >
                <option value="">No project</option>
                {props.projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}
              </select>
              <p className="text-xs text-muted-foreground">Optional home for outputs and relevance decisions.</p>
            </label>
            <label className="space-y-1.5">
              <span className="text-xs font-medium text-muted-foreground">Batch size</span>
              <input
                type="number"
                min={1}
                max={100}
                value={form.itemLimit}
                onChange={event => setForm(current => ({ ...current, itemLimit: event.target.value }))}
                className="flex h-9 w-full rounded-md border border-border bg-input px-3 text-sm"
              />
              <p className="text-xs text-muted-foreground">Default 10; max items sent to one run.</p>
            </label>
          </div>

          <div className="grid gap-3 lg:grid-cols-4">
            <label className="space-y-1.5">
              <span className="text-xs font-medium text-muted-foreground">Run when</span>
              <select
                value={form.triggerType}
                onChange={event => setForm(current => ({ ...current, triggerType: event.target.value as SourcePostProcessingTriggerType }))}
                className="flex h-9 w-full rounded-md border border-border bg-input px-3 text-sm"
              >
                <option value="items_materialized">Items materialized</option>
                <option value="schedule">Schedule</option>
                <option value="manual">Manual</option>
              </select>
              <p className="text-xs text-muted-foreground">Most sources should use new items.</p>
            </label>
            {form.triggerType === 'schedule' && (
              <label className="space-y-1.5">
                <span className="text-xs font-medium text-muted-foreground">Cron</span>
                <input
                  value={form.cron}
                  onChange={event => setForm(current => ({ ...current, cron: event.target.value }))}
                  className="flex h-9 w-full rounded-md border border-border bg-input px-3 font-mono text-sm"
                />
                <p className="text-xs text-muted-foreground">Only used for schedule rules.</p>
              </label>
            )}
            <label className="flex items-start gap-2 rounded-md border border-border p-3 text-sm lg:col-span-2">
              <input
                type="checkbox"
                className="mt-0.5"
                checked={form.actions.batch_digest}
                onChange={event => setAction('batch_digest', event.target.checked)}
              />
              <span>
                <span className="block font-medium">Create digest artifact</span>
                <span className="text-xs text-muted-foreground">Default output: one summary for the batch.</span>
              </span>
            </label>
          </div>

          <div className="space-y-3 rounded-md border border-border p-3">
            <label className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                aria-label="Screen for relevance"
                className="mt-0.5"
                checked={form.relevanceEnabled}
                onChange={event => setForm(current => ({
                  ...current,
                  relevanceEnabled: event.target.checked,
                  processingStrategy: event.target.checked ? 'screen_then_digest' : 'batch_digest',
                  actions: { ...current.actions, mark_items: event.target.checked },
                }))}
              />
              <span>
                <span className="block font-medium">Screen for relevance</span>
                <span className="text-xs text-muted-foreground">Use when the source should filter items against your topic.</span>
              </span>
            </label>
            {form.relevanceEnabled && (
              <div className="grid gap-3 lg:grid-cols-2">
                <label className="space-y-1.5 lg:col-span-2">
                  <span className="text-xs font-medium text-muted-foreground">Objective</span>
                  <Textarea
                    value={form.relevanceObjective}
                    onChange={event => setForm(current => ({ ...current, relevanceObjective: event.target.value }))}
                    placeholder="What counts as relevant for this source?"
                    rows={2}
                  />
                </label>
                <label className="space-y-1.5">
                  <span className="text-xs font-medium text-muted-foreground">Include criteria (one per line)</span>
                  <Textarea
                    value={form.relevanceIncludeCriteria}
                    onChange={event => setForm(current => ({ ...current, relevanceIncludeCriteria: event.target.value }))}
                    rows={3}
                  />
                </label>
                <label className="space-y-1.5">
                  <span className="text-xs font-medium text-muted-foreground">Exclude criteria (one per line)</span>
                  <Textarea
                    value={form.relevanceExcludeCriteria}
                    onChange={event => setForm(current => ({ ...current, relevanceExcludeCriteria: event.target.value }))}
                    rows={3}
                  />
                </label>
              </div>
            )}
          </div>

          <details className="rounded-md border border-border p-3">
            <summary className="cursor-pointer text-sm font-medium">Advanced options</summary>
            <div className="mt-4 space-y-5">
              <div className="grid gap-3 lg:grid-cols-4">
                <label className="space-y-1.5">
                  <span className="text-xs font-medium text-muted-foreground">Agent</span>
                  <select
                    value={form.agentId}
                    onChange={event => setForm(current => ({ ...current, agentId: event.target.value }))}
                    className="flex h-9 w-full rounded-md border border-border bg-input px-3 text-sm"
                  >
                    <option value="">Default Intake post-processing</option>
                    {props.agents.map(agent => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
                  </select>
                  <p className="text-xs text-muted-foreground">Reuse a specific agent when needed.</p>
                </label>
                <label className="space-y-1.5">
                  <span className="text-xs font-medium text-muted-foreground">Input window</span>
                  <select
                    value={form.window}
                    onChange={event => setForm(current => ({ ...current, window: event.target.value as SourcePostProcessingInputConfig['window'] }))}
                    className="flex h-9 w-full rounded-md border border-border bg-input px-3 text-sm"
                  >
                    <option value="new_since_last_success">New since success</option>
                    <option value="local_day">Local day</option>
                    <option value="last_24h">Last 24h</option>
                  </select>
                  <p className="text-xs text-muted-foreground">Which items the run can see.</p>
                </label>
                <label className="space-y-1.5">
                  <span className="text-xs font-medium text-muted-foreground">Processing</span>
                  <select
                    value={form.processingStrategy}
                    onChange={event => setForm(current => ({ ...current, processingStrategy: event.target.value as SourcePostProcessingStrategy }))}
                    className="flex h-9 w-full rounded-md border border-border bg-input px-3 text-sm"
                  >
                    <option value="batch_digest">Digest batch</option>
                    <option value="screen_then_digest">Screen then digest</option>
                    <option value="screen_extract_digest">Screen + evidence</option>
                  </select>
                  <p className="text-xs text-muted-foreground">How the agent should structure the run.</p>
                </label>
                <label className="space-y-1.5">
                  <span className="text-xs font-medium text-muted-foreground">Content source</span>
                  <select
                    value={form.contentSource}
                    onChange={event => setForm(current => ({ ...current, contentSource: event.target.value as SourcePostProcessingContentSource }))}
                    className="flex h-9 w-full rounded-md border border-border bg-input px-3 text-sm"
                  >
                    <option value="excerpt_only">Title + excerpt</option>
                    <option value="prefer_extracted_text_for_candidates">Prefer extracted text</option>
                    <option value="require_extracted_text_for_candidates">Require extracted text</option>
                  </select>
                  <p className="text-xs text-muted-foreground">Only already extracted text is sent to the agent.</p>
                </label>
                <label className="space-y-1.5">
                  <span className="text-xs font-medium text-muted-foreground">Min items</span>
                  <input
                    type="number"
                    min={1}
                    value={form.minNewItems}
                    onChange={event => setForm(current => ({ ...current, minNewItems: event.target.value }))}
                    className="flex h-9 w-full rounded-md border border-border bg-input px-3 text-sm"
                  />
                  <p className="text-xs text-muted-foreground">Skip runs below this count.</p>
                </label>
                <label className="space-y-1.5">
                  <span className="text-xs font-medium text-muted-foreground">Max auto batches</span>
                  <input
                    type="number"
                    min={1}
                    max={50}
                    value={form.maxBatchesPerEvent}
                    onChange={event => setForm(current => ({ ...current, maxBatchesPerEvent: event.target.value }))}
                    className="flex h-9 w-full rounded-md border border-border bg-input px-3 text-sm"
                  />
                  <p className="text-xs text-muted-foreground">Cap for materialized-item backlog drain.</p>
                </label>
                <label className="space-y-1.5">
                  <span className="text-xs font-medium text-muted-foreground">Cooldown seconds</span>
                  <input
                    type="number"
                    min={0}
                    value={form.cooldownSeconds}
                    onChange={event => setForm(current => ({ ...current, cooldownSeconds: event.target.value }))}
                    className="flex h-9 w-full rounded-md border border-border bg-input px-3 text-sm"
                  />
                  <p className="text-xs text-muted-foreground">Minimum time between auto-runs.</p>
                </label>
              </div>

              <div className="space-y-3 rounded-md border border-border p-3">
                <div className="space-y-1">
                  <div className="text-sm font-medium">Judging context</div>
                  <p className="text-xs text-muted-foreground">
                    Choose the existing context the agent may use as references before judging new source items.
                  </p>
                </div>
                <div className="grid gap-2 lg:grid-cols-2">
                  <label className={`flex items-start gap-2 rounded-md border border-border p-3 text-sm ${form.projectId ? '' : 'opacity-60'}`}>
                    <input
                      type="checkbox"
                      className="mt-0.5"
                      disabled={!form.projectId}
                      checked={Boolean(form.projectId) && form.retrievalDomains.includes('project')}
                      onChange={event => setRetrievalDomain('project', event.target.checked)}
                    />
                    <span>
                      <span className="block font-medium">Use project context</span>
                      <span className="text-xs text-muted-foreground">
                        {form.projectId
                          ? 'Use the linked project summary and current focus as the primary judging reference.'
                          : 'Select a project above to enable project-specific context.'}
                      </span>
                    </span>
                  </label>
                  <label className="flex items-start gap-2 rounded-md border border-border p-3 text-sm">
                    <input
                      type="checkbox"
                      className="mt-0.5"
                      checked={form.retrievalDomains.includes('knowledge')}
                      onChange={event => setRetrievalDomain('knowledge', event.target.checked)}
                    />
                    <span>
                      <span className="block font-medium">Compare with knowledge base</span>
                      <span className="text-xs text-muted-foreground">
                        Optional background comparison. Useful for duplicates or conflicts; can add noise for narrow screening.
                      </span>
                    </span>
                  </label>
                  <label className="flex items-start gap-2 rounded-md border border-border p-3 text-sm">
                    <input
                      type="checkbox"
                      className="mt-0.5"
                      checked={form.retrievalDomains.includes('intake')}
                      onChange={event => setRetrievalDomain('intake', event.target.checked)}
                    />
                    <span>
                      <span className="block font-medium">Compare with intake history</span>
                      <span className="text-xs text-muted-foreground">
                        Look at previous intake items to spot repeats, follow-ups, or stream drift.
                      </span>
                    </span>
                  </label>
                  <label className="flex items-start gap-2 rounded-md border border-border p-3 text-sm">
                    <input
                      type="checkbox"
                      className="mt-0.5"
                      checked={form.retrievalDomains.includes('memory')}
                      onChange={event => setRetrievalDomain('memory', event.target.checked)}
                    />
                    <span>
                      <span className="block font-medium">Use memory context</span>
                      <span className="text-xs text-muted-foreground">
                        Use allowed memory only when preferences or remembered goals should affect screening.
                      </span>
                    </span>
                  </label>
                </div>
                {selectedRetrievalDomains(form).length > 0 && (
                  <div className="grid gap-3 lg:grid-cols-4">
                    <label className="space-y-1.5 lg:col-span-2">
                      <span className="text-xs font-medium text-muted-foreground">Query</span>
                      <input
                        value={form.retrievalQuery}
                        onChange={event => setForm(current => ({ ...current, retrievalQuery: event.target.value }))}
                        placeholder="Leave blank to use the rule goal and source hints"
                        className="flex h-9 w-full rounded-md border border-border bg-input px-3 text-sm"
                      />
                      <p className="text-xs text-muted-foreground">Override only when the context search needs a narrower query.</p>
                    </label>
                    <label className="space-y-1.5">
                      <span className="text-xs font-medium text-muted-foreground">Mode</span>
                      <select
                        value={form.retrievalMode}
                        onChange={event => setForm(current => ({ ...current, retrievalMode: event.target.value as SourcePostProcessingRetrievalMode }))}
                        className="flex h-9 w-full rounded-md border border-border bg-input px-3 text-sm"
                      >
                        <option value="exact">Exact</option>
                        <option value="lexical">Lexical</option>
                        <option value="hybrid">Hybrid</option>
                        <option value="hybrid_rerank">Hybrid rerank</option>
                      </select>
                    </label>
                    <label className="space-y-1.5">
                      <span className="text-xs font-medium text-muted-foreground">Max per domain</span>
                      <input
                        type="number"
                        min={1}
                        max={20}
                        value={form.retrievalMaxResults}
                        onChange={event => setForm(current => ({ ...current, retrievalMaxResults: event.target.value }))}
                        className="flex h-9 w-full rounded-md border border-border bg-input px-3 text-sm"
                      />
                    </label>
                  </div>
                )}
              </div>

              <div className="space-y-3 rounded-md border border-border p-3">
                <label className="flex items-start gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={form.candidatePrefilterEnabled}
                    onChange={event => setForm(current => ({ ...current, candidatePrefilterEnabled: event.target.checked }))}
                  />
                  <span>
                    <span className="block font-medium">Prefilter candidates</span>
                    <span className="text-xs text-muted-foreground">Use retrieval ranking to reduce the current batch before the agent screens it.</span>
                  </span>
                </label>
                {form.candidatePrefilterEnabled && (
                  <div className="grid gap-3 lg:grid-cols-4">
                    <label className="space-y-1.5">
                      <span className="text-xs font-medium text-muted-foreground">Mode</span>
                      <select
                        value={form.candidatePrefilterMode}
                        onChange={event => setForm(current => ({ ...current, candidatePrefilterMode: event.target.value as SourcePostProcessingRetrievalMode }))}
                        className="flex h-9 w-full rounded-md border border-border bg-input px-3 text-sm"
                      >
                        <option value="lexical">Lexical</option>
                        <option value="hybrid">Hybrid</option>
                        <option value="hybrid_rerank">Hybrid rerank</option>
                      </select>
                    </label>
                    <label className="space-y-1.5">
                      <span className="text-xs font-medium text-muted-foreground">Max candidates</span>
                      <input
                        type="number"
                        min={1}
                        max={100}
                        value={form.candidatePrefilterMaxCandidates}
                        onChange={event => setForm(current => ({ ...current, candidatePrefilterMaxCandidates: event.target.value }))}
                        className="flex h-9 w-full rounded-md border border-border bg-input px-3 text-sm"
                      />
                    </label>
                    <label className="space-y-1.5">
                      <span className="text-xs font-medium text-muted-foreground">Min score</span>
                      <input
                        type="number"
                        min={0}
                        step="0.01"
                        value={form.candidatePrefilterMinScore}
                        onChange={event => setForm(current => ({ ...current, candidatePrefilterMinScore: event.target.value }))}
                        placeholder="Optional"
                        className="flex h-9 w-full rounded-md border border-border bg-input px-3 text-sm"
                      />
                    </label>
                  </div>
                )}
              </div>

              <div className="space-y-3 rounded-md border border-border p-3">
                <label className="flex items-start gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={form.deepAnalysisEnabled}
                    onChange={event => setForm(current => ({ ...current, deepAnalysisEnabled: event.target.checked }))}
                  />
                  <span>
                    <span className="block font-medium">Deep analysis after screening</span>
                    <span className="text-xs text-muted-foreground">Queue full text only for strong candidates, then run a follow-up report.</span>
                  </span>
                </label>
                {form.deepAnalysisEnabled && (
                  <div className="grid gap-3 lg:grid-cols-4">
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={form.deepAnalysisIncludeMaybe}
                        onChange={event => setForm(current => ({ ...current, deepAnalysisIncludeMaybe: event.target.checked }))}
                      />
                      <span>Include maybe</span>
                    </label>
                    <label className="space-y-1.5">
                      <span className="text-xs font-medium text-muted-foreground">Min confidence</span>
                      <input
                        type="number"
                        min={0}
                        max={1}
                        step="0.05"
                        value={form.deepAnalysisMinConfidence}
                        onChange={event => setForm(current => ({ ...current, deepAnalysisMinConfidence: event.target.value }))}
                        className="flex h-9 w-full rounded-md border border-border bg-input px-3 text-sm"
                      />
                    </label>
                    <label className="space-y-1.5">
                      <span className="text-xs font-medium text-muted-foreground">Max candidates</span>
                      <input
                        type="number"
                        min={1}
                        max={25}
                        value={form.deepAnalysisMaxCandidates}
                        onChange={event => setForm(current => ({ ...current, deepAnalysisMaxCandidates: event.target.value }))}
                        className="flex h-9 w-full rounded-md border border-border bg-input px-3 text-sm"
                      />
                    </label>
                    <label className="space-y-1.5">
                      <span className="text-xs font-medium text-muted-foreground">Text requirement</span>
                      <select
                        value={form.deepAnalysisContentSource}
                        onChange={event => setForm(current => ({ ...current, deepAnalysisContentSource: event.target.value as SourcePostProcessingDeepAnalysisContentSource }))}
                        className="flex h-9 w-full rounded-md border border-border bg-input px-3 text-sm"
                      >
                        <option value="prefer_extracted_text">Prefer text</option>
                        <option value="require_extracted_text">Require text</option>
                      </select>
                    </label>
                    <label className="space-y-1.5">
                      <span className="text-xs font-medium text-muted-foreground">Output</span>
                      <select
                        value={form.deepAnalysisOutput}
                        onChange={event => setForm(current => ({ ...current, deepAnalysisOutput: event.target.value as SourcePostProcessingDeepAnalysisOutput }))}
                        className="flex h-9 w-full rounded-md border border-border bg-input px-3 text-sm"
                      >
                        <option value="deep_report">Deep report</option>
                        <option value="per_item_deep_summary">Per-item deep summaries</option>
                      </select>
                    </label>
                  </div>
                )}
              </div>

              <div className="space-y-2">
                <span className="text-xs font-medium text-muted-foreground">Advanced actions</span>
                <div className="flex flex-wrap gap-3">
                  {POST_PROCESSING_ACTIONS.filter(action => action.key !== 'batch_digest').map(action => (
                    <label key={action.key} className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={form.actions[action.key]}
                        onChange={event => setAction(action.key, event.target.checked)}
                      />
                      <span>{action.label}</span>
                    </label>
                  ))}
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={form.includeEvidence}
                      onChange={event => setForm(current => ({ ...current, includeEvidence: event.target.checked }))}
                    />
                    <span>Include extracted evidence in input</span>
                  </label>
                </div>
                <p className="text-xs text-muted-foreground">
                  Mark relevance updates item status from the agent&apos;s decision.
                </p>
              </div>
            </div>
          </details>

          <div>
            <div className="flex flex-wrap gap-2">
              <Button type="submit" disabled={props.busy === 'post-processing:create' || props.busy?.startsWith('post-processing:update:')}>
                {form.editingRuleId ? <CheckCircle2 className="size-4" /> : <Plus className="size-4" />}
                {form.editingRuleId ? 'Save rule' : 'Create rule'}
              </Button>
              {form.editingRuleId && (
                <Button type="button" variant="outline" onClick={() => setForm(defaultPostProcessingForm())}>
                  Cancel edit
                </Button>
              )}
            </div>
          </div>
        </form>
      </Card>

      <PostProcessingBacklogCard backlog={props.backlog} rules={props.rules} />

      <Card className="space-y-3">
        <CardHeader>
          <CardTitle>Rules</CardTitle>
        </CardHeader>
        {props.rules.length === 0 ? (
          <EmptyState title="No rules" description="Post-processing rules for this source appear here." />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Rule</TableHead>
                <TableHead>Trigger</TableHead>
                <TableHead>Actions</TableHead>
                <TableHead>Cursor</TableHead>
                <TableHead>Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {props.rules.map(rule => {
                const runningThisRule = props.busy === `post-processing:run:${rule.id}`
                const drainingThisRule = props.busy === `post-processing:drain:${rule.id}`
                return (
                  <TableRow key={rule.id}>
                    <TableCell>
                      <div className="font-medium">{rule.name}</div>
                      <div className="mt-1 flex flex-wrap gap-1.5">
                        <StatusBadge status={rule.status} />
                        <Badge variant="muted"><Bot className="mr-1 size-3" />{agentName(rule.agent_id)}</Badge>
                        {projectName(rule.project_id) && <Badge variant="muted">{projectName(rule.project_id)}</Badge>}
                      </div>
                    </TableCell>
                    <TableCell>
                      <div>{triggerLabel(rule.trigger_type)}</div>
                      {rule.trigger_type === 'schedule' && <p className="text-xs text-muted-foreground">{rule.trigger_config_json.cron ?? 'no cron'}</p>}
                      <p className="text-xs text-muted-foreground">Next {fmt(rule.next_run_at)}</p>
                    </TableCell>
                    <TableCell>{actionLabel(rule.actions_json)}</TableCell>
                    <TableCell>
                      <div className="text-xs text-muted-foreground">Last fired {fmt(rule.last_fired_at)}</div>
                      <div className="text-xs text-muted-foreground">{cursorLabel(rule.cursor_json)}</div>
                      <div className="text-xs text-muted-foreground">{rule.input_config_json.processing_strategy}</div>
                      <div className="text-xs text-muted-foreground">{rule.input_config_json.content_source}</div>
                    </TableCell>
                    <TableCell>
                      {rule.status !== 'archived' && (
                        <div className="flex flex-wrap gap-1.5">
                          <Button size="sm" variant="outline" disabled={Boolean(props.busy)} onClick={() => editRule(rule)}>
                            Edit
                          </Button>
                          <Button size="sm" variant="outline" disabled={Boolean(props.busy)} onClick={() => props.onRun(rule)}>
                            {runningThisRule ? <Loader2 className="size-3.5 animate-spin" /> : <Play className="size-3.5" />}
                            {runningThisRule ? 'Running...' : 'Run'}
                          </Button>
                          <Button size="sm" variant="outline" disabled={Boolean(props.busy)} onClick={() => props.onDrain(rule)}>
                            <RefreshCw className={`size-3.5 ${drainingThisRule ? 'animate-spin' : ''}`} />
                            {drainingThisRule ? 'Draining...' : 'Drain'}
                          </Button>
                          {rule.status === 'active' ? (
                            <Button
                              size="sm"
                              variant="outline"
                              disabled={Boolean(props.busy)}
                              onClick={() => props.onUpdate(rule, { status: 'paused' }, 'Rule paused')}
                            >
                              <Pause className="size-3.5" />
                            </Button>
                          ) : (
                            <Button
                              size="sm"
                              variant="outline"
                              disabled={Boolean(props.busy)}
                              onClick={() => props.onUpdate(rule, { status: 'active' }, 'Rule activated')}
                            >
                              <Play className="size-3.5" />
                            </Button>
                          )}
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={Boolean(props.busy)}
                            onClick={() => props.onUpdate(rule, { status: 'archived' }, 'Rule archived')}
                          >
                            <Archive className="size-3.5" />
                          </Button>
                        </div>
                      )}
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        )}
      </Card>

      <Card className="space-y-3">
        <CardHeader>
          <CardTitle>Recent Runs</CardTitle>
        </CardHeader>
        <PostProcessingRunsTable runs={props.runs} rules={props.rules} agents={props.agents} />
      </Card>

      <Card className="space-y-3">
        <CardHeader>
          <CardTitle>Review Decisions</CardTitle>
        </CardHeader>
        <PostProcessingDecisionsTable
          decisions={props.decisions}
          busy={props.busy}
          onAction={props.onDecisionAction}
        />
      </Card>
    </div>
  )
}

function PostProcessingEgressCard(props: {
  connection: SourceConnection
  busy: boolean
  onAllowExternalModelProcessing: () => Promise<void>
}) {
  const allowed = sourceAllowsExternalModelProcessing(props.connection)
  if (allowed) return null
  const egressClass = sourceEgressClassForDisplay(props.connection)
  const consent = props.connection.consent_json ?? {}
  return (
    <Card className="space-y-3">
      <CardHeader>
        <CardTitle>External Model Processing Blocked</CardTitle>
      </CardHeader>
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="space-y-1">
          <div className="flex flex-wrap gap-1.5">
            <Badge variant="destructive">External model blocked</Badge>
            <Badge variant="muted">{egressClass}</Badge>
            <Badge variant="muted">external consent {consent.allow_external_model_egress === true ? 'on' : 'off'}</Badge>
          </div>
          <p className="text-sm text-muted-foreground">
            This source is set to internal-only processing. Public sources normally allow external model analysis by default; enable it here or change the source policy under Advanced governance.
          </p>
        </div>
        <Button
          type="button"
          variant="secondary"
          disabled={props.busy}
          onClick={() => void props.onAllowExternalModelProcessing()}
        >
          <ShieldCheck className="size-4" />
          {props.busy ? 'Saving...' : 'Allow external model'}
        </Button>
      </div>
    </Card>
  )
}

function PostProcessingOperationCard(props: {
  operation: PostProcessingOperation | null
  lastRefreshAt: string | null
}) {
  const operation = props.operation
  if (!operation) return null
  const title = operation.status === 'running'
    ? operation.kind === 'drain' ? 'Draining post-processing backlog' : 'Running post-processing'
    : operation.status === 'succeeded'
      ? operation.kind === 'drain' ? 'Post-processing drain finished' : 'Post-processing run finished'
      : operation.kind === 'drain' ? 'Post-processing drain failed' : 'Post-processing run failed'
  return (
    <Card className="space-y-3">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            {operation.status === 'running' && <Loader2 className="size-4 animate-spin text-muted-foreground" />}
            <h3 className="text-sm font-medium">{title}</h3>
            <StatusBadge status={operation.status} />
          </div>
          <p className="text-sm text-muted-foreground">{operation.ruleName}</p>
          <p className="text-xs text-muted-foreground">{operation.message}</p>
        </div>
        <div className="text-xs text-muted-foreground md:text-right">
          <p>Started {fmt(operation.startedAt)}</p>
          <p>Updated {fmt(operation.updatedAt)}</p>
          {operation.status === 'running' && (
            <p>Refreshing runs every 2s{props.lastRefreshAt ? `; last ${fmt(props.lastRefreshAt)}` : ''}</p>
          )}
        </div>
      </div>
    </Card>
  )
}

function PostProcessingBacklogCard(props: {
  backlog: SourcePostProcessingBacklog | null
  rules: SourcePostProcessingRule[]
}) {
  const rows = props.backlog?.rules ?? []
  return (
    <Card className="space-y-3">
      <CardHeader>
        <CardTitle>Backlog</CardTitle>
      </CardHeader>
      {rows.length === 0 ? (
        <EmptyState title="No backlog" description="Create a rule to track pending post-processing work." />
      ) : (
        <div className="grid gap-3 lg:grid-cols-3">
          {rows.map(row => {
            const rule = props.rules.find(item => item.id === row.rule_id)
            return (
              <div key={row.rule_id} className="rounded-md border border-border p-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{row.rule_name}</p>
                    <p className="text-xs text-muted-foreground">{rule?.input_config_json.processing_strategy ?? 'batch_digest'}</p>
                  </div>
                  <StatusBadge status={row.status} />
                </div>
                <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
                  <div>
                    <p className="text-muted-foreground">Pending</p>
                    <p className="font-medium">{row.pending_item_count}</p>
                  </div>
                  <div>
                    <p className="text-muted-foreground">Batch</p>
                    <p className="font-medium">{row.batch_size}</p>
                  </div>
                  <div>
                    <p className="text-muted-foreground">Auto cap</p>
                    <p className="font-medium">{row.max_batches_per_event}</p>
                  </div>
                </div>
                <p className="mt-2 text-xs text-muted-foreground">Last fired {fmt(row.last_fired_at)}</p>
                {row.last_failed_run && <p className="mt-1 text-xs text-destructive">Last failed {fmt(row.last_failed_run.completed_at ?? row.last_failed_run.created_at)}</p>}
              </div>
            )
          })}
        </div>
      )}
    </Card>
  )
}

function PostProcessingDecisionsTable(props: {
  decisions: SourcePostProcessingItemDecision[]
  busy: string | null
  onAction: (decision: SourcePostProcessingItemDecision, action: string) => Promise<void>
}) {
  const [relevanceFilter, setRelevanceFilter] = useState<'all' | SourcePostProcessingItemRelevance>('all')
  const [reviewFilter, setReviewFilter] = useState<'all' | SourcePostProcessingDecisionReviewStatus>('all')
  if (props.decisions.length === 0) return <EmptyState title="No decisions" description="Screening decisions appear here after a rule runs." />
  const filtered = props.decisions.filter(decision =>
    (relevanceFilter === 'all' || decision.relevance === relevanceFilter) &&
    (reviewFilter === 'all' || decision.review_status === reviewFilter)
  )
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <div className="w-44 space-y-1">
          <Label>Decision</Label>
          <Select
            size="sm"
            value={relevanceFilter}
            onChange={value => setRelevanceFilter(value as 'all' | SourcePostProcessingItemRelevance)}
            options={[
              { value: 'all', label: 'All decisions' },
              { value: 'relevant', label: 'Relevant' },
              { value: 'maybe', label: 'Maybe' },
              { value: 'not_relevant', label: 'Not relevant' },
            ]}
          />
        </div>
        <div className="w-44 space-y-1">
          <Label>Review</Label>
          <Select
            size="sm"
            value={reviewFilter}
            onChange={value => setReviewFilter(value as 'all' | SourcePostProcessingDecisionReviewStatus)}
            options={[
              { value: 'all', label: 'All review states' },
              { value: 'pending', label: 'Pending' },
              { value: 'accepted', label: 'Accepted' },
              { value: 'ignored', label: 'Ignored' },
              { value: 'queued', label: 'Queued' },
              { value: 'proposed', label: 'Proposed' },
              { value: 'rerun', label: 'Rerun' },
              { value: 'dismissed', label: 'Dismissed' },
            ]}
          />
        </div>
        <p className="pb-1 text-xs text-muted-foreground">{filtered.length} of {props.decisions.length}</p>
      </div>
      {filtered.length === 0 ? (
        <EmptyState title="No matching decisions" description="Change the filters to see more results." />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Item</TableHead>
              <TableHead>Decision</TableHead>
              <TableHead>Review</TableHead>
              <TableHead>Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.map(decision => (
              <TableRow key={decision.id}>
                <TableCell>
                  <Link to={`/intake/items/${decision.intake_item_id}`} className="font-medium hover:underline">
                    {decision.item.title ?? short(decision.intake_item_id)}
                  </Link>
                  <p className="mt-1 line-clamp-1 text-xs text-muted-foreground">{decision.item.source_domain ?? decision.item.source_uri ?? 'intake item'}</p>
                </TableCell>
                <TableCell>
                  <div className="flex flex-wrap gap-1.5">
                    <Badge variant={decision.relevance === 'relevant' ? 'default' : decision.relevance === 'maybe' ? 'outline' : 'muted'}>{decision.relevance}</Badge>
                    {decision.confidence !== null && <Badge variant="muted">{Math.round(decision.confidence * 100)}%</Badge>}
                  </div>
                  {decision.reason && <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{decision.reason}</p>}
                </TableCell>
                <TableCell>
                  <StatusBadge status={decision.review_status} />
                  <p className="mt-1 text-xs text-muted-foreground">{decision.applied_item_status ?? decision.item.status ?? 'not applied'}</p>
                </TableCell>
                <TableCell>
                  <div className="flex flex-wrap gap-1.5">
                    <Button size="sm" variant="outline" disabled={Boolean(props.busy)} onClick={() => props.onAction(decision, 'select')}>Select</Button>
                    <Button size="sm" variant="outline" disabled={Boolean(props.busy)} onClick={() => props.onAction(decision, 'triage')}>Triage</Button>
                    <Button size="sm" variant="outline" disabled={Boolean(props.busy)} onClick={() => props.onAction(decision, 'ignore')}>Ignore</Button>
                    <Button size="sm" variant="outline" disabled={Boolean(props.busy)} onClick={() => props.onAction(decision, 'queue_content')}>Queue text</Button>
                    <Button size="sm" variant="outline" disabled={Boolean(props.busy)} onClick={() => props.onAction(decision, 'deep_analysis')}>Deep</Button>
                    <Button size="sm" variant="outline" disabled={Boolean(props.busy)} onClick={() => props.onAction(decision, 'extract_evidence')}>Evidence</Button>
                    <Button size="sm" variant="outline" disabled={Boolean(props.busy)} onClick={() => props.onAction(decision, 'create_proposal')}>Proposal</Button>
                    <Button size="sm" variant="ghost" disabled={Boolean(props.busy)} onClick={() => props.onAction(decision, 'rerun_item')}>Rerun</Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  )
}

function PostProcessingRunsTable(props: {
  runs: SourcePostProcessingRun[]
  rules: SourcePostProcessingRule[]
  agents: AgentOut[]
}) {
  const [selectedRun, setSelectedRun] = useState<SourcePostProcessingRun | null>(null)
  if (props.runs.length === 0) return <EmptyState title="No post-processing runs" description="Rule runs appear here." />
  const ruleName = (id: string | null) => (id ? props.rules.find(rule => rule.id === id)?.name ?? short(id) : 'one-off')
  const agentName = (id: string) => props.agents.find(agent => agent.id === id)?.name ?? short(id)
  return (
    <>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Run</TableHead>
            <TableHead>Input</TableHead>
            <TableHead>Output</TableHead>
            <TableHead>Completed</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {props.runs.map(run => (
            <TableRow key={run.id}>
              <TableCell>
                <div className="font-medium">{ruleName(run.rule_id)}</div>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  <StatusBadge status={run.status} />
                  <Badge variant="muted">{triggerLabel(run.trigger_type)}</Badge>
                  <Badge variant="muted">{agentName(run.agent_id)}</Badge>
                </div>
              </TableCell>
              <TableCell>
                <div>{run.input_item_ids.length} items</div>
                <div className="text-xs text-muted-foreground">{run.input_evidence_ids.length} evidence</div>
              </TableCell>
              <TableCell>
                <div className="flex flex-col gap-1 text-xs">
                  {run.output_artifact_ids.map(id => (
                    <Link key={id} to={`/artifacts/${id}`} className="text-accent-foreground hover:underline">artifact {short(id)}</Link>
                  ))}
                  {run.output_proposal_ids.length > 0 && <Link to="/proposals" className="text-muted-foreground hover:underline">{run.output_proposal_ids.length} proposal{run.output_proposal_ids.length === 1 ? '' : 's'}</Link>}
                  {run.output_job_ids.length > 0 && <Link to="/jobs" className="text-muted-foreground hover:underline">{run.output_job_ids.length} job{run.output_job_ids.length === 1 ? '' : 's'}</Link>}
                  {run.output_artifact_ids.length === 0 && run.output_proposal_ids.length === 0 && run.output_job_ids.length === 0 && <span className="text-muted-foreground">none</span>}
                </div>
                {run.summary && <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{run.summary}</p>}
                {(run.item_decisions_json.length > 0 || retrievalContextCount(run.retrieval_context_json) > 0) && (
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {run.item_decisions_json.length > 0 && <Badge variant="muted">{run.item_decisions_json.length} decisions</Badge>}
                    {retrievalContextCount(run.retrieval_context_json) > 0 && (
                      <Badge variant="muted">{retrievalContextCount(run.retrieval_context_json)} context refs</Badge>
                    )}
                  </div>
                )}
                {run.item_decisions_json.length > 0 && <ItemDecisionsSummary decisions={run.item_decisions_json} />}
                {run.error_json && <JsonSnippet value={run.error_json} label="error" />}
              </TableCell>
              <TableCell>
                {fmt(run.completed_at ?? run.created_at)}
                {run.agent_run_id && <Link to={`/runs/${run.agent_run_id}`} className="block text-xs text-muted-foreground hover:underline">run {short(run.agent_run_id)}</Link>}
                <Button size="sm" variant="ghost" className="mt-1 px-0" onClick={() => setSelectedRun(run)}>Details</Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <PostProcessingRunDetailDialog
        run={selectedRun}
        ruleName={ruleName(selectedRun?.rule_id ?? null)}
        agentName={selectedRun ? agentName(selectedRun.agent_id) : ''}
        onOpenChange={open => { if (!open) setSelectedRun(null) }}
      />
    </>
  )
}

function PostProcessingRunDetailDialog(props: {
  run: SourcePostProcessingRun | null
  ruleName: string
  agentName: string
  onOpenChange: (open: boolean) => void
}) {
  const run = props.run
  return (
    <Dialog open={Boolean(run)} onOpenChange={props.onOpenChange}>
      <DialogContent className="max-h-[82vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Post-processing run</DialogTitle>
        </DialogHeader>
        {run && (
          <div className="space-y-4 text-sm">
            <div className="flex flex-wrap gap-1.5">
              <StatusBadge status={run.status} />
              <Badge variant="muted">{triggerLabel(run.trigger_type)}</Badge>
              <Badge variant="muted">{props.agentName}</Badge>
            </div>
            <div className="grid gap-3 md:grid-cols-3">
              <div>
                <p className="text-xs text-muted-foreground">Rule</p>
                <p className="font-medium">{props.ruleName}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Input</p>
                <p className="font-medium">{run.input_item_ids.length} items / {run.input_evidence_ids.length} evidence</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Completed</p>
                <p className="font-medium">{fmt(run.completed_at ?? run.created_at)}</p>
              </div>
            </div>
            {run.summary && <p className="rounded-md border border-border p-3 text-muted-foreground">{run.summary}</p>}
            <div className="flex flex-wrap gap-2 text-xs">
              {run.output_artifact_ids.map(id => (
                <Link key={id} to={`/artifacts/${id}`} className="rounded-md border border-border px-2 py-1 hover:bg-muted">artifact {short(id)}</Link>
              ))}
              {run.output_proposal_ids.map(id => (
                <Link key={id} to="/proposals" className="rounded-md border border-border px-2 py-1 hover:bg-muted">proposal {short(id)}</Link>
              ))}
              {run.output_job_ids.map(id => (
                <Link key={id} to="/jobs" className="rounded-md border border-border px-2 py-1 hover:bg-muted">job {short(id)}</Link>
              ))}
              {run.agent_run_id && (
                <Link to={`/runs/${run.agent_run_id}`} className="rounded-md border border-border px-2 py-1 hover:bg-muted">agent run {short(run.agent_run_id)}</Link>
              )}
            </div>
            {run.item_decisions_json.length > 0 && <ItemDecisionsSummary decisions={run.item_decisions_json} />}
            {retrievalContextCount(run.retrieval_context_json) > 0 && <JsonSnippet value={run.retrieval_context_json} label="retrieval context" />}
            {run.error_json && <JsonSnippet value={run.error_json} label="error" />}
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

function RecipePreview({ preview }: { preview: SourceRecipeDryRunResult }) {
  return (
    <div className="space-y-4">
      <Card className="space-y-3">
        <CardHeader>
          <CardTitle>Sample Output</CardTitle>
        </CardHeader>
        <div className="flex flex-wrap gap-1.5">
          <StatusBadge status={preview.status} />
          <Badge variant="outline">{preview.item_count} items</Badge>
          <Badge variant="muted">{preview.followed_urls.length} followed</Badge>
          <Badge variant="muted">{preview.skipped_urls.length} skipped</Badge>
        </div>
        {preview.sample_items.length === 0 ? (
          <EmptyState title="No sample items" description="The latest preview did not produce sample items." />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Item</TableHead>
                <TableHead>Source</TableHead>
                <TableHead>Excerpt</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {preview.sample_items.map((item, index) => (
                <TableRow key={`${item.external_id}-${index}`}>
                  <TableCell className="font-medium">{item.title}</TableCell>
                  <TableCell className="break-all text-xs text-muted-foreground">{item.source_uri}</TableCell>
                  <TableCell>{item.excerpt ?? 'none'}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>
      {(preview.warnings.length > 0 || preview.errors.length > 0) && (
        <Card className="space-y-3">
          <CardHeader>
            <CardTitle>Preview Notes</CardTitle>
          </CardHeader>
          <ul className="space-y-1 text-sm">
            {[...preview.errors, ...preview.warnings].map((message, index) => (
              <li key={`${message}-${index}`} className="text-muted-foreground">{message}</li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  )
}

function AdvancedPanel(props: {
  connection: SourceConnection
  isCustomSource: boolean
  isRecipeSource: boolean
  summary: CustomSourceHandlerSummary | null
  handlerVersions: CustomSourceHandlerVersion[]
  handlerRuns: CustomSourceHandlerRun[]
  recipeVersions: SourceRecipeVersion[]
  jobs: ExtractionJob[]
  fixtureHtml: string
  setFixtureHtml: (value: string) => void
  busy: string | null
  latestDraft: CustomSourceHandlerVersion | null
  onGenerate: () => void
  onTest: (version: CustomSourceHandlerVersion) => void
  onActivate: (version: CustomSourceHandlerVersion) => void
}) {
  return (
    <div className="space-y-4">
      <Card className="space-y-3">
        <CardHeader>
          <CardTitle>Advanced Audit</CardTitle>
        </CardHeader>
        <p className="text-sm text-muted-foreground">
          Raw implementation details live here for debugging and audit. The normal tabs show product-level source status,
          plan, preview, items, evidence, and runs.
        </p>
      </Card>

      {props.isCustomSource && (
        <Card className="space-y-4">
          <div className="flex items-center justify-between gap-3">
            <CardHeader>
              <CardTitle>Handler Versions</CardTitle>
            </CardHeader>
            <Button onClick={props.onGenerate} disabled={props.busy === 'generate'}>
              <Code2 className="size-4" />
              Generate
            </Button>
          </div>
          <Textarea
            value={props.fixtureHtml}
            onChange={event => props.setFixtureHtml(event.target.value)}
            className="min-h-28 font-mono text-xs"
          />
          <VersionsTable
            versions={props.handlerVersions}
            busy={props.busy}
            onTest={props.onTest}
            onActivate={props.onActivate}
          />
          {props.latestDraft?.test_result_json && (
            <TestResultPanel title={`Latest test v${props.latestDraft.version_number}`} result={props.latestDraft.test_result_json} />
          )}
        </Card>
      )}

      {props.isRecipeSource && (
        <RecipeVersionsPanel versions={props.recipeVersions} />
      )}

      {props.summary?.active_handler_version && (
        <SecurityPanel version={props.summary.active_handler_version} />
      )}

      <Card className="space-y-3">
        <CardHeader>
          <CardTitle>Raw Source JSON</CardTitle>
        </CardHeader>
        <JsonBlock value={{
          config_json: props.connection.config_json,
          consent_json: props.connection.consent_json,
          policy_json: props.connection.policy_json,
        }} />
      </Card>

      <Card className="space-y-3">
        <CardHeader>
          <CardTitle>Raw Handler Runs</CardTitle>
        </CardHeader>
        <HandlerRunsTable runs={props.handlerRuns} />
      </Card>

      <Card className="space-y-3">
        <CardHeader>
          <CardTitle>Extraction Jobs</CardTitle>
        </CardHeader>
        <SourceJobsTable jobs={props.jobs} />
      </Card>
    </div>
  )
}

function RecipeVersionsPanel({ versions }: { versions: SourceRecipeVersion[] }) {
  if (versions.length === 0) return <EmptyState title="No recipe versions" description="Recipe versions appear here." />
  return (
    <Card className="space-y-3">
      <CardHeader>
        <CardTitle>Recipe Versions</CardTitle>
      </CardHeader>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Version</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Dry-run</TableHead>
            <TableHead>Created</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {versions.map(version => (
            <TableRow key={version.id}>
              <TableCell>v{version.version_number}</TableCell>
              <TableCell><StatusBadge status={version.status} /></TableCell>
              <TableCell>{stringValue(version.test_result_json?.status) ?? 'untested'}</TableCell>
              <TableCell>{fmt(version.created_at)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <JsonSnippet value={versions[0]?.recipe_json ?? null} label="latest recipe JSON" />
      <JsonSnippet value={versions[0]?.test_result_json ?? null} label="latest preview JSON" />
    </Card>
  )
}

function KeyValueGrid(props: { rows: Array<[string, string]> }) {
  return (
    <div className="grid gap-2 text-sm md:grid-cols-[180px_minmax(0,1fr)]">
      {props.rows.map(([label, value]) => (
        <div key={label} className="contents">
          <span className="text-muted-foreground">{label}</span>
          <span className="min-w-0 break-all">{value}</span>
        </div>
      ))}
    </div>
  )
}

function HandlerVersionSummary({ version }: { version: CustomSourceHandlerVersion }) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5">
        <Badge variant="outline">v{version.version_number}</Badge>
        <StatusBadge status={version.status} />
        <Badge variant="muted">{version.language}</Badge>
        {version.proposal_id && <Badge variant="muted">proposal {short(version.proposal_id)}</Badge>}
      </div>
      <KeyValueGrid rows={[
        ['Entrypoint', version.entrypoint],
        ['Checksum', version.checksum],
        ['Created', fmt(version.created_at)],
        ['Activated', fmt(version.activated_at)],
      ]} />
    </div>
  )
}

function VersionsTable(props: {
  versions: CustomSourceHandlerVersion[]
  busy: string | null
  onTest: (version: CustomSourceHandlerVersion) => void
  onActivate: (version: CustomSourceHandlerVersion) => void
}) {
  if (props.versions.length === 0) {
    return <EmptyState title="No handler versions" description="Generated versions appear here." />
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Version</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Test</TableHead>
          <TableHead>Created</TableHead>
          <TableHead>Actions</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {props.versions.map(version => {
          const testStatus = stringValue(version.test_result_json?.status) ?? 'untested'
          const canTest = version.status === 'draft' || version.status === 'test_failed'
          const canActivate = version.status === 'draft' && testStatus === 'succeeded'
          return (
            <TableRow key={version.id}>
              <TableCell>v{version.version_number}</TableCell>
              <TableCell><StatusBadge status={version.status} /></TableCell>
              <TableCell>{testStatus}</TableCell>
              <TableCell>{fmt(version.created_at)}</TableCell>
              <TableCell>
                <div className="flex gap-1.5">
                  <Button size="sm" variant="outline" disabled={!canTest || props.busy === `test:${version.id}`} onClick={() => props.onTest(version)}>
                    <TestTube2 className="size-3.5" />
                    Test
                  </Button>
                  <Button size="sm" variant="secondary" disabled={!canActivate || props.busy === `activate:${version.id}`} onClick={() => props.onActivate(version)}>
                    <CheckCircle2 className="size-3.5" />
                    Activate
                  </Button>
                </div>
              </TableCell>
            </TableRow>
          )
        })}
      </TableBody>
    </Table>
  )
}

function SourceRunsTable({ runs }: { runs: SourceRunSummary[] }) {
  if (runs.length === 0) return <EmptyState title="No runs" description="Dry-runs, scans, tests, and extraction work appear here." />
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Run</TableHead>
          <TableHead>Kind</TableHead>
          <TableHead>Implementation</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Items</TableHead>
          <TableHead>Completed</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {runs.map(run => (
          <TableRow key={run.id}>
            <TableCell>{short(run.id)}</TableCell>
            <TableCell>{sourceRunKindLabel(run.run_kind)}</TableCell>
            <TableCell>{sourceRunImplementationLabel(run.implementation)}</TableCell>
            <TableCell><StatusBadge status={run.status} /></TableCell>
            <TableCell>{run.items_created ?? 0}</TableCell>
            <TableCell>
              {fmt(run.completed_at ?? null)}
              {run.error && <p className="text-xs text-destructive">{run.error}</p>}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function HandlerRunsTable({ runs }: { runs: CustomSourceHandlerRun[] }) {
  if (runs.length === 0) return <EmptyState title="No handler runs" description="Raw handler run rows appear here." />
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Run</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Artifacts</TableHead>
          <TableHead>Diagnostics</TableHead>
          <TableHead>Completed</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {runs.map(run => (
          <TableRow key={run.id}>
            <TableCell>{short(run.id)}</TableCell>
            <TableCell><StatusBadge status={run.status} /></TableCell>
            <TableCell>
              <div className="space-y-1 text-xs">
                {run.extraction_job_id && <p>job {short(run.extraction_job_id)}</p>}
                {run.input_artifact_id && <p>input {short(run.input_artifact_id)}</p>}
                {run.output_artifact_id && <p>output {short(run.output_artifact_id)}</p>}
                {run.logs_artifact_id && <p>logs {short(run.logs_artifact_id)}</p>}
                {!run.extraction_job_id && !run.input_artifact_id && !run.output_artifact_id && !run.logs_artifact_id && <p>none</p>}
              </div>
            </TableCell>
            <TableCell>
              <div className="space-y-2">
                <p>{run.failure_class ?? 'none'}</p>
                <JsonSnippet value={run.failure_detail_json} label="failure detail" />
                <JsonSnippet value={run.validation_result_json} label="validation" />
                <JsonSnippet value={run.resource_usage_json} label="resources" />
              </div>
            </TableCell>
            <TableCell>{fmt(run.completed_at)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function JsonSnippet({ value, label }: { value: Record<string, unknown> | null; label: string }) {
  if (!value || Object.keys(value).length === 0) return null
  return (
    <details className="rounded-md border border-border bg-muted/30 p-2 text-xs">
      <summary className="cursor-pointer text-muted-foreground">{label}</summary>
      <pre className="mt-2 max-h-36 overflow-auto">{JSON.stringify(value, null, 2)}</pre>
    </details>
  )
}

function JsonBlock({ value }: { value: unknown }) {
  return <pre className="max-h-72 overflow-auto rounded-md bg-muted p-3 text-xs">{JSON.stringify(value, null, 2)}</pre>
}

function ItemDecisionsSummary({ decisions }: { decisions: Array<Record<string, unknown>> }) {
  return (
    <details className="mt-1 rounded-md border border-border bg-muted/30 p-2 text-xs">
      <summary className="cursor-pointer text-muted-foreground">{decisions.length} item decisions</summary>
      <ul className="mt-2 max-h-48 space-y-1 overflow-auto">
        {decisions.map((decision, index) => (
          <li key={`${decision.intake_item_id ?? index}`} className="flex flex-wrap items-baseline gap-1.5">
            <Badge variant={relevanceBadgeVariant(decision.relevance)}>{String(decision.relevance ?? 'unknown')}</Badge>
            <span className="text-muted-foreground">{short(String(decision.intake_item_id ?? ''))}</span>
            {typeof decision.reason === 'string' && decision.reason && (
              <span className="text-muted-foreground">— {decision.reason}</span>
            )}
          </li>
        ))}
      </ul>
    </details>
  )
}

function relevanceBadgeVariant(relevance: unknown): 'success' | 'warning' | 'muted' {
  if (relevance === 'relevant') return 'success'
  if (relevance === 'maybe') return 'warning'
  return 'muted'
}

function SourceItemsTable({ items }: { items: IntakeItem[] }) {
  if (items.length === 0) return <EmptyState title="No items" description="Items from this source appear here." />
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Item</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Content</TableHead>
          <TableHead>Seen</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map(item => (
          <TableRow key={item.id}>
            <TableCell>
              <Link to={`/intake/items/${item.id}`} className="font-medium hover:underline">{item.title}</Link>
              {item.source_domain && <p className="text-xs text-muted-foreground">{item.source_domain}</p>}
            </TableCell>
            <TableCell><StatusBadge status={item.status} /></TableCell>
            <TableCell>{item.content_state}</TableCell>
            <TableCell>{fmt(item.last_seen_at)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function SourceEvidenceTable({ evidence }: { evidence: ExtractedEvidence[] }) {
  if (evidence.length === 0) return <EmptyState title="No evidence" description="Candidate evidence from this source appears here." />
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Evidence</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Method</TableHead>
          <TableHead>Created</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {evidence.map(row => (
          <TableRow key={row.id}>
            <TableCell>
              <span className="font-medium">{row.title}</span>
              {row.content_excerpt && <p className="text-xs text-muted-foreground">{row.content_excerpt}</p>}
            </TableCell>
            <TableCell><StatusBadge status={row.status} /></TableCell>
            <TableCell>{row.extraction_method}</TableCell>
            <TableCell>{fmt(row.created_at)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function SourceJobsTable({ jobs }: { jobs: ExtractionJob[] }) {
  if (jobs.length === 0) return <EmptyState title="No jobs" description="Raw extraction jobs for this source appear here." />
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Job</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Items</TableHead>
          <TableHead>Created</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {jobs.map(job => (
          <TableRow key={job.id}>
            <TableCell>
              <span className="font-medium">{job.job_type}</span>
              {job.error_message && <p className="text-xs text-destructive">{job.error_message}</p>}
            </TableCell>
            <TableCell><StatusBadge status={job.status} /></TableCell>
            <TableCell>{job.items_created ?? 0}/{job.items_seen ?? 0}</TableCell>
            <TableCell>{fmt(job.created_at)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function SecurityPanel({ version }: { version: CustomSourceHandlerVersion | null }) {
  if (!version) return <EmptyState title="No policy envelope" description="Generate a handler version first." />
  const envelope = version.policy_envelope_json
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card className="space-y-3">
        <CardHeader>
          <CardTitle>Raw Policy Envelope</CardTitle>
        </CardHeader>
        <div className="flex flex-wrap gap-1.5">
          {envelope.allowed_network_origins.map(origin => <Badge key={origin} variant="outline">{origin}</Badge>)}
        </div>
        <KeyValueGrid rows={[
          ['Capture', envelope.capture_policy],
          ['Retention', envelope.retention_policy],
          ['Credential', envelope.credential_ref ?? 'none'],
          ['Language', envelope.language],
          ['Log redaction', envelope.log_redaction_enabled ? 'enabled' : 'disabled'],
        ]} />
      </Card>
      <Card className="space-y-3">
        <CardHeader>
          <CardTitle>Sandbox</CardTitle>
        </CardHeader>
        <div className="flex flex-wrap gap-1.5">
          <Badge variant={envelope.browser_automation_enabled ? 'warning' : 'secondary'}>browser {envelope.browser_automation_enabled ? 'on' : 'off'}</Badge>
          <Badge variant={envelope.shell_enabled ? 'warning' : 'secondary'}>shell {envelope.shell_enabled ? 'on' : 'off'}</Badge>
          <Badge variant={envelope.dependency_installation_enabled ? 'warning' : 'secondary'}>deps {envelope.dependency_installation_enabled ? 'on' : 'off'}</Badge>
        </div>
        <JsonBlock value={envelope.limits} />
      </Card>
      {version.test_result_json && (
        <div className="lg:col-span-2">
          <TestResultPanel title="Test result" result={version.test_result_json} />
        </div>
      )}
    </div>
  )
}

function TestResultPanel(props: { title: string; result: Record<string, unknown> }) {
  return (
    <Card className="space-y-3">
      <CardHeader>
        <CardTitle>{props.title}</CardTitle>
      </CardHeader>
      <div className="flex items-center gap-2">
        <ShieldCheck className="size-4 text-muted-foreground" />
        <Badge variant="outline">{stringValue(props.result.status) ?? 'unknown'}</Badge>
      </div>
      <JsonBlock value={props.result} />
    </Card>
  )
}

function PolicySummary({ envelope }: { envelope: SourcePolicyEnvelope | null }) {
  if (!envelope) return <p className="text-sm text-muted-foreground">No active source policy envelope.</p>
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5">
        {envelope.allowed_network_origins.length > 0
          ? envelope.allowed_network_origins.map(origin => <Badge key={origin} variant="outline">{origin}</Badge>)
          : <Badge variant="muted">primary endpoint only</Badge>}
      </div>
      <KeyValueGrid rows={[
        ['Capture', envelope.capture_policy],
        ['Retention', envelope.retention_policy],
        ['Credential', envelope.credential_ref ?? 'none'],
        ['Log redaction', envelope.log_redaction_enabled ? 'enabled' : 'disabled'],
        ['Max items', String(envelope.limits.max_items)],
      ]} />
    </div>
  )
}

function positiveInt(value: string, fallback: number): number {
  const parsed = Number.parseInt(value, 10)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback
}

function nonNegativeInt(value: string, fallback: number): number {
  const parsed = Number.parseInt(value, 10)
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback
}

function decimalNumber(value: string, fallback: number): number {
  const parsed = Number.parseFloat(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function selectedRetrievalDomains(form: PostProcessingFormState): SourcePostProcessingRetrievalDomain[] {
  const domains = form.retrievalDomains.filter(domain => domain !== 'project' || Boolean(form.projectId))
  return Array.from(new Set(domains))
}

function sourceAllowsExternalModelProcessing(connection: SourceConnection): boolean {
  const consent = connection.consent_json ?? {}
  if (consent.allow_external_model_egress !== true) return false
  return sourceEgressClassForDisplay(connection) === 'external_provider_allowed'
}

function sourceEgressClassForDisplay(connection: SourceConnection): string {
  const consent = connection.consent_json ?? {}
  const policy = connection.policy_json ?? {}
  const raw = stringFrom(policy.source_egress_class, '')
  if (raw === 'external_provider_allowed' && consent.allow_external_model_egress === true) return raw
  if (
    raw === 'local_provider_allowed' &&
    (consent.allow_local_provider_egress === true || consent.allow_external_model_egress === true)
  ) {
    return raw
  }
  if (raw === 'internal_only') return raw
  if (consent.allow_external_model_egress === true) return 'external_provider_allowed'
  if (consent.allow_local_provider_egress === true) return 'local_provider_allowed'
  return 'internal_only'
}

function stringFrom(value: unknown, fallback: string): string {
  return typeof value === 'string' && value.trim() ? value : fallback
}

function operationStatusFromRun(status: SourcePostProcessingRun['status']): PostProcessingOperation['status'] {
  if (status === 'queued' || status === 'running') return 'running'
  if (status === 'succeeded' || status === 'skipped') return 'succeeded'
  return 'failed'
}

function operationMessageFromRun(status: SourcePostProcessingRun['status']): string {
  if (status === 'queued') return 'Run is queued and waiting to start.'
  if (status === 'running') return 'Run is still processing. Recent Runs will update as it progresses.'
  if (status === 'succeeded') return 'Run completed successfully.'
  if (status === 'skipped') return 'Run finished without new work.'
  return 'Run failed. Check Recent Runs for the error.'
}

function triggerLabel(trigger: SourcePostProcessingTriggerType): string {
  if (trigger === 'items_materialized') return 'Items materialized'
  if (trigger === 'schedule') return 'Schedule'
  return 'Manual'
}

function actionLabel(actions: SourcePostProcessingActions): string {
  const labels = POST_PROCESSING_ACTIONS
    .filter(action => actions[action.key])
    .map(action => action.label)
  return labels.length ? labels.join(', ') : 'none'
}

function cursorLabel(cursor: Record<string, unknown> | null): string {
  const watermark = cursor?.intake_watermark
  if (!watermark || typeof watermark !== 'object') return 'No cursor'
  const record = watermark as Record<string, unknown>
  return typeof record.created_at === 'string' ? `Cursor ${fmt(record.created_at)}` : 'Cursor set'
}

function retrievalContextCount(value: Record<string, unknown>): number {
  const pinned = Array.isArray(value.pinned) ? value.pinned.length : 0
  const items = Array.isArray(value.items) ? value.items.length : 0
  return pinned + items
}

function sourceKindLabel(connection: SourceConnection, activeRecipe?: SourceRecipeVersion | null) {
  if (connection.handler_kind === 'recipe') return recipeIsFeed(activeRecipe) ? 'Feed source' : 'Recipe source'
  if (connection.handler_kind === 'generated_custom') return 'Advanced handler'
  return 'Built-in source'
}

function canRunConnectionNow(connection: SourceConnection) {
  if (connection.status === 'archived') return false
  if (connection.handler_kind === 'generated_custom') return Boolean(connection.active_handler_version_id)
  if (connection.handler_kind === 'recipe') return Boolean(connection.active_recipe_version_id)
  return true
}

function recipeVersionLabel(version: SourceRecipeVersion) {
  return `${recipeIsFeed(version) ? 'feed parser' : 'recipe'} v${version.version_number}`
}

function recipePlanTitle(version: SourceRecipeVersion) {
  return recipeIsFeed(version) ? 'Feed Parser' : 'Recipe Plan'
}

function recipeIsFeed(version: SourceRecipeVersion | null | undefined) {
  const steps = Array.isArray(version?.recipe_json.steps) ? version.recipe_json.steps : []
  return steps.some(step => step.type === 'parse_rss' || step.type === 'parse_atom')
}

function sourceRunKindLabel(kind: SourceRunSummary['run_kind']) {
  if (kind === 'dry_run') return 'preview'
  if (kind === 'manual_url') return 'saved URL'
  return kind.replace(/_/g, ' ')
}

function sourceRunImplementationLabel(implementation: SourceRunSummary['implementation']) {
  if (implementation === 'generated_handler') return 'advanced handler'
  if (implementation === 'built_in') return 'built-in'
  return 'source recipe'
}

function primitiveLabel(type: string) {
  if (type === 'fetch_page') return 'Fetch source'
  if (type === 'parse_rss') return 'RSS parser'
  if (type === 'parse_atom') return 'Atom parser'
  if (type === 'extract_list') return 'List extractor'
  if (type === 'extract_single') return 'Page extractor'
  if (type === 'follow_link') return 'Link follower'
  if (type === 'download_asset') return 'Asset downloader'
  if (type === 'paginate') return 'Paginator'
  if (type === 'dedupe') return 'Dedupe'
  return type.replace(/_/g, ' ')
}

function describeRecipeStep(step: Record<string, unknown>): string {
  const type = String(step.type)
  if (type === 'fetch_page') return 'Fetches the configured page or a policy-approved URL.'
  if (type === 'parse_rss') return `Parses RSS items from ${stringValue(step.input) ?? 'the fetched content'}.`
  if (type === 'parse_atom') return `Parses Atom entries from ${stringValue(step.input) ?? 'the fetched content'}.`
  if (type === 'extract_list') return `Extracts repeated page items${stringValue(step.item_selector) ? ` with selector ${step.item_selector}` : ''}.`
  if (type === 'extract_single') return 'Extracts one page-level item.'
  if (type === 'follow_link') return 'Follows item links within the configured limits.'
  if (type === 'download_asset') return 'Downloads item assets within the configured MIME and size limits.'
  if (type === 'paginate') return 'Repeats nested fetch/extract steps across bounded pages.'
  if (type === 'dedupe') return 'Removes duplicate items before materialization.'
  return 'Runs a source recipe primitive.'
}

function stringValue(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null
}
