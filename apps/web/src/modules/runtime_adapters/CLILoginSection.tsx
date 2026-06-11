import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { credentialsApi } from '../../api/client'
import type { CredentialLoginMethod, CredentialStatus, LoginEvent } from '../../types/api'
import { Card, CardTitle } from '../../components/ui/card'
import { Button } from '../../components/ui/button'
import { Badge } from '../../components/ui/badge'
import { Skeleton } from '../../components/ui/skeleton'
import { errMsg } from '../../lib/utils'

const URL_RE = /https?:\/\/[^\s]+/g

function extractUrls(text: string): string[] {
  // PTY terminals wrap long lines — join non-space chars split by a newline so the
  // regex can capture URLs that span two terminal lines (e.g. Claude auth URLs >220 chars).
  const joined = text.replace(/([^\s])\r?\n([^\s])/g, '$1$2')
  return [...new Set(joined.match(URL_RE) ?? [])]
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

// ── API key form ──────────────────────────────────────────────────────────────

function ApiKeyForm({ runtime, envVar, hint, onSaved }: {
  runtime: string
  envVar: string | null
  hint: string
  onSaved: () => void
}) {
  const [key, setKey] = useState('')
  const [saving, setSaving] = useState(false)

  async function save() {
    if (!key.trim()) return
    setSaving(true)
    try {
      await credentialsApi.saveApiKey(runtime, key.trim())
      toast.success('API key saved')
      setKey('')
      onSaved()
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-2 border-t pt-3 mt-1">
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      {envVar && (
        <p className="text-xs text-muted-foreground">
          Injected as <code className="bg-muted px-1 rounded">{envVar}</code> for each sandboxed run.
        </p>
      )}
      <div className="flex gap-2">
        <input
          type="password"
          className="flex-1 text-sm border rounded px-2 py-1 bg-background font-mono"
          placeholder={envVar?.startsWith('ANTHROPIC') ? 'sk-ant-…' : 'sk-…'}
          value={key}
          onChange={e => setKey(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && save()}
          autoComplete="off"
        />
        <Button size="sm" onClick={save} disabled={saving || !key.trim()}>
          {saving ? 'Saving…' : 'Save key'}
        </Button>
      </div>
    </div>
  )
}

// ── Single runtime card ───────────────────────────────────────────────────────

function LoginCard({ status, method, onRefresh, onLoginSuccess }: {
  status: CredentialStatus
  method: CredentialLoginMethod
  onRefresh: () => void
  onLoginSuccess?: () => void
}) {
  const [logs, setLogs]               = useState<LoginEvent[]>([])
  const [urls, setUrls]               = useState<string[]>([])
  const [running, setRunning]         = useState(false)
  const [exitCode, setExitCode]       = useState<number | null>(null)
  const [active, setActive]           = useState(false)   // whether login panel is open
  const [showLog, setShowLog]         = useState(false)   // dev: raw log toggle
  const [needsCode, setNeedsCode]     = useState(false)
  const [showKeyForm, setShowKeyForm] = useState(false)
  const accTextRef = useRef('')

  async function startCLILogin() {
    setLogs([])
    setUrls([])
    setExitCode(null)
    setNeedsCode(false)
    setActive(true)
    setShowLog(false)
    setShowKeyForm(false)
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
        if (event.type === 'needs_input') setNeedsCode(true)
        if (event.type === 'done') {
          setExitCode(event.exit_code ?? -1)
          setNeedsCode(false)
          if (event.exit_code === 0) {
            onRefresh()
            // Re-read usage ~8s after login — gives credentials time to sync
            setTimeout(() => onLoginSuccess?.(), 8000)
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
    if (urls.length > 0) return { text: 'Completing login…', color: 'text-blue-600' }
    return { text: 'Setting up…', color: 'text-muted-foreground' }
  })()

  const loggedIn = status.logged_in

  return (
    <div className="border rounded-lg p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2 min-w-0">
          <span className="font-medium">{status.label}</span>
          <span className="text-xs font-mono text-muted-foreground">{status.runtime}</span>
          <Badge variant={loggedIn ? 'default' : 'secondary'} className="shrink-0">
            {loggedIn
              ? `logged in · ${status.file_count} file${status.file_count !== 1 ? 's' : ''}`
              : 'not configured'}
          </Badge>
        </div>

        <div className="flex gap-2 shrink-0 flex-wrap">
          {method.supports_cli && (
            <Button
              size="sm"
              variant={loggedIn && !active ? 'outline' : 'default'}
              onClick={startCLILogin}
              disabled={running}
            >
              {running ? 'Logging in…' : 'Login via CLI'}
            </Button>
          )}
          {method.supports_api_key && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => { setShowKeyForm(v => !v); setActive(false) }}
            >
              {loggedIn && !method.supports_cli ? 'Update key' : 'Use API key'}
            </Button>
          )}
        </div>
      </div>

      {/* CLI login panel */}
      {active && (
        <div className="space-y-2">
          {/* Status line */}
          {statusMsg && (
            <div className="flex items-center justify-between">
              <p className={`text-xs font-medium ${statusMsg.color} ${running && !needsCode && urls.length === 0 ? 'animate-pulse' : ''}`}>
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

          {/* URL card */}
          <UrlCard urls={urls} />

          {/* Raw log — hidden by default */}
          {showLog && <LogPanel events={logs} />}

          {/* Code input */}
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

      {/* API key form */}
      {showKeyForm && (
        <ApiKeyForm
          runtime={status.runtime}
          envVar={method.env_var}
          hint={method.hint_api_key}
          onSaved={() => { setShowKeyForm(false); onRefresh() }}
        />
      )}
    </div>
  )
}

// ── Exported section ──────────────────────────────────────────────────────────

export default function CLILoginSection({ onLoginSuccess }: { onLoginSuccess?: () => void } = {}) {
  const [statuses, setStatuses] = useState<CredentialStatus[]>([])
  const [methods, setMethods]   = useState<CredentialLoginMethod[]>([])
  const [loading, setLoading]   = useState(true)

  async function load() {
    setLoading(true)
    try {
      const [s, m] = await Promise.all([credentialsApi.status(), credentialsApi.methods()])
      setStatuses(s)
      setMethods(m)
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const methodMap = Object.fromEntries(methods.map(m => [m.runtime, m]))

  return (
    <Card>
      <div className="flex items-center justify-between mb-4">
        <CardTitle>CLI Credentials</CardTitle>
        <Button size="sm" variant="ghost" onClick={load} disabled={loading}>Refresh</Button>
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
            return <LoginCard key={s.runtime} status={s} method={m} onRefresh={load} onLoginSuccess={onLoginSuccess} />
          })}
        </div>
      )}
    </Card>
  )
}
