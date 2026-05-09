import { useState, useEffect, useRef } from 'react'
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom'
import { KeyRound, X, Settings, Sun, Moon, LogOut } from 'lucide-react'
import { Toaster } from 'sonner'
import { useAuth } from '../contexts/AuthContext'
import { useTheme } from '../contexts/ThemeContext'
import { SpaceSwitcher } from '../components/SpaceSwitcher'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { cn } from '../lib/utils'

/* ── Aperture A brand mark ─────────────────────────────────────────────────── */
function ApertureMark({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 512 512" style={{ flexShrink: 0 }}>
      <rect width="512" height="512" rx="96" fill="var(--card)" />
      <rect x="80" y="80" width="352" height="352" rx="48" fill="var(--background)" stroke="var(--border)" strokeWidth="8" />
      <path
        d="M 176 360 L 232 184 Q 256 132 280 184 L 336 360"
        fill="none" stroke="var(--primary)" strokeWidth="44"
        strokeLinecap="round" strokeLinejoin="round"
      />
      <line x1="212" y1="288" x2="300" y2="288"
        stroke="var(--primary)" strokeWidth="44" strokeLinecap="round" />
      <circle cx="256" cy="288" r="18" fill="var(--accent-foreground)" />
    </svg>
  )
}

/* ── API key panel — opens as a popover from the key icon button ─────────────── */
function ApiKeyPanel() {
  const { apiKey, saveApiKey, clearApiKey, authRequired, setAuthRequired } = useAuth()
  const [open, setOpen]   = useState(false)
  const [draft, setDraft] = useState(apiKey)

  useEffect(() => { if (authRequired) setOpen(true) }, [authRequired])

  return (
    <div className="relative">
      <button
        onClick={() => { setDraft(apiKey); setOpen(o => !o) }}
        className={cn(
          'flex items-center justify-center w-8 h-8 rounded-md border transition-colors',
          authRequired
            ? 'border-warning/60 text-warning bg-warning/10'
            : apiKey
              ? 'border-border text-muted-foreground hover:text-foreground hover:bg-accent'
              : 'border-warning/40 text-warning/80 hover:bg-warning/10',
        )}
        title={apiKey ? 'API key configured' : 'No API key set'}
      >
        <KeyRound className="size-3.5" />
      </button>

      {open && (
        <div className="absolute top-[calc(100%+8px)] right-0 w-72 bg-card border border-border rounded-lg p-3.5 z-50">
          <div className="flex items-center justify-between mb-2.5">
            <span className="text-xs font-medium text-foreground">API Key</span>
            <button
              onClick={() => { setOpen(false); setAuthRequired(false) }}
              className="text-muted-foreground hover:text-foreground transition-colors"
            >
              <X className="size-3.5" />
            </button>
          </div>
          {authRequired && (
            <p className="text-xs text-warning mb-2">Authentication required by server.</p>
          )}
          <Input
            type="password"
            value={draft}
            onChange={e => setDraft(e.target.value)}
            placeholder="ask_…"
            className="h-7 text-xs mb-2"
            onKeyDown={e => {
              if (e.key === 'Enter') { saveApiKey(draft); setOpen(false) }
            }}
          />
          <div className="flex gap-1.5">
            <Button
              size="sm"
              className="flex-1 h-6 text-xs"
              onClick={() => { saveApiKey(draft); setOpen(false) }}
            >
              Save
            </Button>
            {apiKey && (
              <Button
                size="sm"
                variant="outline"
                className="h-6 text-xs"
                onClick={() => { clearApiKey(); setDraft(''); setOpen(false) }}
              >
                Clear
              </Button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

/* ── Theme toggle button ───────────────────────────────────────────────────── */
function ThemeToggle() {
  const { theme, toggleTheme } = useTheme()
  return (
    <button
      onClick={toggleTheme}
      className="flex items-center justify-center w-8 h-8 rounded-md border border-border text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
      title={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
    >
      {theme === 'dark' ? <Sun className="size-3.5" /> : <Moon className="size-3.5" />}
    </button>
  )
}

/* ── User menu ─────────────────────────────────────────────────────────────── */
function UserMenu() {
  const { currentUser, logout } = useAuth()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  if (!currentUser) {
    return (
      <button
        onClick={() => navigate('/login')}
        className="flex items-center gap-1.5 h-8 px-2.5 rounded-md border border-border text-[12px] font-medium text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
      >
        Sign in
      </button>
    )
  }

  const initials = currentUser.display_name.slice(0, 2).toUpperCase()

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center justify-center w-8 h-8 rounded-full border border-border overflow-hidden hover:opacity-90 transition-opacity"
        title={currentUser.display_name}
      >
        {currentUser.avatar_url
          ? <img src={currentUser.avatar_url} alt={currentUser.display_name} className="w-full h-full object-cover" />
          : <span className="text-[11px] font-semibold text-accent-foreground">{initials}</span>
        }
      </button>

      {open && (
        <div className="absolute top-[calc(100%+6px)] right-0 w-56 bg-card border border-border rounded-lg shadow-lg z-50 py-1 overflow-hidden">
          <div className="px-3 py-2 border-b border-border">
            <div className="text-[13px] font-medium text-foreground truncate">{currentUser.display_name}</div>
            <div className="text-[11px] text-muted-foreground truncate">{currentUser.email}</div>
          </div>
          <button
            onClick={() => { setOpen(false); logout() }}
            className="w-full flex items-center gap-2 px-3 py-2 text-left text-[13px] text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
          >
            <LogOut size={13} />
            Sign out
          </button>
        </div>
      )}
    </div>
  )
}

/* ── Top bar ───────────────────────────────────────────────────────────────── */
function TopBar() {
  return (
    <header className="shrink-0 flex items-center gap-2.5 h-14 px-4 border-b border-border bg-card">
      {/* Brand — always links home */}
      <Link
        to="/"
        className="flex items-center gap-2.5 pr-3 h-full border-r border-border shrink-0"
        style={{ textDecoration: 'none' }}
      >
        <ApertureMark size={22} />
        <span className="font-bold text-[13px] tracking-tight text-accent-foreground">
          agent-space
        </span>
      </Link>

      {/* Space switcher */}
      <SpaceSwitcher />

      {/* Spacer */}
      <div className="flex-1" />

      {/* Right controls */}
      <div className="flex items-center gap-1.5">
        <NavLink
          to="/proposals"
          className={({ isActive }) =>
            cn(
              'flex items-center gap-1.5 h-8 px-2.5 rounded-md border text-[12px] font-medium transition-colors',
              isActive
                ? 'border-primary/40 text-accent-foreground bg-primary/10'
                : 'border-border text-muted-foreground hover:text-foreground hover:bg-accent',
            )
          }
        >
          Proposals
        </NavLink>

        <ThemeToggle />

        <ApiKeyPanel />

        <UserMenu />

        <NavLink
          to="/settings"
          className={({ isActive }) =>
            cn(
              'flex items-center justify-center w-8 h-8 rounded-md border border-border transition-colors',
              isActive
                ? 'text-accent-foreground bg-primary/10 border-primary/40'
                : 'text-muted-foreground hover:text-foreground hover:bg-accent',
            )
          }
          title="Settings"
        >
          <Settings className="size-3.5" />
        </NavLink>
      </div>
    </header>
  )
}

/* ── Shell ─────────────────────────────────────────────────────────────────── */
export default function Shell() {
  const { theme } = useTheme()
  return (
    <div className="flex flex-col h-screen overflow-hidden bg-background text-foreground">
      <TopBar />

      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>

      <Toaster
        theme={theme}
        position="bottom-right"
        toastOptions={{
          style: {
            background: 'var(--card)',
            border: '1px solid var(--border)',
            color: 'var(--foreground)',
          },
        }}
      />
    </div>
  )
}
