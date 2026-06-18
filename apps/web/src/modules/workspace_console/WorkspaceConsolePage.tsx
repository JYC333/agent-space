import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Terminal, Folder, GitBranch, Clock, Play, Square,
  Loader, FileDiff, RefreshCw,
} from 'lucide-react'
import { toast } from 'sonner'
import { workspaceConsoleApi } from '../../api/client'
import { useSpace } from '../../contexts/SpaceContext'
import { errMsg } from '../../lib/utils'
import type {
  WorkspaceInfo, FileNode, FileContent, GitStatus,
  GitChangedFile, RuntimeInfo, ConsoleSession, RuntimeEvent,
} from '../../types/api'
import { Button } from '../../components/ui/button'
import { Badge } from '../../components/ui/badge'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../../components/ui/tabs'
import { Select } from '../../components/ui/select'
import {
  CenterEmpty,
  DiffViewer,
  EventItem,
  FileTreeNode,
  FileViewer,
  fmtDate,
  fmtTime,
  SessionDetail,
  STATUS_VARIANT,
} from './WorkspaceConsoleParts'

// ── Main page ─────────────────────────────────────────────────────────────────

type CenterView =
  | { mode: 'empty' }
  | { mode: 'file';    data: FileContent }
  | { mode: 'diff';    diff: string; path: string }
  | { mode: 'session'; session: ConsoleSession }

export default function WorkspaceConsolePage() {
  const { activeSpaceId, activeSpaceName } = useSpace()

  // ── Workspace state ──────────────────────────────────────────────────────
  const [workspaces, setWorkspaces]               = useState<WorkspaceInfo[]>([])
  const [selectedWs, setSelectedWs]               = useState<WorkspaceInfo | null>(null)

  // ── Left panel ───────────────────────────────────────────────────────────
  const [fileTree, setFileTree]                   = useState<FileNode | null>(null)
  const [gitStatus, setGitStatus]                 = useState<GitStatus | null>(null)
  const [sessions, setSessions]                   = useState<ConsoleSession[]>([])
  const [selectedFilePath, setSelectedFilePath]   = useState<string | null>(null)
  const [treeLoading, setTreeLoading]             = useState(false)
  const [gitLoading, setGitLoading]               = useState(false)

  // ── Center panel ─────────────────────────────────────────────────────────
  const [centerView, setCenterView]               = useState<CenterView>({ mode: 'empty' })
  const [centerLoading, setCenterLoading]         = useState(false)

  // ── Right panel ──────────────────────────────────────────────────────────
  const [runtimes, setRuntimes]                   = useState<RuntimeInfo[]>([])
  const [selectedRuntime, setSelectedRuntime]     = useState('claude_code')
  const [selectedModel, setSelectedModel]         = useState('')
  const [prompt, setPrompt]                       = useState('')
  const [running, setRunning]                     = useState(false)
  const [activeSessionId, setActiveSessionId]     = useState<string | null>(null)
  const [displayedEvents, setDisplayedEvents]     = useState<RuntimeEvent[]>([])
  const eventsEndRef                              = useRef<HTMLDivElement>(null)

  // ── Load workspaces + runtimes on mount ──────────────────────────────────
  useEffect(() => {
    if (!activeSpaceId) {
      setWorkspaces([])
      setSelectedWs(null)
      setFileTree(null)
      setGitStatus(null)
      setSessions([])
    } else {
      workspaceConsoleApi.listWorkspaces()
        .then(r => {
          setWorkspaces(r.items)
          if (r.items.length > 0 && !selectedWs) setSelectedWs(r.items[0])
        })
        .catch(e => toast.error(errMsg(e)))
    }

    workspaceConsoleApi.runtimes()
      .then(r => setRuntimes(r.runtimes))
      .catch(() => {/* non-fatal */})
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSpaceId])

  // ── Load file tree + git status when workspace changes ───────────────────
  const loadTree = useCallback(async (ws: WorkspaceInfo) => {
    setTreeLoading(true)
    setFileTree(null)
    try {
      const tree = await workspaceConsoleApi.fileTree(ws.id)
      setFileTree(tree)
    } catch {
      // Workspace might have no directory yet — silently fail
    } finally {
      setTreeLoading(false)
    }
  }, [])

  const loadGitStatus = useCallback(async (ws: WorkspaceInfo) => {
    setGitLoading(true)
    try {
      setGitStatus(await workspaceConsoleApi.gitStatus(ws.id))
    } catch {
      setGitStatus(null)
    } finally {
      setGitLoading(false)
    }
  }, [])

  const loadSessions = useCallback(async (wsId?: string) => {
    try {
      const r = await workspaceConsoleApi.listSessions(wsId)
      setSessions(r.items)
    } catch {/* non-fatal */}
  }, [])

  useEffect(() => {
    if (!selectedWs) return
    setCenterView({ mode: 'empty' })
    setSelectedFilePath(null)
    setDisplayedEvents([])
    loadTree(selectedWs)
    loadGitStatus(selectedWs)
    loadSessions(selectedWs.id)
  }, [selectedWs, loadTree, loadGitStatus, loadSessions])

  // ── File select → show content ────────────────────────────────────────────
  async function handleFileSelect(path: string) {
    if (!selectedWs) return
    setSelectedFilePath(path)
    setCenterLoading(true)
    try {
      const fc = await workspaceConsoleApi.fileContent(selectedWs.id, path)
      setCenterView({ mode: 'file', data: fc })
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setCenterLoading(false)
    }
  }

  // ── Changed file select → show diff ──────────────────────────────────────
  async function handleDiffSelect(file: GitChangedFile) {
    if (!selectedWs) return
    setSelectedFilePath(file.path)
    setCenterLoading(true)
    try {
      const { diff } = await workspaceConsoleApi.gitDiff(selectedWs.id, file.path)
      setCenterView({ mode: 'diff', diff, path: file.path })
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setCenterLoading(false)
    }
  }

  // ── Session select ────────────────────────────────────────────────────────
  function handleSessionSelect(session: ConsoleSession) {
    setCenterView({ mode: 'session', session })
  }

  // ── Run / continue session ────────────────────────────────────────────────
  async function handleRun() {
    if (!prompt.trim()) return
    if (!activeSpaceId) {
      toast.error('Select an operational space before running a console session')
      return
    }
    setRunning(true)
    // For a new session clear the board; for a continuation keep prior events
    const isContinuation = activeSessionId !== null
    if (!isContinuation) setDisplayedEvents([])

    try {
      // Either continue the active session or start a fresh one
      let session = activeSessionId
        ? await workspaceConsoleApi.runTurn(activeSessionId, prompt.trim())
        : await workspaceConsoleApi.createSession({
            workspace_id: selectedWs?.id,
            runtime: selectedRuntime,
            model: selectedModel || undefined,
            prompt: prompt.trim(),
          })

      // CLI runtimes return status="running"; poll until done
      if (session.status === 'running') {
        const POLL_MS = 2000
        const TIMEOUT_MS = 10 * 60 * 1000
        const deadline = Date.now() + TIMEOUT_MS
        while (session.status === 'running') {
          if (Date.now() > deadline) {
            toast.error('Session timed out after 10 minutes')
            break
          }
          await new Promise(r => setTimeout(r, POLL_MS))
          session = await workspaceConsoleApi.getSession(session.id)
        }
      }

      setActiveSessionId(session.id)

      // For continuations: replay only the new events (after the prior events)
      const prevCount = isContinuation ? displayedEvents.length : 0
      const newEvents = session.events.slice(prevCount)
      for (const ev of newEvents) {
        await new Promise<void>(r => setTimeout(r, 60))
        setDisplayedEvents(prev => [...prev, ev])
        eventsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
      }
      await loadSessions(selectedWs?.id)
      if (selectedWs) {
        loadTree(selectedWs)
        loadGitStatus(selectedWs)
      }
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setRunning(false)
    }
  }

  function handleNewSession() {
    setActiveSessionId(null)
    setDisplayedEvents([])
  }

  // ── Git groups ────────────────────────────────────────────────────────────
  const gitGroups: Record<string, GitChangedFile[]> = {}
  for (const f of gitStatus?.files ?? []) {
    ;(gitGroups[f.status] ??= []).push(f)
  }
  const gitGroupOrder = ['modified', 'added', 'deleted', 'untracked', 'renamed'] as const

  const currentRuntime = runtimes.find(r => r.id === selectedRuntime)

  return (
    <div className="flex flex-col overflow-hidden" style={{ height: 'calc(100vh - 56px)' }}>

      {/* ── Page header ─────────────────────────────────────────────────── */}
      <div className="shrink-0 flex items-center gap-3 px-4 py-2.5 border-b bg-card">
        <div
          className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
          style={{ background: 'color-mix(in oklch, var(--primary) 12%, transparent)', border: '1px solid color-mix(in oklch, var(--primary) 30%, transparent)' }}
        >
          <Terminal className="size-4 text-primary" />
        </div>
        <h1 className="text-sm font-semibold">Workspace Console</h1>
        <span className="text-[10px] text-muted-foreground hidden md:inline">
          Viewing: {activeSpaceName ?? activeSpaceId ?? 'No operational space selected'}
        </span>

        {/* Workspace selector */}
        {workspaces.length > 0 && (
          <div className="flex items-center gap-1.5 ml-2">
            <Folder className="size-3.5 text-muted-foreground shrink-0" />
            <Select
              size="sm"
              value={selectedWs?.id ?? ''}
              onChange={id => setSelectedWs(workspaces.find(w => w.id === id) ?? null)}
              options={workspaces.map(w => ({ value: w.id, label: w.name }))}
              className="w-40"
            />
          </div>
        )}

        {selectedWs?.path && (
          <span className="text-[10px] text-muted-foreground font-mono hidden sm:block truncate max-w-[260px]">
            {selectedWs.path}
          </span>
        )}

        <div className="ml-auto flex items-center gap-1.5">
          {selectedWs && (
            <button
              onClick={() => { loadTree(selectedWs); loadGitStatus(selectedWs); loadSessions(selectedWs.id) }}
              className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              <RefreshCw className="size-3" />
            </button>
          )}
          {gitStatus?.branch && (
            <Badge variant="muted" className="text-[10px] px-1.5">
              <GitBranch className="size-2.5 mr-1" />{gitStatus.branch}
            </Badge>
          )}
        </div>
      </div>

      {/* ── 3-column body ───────────────────────────────────────────────── */}
      <div className="flex-1 flex min-h-0">

        {/* ── LEFT SIDEBAR ─────────────────────────────────────────────── */}
        <div className="w-56 shrink-0 border-r flex flex-col min-h-0 bg-card/50">
          <Tabs defaultValue="files" className="flex flex-col flex-1 min-h-0">
            <div className="shrink-0 px-2 pt-2">
              <TabsList className="w-full grid grid-cols-3 h-7 text-[10px]">
                <TabsTrigger value="files"   className="text-[10px] px-1">Files</TabsTrigger>
                <TabsTrigger value="changes" className="text-[10px] px-1">
                  Changes
                  {(gitStatus?.files.length ?? 0) > 0 && (
                    <span className="ml-1 bg-primary/20 text-primary rounded-full px-1 text-[9px]">
                      {gitStatus!.files.length}
                    </span>
                  )}
                </TabsTrigger>
                <TabsTrigger value="sessions" className="text-[10px] px-1">Sessions</TabsTrigger>
              </TabsList>
            </div>

            {/* Files tab */}
            <TabsContent value="files" className="flex-1 overflow-y-auto mt-0 px-1 py-1">
              {!selectedWs ? (
                <p className="text-xs text-muted-foreground p-3">No workspace selected</p>
              ) : treeLoading ? (
                <p className="text-xs text-muted-foreground p-3 flex items-center gap-1.5">
                  <Loader className="size-3 animate-spin" /> Loading…
                </p>
              ) : fileTree ? (
                <FileTreeNode
                  node={fileTree}
                  depth={0}
                  selectedPath={selectedFilePath}
                  onFileSelect={handleFileSelect}
                />
              ) : (
                <p className="text-xs text-muted-foreground p-3">No files found</p>
              )}
            </TabsContent>

            {/* Changes tab */}
            <TabsContent value="changes" className="flex-1 overflow-y-auto mt-0 px-1 py-1">
              {!selectedWs ? (
                <p className="text-xs text-muted-foreground p-3">No workspace selected</p>
              ) : gitLoading ? (
                <p className="text-xs text-muted-foreground p-3 flex items-center gap-1.5">
                  <Loader className="size-3 animate-spin" /> Loading…
                </p>
              ) : !gitStatus?.is_repo ? (
                <p className="text-xs text-muted-foreground p-3">Not a git repository</p>
              ) : gitStatus.files.length === 0 ? (
                <p className="text-xs text-muted-foreground p-3">Working tree clean</p>
              ) : (
                <div className="space-y-3">
                  {gitGroupOrder.map(grp => {
                    const files = gitGroups[grp]
                    if (!files?.length) return null
                    return (
                      <div key={grp}>
                        <p className="text-[9px] font-bold uppercase tracking-widest text-muted-foreground px-2 py-1">
                          {grp} · {files.length}
                        </p>
                        {files.map(f => (
                          <button
                            key={f.path}
                            onClick={() => handleDiffSelect(f)}
                            className={[
                              'w-full flex items-center gap-1.5 py-[3px] px-2 text-xs text-left rounded-sm transition-colors',
                              selectedFilePath === f.path
                                ? 'bg-primary/10 text-primary'
                                : 'text-muted-foreground hover:text-foreground hover:bg-accent/50',
                            ].join(' ')}
                          >
                            <span className={`text-[9px] px-1 rounded ${STATUS_VARIANT[f.status] ?? ''}`}>
                              {f.status[0].toUpperCase()}
                            </span>
                            <span className="truncate font-mono text-[10px]">{f.path}</span>
                          </button>
                        ))}
                      </div>
                    )
                  })}
                </div>
              )}
            </TabsContent>

            {/* Sessions tab */}
            <TabsContent value="sessions" className="flex-1 overflow-y-auto mt-0 px-1 py-1">
              {sessions.length === 0 ? (
                <p className="text-xs text-muted-foreground p-3">No sessions yet</p>
              ) : (
                sessions.map(s => (
                  <button
                    key={s.id}
                    onClick={() => handleSessionSelect(s)}
                    className={[
                      'w-full flex flex-col items-start gap-0.5 py-2 px-2 text-left rounded-sm transition-colors',
                      centerView.mode === 'session' && centerView.session.id === s.id
                        ? 'bg-primary/10'
                        : 'hover:bg-accent/50',
                    ].join(' ')}
                  >
                    <div className="flex items-center gap-1.5 w-full">
                      <Clock className="size-2.5 text-muted-foreground shrink-0" />
                      <span className="text-[10px] text-muted-foreground">
                        {fmtDate(s.created_at)} {fmtTime(s.created_at)}
                      </span>
                      <span className={[
                        'ml-auto text-[9px] px-1 rounded',
                        s.status === 'completed' ? 'bg-emerald-500/15 text-emerald-600' :
                        s.status === 'failed'    ? 'bg-red-500/15 text-red-500' :
                        'bg-muted text-muted-foreground',
                      ].join(' ')}>
                        {s.status}
                      </span>
                    </div>
                    <span className="text-xs text-foreground/80 truncate w-full">{s.prompt}</span>
                    <span className="text-[10px] text-muted-foreground">{s.runtime}</span>
                  </button>
                ))
              )}
            </TabsContent>
          </Tabs>
        </div>

        {/* ── CENTER PANEL ─────────────────────────────────────────────── */}
        <div className="flex-1 min-w-0 flex flex-col min-h-0 bg-background">
          {centerLoading ? (
            <div className="flex items-center justify-center h-full">
              <Loader className="size-5 animate-spin text-muted-foreground" />
            </div>
          ) : centerView.mode === 'file' ? (
            <FileViewer file={centerView.data} />
          ) : centerView.mode === 'diff' ? (
            <div className="flex flex-col h-full">
              <div className="shrink-0 flex items-center gap-2 px-4 py-2 border-b bg-muted/30">
                <FileDiff className="size-3.5 text-muted-foreground" />
                <span className="text-xs font-mono text-muted-foreground">{centerView.path}</span>
              </div>
              <div className="flex-1 min-h-0 overflow-auto">
                <DiffViewer diff={centerView.diff} />
              </div>
            </div>
          ) : centerView.mode === 'session' ? (
            <SessionDetail session={centerView.session} />
          ) : (
            <CenterEmpty />
          )}
        </div>

        {/* ── RIGHT PANEL ──────────────────────────────────────────────── */}
        <div className="w-72 shrink-0 border-l flex flex-col min-h-0 bg-card/50">

          {/* Runtime selector */}
          <div className="shrink-0 p-3 border-b space-y-2">
            <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Runtime</p>
            <Select
              value={selectedRuntime}
              onChange={id => { setSelectedRuntime(id); setSelectedModel('') }}
              options={runtimes.map(r => ({
                value: r.id,
                label: r.name + (!r.available ? ' (unavailable)' : ''),
              }))}
              className="w-full"
            />

            {(currentRuntime?.models.length ?? 0) > 0 && (
              <>
                <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Model</p>
                <Select
                  value={selectedModel}
                  onChange={setSelectedModel}
                  options={[
                    { value: '', label: 'Default' },
                    ...currentRuntime!.models.map(m => ({ value: m, label: m })),
                  ]}
                  className="w-full"
                />
              </>
            )}
          </div>

          {/* Prompt + run */}
          <div className="shrink-0 p-3 border-b space-y-2">
            <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Prompt</p>
            <textarea
              value={prompt}
              onChange={e => setPrompt(e.target.value)}
              placeholder={selectedWs ? "Describe what you want the agent to do…" : "Select or create a workspace first…"}
              rows={4}
              disabled={!selectedWs || !activeSpaceId}
              className="w-full text-xs bg-background border border-border rounded px-2.5 py-2 resize-none focus:outline-none focus:ring-1 focus:ring-ring placeholder:text-muted-foreground/50 disabled:opacity-50 disabled:cursor-not-allowed"
              onKeyDown={e => {
                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && !running && selectedWs) {
                  e.preventDefault()
                  handleRun()
                }
              }}
            />
            <div className="flex gap-2">
              <Button
                size="sm"
                className="flex-1 h-7 text-xs"
                disabled={!selectedWs || !activeSpaceId || !prompt.trim() || running}
                onClick={handleRun}
              >
                {running ? (
                  <><Loader className="size-3 mr-1.5 animate-spin" />Running…</>
                ) : activeSessionId ? (
                  <><Play className="size-3 mr-1.5" />Continue</>
                ) : (
                  <><Play className="size-3 mr-1.5" />Run</>
                )}
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="h-7 text-xs"
                disabled={!running}
                onClick={() => setRunning(false)}
              >
                <Square className="size-3" />
              </Button>
            </div>
            <div className="flex items-center justify-between">
              <p className="text-[9px] text-muted-foreground">⌘↵ to run</p>
              {activeSessionId && !running && (
                <button
                  onClick={handleNewSession}
                  className="text-[9px] text-muted-foreground hover:text-foreground transition-colors"
                >
                  + New session
                </button>
              )}
            </div>
          </div>

          {/* Event timeline */}
          <div className="flex-1 overflow-y-auto min-h-0">
            <div className="flex items-center justify-between px-3 py-1.5 border-b">
              <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
                Events
              </p>
              {displayedEvents.length > 0 && (
                <button
                  onClick={() => setDisplayedEvents([])}
                  className="text-[9px] text-muted-foreground hover:text-foreground"
                >
                  Clear
                </button>
              )}
            </div>

            {displayedEvents.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-8 gap-2 text-muted-foreground">
                {running ? (
                  <>
                    <Loader className="size-5 animate-spin opacity-50" />
                    <p className="text-xs">Waiting for runtime…</p>
                  </>
                ) : (
                  <>
                    <Terminal className="size-6 opacity-30" />
                    <p className="text-xs">Run a prompt to see events</p>
                  </>
                )}
              </div>
            ) : (
              <div className="py-1">
                {displayedEvents.map((ev, i) => <EventItem key={i} event={ev} />)}
                <div ref={eventsEndRef} />
              </div>
            )}
          </div>
        </div>

      </div>
    </div>
  )
}
