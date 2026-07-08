import type { ComponentType, CSSProperties, ElementType, ReactNode } from 'react'
import type { GraphProjection, GraphProjectionNode } from '@agent-space/protocol'

export interface ResearchAtlasStatus {
  ok: boolean
  plugin_id: string
  version: string
  scope: 'space'
  space_id: string
}

export interface ResearchAtlasPaper {
  id: string
  title: string
  abstract: string | null
  publication_date: string | null
  publication_year: number | null
  paper_type: string
  doi: string | null
  arxiv_id: string | null
  oa_status: string
  best_oa_url: string | null
  raw_author_names: string[]
  merged_into_id: string | null
}

export interface ResearchAtlasAuthorship {
  id: string
  scholar_id: string | null
  author_position: number
  raw_author_name: string
  raw_affiliation_text: string | null
  confidence: number | null
}

export interface ResearchAtlasExternalId {
  id_type: string
  id_value: string
  is_primary: boolean
}

export interface ResearchAtlasPaperDetail {
  paper: ResearchAtlasPaper
  authorships: ResearchAtlasAuthorship[]
  external_ids: ResearchAtlasExternalId[]
  provenance: Array<{ connector: string; fetched_at: string; fetch_status: string }>
}

export interface ResearchAtlasScholar {
  id: string
  display_name: string
  orcid: string | null
  h_index: number | null
  works_count: number | null
}

export interface ResearchAtlasScholarDetail {
  scholar: ResearchAtlasScholar
  papers: ResearchAtlasPaper[]
  external_ids: ResearchAtlasExternalId[]
  coauthors: Array<{ id: string; display_name: string; shared_paper_count: number }>
  affiliations: Array<{
    id: string
    role: string | null
    institution: { id: string; name: string } | null
    department: { id: string; name: string } | null
  }>
}

export interface ResearchAtlasSearchResult {
  entity_type: string
  id: string
  label: string
  detail: string | null
}

export interface ResearchAtlasSyncStatus {
  cursors: Array<{
    cursor_key: string
    watermark_json: Record<string, unknown>
    last_run_at: string | null
    last_error: string | null
    updated_at: string
  }>
  due_refresh_count: number
}

export interface ResearchAtlasProjectPaper {
  id: string
  project_id: string
  paper_id: string
  status: 'candidate' | 'shortlist' | 'reading' | 'done' | 'rejected'
  read_status: 'unread' | 'skimmed' | 'read'
  rating: number | null
  tags: string[]
  note: string | null
  pinned: boolean
  source: string
  source_item_id: string | null
  paper: ResearchAtlasPaper
}

export interface ResearchAtlasTopic {
  id: string
  label: string
  kind: string
  taxonomy: string
}

export interface ResearchAtlasGroup {
  id: string
  name: string
  aliases: string[]
  pi_scholar_id: string | null
  confidence: number | null
  member_count?: number
}

export interface ResearchAtlasGroupMembership {
  id: string
  group_id: string
  scholar_id: string
  role: string
  source: string
  confidence: number | null
  scholar?: ResearchAtlasScholar
}

export interface ResearchAtlasPaperRelated {
  references: ResearchAtlasPaper[]
  citations: ResearchAtlasPaper[]
  coauthors: Array<{ id: string; display_name: string }>
}

export interface ResearchAtlasApi {
  status(): Promise<ResearchAtlasStatus>
  listPapers(params?: { q?: string; year?: number; cursor?: string; limit?: number }): Promise<{ papers: ResearchAtlasPaper[]; next_cursor: string | null }>
  importPaper(input: { doi?: string; arxiv_id?: string }): Promise<{ paper: ResearchAtlasPaper; status: 'created' | 'matched'; job_id: string | null }>
  importFile(input: { format: 'bibtex' | 'ris' | 'csl_json'; content: string | unknown }): Promise<{ imported: Array<{ paper: ResearchAtlasPaper; status: 'created' | 'matched'; job_id: string | null }>; count: number }>
  getPaper(paperId: string): Promise<ResearchAtlasPaperDetail>
  patchPaper(paperId: string, input: Partial<Pick<ResearchAtlasPaper, 'title' | 'abstract' | 'publication_year' | 'paper_type' | 'doi' | 'arxiv_id'>>): Promise<{ paper: ResearchAtlasPaper }>
  search(query: string): Promise<{ results: ResearchAtlasSearchResult[] }>
  getScholar(scholarId: string): Promise<ResearchAtlasScholarDetail>
  getPaperReferences(paperId: string): Promise<{ papers: ResearchAtlasPaper[] }>
  getPaperCitations(paperId: string): Promise<{ papers: ResearchAtlasPaper[] }>
  getPaperRelated(paperId: string): Promise<ResearchAtlasPaperRelated>
  getGraph(params: { mode?: 'global' | 'library'; paper_id?: string }): Promise<GraphProjection>
  listTopics(): Promise<{ topics: ResearchAtlasTopic[] }>
  listGroups(): Promise<{ groups: ResearchAtlasGroup[] }>
  createGroup(input: { name: string; aliases?: string[]; pi_scholar_id?: string | null; confidence?: number | null }): Promise<{ group: ResearchAtlasGroup }>
  addGroupMembership(groupId: string, input: { scholar_id: string; role?: string; confidence?: number | null }): Promise<{ membership: ResearchAtlasGroupMembership }>
  exportEntities(params: { type: string; since?: string; cursor?: string; limit?: number; include_merged?: boolean; active_only?: boolean }): Promise<string>
  settings(): Promise<ResearchAtlasSyncStatus>
  syncSource(): Promise<{ imported: number; scanned: number; last_error: string | null }>
  listProjectPapers(projectId: string): Promise<{ project_id: string; papers: ResearchAtlasProjectPaper[] }>
  addProjectPaper(projectId: string, input: { paper_id: string; status?: ResearchAtlasProjectPaper['status'] }): Promise<{ project_paper: ResearchAtlasProjectPaper }>
  updateProjectPaper(projectId: string, paperId: string, input: Partial<Pick<ResearchAtlasProjectPaper, 'status' | 'read_status' | 'rating' | 'tags' | 'note' | 'pinned'>>): Promise<{ project_paper: ResearchAtlasProjectPaper }>
  removeProjectPaper(projectId: string, paperId: string): Promise<{ deleted: boolean }>
  getPluginSettings(): Promise<Record<string, unknown>>
  patchPluginSettings(settings: Record<string, unknown>): Promise<unknown>
}

export interface ResearchAtlasPluginState {
  loading: boolean
  enabled: boolean
}

export interface ResearchAtlasHostLinkProps {
  to: string
  style?: CSSProperties
  children?: ReactNode
}

export interface ResearchAtlasGraphNodeStyle {
  color?: string
  borderColor?: string
  textColor?: string
  size?: number
  shape?: 'circle' | 'rect' | 'diamond'
  haloColor?: string
}

export interface ResearchAtlasGraphEdgeStyle {
  color?: string
  textColor?: string
  width?: number
  opacity?: number
  lineDash?: number[]
}

export interface ResearchAtlasGraphViewProps {
  projection: GraphProjection | null
  theme?: {
    node?: Record<string, ResearchAtlasGraphNodeStyle>
    edge?: Record<string, ResearchAtlasGraphEdgeStyle>
  }
  loading?: boolean
  error?: string | null
  className?: string
  onNodeSelect?: (node: GraphProjectionNode | null) => void
  onNodeExpand?: (node: GraphProjectionNode) => void
  renderNodeDetails?: (node: GraphProjectionNode) => ReactNode
}

export interface ResearchAtlasWebHost {
  api: ResearchAtlasApi
  Link: ElementType<ResearchAtlasHostLinkProps>
  GraphView: ComponentType<ResearchAtlasGraphViewProps>
  usePluginState(pluginId: string): ResearchAtlasPluginState
  usePathname(): string
}
