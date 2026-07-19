import { cn } from '../../lib/utils'

export function ReviewAttentionIndicator({
  count,
  compact = false,
  className,
}: {
  count: number
  compact?: boolean
  className?: string
}) {
  if (count <= 0) return null

  return compact ? (
    <span
      aria-label={`${count} review${count === 1 ? '' : 's'} waiting`}
      className={cn('absolute right-0.5 top-0.5 size-2 rounded-full bg-destructive ring-2 ring-card', className)}
      role="status"
    />
  ) : (
    <span
      className={cn('ml-auto inline-flex min-w-4 items-center justify-center rounded-full bg-destructive px-1.5 py-0.5 text-[10px] font-bold leading-none text-destructive-foreground', className)}
      title={`${count} review${count === 1 ? '' : 's'} waiting`}
    >
      {count > 99 ? '99+' : count}
    </span>
  )
}
