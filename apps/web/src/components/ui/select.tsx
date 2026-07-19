import { useRef, useState, useEffect, useId, useLayoutEffect, type CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { ChevronDown, Check } from 'lucide-react'
import { cn } from '../../lib/utils'

export interface SelectOption {
  value: string
  label: string
}

interface SelectProps {
  options: SelectOption[]
  value: string
  onChange: (value: string) => void
  className?: string
  size?: 'sm' | 'md'
  dropUp?: boolean
  disabled?: boolean
  ariaLabel?: string
  /** Render inside the current stacking context. Useful for modal dialogs. */
  portal?: boolean
}

export function Select({ options, value, onChange, className, size = 'md', dropUp = false, disabled = false, ariaLabel, portal = true }: SelectProps) {
  const [open, setOpen] = useState(false)
  const [insideDialog, setInsideDialog] = useState(false)
  const triggerRef = useRef<HTMLDivElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const listboxId = useId()
  const [menuStyle, setMenuStyle] = useState<CSSProperties | null>(null)
  const selected = options.find(o => o.value === value)

  useEffect(() => {
    function handler(e: MouseEvent) {
      const target = e.target as Node
      if (triggerRef.current?.contains(target) || menuRef.current?.contains(target)) return
      setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  useLayoutEffect(() => {
    if (!open) {
      setInsideDialog(false)
      return undefined
    }
    setInsideDialog(Boolean(triggerRef.current?.closest('[role="dialog"]')))
    function updatePosition() {
      const trigger = triggerRef.current
      if (!trigger) return
      const rect = trigger.getBoundingClientRect()
      const gap = 4
      const viewportPadding = 8
      const maxWidth = Math.min(Math.max(rect.width, 320), window.innerWidth - viewportPadding * 2)
      const left = Math.min(
        Math.max(rect.left, viewportPadding),
        Math.max(viewportPadding, window.innerWidth - maxWidth - viewportPadding),
      )
      setMenuStyle({
        left,
        top: dropUp ? undefined : rect.bottom + gap,
        bottom: dropUp ? window.innerHeight - rect.top + gap : undefined,
        minWidth: Math.min(rect.width, maxWidth),
        maxWidth,
        maxHeight: dropUp
          ? Math.max(120, rect.top - gap * 2)
          : Math.max(120, window.innerHeight - rect.bottom - gap * 2),
      })
    }
    updatePosition()
    window.addEventListener('resize', updatePosition)
    window.addEventListener('scroll', updatePosition, true)
    return () => {
      window.removeEventListener('resize', updatePosition)
      window.removeEventListener('scroll', updatePosition, true)
    }
  }, [dropUp, open])

  const h = size === 'sm' ? 'h-7' : 'h-9'
  const renderInPlace = !portal || insideDialog
  const menu = (
    <div
      ref={menuRef}
      id={listboxId}
      role="listbox"
      style={renderInPlace ? { maxHeight: 'min(18rem, 40vh)' } : menuStyle ?? undefined}
      className={cn(
        'z-[1000] overflow-auto rounded-lg border border-border bg-card shadow-md',
        renderInPlace
          ? ['absolute left-0 right-0', dropUp ? 'bottom-full mb-1' : 'top-full mt-1']
          : 'fixed',
      )}
    >
      {options.map(opt => (
        <button
          key={opt.value}
          type="button"
          role="option"
          aria-selected={opt.value === value}
          onClick={() => { onChange(opt.value); setOpen(false) }}
          className={cn(
            'flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm transition-colors',
            opt.value === value
              ? 'text-foreground bg-accent'
              : 'text-muted-foreground hover:text-foreground hover:bg-accent',
          )}
        >
          <span className="flex-1 truncate">{opt.label}</span>
          {opt.value === value && <Check size={12} className="shrink-0 text-accent-foreground" />}
        </button>
      ))}
    </div>
  )

  return (
    <div className={cn('relative', className)} ref={triggerRef}>
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen(o => !o)}
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listboxId : undefined}
        className={cn(
          'flex w-full items-center justify-between gap-1.5 rounded-md border border-border',
          'bg-input px-3 text-sm text-foreground transition-colors',
          'hover:bg-accent focus:outline-none focus:ring-1 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-60',
          h,
        )}
      >
        <span className="truncate">{selected?.label ?? value}</span>
        <ChevronDown size={13} className="shrink-0 text-muted-foreground" />
      </button>

      {open && !disabled && (renderInPlace ? menu : menuStyle ? createPortal(menu, document.body) : null)}
    </div>
  )
}
