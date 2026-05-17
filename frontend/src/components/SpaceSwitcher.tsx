import { useState, useRef, useEffect } from 'react'
import { Plus, Check, ChevronDown, Users, Home, Heart, UserRound } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useSpace } from '../contexts/SpaceContext'
import { useAuth } from '../contexts/AuthContext'
import { cn } from '../lib/utils'
import type { SpaceType } from '../types/api'

const TYPE_ICON: Record<SpaceType, typeof Home> = {
  personal: Home,
  household: Heart,
  team:     Users,
}

function SpaceIcon({ type, size = 12 }: { type: SpaceType; size?: number }) {
  const Icon = TYPE_ICON[type] ?? Users
  return <Icon size={size} />
}

export function SpaceSwitcher() {
  const { perspective, spaceId, spaces, setSpace, setPerspective } = useSpace()
  const { currentUser } = useAuth()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  const active = perspective === 'space' ? spaces.find(s => s.id === spaceId) ?? null : null

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [])

  if (!currentUser) {
    // Dev mode — show the static space badge as before
    return (
      <div className="flex items-center gap-1.5 h-8 px-2.5 border border-border rounded-md shrink-0">
        <span className="text-[9px] font-bold tracking-[.1em] uppercase text-muted-foreground">space</span>
        <span className="text-[13px] text-foreground font-medium">{spaceId}</span>
      </div>
    )
  }

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(o => !o)}
        disabled={spaces.length === 0}
        className="flex items-center gap-1.5 h-8 px-2.5 border border-border rounded-md hover:bg-accent transition-colors shrink-0 disabled:opacity-50"
      >
        {active && (
          <SpaceIcon type={active.type} size={11} />
        )}
        <span className="text-[13px] text-foreground font-medium max-w-[120px] truncate">
          {perspective === 'personal' ? 'Personal' : active?.name ?? (spaces.length === 0 ? '…' : spaceId)}
        </span>
        <ChevronDown size={11} className="text-muted-foreground shrink-0" />
      </button>

      {open && (
        <div className="absolute top-[calc(100%+6px)] left-0 min-w-[200px] bg-card border border-border rounded-lg shadow-lg z-50 py-1 overflow-hidden">
          {spaces.length > 0 && (
            <>
              <button
                onClick={() => { setPerspective('personal'); setOpen(false); navigate('/personal') }}
                className={cn(
                  'w-full flex items-start gap-2.5 px-3 py-2 text-left hover:bg-accent transition-colors',
                  perspective === 'personal' ? 'text-foreground' : 'text-muted-foreground hover:text-foreground',
                )}
              >
                <UserRound size={12} className="mt-0.5 shrink-0" />
                <span className="flex-1 min-w-0">
                  <span className="block text-[13px] font-medium">Personal</span>
                  <span className="block text-[10px] text-muted-foreground">My aggregated view across spaces</span>
                </span>
                {perspective === 'personal' && <Check size={12} className="text-accent-foreground shrink-0 mt-0.5" />}
              </button>
              <div className="border-t border-border my-1" />
              <div className="px-3 py-1.5">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Spaces · Shared collaboration boundary</span>
              </div>
              {spaces.map(s => (
                <button
                  key={s.id}
                  onClick={() => { setSpace(s.id); setOpen(false); navigate('/') }}
                  className={cn(
                    'w-full flex items-start gap-2.5 px-3 py-2 text-left hover:bg-accent transition-colors',
                    perspective === 'space' && s.id === spaceId ? 'text-foreground' : 'text-muted-foreground hover:text-foreground',
                  )}
                >
                  <span className="mt-0.5"><SpaceIcon type={s.type} size={12} /></span>
                  <span className="flex-1 min-w-0">
                    <span className="block text-[13px] font-medium truncate">{s.name}</span>
                    <span className="block text-[10px] text-muted-foreground">{s.type === 'personal' ? 'Personal Space' : s.type}</span>
                  </span>
                  <span className="text-[10px] text-muted-foreground">{s.role}</span>
                  {perspective === 'space' && s.id === spaceId && <Check size={12} className="text-accent-foreground shrink-0 mt-0.5" />}
                </button>
              ))}
              <div className="border-t border-border my-1" />
            </>
          )}

          <button
            onClick={() => { setOpen(false); window.location.href = '/settings#spaces' }}
            className="w-full flex items-center gap-2.5 px-3 py-2 text-left text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
          >
            <Plus size={12} />
            <span className="text-[13px]">Create space…</span>
          </button>
        </div>
      )}
    </div>
  )
}
