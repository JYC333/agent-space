import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { ChevronDown, ChevronRight, Copy, Download, ExternalLink } from 'lucide-react'
import { credentialsApi, runtimeToolsApi } from '../../api/client'
import type { CliUsageAutoRefreshSettings, CliUsageEntry, CredentialLoginMethod, CredentialStatus, LoginEvent, RuntimeToolStatus } from '../../types/api'
import { Card, CardTitle } from '../../components/ui/card'
import { Button } from '../../components/ui/button'
import { Badge } from '../../components/ui/badge'
import { Input } from '../../components/ui/input'
import { Skeleton } from '../../components/ui/skeleton'
import { errMsg } from '../../lib/utils'

const URL_RE = /https?:\/\/[^\s<>"']+/g
const NON_BROWSER_LOGIN_URL_RE = /https:\/\/auth\.openai\.com\/api\/accounts\/deviceauth\/usercode\b/
const CLI_USAGE_CACHE_RELOAD_MS = 3 * 60 * 60 * 1000

function extractUrls(text: string): string[] {
  // PTY terminals wrap long lines — join non-space chars split by a newline so the
  // regex can capture URLs that span two terminal lines (e.g. Claude auth URLs >220 chars).
  const joined = text.replace(/([^\s])\r?\n([^\s])/g, '$1$2')
  const urls = (joined.match(URL_RE) ?? [])
    .map(url => url.replace(/[)\].,;:!?]+$/g, ''))
    .filter(url => !NON_BROWSER_LOGIN_URL_RE.test(url))
    .filter(Boolean)
  return [...new Set(urls)]
}

// ── URL card — shown above the log when OAuth URLs are detected ───────────────

function UrlCard({ urls }: { urls: string[] }) {
  if (urls.length === 0) return null
  return (
    <div className="rounded-md border border-blue-200 bg-blue-50 p-3 space-y-2">
      <p className="text-xs font-semibold text-blue-800">Open this URL to sign in:</p>
      {urls.map(url => (
        <a
          key={url}
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="block text-xs text-blue-700 underline break-all"
        >
          {url}
        </a>
      ))}
      <Button
        size="sm"
        variant="outline"
        className="text-blue-700 border-blue-300 h-7 text-xs"
        onClick={() => window.open(urls[0], '_blank')}
      >
        Open in browser ↗
      </Button>
    </div>
  )
}

interface DeviceAuthInfo {
  url: string
  code: string
  expires_in_minutes?: number
}

function DeviceAuthCard({ auth }: { auth: DeviceAuthInfo | null }) {
  if (!auth) return null
  const info = auth

  async function copyCode() {
    try {
      await navigator.clipboard.writeText(info.code)
      toast.success('Code copied')
    } catch {
      toast.error('Could not copy code')
    }
  }

  return (
    <div className="rounded-md border border-blue-200 bg-blue-50 p-3 space-y-3">
      <div className="space-y-1">
        <p className="text-xs font-semibold text-blue-800">Open this URL:</p>
        <a
          href={info.url}
          target="_blank"
          rel="noopener noreferrer"
          className="block text-xs text-blue-700 underline break-all"
        >
          {info.url}
        </a>
      </div>
      <div className="flex items-center justify-between gap-3 rounded border border-blue-200 bg-background px-3 py-2">
        <div className="min-w-0">
          <p className="text-[11px] font-medium text-muted-foreground">One-time code</p>
          <p className="font-mono text-lg font-semibold tracking-wide text-foreground">{info.code}</p>
          {info.expires_in_minutes && (
            <p className="text-[11px] text-muted-foreground">Expires in {info.expires_in_minutes} minutes</p>
          )}
        </div>
        <div className="flex gap-2 shrink-0">
          <Button size="sm" variant="outline" onClick={copyCode}>
            <Copy className="size-3.5" />
            Copy
          </Button>
          <Button size="sm" onClick={() => window.open(info.url, '_blank')}>
            <ExternalLink className="size-3.5" />
            Open
          </Button>
        </div>
      </div>
    </div>
  )
}

// ── Terminal log panel ────────────────────────────────────────────────────────

function LogPanel({ events }: { events: LoginEvent[] }) {
  const bottomRef = useRef<HTMLDivElement>(null)
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [events])

  const cls = (type: LoginEvent['type']) => {
    if (type === 'error')       return 'text-red-400'
    if (type === 'warning')     return 'text-yellow-400'
    if (type === 'hint')        return 'text-cyan-400'
    if (type === 'synced')      return 'text-emerald-400'
    if (type === 'needs_input') return 'text-yellow-300'
    return 'text-green-300'
  }

  return (
    <div className="bg-zinc-950 rounded-md p-3 h-40 overflow-y-auto font-mono text-xs leading-relaxed">
      {events.map((e, i) => {
        // Strip URLs from terminal output — they're shown in the UrlCard above
        const text = (e.text ?? '').replace(URL_RE, '[url]')
        return <div key={i} className={cls(e.type)}>{text}</div>
      })}
      <div ref={bottomRef} />
    </div>
  )
}

// ── Interactive PTY input (menu choices, OAuth code, etc.) ────────────────────

function CodeInput({ runtime, prompt, onSent, onRefresh }: {
  runtime: string
  prompt: string
  onSent: () => void
  onRefresh: () => void
}) {
  const [code, setCode] = useState('')
  const [sending, setSending] = useState(false)

  async function send() {
    if (!code.trim()) return
    setSending(true)
    try {
      await credentialsApi.sendLoginInput(runtime, code.trim())
      setCode('')
      onSent()
      // Give the backend time to complete login and sync credentials
      setTimeout(onRefresh, 5000)
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="rounded-md border border-yellow-200 bg-yellow-50 p-3 space-y-2">
      <p className="text-xs font-semibold text-yellow-800">{prompt}</p>
      <div className="flex gap-2">
        <input
          autoFocus
          className="flex-1 text-sm border rounded px-2 py-1 bg-background font-mono"
          placeholder="Paste the authorization code from your browser…"
          value={code}
          onChange={e => setCode(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && send()}
        />
        <Button size="sm" onClick={send} disabled={sending || !code.trim()}>
          {sending ? 'Sending…' : 'Submit'}
        </Button>
      </div>
    </div>
  )
}

// ── Usage panel ────────────────────────────────────────────────────────────────

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

function fmtCost(n: number): string {
  if (n > 0 && n < 0.01) return `$${n.toFixed(6)}`
  return `$${n.toFixed(2)}`
}

function QuotaBar({ label, pct, resets }: { label: string; pct: number; resets: string | null }) {
  const clamped = Math.max(0, Math.min(100, pct))
  const tone = pct > 90
    ? { bar: 'bg-destructive', text: 'text-destructive' }
    : pct > 80
      ? { bar: 'bg-warning', text: 'text-warning' }
      : { bar: 'bg-primary', text: '' }

  return (
    <div className="space-y-0.5">
      <div className="flex justify-between"><span>{label}</span><span className={tone.text}>{pct}% used</span></div>
      <div className="h-1.5 rounded bg-muted overflow-hidden">
        <div className={`h-full ${tone.bar}`} style={{ width: `${clamped}%` }} />
      </div>
      {resets && <p className="text-[10px] text-muted-foreground">{resets}</p>}
    </div>
  )
}

// Token totals come from the CLI's local transcripts/sessions; quota bars come
// from the cached runtime-specific probe. Either may be absent, so each block
// renders on its own.
function UsagePanel({ usage, onRefreshQuota, refreshingQuota }: {
  usage?: CliUsageEntry
  onRefreshQuota?: () => void
  refreshingQuota?: boolean
}) {
  if (!usage) return null
  const t = usage.tokens
  const q = usage.quota
  // Show the token block for any runtime that supports transcript parsing, even
  // at zero — "0" is meaningful (logged in, no runs yet) vs. hidden.
  const showTokens = t.source !== 'unsupported'
  const hasQuota = Boolean(q?.available && (q.session_pct !== null || q.week_pct !== null))
  const canProbeQuota = (usage.runtime === 'claude_code' || usage.runtime === 'codex_cli') && Boolean(onRefreshQuota)

  if (!showTokens && !hasQuota && !canProbeQuota) {
    return <p className="text-xs text-muted-foreground">No recorded usage yet.</p>
  }

  return (
    <div className="rounded-md border bg-muted/30 p-2.5 space-y-2 text-xs">
      {showTokens && (
        <div className="space-y-1">
          <div className="flex items-center justify-between">
            <span className="font-medium text-muted-foreground">Token usage</span>
            <span className="text-[11px] text-muted-foreground">
              {t.session_count} session{t.session_count !== 1 ? 's' : ''}
            </span>
          </div>
          <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 font-mono">
            <span>in: {fmtTokens(t.input_tokens)}</span>
            <span>cached: {fmtTokens(t.cache_read_input_tokens)}</span>
            <span>out: {fmtTokens(t.output_tokens)}</span>
            {t.cache_creation_input_tokens > 0 && (
              <span>cache w: {fmtTokens(t.cache_creation_input_tokens)}</span>
            )}
          </div>
          <div className="text-muted-foreground">est. cost {fmtCost(t.cost_usd)}</div>
          {t.message_count === 0
            ? <p className="text-[10px] text-muted-foreground/70">No runs recorded yet for this runtime.</p>
            : <p className="text-[10px] text-muted-foreground/70">From local {t.source === 'codex_sessions' ? 'sessions' : 'transcripts'} — approximate (excludes thinking tokens).</p>}
        </div>
      )}

      {(hasQuota || canProbeQuota) && (
        <div className="space-y-1.5 border-t pt-2">
          <div className="flex items-center justify-between">
            <span className="font-medium text-muted-foreground">Subscription quota</span>
            {canProbeQuota && (
              <button
                className="text-[11px] text-muted-foreground underline underline-offset-2 disabled:opacity-50"
                onClick={onRefreshQuota}
                disabled={refreshingQuota}
              >
                {refreshingQuota ? 'Checking…' : 'Refresh'}
              </button>
            )}
          </div>
          {hasQuota && q && (
            <>
              {q.session_pct !== null && <QuotaBar label="Current session" pct={q.session_pct} resets={q.session_resets} />}
              {q.week_pct !== null && <QuotaBar label="Current week" pct={q.week_pct} resets={q.week_resets} />}
              {q.checked_at && (
                <p className="text-[10px] text-muted-foreground/70">checked {new Date(q.checked_at).toLocaleString()}</p>
              )}
            </>
          )}
          {q?.error && <p className="text-[10px] text-amber-600">{q.error}</p>}
          {!hasQuota && !q?.error && (
            <p className="text-[10px] text-muted-foreground/70">Click Refresh to read live subscription usage.</p>
          )}
        </div>
      )}
    </div>
  )
}

// ── Single runtime card ───────────────────────────────────────────────────────

function LoginCard({
  status,
  method,
  runtimeTool,
  toolsLoading = false,
  installingTool = false,
  onInstallTool,
  onRefresh,
  usage,
  onRefreshQuota,
  refreshingQuota = false,
  version,
  onVersionChange,
}: {
  status: CredentialStatus
  method: CredentialLoginMethod
  onRefresh: () => void
  usage?: CliUsageEntry
  onRefreshQuota?: () => void
  refreshingQuota?: boolean
  runtimeTool?: RuntimeToolStatus
  toolsLoading?: boolean
  installingTool?: boolean
  onInstallTool?: (runtime: string) => void
  version: string
  onVersionChange: (runtime: string, version: string) => void
}) {
  const [logs, setLogs]               = useState<LoginEvent[]>([])
  const [urls, setUrls]               = useState<string[]>([])
  const [deviceAuth, setDeviceAuth]   = useState<DeviceAuthInfo | null>(null)
  const [running, setRunning]         = useState(false)
  const [exitCode, setExitCode]       = useState<number | null>(null)
  const [active, setActive]           = useState(false)   // whether login panel is open
  const [showLog, setShowLog]         = useState(false)   // dev: raw log toggle
  const [needsCode, setNeedsCode]     = useState(false)
  // Installed/logged-in runtimes start expanded; the rest collapse to a row.
  const [expanded, setExpanded]       = useState(() => status.logged_in || Boolean(runtimeTool?.installed))
  const [showTool, setShowTool]       = useState(false)   // advanced tool-management
  const [latest, setLatest]           = useState<string | null | undefined>(undefined)
  const [latestError, setLatestError] = useState(false)
  const latestReqRef = useRef(false)
  const accTextRef = useRef('')

  // Check the registry's latest version once the user opens tool management, so
  // they can tell whether an update exists. On-demand to avoid network on load.
  useEffect(() => {
    if (!showTool || !runtimeTool || latestReqRef.current) return
    latestReqRef.current = true
    setLatestError(false)
    runtimeToolsApi.latest(status.runtime)
      .then(r => setLatest(r.latest_version))
      .catch(() => { setLatestError(true); latestReqRef.current = false })
  }, [showTool, runtimeTool, status.runtime])

  async function startCLILogin() {
    if (method.supports_cli && !runtimeTool?.installed) {
      toast.error(`Install ${status.label} runtime tool before starting CLI login`)
      return
    }
    setLogs([])
    setUrls([])
    setDeviceAuth(null)
    setExitCode(null)
    setNeedsCode(false)
    setActive(true)
    setShowLog(false)
    setRunning(true)
    accTextRef.current = ''
    try {
      for await (const event of credentialsApi.loginStream(status.runtime)) {
        setLogs(prev => [...prev, event])
        if (event.type === 'output' && event.text) {
          accTextRef.current += event.text
          const found = extractUrls(accTextRef.current)
          if (found.length > 0) setUrls(found)
        }
        if (event.type === 'device_auth' && event.url && event.code) {
          setDeviceAuth({
            url: event.url,
            code: event.code,
            expires_in_minutes: event.expires_in_minutes,
          })
          setUrls([event.url])
          setNeedsCode(false)
        }
        if (event.type === 'needs_input') setNeedsCode(true)
        if (event.type === 'done') {
          setExitCode(event.exit_code ?? -1)
          setNeedsCode(false)
          if (event.exit_code === 0) {
            onRefresh()
            // Re-read status + usage ~8s after login — credentials/transcripts sync lazily.
            setTimeout(onRefresh, 8000)
          }
        }
      }
    } catch (e) {
      setLogs(prev => [...prev, { type: 'error', text: errMsg(e) + '\n' }])
    } finally {
      setRunning(false)
    }
  }

  // Derive a single status message from current state
  const statusMsg = (() => {
    if (!active) return null
    if (exitCode === 0) return { text: 'Login succeeded', color: 'text-emerald-600' }
    if (exitCode !== null) return { text: `Login failed (exit ${exitCode})`, color: 'text-red-600' }
    if (needsCode) return { text: 'Waiting for authorization code…', color: 'text-yellow-600' }
    if (deviceAuth) return { text: 'Waiting for browser sign-in…', color: 'text-blue-600' }
    if (urls.length > 0) return { text: 'Completing login…', color: 'text-blue-600' }
    return { text: 'Setting up…', color: 'text-muted-foreground' }
  })()

  const loggedIn = status.logged_in
  const cliToolReady = !method.supports_cli || Boolean(runtimeTool?.installed)
  const cliToolKnown = !method.supports_cli || Boolean(runtimeTool)

  const installLabel = installingTool ? 'Installing…' : toolsLoading ? 'Checking…' : 'Install tool'

  return (
    <div className="border rounded-lg p-4 space-y-3">
      {/* Header — click to expand/collapse */}
      <button
        type="button"
        className="flex items-center justify-between gap-2 w-full text-left"
        onClick={() => setExpanded(v => !v)}
      >
        <div className="flex items-center gap-2 min-w-0 flex-wrap">
          {expanded
            ? <ChevronDown className="size-4 text-muted-foreground shrink-0" />
            : <ChevronRight className="size-4 text-muted-foreground shrink-0" />}
          <span className="font-medium">{status.label}</span>
          <span className="text-xs font-mono text-muted-foreground">{status.runtime}</span>
          <Badge variant={loggedIn ? 'default' : 'secondary'} className="shrink-0">
            {loggedIn ? 'logged in' : 'not configured'}
          </Badge>
          {method.supports_cli && (
            <Badge variant={cliToolReady ? 'success' : 'warning'} className="shrink-0">
              {cliToolReady
                ? `tool ${runtimeTool?.active_version ?? 'installed'}`
                : cliToolKnown ? 'not installed' : 'checking tool'}
            </Badge>
          )}
        </div>
      </button>

      {expanded && (
        <div className="space-y-3">
          {/* Usage — tokens (local transcripts/sessions) + subscription quota (cached probe) */}
          {loggedIn && (
            <UsagePanel usage={usage} onRefreshQuota={onRefreshQuota} refreshingQuota={refreshingQuota} />
          )}

          {/* Primary actions */}
          <div className="flex gap-2 flex-wrap">
            {method.supports_cli && !cliToolReady && onInstallTool && (
              <Button
                size="sm"
                onClick={() => onInstallTool(status.runtime)}
                disabled={installingTool || toolsLoading}
              >
                <Download className="size-3.5" />
                {installLabel}
              </Button>
            )}
            {method.supports_cli && (
              <Button
                size="sm"
                variant={loggedIn && !active ? 'outline' : 'default'}
                onClick={startCLILogin}
                disabled={running || !cliToolReady}
              >
                {running ? 'Logging in…' : loggedIn ? 'Re-login via CLI' : 'Login via CLI'}
              </Button>
            )}
          </div>

          {/* CLI login panel */}
          {active && (
            <div className="space-y-2">
              {statusMsg && (
                <div className="flex items-center justify-between">
                  <p className={`text-xs font-medium ${statusMsg.color} ${running && !needsCode && !deviceAuth && urls.length === 0 ? 'animate-pulse' : ''}`}>
                    {statusMsg.text}
                  </p>
                  <button
                    className="text-xs text-muted-foreground underline underline-offset-2"
                    onClick={() => setShowLog(v => !v)}
                  >
                    {showLog ? 'Hide log' : 'Show log'}
                  </button>
                </div>
              )}
              <DeviceAuthCard auth={deviceAuth} />
              {!deviceAuth && <UrlCard urls={urls} />}
              {showLog && <LogPanel events={logs} />}
              {needsCode && (
                <CodeInput
                  runtime={status.runtime}
                  prompt="Open the URL above in your browser, then paste the authorization code here."
                  onSent={() => setNeedsCode(false)}
                  onRefresh={onRefresh}
                />
              )}
            </div>
          )}

          {/* Advanced — tool install/version/update (folded) */}
          {method.supports_cli && runtimeTool && (
            <div className="border-t pt-2">
              <button
                className="text-xs text-muted-foreground underline underline-offset-2"
                onClick={() => setShowTool(v => !v)}
              >
                {showTool ? 'Hide tool management' : 'Manage tool'}
              </button>
              {showTool && (
                <div className="space-y-2 mt-2">
                  {runtimeTool.package_name && (
                    <p className="text-xs font-mono text-muted-foreground break-all">{runtimeTool.package_name}</p>
                  )}
                  {runtimeTool.executable_path && (
                    <p className="text-xs font-mono text-muted-foreground break-all">{runtimeTool.executable_path}</p>
                  )}
                  {runtimeTool.warnings.map(w => (
                    <p key={w} className="text-xs text-amber-600">{w}</p>
                  ))}
                  <div className="flex items-center gap-2 text-xs flex-wrap">
                    <span className="text-muted-foreground">installed {runtimeTool.active_version ?? '—'}</span>
                    {latest === undefined && !latestError && (
                      <span className="text-muted-foreground">· checking latest…</span>
                    )}
                    {latestError && <span className="text-muted-foreground">· latest unavailable</span>}
                    {latest && (
                      <>
                        <span className="text-muted-foreground">· latest {latest}</span>
                        {runtimeTool.active_version && runtimeTool.active_version !== latest
                          ? <Badge variant="warning">update available</Badge>
                          : runtimeTool.installed
                            ? <Badge variant="success">up to date</Badge>
                            : null}
                      </>
                    )}
                  </div>
                  <div className="flex flex-col gap-2 sm:flex-row">
                    <Input
                      className="sm:max-w-48 font-mono"
                      placeholder="latest"
                      value={version}
                      onChange={e => onVersionChange(status.runtime, e.target.value)}
                      onKeyDown={e => e.key === 'Enter' && onInstallTool?.(status.runtime)}
                    />
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => onInstallTool?.(status.runtime)}
                      disabled={installingTool || toolsLoading}
                    >
                      <Download className="size-3.5" />
                      {installingTool ? 'Installing…' : runtimeTool.installed ? 'Update tool' : 'Install tool'}
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── CLI credentials section ───────────────────────────────────────────────────

export default function CLILoginSection({
  runtimeToolsByRuntime = {},
  runtimeToolsLoading = false,
  installingRuntime = null,
  onInstallTool,
  versions = {},
  onVersionChange,
  onRefreshTools,
}: {
  runtimeToolsByRuntime?: Record<string, RuntimeToolStatus | undefined>
  runtimeToolsLoading?: boolean
  installingRuntime?: string | null
  onInstallTool?: (runtime: string) => void
  versions?: Record<string, string>
  onVersionChange?: (runtime: string, version: string) => void
  onRefreshTools?: () => void
} = {}) {
  const [statuses, setStatuses] = useState<CredentialStatus[]>([])
  const [methods, setMethods]   = useState<CredentialLoginMethod[]>([])
  const [usageByRuntime, setUsageByRuntime] = useState<Record<string, CliUsageEntry>>({})
  const [usageAutoRefresh, setUsageAutoRefresh] = useState<CliUsageAutoRefreshSettings | null>(null)
  const [refreshingQuota, setRefreshingQuota] = useState<string | null>(null)
  const [savingAutoRefresh, setSavingAutoRefresh] = useState(false)
  const [loading, setLoading]   = useState(true)

  async function loadUsage(quiet = false) {
    try {
      const usage = await credentialsApi.usage()
      setUsageByRuntime(Object.fromEntries(usage.map(e => [e.runtime, e])))
    } catch (e) {
      if (!quiet) toast.error(errMsg(e))
    }
  }

  async function load() {
    setLoading(true)
    try {
      const [s, m, usage, autoRefresh] = await Promise.all([
        credentialsApi.status(),
        credentialsApi.methods(),
        credentialsApi.usage().catch(() => [] as CliUsageEntry[]),
        credentialsApi.usageAutoRefresh().catch(() => null),
      ])
      setStatuses(s)
      setMethods(m)
      setUsageByRuntime(Object.fromEntries(usage.map(e => [e.runtime, e])))
      if (autoRefresh) setUsageAutoRefresh(autoRefresh)
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setLoading(false)
    }
  }

  // Live subscription-usage probe; merges the fresh entry in place.
  async function refreshQuota(runtime: string) {
    setRefreshingQuota(runtime)
    try {
      const entry = await credentialsApi.refreshUsage(runtime)
      setUsageByRuntime(prev => ({ ...prev, [runtime]: entry }))
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setRefreshingQuota(null)
    }
  }

  useEffect(() => {
    load()
  }, [])

  useEffect(() => {
    if (!usageAutoRefresh?.enabled) return
    const usageReloadTimer = window.setInterval(() => {
      void loadUsage(true)
    }, CLI_USAGE_CACHE_RELOAD_MS)
    return () => window.clearInterval(usageReloadTimer)
  }, [usageAutoRefresh?.enabled])

  async function updateAutoRefresh(enabled: boolean) {
    setSavingAutoRefresh(true)
    try {
      setUsageAutoRefresh(await credentialsApi.setUsageAutoRefresh(enabled))
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setSavingAutoRefresh(false)
    }
  }

  // One Refresh reloads both credentials/usage and runtime-tool state.
  function refreshAll() {
    load()
    onRefreshTools?.()
  }

  const methodMap = Object.fromEntries(methods.map(m => [m.runtime, m]))

  return (
    <Card>
      <div className="flex items-center justify-between mb-4">
        <CardTitle>CLI Runtimes</CardTitle>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <input
              type="checkbox"
              className="accent-primary"
              checked={usageAutoRefresh?.enabled ?? true}
              disabled={!usageAutoRefresh || savingAutoRefresh}
              onChange={e => updateAutoRefresh(e.target.checked)}
            />
            Auto usage checks
          </label>
          <Button size="sm" variant="ghost" onClick={refreshAll} disabled={loading}>Refresh</Button>
        </div>
      </div>

      {loading ? (
        <div className="space-y-2">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      ) : (
        <div className="space-y-3">
          {statuses.map(s => {
            const m = methodMap[s.runtime]
            if (!m) return null
            return (
              <LoginCard
                key={s.runtime}
                status={s}
                method={m}
                runtimeTool={runtimeToolsByRuntime[s.runtime]}
                toolsLoading={runtimeToolsLoading}
                installingTool={installingRuntime === s.runtime}
                onInstallTool={onInstallTool}
                onRefresh={refreshAll}
                usage={usageByRuntime[s.runtime]}
                onRefreshQuota={() => refreshQuota(s.runtime)}
                refreshingQuota={refreshingQuota === s.runtime}
                version={versions[s.runtime] ?? ''}
                onVersionChange={onVersionChange ?? (() => {})}
              />
            )
          })}
        </div>
      )}
    </Card>
  )
}
