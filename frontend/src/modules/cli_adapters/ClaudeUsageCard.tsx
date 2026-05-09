import { useState, useEffect, useCallback, useRef, forwardRef, useImperativeHandle } from 'react'
import { RefreshCw, Loader2 } from 'lucide-react'
import { cliAdaptersApi } from '../../api/client'
import { errMsg } from '../../lib/utils'
import { Card, CardTitle } from '../../components/ui/card'
import { Button } from '../../components/ui/button'
import { Skeleton } from '../../components/ui/skeleton'
import { cn } from '../../lib/utils'

// ── Types ──────────────────────────────────────────────────────────────────

interface DayActivity {
  date: string
  messages: number
  sessions: number
  tool_calls: number
}

interface ModelUsage {
  model: string
  input_tokens: number
  output_tokens: number
  cache_read_tokens: number
  cache_write_tokens: number
  total_tokens: number
  cost_usd: number
}

interface Quota {
  session_pct: number | null
  session_resets: string | null
  week_pct: number | null
  week_resets: string | null
  checked_at?: string   // ISO timestamp of last fetch
  error?: string
}

interface ClaudeStats {
  available: boolean
  stats_available?: boolean  // false when no stats-cache.json (subscription-only users)
  error?: string
  last_computed?: string
  first_session_date?: string
  total_sessions: number
  total_messages: number
  week_messages: number
  week_sessions: number
  week_tool_calls: number
  daily: DayActivity[]
  models: ModelUsage[]
  quota?: Quota
}

// ── Helpers ────────────────────────────────────────────────────────────────

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000)     return `${(n / 1_000).toFixed(0)}k`
  return String(n)
}

function timeAgo(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diffMs / 60_000)
  if (mins < 1)   return 'just now'
  if (mins < 60)  return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24)   return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

function fmtDate(iso: string | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function shortModel(id: string): string {
  const m = id.match(/claude-(\w+)-(\d+)-(\d+)/)
  if (m) return `${m[1].charAt(0).toUpperCase() + m[1].slice(1)} ${m[2]}.${m[3]}`
  return id
}

// ── Quota bar ──────────────────────────────────────────────────────────────

function QuotaBar({ label, pct, resets }: { label: string; pct: number; resets: string | null }) {
  const color = pct >= 90 ? 'bg-red-500' : pct >= 70 ? 'bg-orange-400' : pct >= 50 ? 'bg-yellow-400' : 'bg-primary/70'
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-medium text-foreground">{label}</span>
        <span className={cn(
          'text-xs font-semibold px-1.5 py-0.5 rounded',
          pct >= 90 ? 'bg-red-500/15 text-red-600' :
          pct >= 70 ? 'bg-orange-500/15 text-orange-600' :
          pct >= 50 ? 'bg-yellow-500/15 text-yellow-600' :
          'bg-primary/10 text-primary',
        )}>
          {pct}% used
        </span>
      </div>
      <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
        <div className={cn('h-full rounded-full transition-all', color)} style={{ width: `${pct}%` }} />
      </div>
      {resets && <p className="text-[11px] text-muted-foreground mt-0.5">{resets}</p>}
    </div>
  )
}

// ── Mini bar chart ─────────────────────────────────────────────────────────

function ActivityBar({ daily }: { daily: DayActivity[] }) {
  const max = Math.max(...daily.map(d => d.messages), 1)
  const today = new Date().toISOString().slice(0, 10)
  return (
    <div className="flex items-end gap-0.5 h-10">
      {daily.map(d => {
        const pct = Math.max((d.messages / max) * 100, d.messages > 0 ? 4 : 0)
        const isToday = d.date === today
        return (
          <div
            key={d.date}
            title={`${fmtDate(d.date)}: ${d.messages.toLocaleString()} messages, ${d.tool_calls.toLocaleString()} tool calls`}
            className="flex-1 flex items-end"
          >
            <div
              className={cn(
                'w-full rounded-sm',
                isToday ? 'bg-primary/70' : d.messages > 0 ? 'bg-primary/30' : 'bg-muted/40',
              )}
              style={{ height: `${pct}%`, minHeight: d.messages > 0 ? '3px' : '2px' }}
            />
          </div>
        )
      })}
    </div>
  )
}

// ── Main card ──────────────────────────────────────────────────────────────

export interface ClaudeUsageCardHandle {
  refreshQuota: () => void
}

const AUTO_REFRESH_MS = 2.5 * 60 * 60 * 1000  // 2.5 hours

const ClaudeUsageCard = forwardRef<ClaudeUsageCardHandle>(function ClaudeUsageCard(_, ref) {
  const [stats, setStats]           = useState<ClaudeStats | null>(null)
  const [loading, setLoading]       = useState(true)
  const [quotaLoading, setQuotaLoading] = useState(false)
  const [error, setError]           = useState<string | null>(null)
  const autoRefreshTimer            = useRef<ReturnType<typeof setInterval> | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await cliAdaptersApi.claudeUsage()
      setStats(data as unknown as ClaudeStats)
    } catch (e) {
      setError(errMsg(e))
    } finally {
      setLoading(false)
    }
  }, [])

  const refreshQuota = useCallback(async () => {
    setQuotaLoading(true)
    try {
      const data = await cliAdaptersApi.refreshClaudeQuota()
      setStats(prev => prev ? { ...prev, quota: data as unknown as Quota } : prev)
    } catch (e) {
      setStats(prev => prev ? { ...prev, quota: { session_pct: null, session_resets: null, week_pct: null, week_resets: null, error: errMsg(e) } } : prev)
    } finally {
      setQuotaLoading(false)
    }
  }, [])

  useImperativeHandle(ref, () => ({ refreshQuota }), [refreshQuota])

  useEffect(() => {
    load()
    // Auto-refresh quota every 2.5 hours
    autoRefreshTimer.current = setInterval(refreshQuota, AUTO_REFRESH_MS)
    return () => { if (autoRefreshTimer.current) clearInterval(autoRefreshTimer.current) }
  }, [load, refreshQuota])

  const quota = stats?.quota

  return (
    <Card>
      <div className="flex items-center justify-between mb-4">
        <CardTitle>Claude Code Activity</CardTitle>
        <Button variant="ghost" size="sm" onClick={load} disabled={loading} className="h-7 w-7 p-0">
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
        </Button>
      </div>

      {loading && !stats && (
        <div className="space-y-3">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="h-4 w-1/2" />
        </div>
      )}

      {error && <p className="text-sm text-destructive">{error}</p>}

      {stats && !stats.available && (
        <p className="text-sm text-muted-foreground">{stats.error ?? 'Stats unavailable'}</p>
      )}

      {stats?.available && (
        <div className="space-y-4">
          {/* Subscription quota bars */}
          <div className="space-y-3 p-3 rounded-lg bg-muted/20 border border-border">
            <div className="flex items-center justify-between">
              <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Subscription quota</p>
              <div className="flex items-center gap-2">
                {quota?.checked_at && !quotaLoading && (
                  <span className="text-[11px] text-muted-foreground">
                    checked {timeAgo(quota.checked_at)}
                  </span>
                )}
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={refreshQuota}
                  disabled={quotaLoading}
                  className="h-6 text-[11px] px-2"
                >
                  {quotaLoading
                    ? <><Loader2 size={11} className="animate-spin mr-1" />Fetching…</>
                    : <><RefreshCw size={10} className="mr-1" />Refresh</>}
                </Button>
              </div>
            </div>

            {quotaLoading && (
              <div className="space-y-2">
                <Skeleton className="h-6 w-full" />
                <Skeleton className="h-6 w-full" />
              </div>
            )}

            {!quota && !quotaLoading && (
              <p className="text-[11px] text-muted-foreground">
                No quota data yet. Click Refresh to fetch (takes ~5s).
              </p>
            )}

            {quota?.error && (
              <p className="text-[11px] text-destructive">{quota.error}</p>
            )}

            {quota && !quota.error && !quotaLoading && (
              <div className="space-y-3">
                {quota.session_pct != null
                  ? <QuotaBar label="Current session" pct={quota.session_pct} resets={quota.session_resets} />
                  : <p className="text-[11px] text-muted-foreground">Session quota unavailable</p>
                }
                {quota.week_pct != null
                  ? <QuotaBar label="Current week (all models)" pct={quota.week_pct} resets={quota.week_resets} />
                  : <p className="text-[11px] text-muted-foreground">Weekly quota unavailable</p>
                }
              </div>
            )}
          </div>

          {/* Activity stats — only when stats-cache.json is present */}
          {stats.stats_available !== false && (
            <>
              {/* Summary tiles */}
              <div className="grid grid-cols-3 gap-3">
                {[
                  { label: 'Messages (7d)',  value: stats.week_messages.toLocaleString() },
                  { label: 'Sessions (7d)',  value: stats.week_sessions.toLocaleString() },
                  { label: 'Tool calls (7d)', value: stats.week_tool_calls.toLocaleString() },
                ].map(({ label, value }) => (
                  <div key={label} className="bg-muted/30 rounded-lg p-3">
                    <div className="text-[11px] text-muted-foreground mb-1">{label}</div>
                    <div className="text-lg font-semibold text-foreground">{value}</div>
                  </div>
                ))}
              </div>

              {/* 14-day message activity */}
              {stats.daily.length > 0 && (
                <div>
                  <p className="text-[11px] text-muted-foreground mb-1.5">Messages — last 14 days (today highlighted)</p>
                  <ActivityBar daily={stats.daily} />
                </div>
              )}

              {/* Per-model token breakdown */}
              {stats.models.length > 0 && (
                <div>
                  <p className="text-[11px] text-muted-foreground mb-2">Token usage by model (all time)</p>
                  <div className="space-y-2.5">
                    {stats.models.map(m => {
                      const pct = stats.models[0].total_tokens > 0
                        ? Math.round((m.total_tokens / stats.models[0].total_tokens) * 100) : 0
                      return (
                        <div key={m.model}>
                          <div className="flex items-center justify-between mb-0.5">
                            <span className="text-xs font-medium text-foreground">{shortModel(m.model)}</span>
                            <span className="text-xs text-muted-foreground font-mono">{fmtTokens(m.total_tokens)}</span>
                          </div>
                          <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
                            <div className="h-full rounded-full bg-primary/50" style={{ width: `${pct}%` }} />
                          </div>
                          <div className="flex gap-3 mt-0.5">
                            {([['in', m.input_tokens], ['out', m.output_tokens], ['cache↑', m.cache_write_tokens], ['cache↓', m.cache_read_tokens]] as const).map(([lbl, val]) => (
                              <span key={lbl} className="text-[10px] text-muted-foreground">{lbl} {fmtTokens(val)}</span>
                            ))}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              {/* Footer */}
              <div className="flex items-center justify-between pt-1 border-t border-border">
                <span className="text-[11px] text-muted-foreground">
                  {stats.total_messages.toLocaleString()} total messages · {stats.total_sessions} sessions
                </span>
                <span className="text-[11px] text-muted-foreground">since {fmtDate(stats.first_session_date)}</span>
              </div>
            </>
          )}
        </div>
      )}
    </Card>
  )
})

export default ClaudeUsageCard
