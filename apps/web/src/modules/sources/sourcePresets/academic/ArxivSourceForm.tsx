import { useMemo, useState, type FormEvent } from 'react'
import { CheckCircle2, ChevronDown, Sparkles } from 'lucide-react'
import { Badge } from '../../../../components/ui/badge'
import { Button } from '../../../../components/ui/button'
import { Input } from '../../../../components/ui/input'
import { Label } from '../../../../components/ui/label'
import { Select } from '../../../../components/ui/select'
import { Textarea } from '../../../../components/ui/textarea'
import type { ArxivPresetMode, ArxivPresetPreviewResponse, SourceCapturePolicy, SourcePreset } from '../../../../types/api'
import { ScheduleRuleFields } from '../../SourcesPageSections'
import { CAPTURE_POLICIES, capturePolicyDescription, FREQUENCIES, fmt, isScheduleFormComplete, preview, type ScheduleFormValue } from '../../sourcePageModel'
import {
  SOURCE_POST_PROCESSING_PRESET_OPTIONS,
  type SourcePostProcessingPreset,
} from '../../sourcePostProcessingPresets'

const ARXIV_MODE_OPTIONS = [
  { value: 'recent_by_category', label: 'Recent by category' },
  { value: 'search', label: 'Search query' },
]

function toggleCategorySelection(selected: string[], value: string) {
  if (selected.includes(value)) return selected.filter(category => category !== value)
  return [...selected, value]
}

export function ArxivSourceForm(props: {
  preset: SourcePreset
  mode: ArxivPresetMode
  name: string
  searchQuery: string
  categories: string[]
  maxResults: string
  fetchFrequency: string
  schedule: ScheduleFormValue
  capturePolicy: SourceCapturePolicy
  postProcessingEnabled: boolean
  postProcessingPreset: SourcePostProcessingPreset
  postProcessingCreateProposals: boolean
  postProcessingScreeningObjective: string
  postProcessingDeepAnalysis: boolean
  preview: ArxivPresetPreviewResponse | null
  busy: string | null
  onModeChange: (value: ArxivPresetMode) => void
  onNameChange: (value: string) => void
  onSearchQueryChange: (value: string) => void
  onCategoriesChange: (value: string[]) => void
  onMaxResultsChange: (value: string) => void
  onFetchFrequencyChange: (value: string) => void
  onScheduleChange: (value: ScheduleFormValue) => void
  onCapturePolicyChange: (value: string) => void
  onPostProcessingEnabledChange: (value: boolean) => void
  onPostProcessingPresetChange: (value: SourcePostProcessingPreset) => void
  onPostProcessingCreateProposalsChange: (value: boolean) => void
  onPostProcessingScreeningObjectiveChange: (value: string) => void
  onPostProcessingDeepAnalysisChange: (value: boolean) => void
  onPreview: (event: FormEvent<HTMLFormElement>) => void
  onCreate: () => void
}) {
  const [categoryFilter, setCategoryFilter] = useState('')
  const hasRequiredInput = props.mode === 'recent_by_category'
    ? props.categories.length > 0
    : Boolean(props.searchQuery.trim())
  const scheduleReady = isScheduleFormComplete(props.fetchFrequency, props.schedule)
  const categorySummary = props.categories.length > 0 ? props.categories.join(', ') : 'Select categories'
  const visibleCategoryGroups = useMemo(() => {
    const query = categoryFilter.trim().toLowerCase()
    const groups = props.preset.category_options ?? []
    if (!query) return groups
    return groups
      .map(group => ({
        ...group,
        options: group.options.filter(option =>
          `${group.group} ${option.value} ${option.label}`.toLowerCase().includes(query),
        ),
      }))
      .filter(group => group.options.length > 0)
  }, [categoryFilter, props.preset.category_options])
  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">{props.preset.display_name} - {props.preset.description}</p>
      <form className="space-y-3" onSubmit={props.onPreview}>
        <div className="space-y-1.5">
          <Label>Mode</Label>
          <Select
            options={ARXIV_MODE_OPTIONS}
            value={props.mode}
            onChange={value => props.onModeChange(value as ArxivPresetMode)}
          />
        </div>
        {props.mode === 'recent_by_category' ? (
          <div className="space-y-2">
            <Label>Categories</Label>
            <details className="rounded-md border border-border bg-input">
              <summary className="flex h-9 cursor-pointer list-none items-center justify-between gap-3 px-3 text-sm">
                <span className="truncate">{categorySummary}</span>
                <ChevronDown className="size-4 shrink-0 text-muted-foreground" />
              </summary>
              <div className="border-t border-border bg-background p-2">
                <Input
                  value={categoryFilter}
                  onChange={event => setCategoryFilter(event.target.value)}
                  placeholder="Filter categories"
                  className="mb-2 h-8"
                />
                <div className="max-h-72 space-y-3 overflow-auto pr-1">
                  {visibleCategoryGroups.map(group => (
                    <div key={group.group} className="space-y-1">
                      <p className="px-2 text-[11px] font-semibold uppercase text-muted-foreground">{group.group}</p>
                      <div className="grid gap-1.5 sm:grid-cols-2">
                        {group.options.map(option => {
                          const checked = props.categories.includes(option.value)
                          const disabled = !checked && props.categories.length >= 10
                          return (
                            <label
                              key={option.value}
                              className={[
                                'flex min-h-9 cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-muted/70',
                                disabled ? 'cursor-not-allowed opacity-50' : '',
                              ].join(' ')}
                            >
                              <input
                                type="checkbox"
                                checked={checked}
                                disabled={disabled}
                                onChange={() => props.onCategoriesChange(toggleCategorySelection(props.categories, option.value))}
                              />
                              <span className="font-mono text-xs">{option.value}</span>
                              <span className="min-w-0 truncate text-xs text-muted-foreground">{option.label}</span>
                            </label>
                          )
                        })}
                      </div>
                    </div>
                  ))}
                  {visibleCategoryGroups.length === 0 && (
                    <p className="px-2 py-3 text-xs text-muted-foreground">No categories match.</p>
                  )}
                </div>
              </div>
            </details>
            {props.categories.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {props.categories.map(category => (
                  <Badge key={category} variant="outline">{category}</Badge>
                ))}
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-1.5">
            <Label>Search query</Label>
            <Input
              value={props.searchQuery}
              onChange={event => props.onSearchQueryChange(event.target.value)}
              placeholder='cat:cs.AI AND all:"agent"'
              required
            />
          </div>
        )}
        <div className="space-y-1.5">
          <Label>Source name</Label>
          <Input
            value={props.name}
            onChange={event => props.onNameChange(event.target.value)}
            placeholder="arXiv source name"
          />
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label>Max results</Label>
            <Input
              type="number"
              min={1}
              max={100}
              value={props.maxResults}
              onChange={event => props.onMaxResultsChange(event.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label>Frequency</Label>
            <Select options={FREQUENCIES} value={props.fetchFrequency} onChange={props.onFetchFrequencyChange} />
          </div>
        </div>
        <ScheduleRuleFields
          fetchFrequency={props.fetchFrequency}
          value={props.schedule}
          onChange={props.onScheduleChange}
        />
        <div className="space-y-1.5">
          <Label>Capture</Label>
          <Select options={CAPTURE_POLICIES} value={props.capturePolicy} onChange={props.onCapturePolicyChange} />
          <p className="text-xs text-muted-foreground">{capturePolicyDescription(props.capturePolicy)}</p>
        </div>
        <details className="rounded-md border border-border bg-muted/20 p-3">
          <summary className="cursor-pointer text-sm font-medium">Advanced</summary>
          <div className="mt-3 space-y-3">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="size-4 rounded border-border"
                checked={props.postProcessingEnabled}
                onChange={event => props.onPostProcessingEnabledChange(event.target.checked)}
              />
              <span>Enable post-processing after source</span>
            </label>
            {props.postProcessingEnabled && (
              <>
                <div className="space-y-1.5">
                  <Label>Preset</Label>
                  <Select
                    options={SOURCE_POST_PROCESSING_PRESET_OPTIONS}
                    value={props.postProcessingPreset}
                    onChange={value => props.onPostProcessingPresetChange(value as SourcePostProcessingPreset)}
                  />
                </div>
                {props.postProcessingPreset === 'screen_relevant_papers' && (
                  <>
                    <div className="space-y-1.5">
                      <Label>Screening objective</Label>
                      <Textarea
                        value={props.postProcessingScreeningObjective}
                        onChange={event => props.onPostProcessingScreeningObjectiveChange(event.target.value)}
                        placeholder="e.g. Papers on retrieval-augmented agent memory and context selection"
                        rows={3}
                      />
                      <p className="text-xs text-muted-foreground">
                        Decisions use title, abstract, and metadata first. Leave blank to screen broadly against this stream.
                      </p>
                    </div>
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        className="size-4 rounded border-border"
                        checked={props.postProcessingDeepAnalysis}
                        onChange={event => props.onPostProcessingDeepAnalysisChange(event.target.checked)}
                      />
                      <span>Deep analysis after screening</span>
                    </label>
                  </>
                )}
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="size-4 rounded border-border"
                    checked={props.postProcessingCreateProposals}
                    onChange={event => props.onPostProcessingCreateProposalsChange(event.target.checked)}
                  />
                  <span>Create proposals</span>
                </label>
              </>
            )}
          </div>
        </details>
        <div className="grid gap-2 sm:grid-cols-2">
          <Button type="submit" variant="outline" disabled={props.busy === 'arxiv:preview' || !hasRequiredInput}>
            <Sparkles className="size-4" />
            Preview
          </Button>
          <Button type="button" disabled={props.busy === 'arxiv:create' || !hasRequiredInput || !scheduleReady} onClick={props.onCreate}>
            <CheckCircle2 className="size-4" />
            Create source
          </Button>
        </div>
      </form>
      {props.preview && (
        <div className="space-y-2 rounded-md border border-border bg-muted/20 p-3">
          <div className="flex flex-wrap gap-1.5">
            <Badge variant="outline">arXiv</Badge>
            <Badge variant="muted">{props.preview.items.length} sample papers</Badge>
          </div>
          {props.preview.items.length === 0 ? (
            <p className="text-xs text-muted-foreground">No papers matched this query.</p>
          ) : (
            props.preview.items.slice(0, 5).map(paper => (
              <div key={paper.arxiv_id} className="rounded-md border border-border bg-background/60 p-2 space-y-1">
                <p className="text-sm font-medium line-clamp-2">{paper.title}</p>
                {paper.authors.length > 0 && (
                  <p className="text-xs text-muted-foreground line-clamp-1">{paper.authors.join(', ')}</p>
                )}
                <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                  {paper.primary_category && <Badge variant="muted">{paper.primary_category}</Badge>}
                  <span>{fmt(paper.published_at ?? paper.updated_at)}</span>
                </div>
                <p className="text-xs text-muted-foreground line-clamp-2">{preview(paper.summary, paper.abs_url)}</p>
              </div>
            ))
          )}
          {props.preview.warnings.slice(0, 3).map((warning, index) => (
            <p key={`${warning}-${index}`} className="text-xs text-muted-foreground">{warning}</p>
          ))}
        </div>
      )}
    </div>
  )
}
