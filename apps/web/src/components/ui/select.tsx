import { useRef, useState, useEffect } from 'react'
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
}

export function Select({ options, value, onChange, className, size = 'md', dropUp = false }: SelectProps) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const selected = options.find(o => o.value === value)

  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const h = size === 'sm' ? 'h-7' : 'h-9'

  return (
    <div className={cn('relative', className)} ref={ref}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className={cn(
          'flex w-full items-center justify-between gap-1.5 rounded-md border border-border',
          'bg-input px-3 text-sm text-foreground transition-colors',
          'hover:bg-accent focus:outline-none focus:ring-1 focus:ring-ring',
          h,
        )}
      >
        <span className="truncate">{selected?.label ?? value}</span>
        <ChevronDown size={13} className="shrink-0 text-muted-foreground" />
      </button>

      {open && (
        <div className={cn(
          'absolute z-50 min-w-full overflow-hidden rounded-lg border border-border bg-card shadow-md',
          dropUp ? 'bottom-full mb-1' : 'mt-1',
        )}>
          {options.map(opt => (
            <button
              key={opt.value}
              type="button"
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
      )}
    </div>
  )
}
