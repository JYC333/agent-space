import { ChevronLeft, ChevronRight } from 'lucide-react'
import { Button } from './button'
import { cn } from '../../lib/utils'

interface PaginationProps {
  total: number
  limit: number
  offset: number
  onChange: (offset: number) => void
  className?: string
}

export function Pagination({ total, limit, offset, onChange, className }: PaginationProps) {
  const page     = Math.floor(offset / limit) + 1
  const pages    = Math.ceil(total / limit)
  const hasPrev  = offset > 0
  const hasNext  = offset + limit < total

  if (total <= limit) return null

  return (
    <div className={cn('flex items-center justify-between text-xs text-muted-foreground', className)}>
      <span>
        {offset + 1}–{Math.min(offset + limit, total)} of {total}
      </span>
      <div className="flex items-center gap-1">
        <Button
          variant="ghost"
          size="sm"
          className="h-7 w-7 p-0"
          disabled={!hasPrev}
          onClick={() => onChange(offset - limit)}
        >
          <ChevronLeft className="size-3.5" />
        </Button>
        <span className="px-1">{page} / {pages}</span>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 w-7 p-0"
          disabled={!hasNext}
          onClick={() => onChange(offset + limit)}
        >
          <ChevronRight className="size-3.5" />
        </Button>
      </div>
    </div>
  )
}
