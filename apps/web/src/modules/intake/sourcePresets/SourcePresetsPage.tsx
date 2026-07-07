import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { ArrowLeft, CheckCircle2, Library, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { intakeApi } from '../../../api/client'
import { Badge } from '../../../components/ui/badge'
import { Button } from '../../../components/ui/button'
import { Card, CardHeader, CardTitle } from '../../../components/ui/card'
import { EmptyState } from '../../../components/ui/empty-state'
import { useSpace } from '../../../contexts/SpaceContext'
import { SpaceLink as Link } from '../../../core/spaceNav'
import { errMsg } from '../../../lib/utils'
import type {
  ArxivPresetMode,
  ArxivPresetPreviewRequest,
  ArxivPresetPreviewResponse,
  SourceCapturePolicy,
  SourceConnection,
  SourcePreset,
} from '../../../types/api'
import {
  emptyScheduleFormValue,
  scheduleRuleFromForm,
  sourceCapturePolicyValue,
  type ScheduleFormValue,
} from '../intakePageModel'
import {
  sourcePostProcessingRuleForConnection,
  type SourcePostProcessingPreset,
} from '../sourcePostProcessingPresets'
import { arxivPostProcessingPresetConfig } from './academic/arxivPostProcessing'
import { ArxivSourceForm } from './academic/ArxivSourceForm'

const CATEGORY_ORDER = ['academic']
const CATEGORY_LABELS: Record<string, string> = {
  academic: 'Academic',
}

function categoryLabel(category: string) {
  return CATEGORY_LABELS[category] ?? category.replace(/_/g, ' ').replace(/\b\w/g, char => char.toUpperCase())
}

function groupPresets(presets: SourcePreset[]) {
  const byCategory = new Map<string, SourcePreset[]>()
  for (const preset of presets) {
    const rows = byCategory.get(preset.category) ?? []
    rows.push(preset)
    byCategory.set(preset.category, rows)
  }
  return Array.from(byCategory.entries())
    .sort(([a], [b]) => {
      const orderA = CATEGORY_ORDER.indexOf(a)
      const orderB = CATEGORY_ORDER.indexOf(b)
      if (orderA !== -1 || orderB !== -1) return (orderA === -1 ? 999 : orderA) - (orderB === -1 ? 999 : orderB)
      return categoryLabel(a).localeCompare(categoryLabel(b))
    })
    .map(([category, rows]) => ({
      category,
      label: categoryLabel(category),
      presets: rows.sort((a, b) => a.display_name.localeCompare(b.display_name)),
    }))
}

export default function SourcePresetsPage() {
  const { activeSpaceId, activeSpaceName } = useSpace()
  const [presets, setPresets] = useState<SourcePreset[]>([])
  const [selectedPresetId, setSelectedPresetId] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)

  const [arxivMode, setArxivMode] = useState<ArxivPresetMode>('recent_by_category')
  const [arxivName, setArxivName] = useState('')
  const [arxivQuery, setArxivQuery] = useState('')
  const [arxivCategories, setArxivCategories] = useState(['cs.AI'])
  const [arxivMaxResults, setArxivMaxResults] = useState('50')
  const [arxivFetchFrequency, setArxivFetchFrequency] = useState('daily')
  const [arxivSchedule, setArxivSchedule] = useState<ScheduleFormValue>(() => emptyScheduleFormValue())
  const [arxivCapturePolicy, setArxivCapturePolicy] = useState<SourceCapturePolicy>('extract_text')
  const [arxivPostProcessingEnabled, setArxivPostProcessingEnabled] = useState(false)
  const [arxivPostProcessingPreset, setArxivPostProcessingPreset] = useState<SourcePostProcessingPreset>('batch_digest')
  const [arxivPostProcessingCreateProposals, setArxivPostProcessingCreateProposals] = useState(false)
  const [arxivPostProcessingScreeningObjective, setArxivPostProcessingScreeningObjective] = useState('')
  const [arxivPostProcessingDeepAnalysis, setArxivPostProcessingDeepAnalysis] = useState(false)
  const [arxivPreview, setArxivPreview] = useState<ArxivPresetPreviewResponse | null>(null)
  const [createdConnection, setCreatedConnection] = useState<SourceConnection | null>(null)

  const grouped = useMemo(() => groupPresets(presets), [presets])
  const selectedPreset = useMemo(
    () => presets.find(preset => preset.id === selectedPresetId) ?? presets[0] ?? null,
    [presets, selectedPresetId],
  )
  const arxivPreset = selectedPreset?.id === 'arxiv' ? selectedPreset : null

  const load = useCallback(async () => {
    if (!activeSpaceId) {
      setPresets([])
      setSelectedPresetId('')
      setLoading(false)
      return
    }
    setLoading(true)
    try {
      const response = await intakeApi.sourcePresets()
      setPresets(response.items)
      setSelectedPresetId(current => response.items.some(item => item.id === current) ? current : response.items[0]?.id ?? '')
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setLoading(false)
    }
  }, [activeSpaceId])

  useEffect(() => { load() }, [load])

  function arxivRequestBase(): ArxivPresetPreviewRequest {
    const parsedMaxResults = Number.parseInt(arxivMaxResults, 10)
    return {
      mode: arxivMode,
      ...(arxivMode === 'recent_by_category'
        ? { categories: arxivCategories }
        : { search_query: arxivQuery.trim() }),
      ...(Number.isFinite(parsedMaxResults) ? { max_results: parsedMaxResults } : {}),
    }
  }

  function changeArxivMode(value: ArxivPresetMode) {
    setArxivMode(value)
    setArxivPreview(null)
    setCreatedConnection(null)
    setArxivFetchFrequency(current => {
      if (value === 'recent_by_category' && current === 'weekly') return 'daily'
      return current
    })
  }

  async function previewArxivSource(event: FormEvent) {
    event.preventDefault()
    setBusy('arxiv:preview')
    setCreatedConnection(null)
    try {
      const result = await intakeApi.previewArxivSourcePreset({
        ...arxivRequestBase(),
        max_results: 10,
      })
      setArxivPreview(result)
      toast.success(`arXiv preview: ${result.items.length} sample paper${result.items.length === 1 ? '' : 's'}`)
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBusy(null)
    }
  }

  async function createArxivSource() {
    setBusy('arxiv:create')
    try {
      const row = await intakeApi.createArxivSourcePreset({
        ...arxivRequestBase(),
        name: arxivName.trim() || undefined,
        fetch_frequency: arxivFetchFrequency as 'manual' | 'hourly' | 'daily' | 'weekly',
        schedule_rule: scheduleRuleFromForm(arxivFetchFrequency, arxivSchedule),
        capture_policy: arxivCapturePolicy,
      })
      setCreatedConnection(row)
      await createPostProcessingPreset(row)
      toast.success(`arXiv source created: ${row.name}`)
      setArxivName('')
      setArxivSchedule(emptyScheduleFormValue())
      if (arxivMode === 'search') setArxivQuery('')
      setArxivPreview(null)
      resetArxivPostProcessingPreset()
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBusy(null)
    }
  }

  async function createPostProcessingPreset(connection: SourceConnection): Promise<boolean> {
    const rule = sourcePostProcessingRuleForConnection(connection, arxivPostProcessingPresetConfig({
      enabled: arxivPostProcessingEnabled,
      preset: arxivPostProcessingPreset,
      createProposals: arxivPostProcessingCreateProposals,
      mode: arxivMode,
      categories: arxivCategories,
      searchQuery: arxivQuery,
      screeningObjective: arxivPostProcessingScreeningObjective,
      deepAnalysis: arxivPostProcessingDeepAnalysis,
    }))
    if (!rule) return false
    try {
      await intakeApi.createPostProcessingRule(connection.id, rule)
      toast.success('Post-processing preset added')
      return true
    } catch (e) {
      toast.error(`Source created, post-processing setup failed: ${errMsg(e)}`)
      return false
    }
  }

  function resetArxivPostProcessingPreset() {
    setArxivPostProcessingEnabled(false)
    setArxivPostProcessingPreset('batch_digest')
    setArxivPostProcessingCreateProposals(false)
    setArxivPostProcessingScreeningObjective('')
  }

  function changeArxivFetchFrequency(value: string) {
    setArxivFetchFrequency(value)
    setArxivSchedule(emptyScheduleFormValue())
  }

  if (!activeSpaceId) {
    return (
      <div className="p-6">
        <EmptyState title="No space selected" description="Select an operational space to use Intake." />
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between gap-4 pb-4 border-b border-border">
        <div className="flex items-center gap-4 min-w-0">
          <div
            className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
            style={{
              background: 'color-mix(in oklch, var(--primary) 12%, transparent)',
              border: '1px solid color-mix(in oklch, var(--primary) 35%, transparent)',
            }}
          >
            <Library className="size-5 text-accent-foreground" />
          </div>
          <div className="min-w-0">
            <h1 className="text-xl font-semibold tracking-tight">Preset Sources</h1>
            <p className="text-sm text-muted-foreground">Viewing: {activeSpaceName ?? activeSpaceId}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={load} disabled={loading} type="button">
            <RefreshCw className="size-4" />
            Refresh
          </Button>
          <Button variant="outline" asChild>
            <Link to="/intake">
              <ArrowLeft className="size-4" />
              Intake
            </Link>
          </Button>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[340px_minmax(0,1fr)]">
        <div className="space-y-5">
          {loading ? (
            <Card><p className="text-muted-foreground text-center py-8 text-sm">Loading...</p></Card>
          ) : grouped.length === 0 ? (
            <EmptyState title="No preset sources" description="No source presets are available in this space." />
          ) : (
            grouped.map(group => (
              <section key={group.category} className="space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">{group.label}</h2>
                  <Badge variant="muted">{group.presets.length}</Badge>
                </div>
                <div className="grid gap-2">
                  {group.presets.map(preset => {
                    const selected = selectedPreset?.id === preset.id
                    return (
                      <button
                        key={preset.id}
                        type="button"
                        className={[
                          'w-full rounded-md border p-3 text-left transition-colors',
                          selected
                            ? 'border-primary bg-primary/5'
                            : 'border-border bg-background hover:bg-muted/40',
                        ].join(' ')}
                        onClick={() => {
                          setSelectedPresetId(preset.id)
                          setCreatedConnection(null)
                        }}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-sm font-medium">{preset.display_name}</span>
                          <Badge variant="outline">{preset.connector_key}</Badge>
                        </div>
                        <p className="mt-1 text-xs text-muted-foreground line-clamp-2">{preset.description}</p>
                      </button>
                    )
                  })}
                </div>
              </section>
            ))
          )}
        </div>

        <div className="min-w-0">
          {arxivPreset ? (
            <Card>
              <CardHeader>
                <CardTitle>{arxivPreset.display_name}</CardTitle>
              </CardHeader>
              <ArxivSourceForm
                preset={arxivPreset}
                mode={arxivMode}
                name={arxivName}
                searchQuery={arxivQuery}
                categories={arxivCategories}
                maxResults={arxivMaxResults}
                fetchFrequency={arxivFetchFrequency}
                schedule={arxivSchedule}
                capturePolicy={arxivCapturePolicy}
                postProcessingEnabled={arxivPostProcessingEnabled}
                postProcessingPreset={arxivPostProcessingPreset}
                postProcessingCreateProposals={arxivPostProcessingCreateProposals}
                postProcessingScreeningObjective={arxivPostProcessingScreeningObjective}
                postProcessingDeepAnalysis={arxivPostProcessingDeepAnalysis}
                preview={arxivPreview}
                busy={busy}
                onModeChange={changeArxivMode}
                onNameChange={setArxivName}
                onSearchQueryChange={(value) => {
                  setArxivQuery(value)
                  setArxivPreview(null)
                  setCreatedConnection(null)
                }}
                onCategoriesChange={(value) => {
                  setArxivCategories(value)
                  setArxivPreview(null)
                  setCreatedConnection(null)
                }}
                onMaxResultsChange={setArxivMaxResults}
                onFetchFrequencyChange={changeArxivFetchFrequency}
                onScheduleChange={setArxivSchedule}
                onCapturePolicyChange={value => setArxivCapturePolicy(sourceCapturePolicyValue(value, arxivCapturePolicy))}
                onPostProcessingEnabledChange={setArxivPostProcessingEnabled}
                onPostProcessingPresetChange={setArxivPostProcessingPreset}
                onPostProcessingCreateProposalsChange={setArxivPostProcessingCreateProposals}
                onPostProcessingScreeningObjectiveChange={setArxivPostProcessingScreeningObjective}
                onPostProcessingDeepAnalysisChange={setArxivPostProcessingDeepAnalysis}
                onPreview={previewArxivSource}
                onCreate={createArxivSource}
              />
              {createdConnection && (
                <div className="mt-4 rounded-md border border-border bg-muted/20 p-3">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Badge variant="secondary">created</Badge>
                    <Badge variant="outline">{createdConnection.fetch_frequency}</Badge>
                    <Badge variant="muted">{createdConnection.capture_policy}</Badge>
                  </div>
                  <div className="mt-3 flex items-center justify-between gap-3">
                    <p className="text-sm font-medium truncate">{createdConnection.name}</p>
                    <Button type="button" size="sm" variant="outline" asChild>
                      <Link to={`/intake/sources/${createdConnection.id}`}>
                        <CheckCircle2 className="size-3.5" />
                        Details
                      </Link>
                    </Button>
                  </div>
                </div>
              )}
            </Card>
          ) : (
            <EmptyState title="No preset selected" description="Select a preset source." />
          )}
        </div>
      </div>
    </div>
  )
}
