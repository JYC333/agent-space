import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Send, ChevronRight } from 'lucide-react'
import { toast } from 'sonner'
import { memoryApi, sessionsApi, cliAdaptersApi } from '../../api/client'
import { useSpace } from '../../contexts/SpaceContext'
import { useAuth } from '../../contexts/AuthContext'
import { errMsg } from '../../lib/utils'
import type { MemoryProposal, Session, CLIAdapterConfig } from '../../types/api'
import { MODULE_REGISTRY, APP_GROUPS, type AppGroup } from '../registry'
import { AppCard } from '../../components/AppCard'

/* ── Greeting ──────────────────────────────────────────────────────────────── */
function Greeting({ name }: { name: string }) {
  const h = new Date().getHours()
  const part = h < 5 ? 'late' : h < 12 ? 'morning' : h < 17 ? 'afternoon' : h < 22 ? 'evening' : 'late'
  return (
    <div className="flex flex-col gap-1.5">
      <div
        className="text-[10px] font-bold tracking-[.1em] uppercase"
        style={{ color: 'color-mix(in oklch, var(--muted-foreground) 70%, transparent)' }}
      >
        Home · {part}
      </div>
      <h1 className="text-2xl font-semibold tracking-tight m-0">
        Good {part},{' '}
        <span className="text-accent-foreground">{name}</span>.
      </h1>
      <p className="text-[13px] text-muted-foreground">
        Choose a capability or ask an agent. Nothing changes memory or files without review.
      </p>
    </div>
  )
}

/* ── Today summary card ─────────────────────────────────────────────────────── */
interface Stat { value: number; label: string; warn?: boolean }

function TodaySummaryCard({ stats }: { stats: Stat[] }) {
  return (
    <div className="bg-card border border-border rounded-lg p-4">
      <div className="flex items-center justify-between mb-3">
        <span
          className="text-[11px] font-bold tracking-[.1em] uppercase text-muted-foreground"
        >Today</span>
        <span className="text-[11px] text-muted-foreground" style={{ fontFamily: 'var(--font-mono)' }}>
          {new Date().toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-3">
        {stats.map(s => (
          <div key={s.label} className="flex flex-col gap-1">
            <div
              className="text-[22px] font-semibold leading-none"
              style={{
                fontFamily: 'var(--font-mono)',
                color: s.warn ? 'var(--warning)' : 'var(--foreground)',
              }}
            >
              {s.value}
            </div>
            <div className="text-[11px] text-muted-foreground">{s.label}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ── Quick-capture composer ──────────────────────────────────────────────────── */
type CaptureMode = 'capture' | 'ask' | 'process'

function QuickCapture() {
  const navigate = useNavigate()
  const [text, setText] = useState('')
  const [mode, setMode] = useState<CaptureMode>('capture')
  const [busy, setBusy] = useState(false)

  const modeMap: { id: CaptureMode; label: string; route: string }[] = [
    { id: 'capture', label: 'capture',   route: 'Activity Inbox' },
    { id: 'ask',     label: 'ask agent', route: 'Agents'         },
    { id: 'process', label: 'process',   route: 'Capture · auto-classify' },
  ]

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!text.trim()) return
    setBusy(true)
    try {
      const session = await sessionsApi.create({ title: text.slice(0, 80) })
      await sessionsApi.addMessage(session.id, { role: 'user', content: text })
      toast.success('Captured — opening sessions')
      navigate('/sessions')
    } catch (err) {
      toast.error(errMsg(err))
    } finally {
      setBusy(false)
      setText('')
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="bg-card border border-border rounded-lg p-3.5 flex flex-col gap-2.5"
    >
      {/* Mode tabs */}
      <div className="flex items-center gap-1.5 flex-wrap">
        {modeMap.map(m => {
          const active = m.id === mode
          return (
            <button
              key={m.id}
              type="button"
              onClick={() => setMode(m.id)}
              className="px-2.5 py-1 rounded-md text-[11px] font-semibold tracking-[.04em] lowercase transition-colors"
              style={active ? {
                background: 'color-mix(in oklch, var(--primary) 12%, transparent)',
                border: '1px solid color-mix(in oklch, var(--primary) 35%, transparent)',
                color: 'var(--accent-foreground)',
              } : {
                background: 'transparent',
                border: '1px solid var(--border)',
                color: 'var(--muted-foreground)',
              }}
            >
              {m.label}
            </button>
          )
        })}
        <span
          className="ml-auto text-[10px] text-muted-foreground hidden sm:block"
          style={{ fontFamily: 'var(--font-mono)' }}
        >
          → routes to {modeMap.find(m => m.id === mode)?.route}
        </span>
      </div>

      {/* Text area */}
      <textarea
        value={text}
        onChange={e => setText(e.target.value)}
        placeholder={
          mode === 'capture'
            ? 'Capture a thought, paste a link, or drop a snippet…'
            : mode === 'ask'
              ? 'Ask an agent. Mention @space, @workspace, or @capability to scope.'
              : 'Paste content for the system to classify and route…'
        }
        rows={2}
        className="w-full resize-none bg-transparent border-none outline-none text-[14px] leading-relaxed text-foreground placeholder:text-muted-foreground"
        onKeyDown={e => {
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSubmit(e as unknown as React.FormEvent)
        }}
      />

      {/* Footer */}
      <div className="flex items-center justify-between gap-2">
        <span
          className="text-[10px] text-muted-foreground"
          style={{ fontFamily: 'var(--font-mono)' }}
        >
          {text.length} chars · nothing commits without review
        </span>
        <button
          type="submit"
          disabled={!text.trim() || busy}
          className="flex items-center gap-1.5 h-7 px-3 rounded-md text-[12px] font-medium transition-opacity disabled:opacity-40 disabled:pointer-events-none"
          style={{ background: 'var(--primary)', border: '1px solid var(--primary)', color: 'var(--primary-foreground)' }}
        >
          <Send className="size-3" />
          {mode === 'capture' ? 'Capture' : mode === 'ask' ? 'Ask' : 'Process'}
        </button>
      </div>
    </form>
  )
}

/* ── Section eyebrow ─────────────────────────────────────────────────────────── */
function Eyebrow({ children, count }: { children: React.ReactNode; count?: number }) {
  return (
    <div className="flex items-baseline gap-2 mb-3">
      <span
        className="text-[10px] font-bold tracking-[.1em] uppercase"
        style={{ color: 'color-mix(in oklch, var(--muted-foreground) 70%, transparent)' }}
      >
        {children}
      </span>
      {count !== undefined && (
        <span
          className="text-[11px] text-muted-foreground"
          style={{ fontFamily: 'var(--font-mono)' }}
        >
          {String(count).padStart(2, '0')}
        </span>
      )}
    </div>
  )
}

/* ── App gallery section grid ────────────────────────────────────────────────── */
function AppGallerySection({ groupKey, label }: { groupKey: AppGroup; label: string }) {
  // visible: false hides the card entirely (space policy, deprecated capability, etc.)
  const items = MODULE_REGISTRY.filter(m => m.group === groupKey && m.visible)
  if (items.length === 0) return null
  return (
    <div>
      <Eyebrow count={items.length}>{label}</Eyebrow>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
          gap: 12,
        }}
      >
        {items.map(m => <AppCard key={m.id} module={m} />)}
      </div>
    </div>
  )
}

/* ── Right sidebar: Proposals ────────────────────────────────────────────────── */
function ProposalStatusCard({
  proposals,
  onDecide,
}: {
  proposals: MemoryProposal[]
  onDecide: (id: string, action: 'accept' | 'reject') => void
}) {
  const navigate = useNavigate()
  return (
    <div className="bg-card border border-border rounded-lg p-4 flex flex-col gap-3">
      <div className="flex items-baseline justify-between">
        <span className="text-[11px] font-bold tracking-[.1em] uppercase text-muted-foreground">
          Pending Review
        </span>
        <button
          onClick={() => navigate('/proposals')}
          className="text-[11px] text-accent-foreground flex items-center gap-1 hover:underline"
          style={{ background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'var(--font-sans)' }}
        >
          Review all <ChevronRight className="size-3" />
        </button>
      </div>

      {proposals.length === 0 ? (
        <p className="text-[12px] text-muted-foreground">No pending proposals.</p>
      ) : (
        <div className="flex flex-col">
          {proposals.slice(0, 4).map((p, i) => (
            <div
              key={p.id}
              className="flex items-center gap-2.5 py-2.5"
              style={{ borderTop: i === 0 ? 'none' : '1px solid color-mix(in oklch, var(--border) 50%, transparent)' }}
            >
              <span
                className="shrink-0 px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-[.05em] text-muted-foreground"
                style={{ background: 'var(--accent)', border: '1px solid var(--border)', fontFamily: 'var(--font-mono)' }}
              >
                {p.memory_type?.slice(0, 4) ?? 'mem'}
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-[12px] text-foreground truncate">{p.proposed_title}</div>
                <div
                  className="text-[10px] text-muted-foreground mt-0.5"
                  style={{ fontFamily: 'var(--font-mono)' }}
                >
                  {new Date(p.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </div>
              </div>
              <div className="flex gap-1 shrink-0">
                <button
                  onClick={() => onDecide(p.id, 'accept')}
                  className="w-[22px] h-[22px] rounded flex items-center justify-center transition-colors"
                  style={{
                    background: 'color-mix(in oklch, var(--success) 15%, transparent)',
                    border: '1px solid color-mix(in oklch, var(--success) 30%, transparent)',
                    color: 'var(--success)', cursor: 'pointer',
                  }}
                  title="Accept"
                >
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                </button>
                <button
                  onClick={() => onDecide(p.id, 'reject')}
                  className="w-[22px] h-[22px] rounded flex items-center justify-center transition-colors"
                  style={{
                    background: 'transparent',
                    border: '1px solid var(--border)',
                    color: 'var(--muted-foreground)', cursor: 'pointer',
                  }}
                  title="Reject"
                >
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                    <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
                  </svg>
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/* ── Right sidebar: Runtime ──────────────────────────────────────────────────── */
function RuntimeStatusCard({ adapters }: { adapters: CLIAdapterConfig[] }) {
  function statusColor(a: CLIAdapterConfig) {
    if (!a.enabled) return 'var(--muted-foreground)'
    if (a.quota_status === 'exhausted' || a.quota_status === 'low') return 'var(--warning)'
    return 'var(--success)'
  }
  return (
    <div className="bg-card border border-border rounded-lg p-4 flex flex-col gap-3">
      <div className="flex items-baseline justify-between">
        <span className="text-[11px] font-bold tracking-[.1em] uppercase text-muted-foreground">Runtime</span>
        <span className="text-[10px] text-muted-foreground" style={{ fontFamily: 'var(--font-mono)' }}>
          {adapters.length} adapter{adapters.length !== 1 ? 's' : ''}
        </span>
      </div>
      {adapters.length === 0 ? (
        <p className="text-[12px] text-muted-foreground">No adapters configured.</p>
      ) : (
        <div className="flex flex-col">
          {adapters.map((a, i) => (
            <div
              key={a.id}
              className="flex items-center gap-2.5 py-2"
              style={{ borderTop: i === 0 ? 'none' : '1px solid color-mix(in oklch, var(--border) 50%, transparent)' }}
            >
              <span
                className="w-2 h-2 rounded-full shrink-0"
                style={{ background: statusColor(a) }}
              />
              <span
                className="text-[12px] text-foreground flex-1 truncate"
                style={{ fontFamily: 'var(--font-mono)' }}
              >
                {a.display_name}
              </span>
              <span
                className="text-[11px] text-muted-foreground shrink-0"
                style={{ fontFamily: 'var(--font-mono)' }}
              >
                {a.enabled ? a.quota_status : 'off'}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/* ── Right sidebar: Recent sessions ─────────────────────────────────────────── */
function RecentCard({ sessions }: { sessions: Session[] }) {
  const navigate = useNavigate()
  return (
    <div className="bg-card border border-border rounded-lg p-4 flex flex-col gap-3">
      <span className="text-[11px] font-bold tracking-[.1em] uppercase text-muted-foreground">Recent</span>
      {sessions.length === 0 ? (
        <p className="text-[12px] text-muted-foreground">No recent sessions.</p>
      ) : (
        <div className="flex flex-col">
          {sessions.slice(0, 5).map((s, i) => (
            <button
              key={s.id}
              onClick={() => navigate('/sessions')}
              className="flex items-center gap-2.5 py-2 text-left w-full hover:bg-accent rounded transition-colors -mx-1 px-1"
              style={{ borderTop: i === 0 ? 'none' : '1px solid color-mix(in oklch, var(--border) 50%, transparent)' }}
            >
              <div
                className="w-6 h-6 rounded flex items-center justify-center shrink-0"
                style={{ background: 'var(--accent)', border: '1px solid var(--border)' }}
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" className="text-muted-foreground">
                  <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                </svg>
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-[12px] text-foreground truncate">{s.title ?? '(untitled)'}</div>
                <div className="text-[10px] text-muted-foreground" style={{ fontFamily: 'var(--font-mono)' }}>
                  {new Date(s.updated_at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                </div>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

/* ── Main page ────────────────────────────────────────────────────────────────── */
export default function HomeGalleryPage() {
  const { spaceId, userId } = useSpace()
  const { currentUser } = useAuth()
  const [proposals, setProposals] = useState<MemoryProposal[]>([])
  const [sessions,  setSessions]  = useState<Session[]>([])
  const [adapters,  setAdapters]  = useState<CLIAdapterConfig[]>([])

  const loadProposals = useCallback(async () => {
    try { setProposals((await memoryApi.proposals('pending')).items) }
    catch { /* no proposals endpoint or offline — silent */ }
  }, [spaceId])

  useEffect(() => {
    loadProposals()
    sessionsApi.list().then(r => setSessions(r.items)).catch(() => {})
    cliAdaptersApi.listConfigs().then(r => setAdapters(r)).catch(() => {})
  }, [loadProposals])

  async function decide(id: string, action: 'accept' | 'reject') {
    try {
      if (action === 'accept') await memoryApi.accept(id)
      else await memoryApi.reject(id)
      toast.success(`Proposal ${action}ed`)
      await loadProposals()
    } catch (e) {
      toast.error(errMsg(e))
    }
  }

  const todayStats: Stat[] = [
    { value: proposals.length, label: 'pending proposals', warn: proposals.length > 0 },
    { value: sessions.length,  label: 'sessions' },
    { value: adapters.filter(a => a.enabled).length, label: 'active adapters' },
    { value: 0, label: 'cards due' },
  ]

  const displayName = currentUser?.display_name
    ?? (userId === 'default_user' ? 'you' : userId)

  return (
    <div
      className="min-h-full"
      style={{
        maxWidth: 1440,
        margin: '0 auto',
        padding: '16px 20px 40px',
        display: 'grid',
        gridTemplateColumns: 'minmax(0, 1fr) 300px',
        gap: 18,
        alignItems: 'start',
      }}
    >
      {/* ── Left / main column ───────────────────────────────────────── */}
      <div className="flex flex-col gap-3.5 min-w-0">
        {/* Greeting + Today card */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)',
            gap: 14,
            alignItems: 'stretch',
          }}
        >
          <Greeting name={displayName} />
          <TodaySummaryCard stats={todayStats} />
        </div>

        {/* Quick capture */}
        <QuickCapture />

        {/* App gallery */}
        <div className="flex flex-col gap-6 mt-2">
          {APP_GROUPS.map(g => (
            <AppGallerySection key={g.key} groupKey={g.key} label={g.label} />
          ))}
        </div>
      </div>

      {/* ── Right column ──────────────────────────────────────────────── */}
      <div className="flex flex-col gap-3 min-w-0">
        <ProposalStatusCard proposals={proposals} onDecide={decide} />
        <RuntimeStatusCard adapters={adapters} />
        <RecentCard sessions={sessions} />
      </div>
    </div>
  )
}
