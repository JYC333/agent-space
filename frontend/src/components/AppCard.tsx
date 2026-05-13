import { Link } from 'react-router-dom'
import {
  Sun, Plus, Inbox, Clock, BookOpen, Layers, Database, Cpu,
  CheckCircle, Activity, Folder, Settings, Zap, Code, MessageSquare,
  ListTodo, Package,
} from 'lucide-react'
import { cn } from '../lib/utils'
import type { Module } from '../modules/registry'
import { Badge } from './ui/badge'

type LucideComponent = React.ComponentType<{ className?: string; size?: number }>

const ICONS: Record<string, LucideComponent> = {
  sun:              Sun,
  plus:             Plus,
  inbox:            Inbox,
  clock:            Clock,
  'book-open':      BookOpen,
  layers:           Layers,
  database:         Database,
  cpu:              Cpu,
  'check-circle':   CheckCircle,
  activity:         Activity,
  folder:           Folder,
  settings:         Settings,
  zap:              Zap,
  code:             Code,
  'message-square': MessageSquare,
  'list-todo':      ListTodo,
  package:          Package,
}

interface AppCardProps {
  module: Module
  /** Optional live count shown in top-right of card */
  count?: number
  /** Optional badge label shown in top-right of card */
  badge?: { label: string; variant?: 'warning' | 'success' | 'muted' }
  className?: string
}

export function AppCard({ module, count, badge, className }: AppCardProps) {
  const Icon = ICONS[module.icon] ?? Settings

  /**
   * Two distinct disabled reasons with different semantics:
   *
   *   planned   = not yet implemented ("soon" badge). Dev concern.
   *   !enabled  = capability is off for this space (runtime, from backend).
   *               Distinct visual — no "soon", just muted + non-interactive.
   *
   * Both block navigation; only planned shows the "soon" badge.
   */
  const isPlanned  = module.planned
  const isDisabled = isPlanned || !module.enabled

  const tileStyle: React.CSSProperties = module.accent && !isDisabled
    ? {
        background: 'color-mix(in oklch, var(--primary) 12%, transparent)',
        border: '1px solid color-mix(in oklch, var(--primary) 35%, transparent)',
        color: 'var(--accent-foreground)',
      }
    : {
        background: 'var(--accent)',
        border: '1px solid var(--border)',
        color: 'var(--muted-foreground)',
      }

  return (
    <Link
      to={isDisabled ? '#' : module.path}
      onClick={isDisabled ? (e) => e.preventDefault() : undefined}
      aria-disabled={isDisabled}
      className={cn(
        'flex flex-col gap-3.5 p-4 rounded-lg border border-border transition-colors',
        isDisabled
          ? 'opacity-50 cursor-default bg-card pointer-events-none'
          : 'bg-card hover:bg-accent hover:border-muted-foreground/25 cursor-pointer',
        className
      )}
      style={{ minHeight: 132 }}
    >
      {/* Top row: icon tile + status indicator */}
      <div className="flex items-start justify-between gap-2 w-full">
        <div
          className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
          style={tileStyle}
        >
          <Icon size={16} />
        </div>

        {/* Live count (from parent — e.g. proposals pending) */}
        {count !== undefined && !isDisabled && (
          <div className="text-right">
            <div
              className="text-[16px] font-semibold leading-none"
              style={{ fontFamily: 'var(--font-mono)', color: 'var(--foreground)' }}
            >
              {count}
            </div>
          </div>
        )}

        {/* Text badge from parent (e.g. "3 pending", "ok") */}
        {badge && !count && !isDisabled && (
          <span
            className="text-[11px] font-semibold px-2 py-0.5 rounded-full"
            style={badge.variant === 'warning'
              ? { background: 'color-mix(in oklch, var(--warning) 15%, transparent)', color: 'var(--warning)' }
              : badge.variant === 'success'
                ? { background: 'color-mix(in oklch, var(--success) 15%, transparent)', color: 'var(--success)' }
                : { background: 'var(--accent)', color: 'var(--muted-foreground)' }
            }
          >
            {badge.label}
          </span>
        )}

        {/* "soon" — only for planned (dev status) */}
        {isPlanned && (
          <Badge variant="muted" className="text-[9px] px-1.5 py-0 leading-4 shrink-0">soon</Badge>
        )}

        {/* "off" — capability disabled at runtime (not planned, just disabled) */}
        {!isPlanned && !module.enabled && (
          <Badge variant="muted" className="text-[9px] px-1.5 py-0 leading-4 shrink-0">off</Badge>
        )}
      </div>

      {/* Name + description */}
      <div className="flex flex-col gap-1">
        <span className="text-[14px] font-medium text-foreground tracking-tight leading-none">
          {module.label}
        </span>
        <span className="text-[12px] text-muted-foreground leading-[1.45]">
          {module.description}
        </span>
      </div>
    </Link>
  )
}
