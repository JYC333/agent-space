import { useState, type ReactNode } from 'react'
import {
  AlertCircle,
  CheckCircle,
  ChevronDown,
  ChevronRight,
  Clock,
  Command,
  FileCode,
  FileDiff,
  FileText,
  Folder,
  Loader,
  MessageSquare,
  Search,
  Terminal,
} from 'lucide-react'
import type {
  ConsoleSession,
  FileContent,
  FileNode,
  RuntimeEvent,
} from '../../types/api'

export function fmtTime(iso: string) {
  return new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}

export function fmtDate(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export const STATUS_VARIANT: Record<string, string> = {
  modified:  'bg-amber-500/15 text-amber-600',
  added:     'bg-emerald-500/15 text-emerald-600',
  deleted:   'bg-red-500/15 text-red-600',
  untracked: 'bg-blue-500/15 text-blue-600',
  renamed:   'bg-purple-500/15 text-purple-600',
}

export function FileTreeNode({
  node, depth, selectedPath, onFileSelect,
}: {
  node: FileNode
  depth: number
  selectedPath: string | null
  onFileSelect: (path: string) => void
}) {
  const [open, setOpen] = useState(depth < 2)
  const pl = depth * 12 + 8

  if (node.type === 'file') {
    const active = selectedPath === node.path
    return (
      <button
        onClick={() => onFileSelect(node.path)}
        className={[
          'w-full flex items-center gap-1.5 py-[3px] text-xs text-left transition-colors rounded-sm',
          active
            ? 'bg-primary/10 text-primary font-medium'
            : 'text-muted-foreground hover:text-foreground hover:bg-accent/50',
        ].join(' ')}
        style={{ paddingLeft: pl }}
      >
        <FileCode className="size-3 shrink-0 opacity-60" />
        <span className="truncate">{node.name}</span>
        {node.size !== undefined && (
          <span className="ml-auto pr-2 text-[10px] opacity-40">
            {node.size < 1024 ? `${node.size}B` : `${(node.size / 1024).toFixed(0)}k`}
          </span>
        )}
      </button>
    )
  }

  return (
    <div>
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center gap-1 py-[3px] text-xs text-left text-foreground/80 hover:text-foreground hover:bg-accent/50 transition-colors rounded-sm"
        style={{ paddingLeft: pl }}
      >
        {open ? <ChevronDown className="size-3 shrink-0" /> : <ChevronRight className="size-3 shrink-0" />}
        <Folder className="size-3 shrink-0 text-primary/60" />
        <span className="font-medium">{node.name}</span>
      </button>
      {open && node.children && (
        <div>
          {node.children.map(child => (
            <FileTreeNode
              key={child.path}
              node={child}
              depth={depth + 1}
              selectedPath={selectedPath}
              onFileSelect={onFileSelect}
            />
          ))}
        </div>
      )}
    </div>
  )
}

export function DiffViewer({ diff }: { diff: string }) {
  const lines = diff.split('\n')
  if (!diff.trim()) {
    return (
      <div className="flex items-center justify-center h-full text-sm text-muted-foreground">
        No changes to diff
      </div>
    )
  }
  return (
    <pre className="text-xs font-mono leading-5 overflow-auto h-full p-4">
      {lines.map((line, i) => (
        <div
          key={i}
          className={
            line.startsWith('+') && !line.startsWith('+++')
              ? 'bg-emerald-500/10 text-emerald-400'
              : line.startsWith('-') && !line.startsWith('---')
              ? 'bg-red-500/10 text-red-400'
              : line.startsWith('@@')
              ? 'text-blue-400 bg-blue-500/5'
              : line.startsWith('diff ') || line.startsWith('index ') || line.startsWith('---') || line.startsWith('+++')
              ? 'text-muted-foreground font-bold'
              : 'text-muted-foreground'
          }
        >
          {line || '\u00a0'}
        </div>
      ))}
    </pre>
  )
}

export function FileViewer({ file }: { file: FileContent }) {
  return (
    <div className="flex flex-col h-full">
      <div className="shrink-0 flex items-center gap-2 px-4 py-2 border-b bg-muted/30">
        <FileCode className="size-3.5 text-muted-foreground" />
        <span className="text-xs font-mono text-muted-foreground">{file.path}</span>
        <span className="ml-auto text-[10px] text-muted-foreground">
          {file.line_count} lines · {file.size < 1024 ? `${file.size} B` : `${(file.size / 1024).toFixed(1)} KB`}
        </span>
      </div>
      <pre className="flex-1 overflow-auto text-xs font-mono leading-5 p-4 text-foreground/90">
        {file.content}
      </pre>
    </div>
  )
}

const EVENT_CONFIG: Record<string, { icon: ReactNode; label: string; cls: string }> = {
  text_delta:     { icon: <MessageSquare className="size-3" />, label: 'Text',    cls: 'text-foreground' },
  file_read:      { icon: <FileText className="size-3" />,      label: 'Read',    cls: 'text-blue-400' },
  grep:           { icon: <Search className="size-3" />,        label: 'Search',  cls: 'text-purple-400' },
  command_start:  { icon: <Command className="size-3" />,       label: 'Run',     cls: 'text-amber-400' },
  command_output: { icon: <Terminal className="size-3" />,      label: 'Output',  cls: 'text-muted-foreground' },
  file_changed:   { icon: <FileDiff className="size-3" />,      label: 'Changed', cls: 'text-emerald-400' },
  patch_created:  { icon: <CheckCircle className="size-3" />,   label: 'Patch',   cls: 'text-emerald-500' },
  run_completed:  { icon: <CheckCircle className="size-3" />,   label: 'Done',    cls: 'text-emerald-500' },
  run_failed:     { icon: <AlertCircle className="size-3" />,   label: 'Failed',  cls: 'text-red-400' },
}

function UserTurnDivider({ prompt }: { prompt: string }) {
  return (
    <div className="mx-3 my-2 border-t border-border/60 pt-2">
      <p className="text-[10px] font-medium text-accent-foreground/70 truncate">{prompt}</p>
    </div>
  )
}

export function EventItem({ event }: { event: RuntimeEvent }) {
  if (event.type === 'user_turn') return <UserTurnDivider prompt={event.prompt} />

  const cfg = EVENT_CONFIG[event.type] ?? EVENT_CONFIG.text_delta

  function body() {
    switch (event.type) {
      case 'text_delta':
        return <span className="text-foreground/80">{event.content}</span>
      case 'file_read':
        return <span className="font-mono">{event.path}</span>
      case 'grep':
        return (
          <span>
            <span className="font-mono">{event.query}</span>
            {event.path && <span className="text-muted-foreground"> in {event.path}</span>}
          </span>
        )
      case 'command_start':
        return <span className="font-mono">{event.command}</span>
      case 'command_output':
        return (
          <span>
            {event.stdout && <span className="block whitespace-pre-wrap">{event.stdout}</span>}
            {event.stderr && <span className="block whitespace-pre-wrap text-red-400">{event.stderr}</span>}
          </span>
        )
      case 'file_changed':
        return <span className="font-mono">{event.path}</span>
      case 'patch_created':
        return <span className="font-mono">{event.files.join(', ')}</span>
      case 'run_completed':
        return <span>Run completed</span>
      case 'run_failed':
        return <span className="text-red-400">{event.error}</span>
      default:
        return null
    }
  }

  return (
    <div className={`flex items-start gap-2 py-1.5 px-3 rounded text-xs ${cfg.cls}`}>
      <span className="mt-0.5 shrink-0 opacity-70">{cfg.icon}</span>
      <div className="min-w-0 flex-1 break-words">{body()}</div>
    </div>
  )
}

export function SessionDetail({ session }: { session: ConsoleSession }) {
  const statusColor =
    session.status === 'completed' ? 'text-emerald-500' :
    session.status === 'failed'    ? 'text-red-400' :
    session.status === 'running'   ? 'text-blue-400' :
    'text-muted-foreground'

  return (
    <div className="flex flex-col h-full p-4 gap-3 overflow-auto">
      <div className="flex items-start gap-2">
        <div className={`shrink-0 mt-0.5 ${statusColor}`}>
          {session.status === 'completed' ? <CheckCircle className="size-4" /> :
           session.status === 'failed'    ? <AlertCircle className="size-4" /> :
           session.status === 'running'   ? <Loader className="size-4 animate-spin" /> :
           <Clock className="size-4" />}
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium leading-snug break-words">{session.prompt}</p>
          <p className="text-xs text-muted-foreground mt-0.5">
            {session.runtime} · {fmtDate(session.created_at)} {fmtTime(session.created_at)}
          </p>
        </div>
      </div>

      {session.notes && (
        <p className="text-xs text-muted-foreground italic border-l-2 border-border pl-3">
          {session.notes}
        </p>
      )}

      {session.events.length > 0 && (
        <div className="border border-border rounded-lg divide-y divide-border/50 overflow-hidden">
          <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground px-3 py-1.5">
            Events · {session.events.length}
          </p>
          <div className="overflow-auto max-h-[60vh]">
            {session.events.map((ev, i) => <EventItem key={i} event={ev} />)}
          </div>
        </div>
      )}
    </div>
  )
}

export function CenterEmpty() {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-2 text-muted-foreground">
      <FileText className="size-8 opacity-30" />
      <p className="text-sm">Select a file, changed file, or session</p>
    </div>
  )
}
