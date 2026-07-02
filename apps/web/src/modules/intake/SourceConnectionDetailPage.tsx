import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { ArrowLeft, CheckCircle2, Code2, RefreshCw, ShieldCheck, TestTube2 } from 'lucide-react'
import { intakeApi } from '../../api/client'
import { Badge, StatusBadge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Card, CardHeader, CardTitle } from '../../components/ui/card'
import { EmptyState } from '../../components/ui/empty-state'
import { Skeleton } from '../../components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../components/ui/tabs'
import { Textarea } from '../../components/ui/textarea'
import { SpaceLink as Link } from '../../core/spaceNav'
import { useSpace } from '../../contexts/SpaceContext'
import { errMsg, isNotFoundError } from '../../lib/utils'
import type {
  CustomSourceHandlerRun,
  CustomSourceHandlerSummary,
  CustomSourceHandlerVersion,
  ExtractedEvidence,
  ExtractionJob,
  IntakeItem,
  SourceConnection,
  SourcePolicyEnvelope,
  SourceRecipeDryRunResult,
  SourceRecipeVersion,
  SourceRunSummary,
} from '../../types/api'
import { fmt, short } from './intakePageModel'

const DEFAULT_FIXTURE = '<html><body><article><a href="/item">Title</a><p>Excerpt text.</p></article></body></html>'

export default function SourceConnectionDetailPage() {
  const { connectionId = '' } = useParams()
  const { activeSpaceId } = useSpace()
  const [connection, setConnection] = useState<SourceConnection | null>(null)
  const [summary, setSummary] = useState<CustomSourceHandlerSummary | null>(null)
  const [handlerVersions, setHandlerVersions] = useState<CustomSourceHandlerVersion[]>([])
  const [handlerRuns, setHandlerRuns] = useState<CustomSourceHandlerRun[]>([])
  const [recipeVersions, setRecipeVersions] = useState<SourceRecipeVersion[]>([])
  const [sourceRuns, setSourceRuns] = useState<SourceRunSummary[]>([])
  const [items, setItems] = useState<IntakeItem[]>([])
  const [evidence, setEvidence] = useState<ExtractedEvidence[]>([])
  const [jobs, setJobs] = useState<ExtractionJob[]>([])
  const [fixtureHtml, setFixtureHtml] = useState(DEFAULT_FIXTURE)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)

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

  const load = useCallback(async () => {
    if (!activeSpaceId || !connectionId) {
      setConnection(null)
      setLoading(false)
      return
    }
    setLoading(true)
    try {
      const row = await intakeApi.getConnection(connectionId)
      setConnection(row)
      const [itemPage, jobPage, evidencePage, runPage] = await Promise.all([
        intakeApi.items({ connection_id: connectionId, limit: 20 }),
        intakeApi.jobs({ connection_id: connectionId, limit: 20 }),
        intakeApi.evidence({ connection_id: connectionId, limit: 20 }),
        intakeApi.sourceRuns(connectionId, { limit: 30 }),
      ])
      setItems(itemPage.items)
      setJobs(jobPage.items)
      setEvidence(evidencePage.items)
      setSourceRuns(runPage.items)

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
      setConnection(null)
    } finally {
      setLoading(false)
    }
  }, [activeSpaceId, connectionId])

  useEffect(() => { void load() }, [load])

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
    setBusy(`activate:${version.id}`)
    try {
      const result = await intakeApi.activateCustomSourceHandler(connection.id, {
        handler_version_id: version.id,
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
        <Button variant="outline" onClick={load} disabled={loading || Boolean(busy)}>
          <RefreshCw className="size-4" />
          Refresh
        </Button>
      </div>

      <Tabs defaultValue="overview" className="space-y-4">
        <TabsList className="flex h-auto flex-wrap justify-start">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="plan">Plan</TabsTrigger>
          <TabsTrigger value="preview">Preview</TabsTrigger>
          <TabsTrigger value="items">Items</TabsTrigger>
          <TabsTrigger value="evidence">Evidence</TabsTrigger>
          <TabsTrigger value="runs">Runs</TabsTrigger>
          <TabsTrigger value="advanced">Advanced</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-4">
          <OverviewPanel connection={connection} activeRecipe={activeRecipe} activeHandler={summary?.active_handler_version ?? null} />
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
          ['Frequency', props.connection.fetch_frequency],
          ['Last checked', fmt(props.connection.last_checked_at)],
          ['Next check', fmt(props.connection.next_check_at)],
          ['Capture', props.connection.capture_policy],
        ]} />
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

function sourceKindLabel(connection: SourceConnection, activeRecipe?: SourceRecipeVersion | null) {
  if (connection.handler_kind === 'recipe') return recipeIsFeed(activeRecipe) ? 'Feed source' : 'Recipe source'
  if (connection.handler_kind === 'generated_custom') return 'Advanced handler'
  return 'Built-in source'
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
