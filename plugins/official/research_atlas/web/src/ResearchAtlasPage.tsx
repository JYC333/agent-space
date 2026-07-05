import { useCallback, useEffect, useMemo, useState, type ComponentType, type CSSProperties } from 'react'
import type { GraphProjection, GraphProjectionNode } from '@agent-space/protocol'
import type {
  ResearchAtlasPaper,
  ResearchAtlasPaperDetail,
  ResearchAtlasGroup,
  ResearchAtlasGraphViewProps,
  ResearchAtlasPaperRelated,
  ResearchAtlasProjectPaper,
  ResearchAtlasScholarDetail,
  ResearchAtlasSearchResult,
  ResearchAtlasSyncStatus,
  ResearchAtlasStatus,
  ResearchAtlasWebHost,
} from './host'

export type {
  ResearchAtlasApi,
  ResearchAtlasGraphViewProps,
  ResearchAtlasPaper,
  ResearchAtlasPaperDetail,
  ResearchAtlasScholarDetail,
  ResearchAtlasStatus,
  ResearchAtlasWebHost,
} from './host'

const PLUGIN_ID = 'research_atlas'
type AtlasGraphMode = 'library' | 'paper'

const shellStyle: CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 14,
  padding: 20,
  maxWidth: 1180,
  margin: '0 auto',
}
const toolbarStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  gap: 12,
  flexWrap: 'wrap',
}
const panelStyle: CSSProperties = {
  border: '1px solid #e5e7eb',
  borderRadius: 8,
  background: '#fff',
  padding: 14,
}
const gridStyle: CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'minmax(0, 1.2fr) minmax(320px, 0.8fr)',
  gap: 14,
  alignItems: 'start',
}
const titleStyle: CSSProperties = {
  fontSize: 22,
  lineHeight: 1.25,
  margin: 0,
  fontWeight: 700,
}
const sectionTitleStyle: CSSProperties = {
  fontSize: 12,
  fontWeight: 700,
  color: '#4b5563',
  textTransform: 'uppercase',
  margin: '0 0 10px',
}
const mutedStyle: CSSProperties = { color: '#6b7280', fontSize: 13, margin: 0 }
const inputStyle: CSSProperties = {
  border: '1px solid #d1d5db',
  borderRadius: 6,
  padding: '7px 9px',
  fontSize: 13,
  fontFamily: 'inherit',
  minWidth: 0,
}
const buttonStyle: CSSProperties = {
  border: '1px solid #d1d5db',
  borderRadius: 6,
  padding: '7px 10px',
  background: '#fff',
  fontSize: 13,
  cursor: 'pointer',
  whiteSpace: 'nowrap',
}
const primaryButtonStyle: CSSProperties = {
  ...buttonStyle,
  background: '#1f6feb',
  borderColor: '#1f6feb',
  color: '#fff',
  fontWeight: 600,
}
const tableStyle: CSSProperties = { width: '100%', borderCollapse: 'collapse', fontSize: 13 }
const thStyle: CSSProperties = {
  textAlign: 'left',
  color: '#6b7280',
  fontWeight: 600,
  borderBottom: '1px solid #e5e7eb',
  padding: '6px 8px',
}
const tdStyle: CSSProperties = { borderBottom: '1px solid #f3f4f6', padding: '7px 8px', verticalAlign: 'top' }
const graphExplorerStyle: CSSProperties = {
  display: 'flex',
  flexWrap: 'wrap',
  gap: 12,
  alignItems: 'stretch',
  flex: 1,
  minHeight: 0,
}
const graphPageShellStyle: CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 12,
  padding: 16,
  minHeight: 'calc(100vh - 4rem)',
  boxSizing: 'border-box',
}
const graphCanvasPanelStyle: CSSProperties = {
  flex: '1 1 640px',
  minWidth: 0,
  minHeight: 'calc(100vh - 9rem)',
  display: 'flex',
  flexDirection: 'column',
}
const graphSidePanelStyle: CSSProperties = {
  ...panelStyle,
  flex: '0 1 340px',
  minWidth: 280,
  minHeight: 0,
  overflow: 'auto',
}
const atlasGraphTheme: NonNullable<ResearchAtlasGraphViewProps['theme']> = {
  node: {
    paper: { color: '#2563eb', borderColor: '#1d4ed8', size: 32 },
    scholar: { color: '#ec4899', borderColor: '#be185d', size: 26 },
    venue: { color: '#14b8a6', borderColor: '#0f766e', size: 28, shape: 'diamond' },
  },
  edge: {
    references: { color: '#2563eb', width: 1.4, opacity: 0.45 },
    authored_by: { color: '#ec4899', width: 1.1, opacity: 0.36 },
    published_in: { color: '#14b8a6', width: 1.2, opacity: 0.4 },
  },
}

function ResearchAtlasPage({ host }: { host: ResearchAtlasWebHost }) {
  const pluginState = host.usePluginState(PLUGIN_ID)
  const [status, setStatus] = useState<ResearchAtlasStatus | null>(null)
  const [papers, setPapers] = useState<ResearchAtlasPaper[]>([])
  const [selectedPaperId, setSelectedPaperId] = useState<string | null>(null)
  const [detail, setDetail] = useState<ResearchAtlasPaperDetail | null>(null)
  const [related, setRelated] = useState<ResearchAtlasPaperRelated | null>(null)
  const [paperGraph, setPaperGraph] = useState<GraphProjection | null>(null)
  const [paperGraphLoading, setPaperGraphLoading] = useState(false)
  const [paperGraphError, setPaperGraphError] = useState<string | null>(null)
  const [libraryGraph, setLibraryGraph] = useState<GraphProjection | null>(null)
  const [libraryGraphLoading, setLibraryGraphLoading] = useState(false)
  const [libraryGraphError, setLibraryGraphError] = useState<string | null>(null)
  const [graphMode, setGraphMode] = useState<AtlasGraphMode>('library')
  const [scholar, setScholar] = useState<ResearchAtlasScholarDetail | null>(null)
  const [query, setQuery] = useState('')
  const [searchResults, setSearchResults] = useState<ResearchAtlasSearchResult[]>([])
  const [importValue, setImportValue] = useState('')
  const [bulkFormat, setBulkFormat] = useState<'bibtex' | 'ris' | 'csl_json'>('bibtex')
  const [bulkContent, setBulkContent] = useState('')
  const [syncStatus, setSyncStatus] = useState<ResearchAtlasSyncStatus | null>(null)
  const [settings, setSettings] = useState<Record<string, unknown>>({})
  const [topics, setTopics] = useState<Array<{ id: string; label: string; taxonomy: string }>>([])
  const [groups, setGroups] = useState<ResearchAtlasGroup[]>([])
  const [groupName, setGroupName] = useState('')
  const [groupAliases, setGroupAliases] = useState('')
  const [groupPi, setGroupPi] = useState('')
  const [selectedGroupId, setSelectedGroupId] = useState('')
  const [memberScholarId, setMemberScholarId] = useState('')
  const [memberRole, setMemberRole] = useState('unknown')
  const [exportPreview, setExportPreview] = useState('')
  const [projectId, setProjectId] = useState(initialProjectId())
  const [projectPapers, setProjectPapers] = useState<ResearchAtlasProjectPaper[]>([])
  const [editTitle, setEditTitle] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const pathname = host.usePathname()
  const graphPageActive = pathname.endsWith('/atlas/graph')
  const Link = host.Link

  const loadPapers = useCallback(async (q = query) => {
    setLoading(true)
    setError(null)
    try {
      const [statusResult, papersResult, syncResult, settingsResult, topicsResult, groupsResult] = await Promise.all([
        host.api.status(),
        host.api.listPapers({ q: q.trim() || undefined, limit: 50 }),
        host.api.settings(),
        host.api.getPluginSettings(),
        host.api.listTopics(),
        host.api.listGroups(),
      ])
      setStatus(statusResult)
      setPapers(papersResult.papers)
      setSyncStatus(syncResult)
      setSettings(settingsResult)
      setTopics(topicsResult.topics)
      setGroups(groupsResult.groups)
      setSelectedGroupId((current) => current || groupsResult.groups[0]?.id || '')
      if (!selectedPaperId && papersResult.papers[0]) {
        setSelectedPaperId(papersResult.papers[0].id)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load Research Atlas')
    } finally {
      setLoading(false)
    }
  }, [host, query, selectedPaperId])

  useEffect(() => {
    if (!pluginState.enabled) return
    void loadPapers('')
  }, [loadPapers, pluginState.enabled])

  useEffect(() => {
    if (!pluginState.enabled || !selectedPaperId) {
      setDetail(null)
      setRelated(null)
      setPaperGraph(null)
      setPaperGraphLoading(false)
      setPaperGraphError(null)
      return
    }
    let cancelled = false
    setDetail(null)
    setRelated(null)
    setPaperGraph(null)
    setPaperGraphLoading(true)
    setPaperGraphError(null)
    setScholar(null)
    setError(null)
    Promise.all([
      host.api.getPaper(selectedPaperId),
      host.api.getPaperRelated(selectedPaperId),
      host.api.getGraph({ paper_id: selectedPaperId }),
    ])
      .then(([nextDetail, nextRelated, nextGraph]) => {
        if (!cancelled) {
          setDetail(nextDetail)
          setRelated(nextRelated)
          setPaperGraph(nextGraph)
          setEditTitle(nextDetail.paper.title)
          setScholar(null)
        }
      })
      .catch((err) => {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : 'Unable to load paper'
          setError(message)
          setPaperGraphError(message)
        }
      })
      .finally(() => {
        if (!cancelled) setPaperGraphLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [host, pluginState.enabled, selectedPaperId])

  useEffect(() => {
    if (!pluginState.enabled || !graphPageActive) return
    let cancelled = false
    setLibraryGraphLoading(true)
    setLibraryGraphError(null)
    host.api.getGraph({ mode: 'global' })
      .then((nextGraph) => {
        if (!cancelled) setLibraryGraph(nextGraph)
      })
      .catch((err) => {
        if (!cancelled) {
          setLibraryGraph(null)
          setLibraryGraphError(err instanceof Error ? err.message : 'Unable to load library graph')
        }
      })
      .finally(() => {
        if (!cancelled) setLibraryGraphLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [host, pluginState.enabled, graphPageActive])

  useEffect(() => {
    if (!pluginState.enabled || query.trim().length < 2) {
      setSearchResults([])
      return
    }
    let cancelled = false
    host.api.search(query.trim())
      .then((result) => {
        if (!cancelled) setSearchResults(result.results)
      })
      .catch(() => {
        if (!cancelled) setSearchResults([])
      })
    return () => {
      cancelled = true
    }
  }, [host, pluginState.enabled, query])

  const importMode = useMemo<'doi' | 'arxiv_id'>(() => {
    return /^\d{4}\.\d{4,5}/.test(importValue.trim()) || importValue.includes('arxiv.org') ? 'arxiv_id' : 'doi'
  }, [importValue])

  const importPaper = async () => {
    if (!importValue.trim()) return
    setLoading(true)
    setError(null)
    try {
      const result = await host.api.importPaper({ [importMode]: importValue.trim() })
      setSelectedPaperId(result.paper.id)
      setImportValue('')
      await loadPapers(query)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to import paper')
    } finally {
      setLoading(false)
    }
  }

  const importBulk = async () => {
    if (!bulkContent.trim()) return
    setLoading(true)
    setError(null)
    try {
      const content = bulkFormat === 'csl_json' ? JSON.parse(bulkContent) as unknown : bulkContent
      const result = await host.api.importFile({ format: bulkFormat, content })
      if (result.imported[0]) setSelectedPaperId(result.imported[0].paper.id)
      setBulkContent('')
      await loadPapers(query)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to import file')
    } finally {
      setLoading(false)
    }
  }

  const runSync = async () => {
    setLoading(true)
    setError(null)
    try {
      await host.api.syncIntake()
      await loadPapers(query)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to run intake sync')
    } finally {
      setLoading(false)
    }
  }

  const toggleSetting = async (key: string) => {
    const next = { ...settings, [key]: !(settings[key] !== false) }
    setSettings(next)
    try {
      await host.api.patchPluginSettings({ [key]: next[key] })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to update settings')
    }
  }

  const loadProject = async (id = projectId.trim()) => {
    if (!id) return
    setLoading(true)
    setError(null)
    try {
      const result = await host.api.listProjectPapers(id)
      setProjectPapers(result.papers)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load project papers')
    } finally {
      setLoading(false)
    }
  }

  const addSelectedToProject = async () => {
    if (!projectId.trim() || !detail) return
    setLoading(true)
    setError(null)
    try {
      await host.api.addProjectPaper(projectId.trim(), { paper_id: detail.paper.id, status: 'candidate' })
      await loadProject(projectId.trim())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to add paper to project')
    } finally {
      setLoading(false)
    }
  }

  const updateProjectPaper = async (
    paperId: string,
    patch: Partial<Pick<ResearchAtlasProjectPaper, 'status' | 'read_status' | 'pinned'>>,
  ) => {
    if (!projectId.trim()) return
    try {
      const result = await host.api.updateProjectPaper(projectId.trim(), paperId, patch)
      setProjectPapers((items) => items.map((item) => item.paper_id === paperId ? { ...item, ...result.project_paper } : item))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to update project paper')
    }
  }

  const createResearchGroup = async () => {
    if (!groupName.trim()) return
    setLoading(true)
    setError(null)
    try {
      const result = await host.api.createGroup({
        name: groupName.trim(),
        aliases: groupAliases.split(',').map((item) => item.trim()).filter(Boolean),
        pi_scholar_id: groupPi.trim() || null,
      })
      setGroups((items) => [result.group, ...items.filter((item) => item.id !== result.group.id)])
      setSelectedGroupId(result.group.id)
      setGroupName('')
      setGroupAliases('')
      setGroupPi('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to create group')
    } finally {
      setLoading(false)
    }
  }

  const addMemberToGroup = async () => {
    if (!selectedGroupId || !memberScholarId.trim()) return
    setLoading(true)
    setError(null)
    try {
      await host.api.addGroupMembership(selectedGroupId, {
        scholar_id: memberScholarId.trim(),
        role: memberRole,
      })
      setMemberScholarId('')
      const result = await host.api.listGroups()
      setGroups(result.groups)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to add group member')
    } finally {
      setLoading(false)
    }
  }

  const exportPaperEntities = async () => {
    setLoading(true)
    setError(null)
    try {
      const text = await host.api.exportEntities({ type: 'paper' })
      setExportPreview(text.trim().split('\n').slice(0, 5).join('\n'))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to export entities')
    } finally {
      setLoading(false)
    }
  }

  const saveTitle = async () => {
    if (!detail || !editTitle.trim()) return
    setLoading(true)
    setError(null)
    try {
      const result = await host.api.patchPaper(detail.paper.id, { title: editTitle.trim() })
      setDetail({ ...detail, paper: result.paper })
      setPapers((items) => items.map((paper) => paper.id === result.paper.id ? result.paper : paper))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to update paper')
    } finally {
      setLoading(false)
    }
  }

  const openScholar = async (scholarId: string) => {
    setLoading(true)
    setError(null)
    try {
      setScholar(await host.api.getScholar(scholarId))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load scholar')
    } finally {
      setLoading(false)
    }
  }

  if (pluginState.loading) return <div style={shellStyle}>Loading Research Atlas...</div>

  if (!pluginState.enabled) {
    return (
      <div style={shellStyle}>
        <h1 style={titleStyle}>Research Atlas</h1>
        <div style={panelStyle}>
          <p style={mutedStyle}>Research Atlas is not enabled for this space.</p>
        </div>
      </div>
    )
  }

  if (graphPageActive) {
    return (
      <GraphExplorerPage
        host={host}
        status={status}
        detail={detail}
        related={related}
        graph={graphMode === 'library' ? libraryGraph : paperGraph}
        graphMode={graphMode}
        loading={graphMode === 'library' ? libraryGraphLoading : paperGraphLoading}
        error={graphMode === 'library' ? libraryGraphError : paperGraphError}
        onGraphMode={setGraphMode}
        onPaper={setSelectedPaperId}
        onScholar={(scholarId) => void openScholar(scholarId)}
      />
    )
  }

  return (
    <div style={shellStyle}>
      <div style={toolbarStyle}>
        <div>
          <h1 style={titleStyle}>Research Atlas</h1>
          <p style={mutedStyle}>Papers-first scholarly graph for this space.</p>
        </div>
        <span style={{ ...mutedStyle, fontFamily: 'ui-monospace, monospace' }}>
          {status ? `${status.plugin_id}@${status.version}` : 'research_atlas'}
        </span>
      </div>

      <div style={panelStyle}>
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(220px, 1fr) auto minmax(220px, 1fr) auto', gap: 8 }}>
          <input
            aria-label="Search papers"
            placeholder="Search papers"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => { if (event.key === 'Enter') void loadPapers(query) }}
            style={inputStyle}
          />
          <button style={buttonStyle} onClick={() => void loadPapers(query)} disabled={loading}>Search</button>
          <input
            aria-label="Import DOI or arXiv ID"
            placeholder="DOI or arXiv ID"
            value={importValue}
            onChange={(event) => setImportValue(event.target.value)}
            onKeyDown={(event) => { if (event.key === 'Enter') void importPaper() }}
            style={inputStyle}
          />
          <button style={primaryButtonStyle} onClick={() => void importPaper()} disabled={loading}>Import</button>
        </div>
        {searchResults.length > 0 && (
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
            {searchResults.map((result) => (
              <button
                key={`${result.entity_type}:${result.id}`}
                style={{ ...buttonStyle, padding: '4px 8px' }}
                onClick={() => {
                  if (result.entity_type === 'paper') setSelectedPaperId(result.id)
                  if (result.entity_type === 'scholar') void openScholar(result.id)
                }}
              >
                {result.entity_type}: {result.label}
              </button>
            ))}
          </div>
        )}
        {error && <p style={{ color: '#b91c1c', fontSize: 13, margin: '8px 0 0' }}>{error}</p>}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(280px, 0.55fr)', gap: 14 }}>
        <div style={panelStyle}>
          <h2 style={sectionTitleStyle}>Bulk Import</h2>
          <div style={{ display: 'flex', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
            <select value={bulkFormat} onChange={(event) => setBulkFormat(event.target.value as 'bibtex' | 'ris' | 'csl_json')} style={inputStyle}>
              <option value="bibtex">BibTeX</option>
              <option value="ris">RIS</option>
              <option value="csl_json">CSL JSON</option>
            </select>
            <button style={buttonStyle} onClick={() => void importBulk()} disabled={loading}>Import file text</button>
          </div>
          <textarea
            aria-label="Bulk import content"
            value={bulkContent}
            onChange={(event) => setBulkContent(event.target.value)}
            placeholder="Paste a Zotero export here"
            style={{ ...inputStyle, width: '100%', minHeight: 80, boxSizing: 'border-box', resize: 'vertical' }}
          />
        </div>

        <div style={panelStyle}>
          <h2 style={sectionTitleStyle}>Sync</h2>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
            {['intake_sync_enabled', 'crossref_enabled', 'openalex_enabled'].map((key) => (
              <label key={key} style={{ display: 'inline-flex', gap: 5, alignItems: 'center', fontSize: 13 }}>
                <input
                  type="checkbox"
                  checked={settings[key] !== false}
                  onChange={() => void toggleSetting(key)}
                />
                {key.replace(/_enabled$/, '').replace(/_/g, ' ')}
              </label>
            ))}
          </div>
          <button style={buttonStyle} onClick={() => void runSync()} disabled={loading}>Run intake sync</button>
          <p style={{ ...mutedStyle, marginTop: 8 }}>
            Due refresh: {syncStatus?.due_refresh_count ?? 0}
          </p>
          {(syncStatus?.cursors ?? []).map((cursor) => (
            <p key={cursor.cursor_key} style={{ ...mutedStyle, marginTop: 4 }}>
              {cursor.cursor_key}: {cursor.last_error ?? cursor.last_run_at ?? 'not run'}
            </p>
          ))}
        </div>
      </div>

      <div style={gridStyle}>
        <div style={panelStyle}>
          <h2 style={sectionTitleStyle}>Papers</h2>
          <table style={tableStyle}>
            <thead>
              <tr>
                <th style={thStyle}>Title</th>
                <th style={thStyle}>Year</th>
                <th style={thStyle}>IDs</th>
              </tr>
            </thead>
            <tbody>
              {papers.map((paper) => (
                <tr key={paper.id}>
                  <td style={tdStyle}>
                    <button
                      style={{ ...buttonStyle, border: 0, padding: 0, color: '#1f6feb', background: 'transparent', whiteSpace: 'normal', textAlign: 'left' }}
                      onClick={() => setSelectedPaperId(paper.id)}
                    >
                      {paper.title}
                    </button>
                  </td>
                  <td style={tdStyle}>{paper.publication_year ?? '-'}</td>
                  <td style={tdStyle}>{paper.doi ?? paper.arxiv_id ?? '-'}</td>
                </tr>
              ))}
              {papers.length === 0 && (
                <tr>
                  <td style={tdStyle} colSpan={3}>No papers yet.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div style={panelStyle}>
          <h2 style={sectionTitleStyle}>{scholar ? 'Scholar' : 'Paper Detail'}</h2>
          {scholar ? (
            <ScholarDetail scholar={scholar} onPaper={(paperId) => setSelectedPaperId(paperId)} />
          ) : detail ? (
            <PaperDetail
              detail={detail}
              editTitle={editTitle}
              onEditTitle={setEditTitle}
              onSaveTitle={() => void saveTitle()}
              onScholar={(scholarId) => void openScholar(scholarId)}
            />
          ) : (
            <p style={mutedStyle}>Select a paper to inspect metadata, authors, identifiers, and provenance.</p>
          )}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 14 }}>
        <div style={panelStyle}>
          <div style={toolbarStyle}>
            <h2 style={sectionTitleStyle}>Graph Explorer</h2>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <Link to="/atlas/graph" style={{ ...primaryButtonStyle, textDecoration: 'none' }}>Open graph</Link>
              <button style={buttonStyle} onClick={() => void exportPaperEntities()} disabled={loading}>Export papers</button>
            </div>
          </div>
          <GraphSummary
            related={related}
            graph={paperGraph}
            loading={paperGraphLoading}
            error={paperGraphError}
            onPaper={setSelectedPaperId}
          />
          {exportPreview && (
            <pre style={{ margin: '12px 0 0', maxHeight: 150, overflow: 'auto', fontSize: 11, background: '#f9fafb', padding: 8, borderRadius: 6 }}>
              {exportPreview}
            </pre>
          )}
        </div>

        <div style={panelStyle}>
          <h2 style={sectionTitleStyle}>Research Groups</h2>
          <GroupCurationPanel
            groups={groups}
            topics={topics}
            selectedGroupId={selectedGroupId}
            onSelectGroup={setSelectedGroupId}
            groupName={groupName}
            onGroupName={setGroupName}
            groupAliases={groupAliases}
            onGroupAliases={setGroupAliases}
            groupPi={groupPi}
            onGroupPi={setGroupPi}
            memberScholarId={memberScholarId}
            onMemberScholarId={setMemberScholarId}
            memberRole={memberRole}
            onMemberRole={setMemberRole}
            onCreateGroup={() => void createResearchGroup()}
            onAddMember={() => void addMemberToGroup()}
            loading={loading}
          />
        </div>
      </div>

      <div style={panelStyle}>
        <div style={toolbarStyle}>
          <div>
            <h2 style={sectionTitleStyle}>Project Literature</h2>
            <p style={mutedStyle}>Shared reading state for a project-bound literature workspace.</p>
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <input
              aria-label="Project ID"
              placeholder="Project ID"
              value={projectId}
              onChange={(event) => setProjectId(event.target.value)}
              style={inputStyle}
            />
            <button style={buttonStyle} onClick={() => void loadProject()} disabled={loading}>Load</button>
            <button style={primaryButtonStyle} onClick={() => void addSelectedToProject()} disabled={loading || !detail}>Add selected</button>
          </div>
        </div>
        <ProjectBoard
          host={host}
          papers={projectPapers}
          onOpenPaper={setSelectedPaperId}
          onUpdate={(paperId, patch) => void updateProjectPaper(paperId, patch)}
        />
      </div>
    </div>
  )
}

function PaperDetail({
  detail, editTitle, onEditTitle, onSaveTitle, onScholar,
}: {
  detail: ResearchAtlasPaperDetail
  editTitle: string
  onEditTitle: (value: string) => void
  onSaveTitle: () => void
  onScholar: (scholarId: string) => void
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', gap: 8 }}>
        <input value={editTitle} onChange={(event) => onEditTitle(event.target.value)} style={{ ...inputStyle, flex: 1 }} />
        <button style={buttonStyle} onClick={onSaveTitle}>Save</button>
      </div>
      <p style={mutedStyle}>{detail.paper.abstract ?? 'No abstract yet.'}</p>
      <div>
        <h3 style={sectionTitleStyle}>Authors</h3>
        {detail.authorships.length === 0 && <p style={mutedStyle}>No resolved authors yet.</p>}
        {detail.authorships.map((author) => (
          <div key={author.id} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, padding: '4px 0' }}>
            <span>{author.author_position}. {author.raw_author_name}</span>
            {author.scholar_id && (
              <button style={{ ...buttonStyle, padding: '2px 7px' }} onClick={() => onScholar(author.scholar_id!)}>Open</button>
            )}
          </div>
        ))}
      </div>
      <div>
        <h3 style={sectionTitleStyle}>Identifiers</h3>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {detail.external_ids.map((id) => (
            <span key={`${id.id_type}:${id.id_value}`} style={{ fontSize: 12, background: '#f3f4f6', borderRadius: 6, padding: '3px 6px' }}>
              {id.id_type}: {id.id_value}
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}

function ScholarDetail({ scholar, onPaper }: { scholar: ResearchAtlasScholarDetail; onPaper: (paperId: string) => void }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div>
        <h3 style={{ fontSize: 17, margin: 0 }}>{scholar.scholar.display_name}</h3>
        <p style={mutedStyle}>{scholar.scholar.orcid ?? 'No ORCID'}</p>
      </div>
      <div>
        <h3 style={sectionTitleStyle}>Papers</h3>
        {scholar.papers.map((paper) => (
          <button
            key={paper.id}
            style={{ ...buttonStyle, display: 'block', width: '100%', marginBottom: 6, textAlign: 'left', whiteSpace: 'normal' }}
            onClick={() => onPaper(paper.id)}
          >
            {paper.title}
          </button>
        ))}
      </div>
      <div>
        <h3 style={sectionTitleStyle}>Coauthors</h3>
        {scholar.coauthors.length === 0 && <p style={mutedStyle}>No coauthors resolved.</p>}
        {scholar.coauthors.map((coauthor) => (
          <p key={coauthor.id} style={{ ...mutedStyle, marginBottom: 4 }}>
            {coauthor.display_name} - {coauthor.shared_paper_count} shared
          </p>
        ))}
      </div>
      <div>
        <h3 style={sectionTitleStyle}>Affiliations</h3>
        {scholar.affiliations.length === 0 && <p style={mutedStyle}>No affiliations curated.</p>}
        {scholar.affiliations.map((affiliation) => (
          <p key={affiliation.id} style={{ ...mutedStyle, marginBottom: 4 }}>
            {affiliation.institution?.name ?? 'Unknown institution'}
            {affiliation.department?.name ? ` - ${affiliation.department.name}` : ''}
            {affiliation.role ? ` - ${affiliation.role}` : ''}
          </p>
        ))}
      </div>
    </div>
  )
}

function GraphExplorerPage({
  host,
  status,
  detail,
  related,
  graph,
  graphMode,
  loading,
  error,
  onGraphMode,
  onPaper,
  onScholar,
}: {
  host: ResearchAtlasWebHost
  status: ResearchAtlasStatus | null
  detail: ResearchAtlasPaperDetail | null
  related: ResearchAtlasPaperRelated | null
  graph: GraphProjection | null
  graphMode: AtlasGraphMode
  loading: boolean
  error: string | null
  onGraphMode: (mode: AtlasGraphMode) => void
  onPaper: (paperId: string) => void
  onScholar: (scholarId: string) => void
}) {
  const GraphView = host.GraphView
  const Link = host.Link
  return (
    <div style={graphPageShellStyle}>
      <div style={toolbarStyle}>
        <div>
          <h1 style={titleStyle}>Graph Explorer</h1>
          <p style={mutedStyle}>
            {graphMode === 'library'
              ? 'Full Research Atlas library graph.'
              : detail?.paper.title ?? 'Select a paper from Research Atlas to inspect its graph.'}
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <button
            type="button"
            style={graphMode === 'library' ? primaryButtonStyle : buttonStyle}
            onClick={() => onGraphMode('library')}
          >
            Library
          </button>
          <button
            type="button"
            style={graphMode === 'paper' ? primaryButtonStyle : buttonStyle}
            onClick={() => onGraphMode('paper')}
          >
            Selected paper
          </button>
          <span style={{ ...mutedStyle, fontFamily: 'ui-monospace, monospace' }}>
            {status ? `${status.plugin_id}@${status.version}` : 'research_atlas'}
          </span>
          <Link to="/atlas" style={{ ...buttonStyle, textDecoration: 'none' }}>Back to Atlas</Link>
        </div>
      </div>

      <div style={graphExplorerStyle}>
        <div style={graphCanvasPanelStyle}>
          <GraphView
            projection={graph}
            theme={atlasGraphTheme}
            loading={loading}
            error={error}
            renderNodeDetails={(node) => (
              <AtlasGraphNodeDetails node={node} onPaper={onPaper} onScholar={onScholar} />
            )}
          />
        </div>
        <div style={graphSidePanelStyle}>
          <GraphProjectionSummary
            related={related}
            graph={graph}
            loading={loading}
            error={error}
            onPaper={onPaper}
            showPaperRelations={graphMode === 'paper'}
          />
        </div>
      </div>
    </div>
  )
}

function GraphSummary({
  related, graph, loading, error, onPaper,
}: {
  related: ResearchAtlasPaperRelated | null
  graph: GraphProjection | null
  loading: boolean
  error: string | null
  onPaper: (paperId: string) => void
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <GraphProjectionSummary related={related} graph={graph} loading={loading} error={error} onPaper={onPaper} />
    </div>
  )
}

function GraphProjectionSummary({
  related, graph, loading, error, onPaper, showPaperRelations = true,
}: {
  related: ResearchAtlasPaperRelated | null
  graph: GraphProjection | null
  loading: boolean
  error: string | null
  onPaper: (paperId: string) => void
  showPaperRelations?: boolean
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div>
        <h3 style={sectionTitleStyle}>Projection</h3>
        <p style={mutedStyle}>
          {loading
            ? 'Loading graph projection...'
            : error
              ? error
              : graph
                ? `${graph.nodes.length} nodes - ${graph.edges.length} edges`
                : 'Select a paper with citation edges.'}
        </p>
      </div>
      {showPaperRelations && (
        <>
          <PaperLinkList title="References" papers={related?.references ?? []} onPaper={onPaper} />
          <PaperLinkList title="Citations" papers={related?.citations ?? []} onPaper={onPaper} />
        </>
      )}
    </div>
  )
}

function AtlasGraphNodeDetails({
  node, onPaper, onScholar,
}: {
  node: GraphProjectionNode
  onPaper: (paperId: string) => void
  onScholar: (scholarId: string) => void
}) {
  const paperId = typeof node.metadata?.paperId === 'string' ? node.metadata.paperId : null
  const scholarId = typeof node.metadata?.scholarId === 'string' ? node.metadata.scholarId : null
  const venueType = typeof node.metadata?.venueType === 'string' ? node.metadata.venueType : null
  const publicationYear = typeof node.metadata?.publicationYear === 'number' ? node.metadata.publicationYear : null
  const doi = typeof node.metadata?.doi === 'string' ? node.metadata.doi : null
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div>
        <strong>{node.label}</strong>
        {node.subtitle && <p style={{ ...mutedStyle, marginTop: 4 }}>{node.subtitle}</p>}
      </div>
      <p style={mutedStyle}>
        {node.kind}
        {publicationYear ? ` - ${publicationYear}` : ''}
        {venueType ? ` - ${venueType}` : ''}
      </p>
      {doi && <p style={mutedStyle}>DOI: {doi}</p>}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {paperId && <button style={buttonStyle} onClick={() => onPaper(paperId)}>Open paper</button>}
        {scholarId && <button style={buttonStyle} onClick={() => onScholar(scholarId)}>Open scholar</button>}
      </div>
    </div>
  )
}

function PaperLinkList({
  title, papers, onPaper,
}: {
  title: string
  papers: ResearchAtlasPaper[]
  onPaper: (paperId: string) => void
}) {
  return (
    <div>
      <h3 style={sectionTitleStyle}>{title}</h3>
      {papers.length === 0 && <p style={mutedStyle}>None recorded.</p>}
      {papers.slice(0, 8).map((paper) => (
        <button
          key={paper.id}
          style={{ ...buttonStyle, display: 'block', width: '100%', marginBottom: 6, textAlign: 'left', whiteSpace: 'normal' }}
          onClick={() => onPaper(paper.id)}
        >
          {paper.title}
        </button>
      ))}
    </div>
  )
}

function GroupCurationPanel({
  groups,
  topics,
  selectedGroupId,
  onSelectGroup,
  groupName,
  onGroupName,
  groupAliases,
  onGroupAliases,
  groupPi,
  onGroupPi,
  memberScholarId,
  onMemberScholarId,
  memberRole,
  onMemberRole,
  onCreateGroup,
  onAddMember,
  loading,
}: {
  groups: ResearchAtlasGroup[]
  topics: Array<{ id: string; label: string; taxonomy: string }>
  selectedGroupId: string
  onSelectGroup: (groupId: string) => void
  groupName: string
  onGroupName: (value: string) => void
  groupAliases: string
  onGroupAliases: (value: string) => void
  groupPi: string
  onGroupPi: (value: string) => void
  memberScholarId: string
  onMemberScholarId: (value: string) => void
  memberRole: string
  onMemberRole: (value: string) => void
  onCreateGroup: () => void
  onAddMember: () => void
  loading: boolean
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8 }}>
        <input aria-label="Group name" placeholder="Group name" value={groupName} onChange={(event) => onGroupName(event.target.value)} style={inputStyle} />
        <input aria-label="Group aliases" placeholder="Aliases" value={groupAliases} onChange={(event) => onGroupAliases(event.target.value)} style={inputStyle} />
        <input aria-label="PI scholar ID" placeholder="PI scholar ID" value={groupPi} onChange={(event) => onGroupPi(event.target.value)} style={inputStyle} />
        <button style={primaryButtonStyle} onClick={onCreateGroup} disabled={loading}>Create group</button>
      </div>
      <select value={selectedGroupId} onChange={(event) => onSelectGroup(event.target.value)} style={inputStyle}>
        <option value="">Select group</option>
        {groups.map((group) => (
          <option key={group.id} value={group.id}>
            {group.name} ({group.member_count ?? 0})
          </option>
        ))}
      </select>
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(150px, 1fr) minmax(120px, 140px) auto', gap: 8 }}>
        <input aria-label="Member scholar ID" placeholder="Scholar ID" value={memberScholarId} onChange={(event) => onMemberScholarId(event.target.value)} style={inputStyle} />
        <select value={memberRole} onChange={(event) => onMemberRole(event.target.value)} style={inputStyle}>
          {['pi', 'faculty', 'postdoc', 'phd_student', 'masters_student', 'engineer', 'alumni', 'unknown'].map((role) => (
            <option key={role} value={role}>{role}</option>
          ))}
        </select>
        <button style={buttonStyle} onClick={onAddMember} disabled={loading || !selectedGroupId}>Add</button>
      </div>
      <div>
        <h3 style={sectionTitleStyle}>Topics</h3>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {topics.slice(0, 10).map((topic) => (
            <span key={topic.id} style={{ fontSize: 12, background: '#f3f4f6', borderRadius: 6, padding: '3px 6px' }}>
              {topic.taxonomy}: {topic.label}
            </span>
          ))}
          {topics.length === 0 && <p style={mutedStyle}>No topics curated.</p>}
        </div>
      </div>
    </div>
  )
}

function ProjectBoard({
  host, papers, onOpenPaper, onUpdate,
}: {
  host: ResearchAtlasWebHost
  papers: ResearchAtlasProjectPaper[]
  onOpenPaper: (paperId: string) => void
  onUpdate: (paperId: string, patch: Partial<Pick<ResearchAtlasProjectPaper, 'status' | 'read_status' | 'pinned'>>) => void
}) {
  return (
    <table style={{ ...tableStyle, marginTop: 10 }}>
      <thead>
        <tr>
          <th style={thStyle}>Paper</th>
          <th style={thStyle}>Status</th>
          <th style={thStyle}>Read</th>
          <th style={thStyle}>Source</th>
        </tr>
      </thead>
      <tbody>
        {papers.map((item) => (
          <tr key={item.id}>
            <td style={tdStyle}>
              <button
                style={{ ...buttonStyle, border: 0, padding: 0, color: '#1f6feb', background: 'transparent', whiteSpace: 'normal', textAlign: 'left' }}
                onClick={() => onOpenPaper(item.paper_id)}
              >
                {item.paper.title}
              </button>
              {item.pinned && <span style={{ marginLeft: 6, color: '#b45309', fontSize: 12 }}>Pinned</span>}
            </td>
            <td style={tdStyle}>
              <select
                value={item.status}
                onChange={(event) => onUpdate(item.paper_id, { status: event.target.value as ResearchAtlasProjectPaper['status'] })}
                style={inputStyle}
              >
                {['candidate', 'shortlist', 'reading', 'done', 'rejected'].map((status) => (
                  <option key={status} value={status}>{status}</option>
                ))}
              </select>
            </td>
            <td style={tdStyle}>
              <select
                value={item.read_status}
                onChange={(event) => onUpdate(item.paper_id, { read_status: event.target.value as ResearchAtlasProjectPaper['read_status'] })}
                style={inputStyle}
              >
                {['unread', 'skimmed', 'read'].map((status) => (
                  <option key={status} value={status}>{status}</option>
                ))}
              </select>
            </td>
            <td style={tdStyle}>
              {item.intake_item_id ? (
                <host.Link to={`/intake/items/${item.intake_item_id}/read`} style={{ color: '#1f6feb' }}>Reader</host.Link>
              ) : item.source}
            </td>
          </tr>
        ))}
        {papers.length === 0 && (
          <tr>
            <td style={tdStyle} colSpan={4}>No project papers loaded.</td>
          </tr>
        )}
      </tbody>
    </table>
  )
}

function initialProjectId(): string {
  if (typeof window === 'undefined') return ''
  const match = window.location.pathname.match(/\/atlas\/projects\/([^/]+)/)
  return match ? decodeURIComponent(match[1]!) : ''
}

export function createResearchAtlasPage(host: ResearchAtlasWebHost): ComponentType {
  return function BoundResearchAtlasPage() {
    return <ResearchAtlasPage host={host} />
  }
}
