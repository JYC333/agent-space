import { type VariantProps, cva } from 'class-variance-authority'
import { cn } from '../../lib/utils'

const badgeVariants = cva(
  'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold transition-colors',
  {
    variants: {
      variant: {
        default:     'bg-primary/15 text-accent-foreground',
        secondary:   'bg-secondary text-secondary-foreground',
        success:     'bg-success/15 text-success',
        warning:     'bg-warning/15 text-warning',
        destructive: 'bg-destructive/15 text-destructive',
        muted:       'bg-muted text-muted-foreground',
        outline:     'border border-border text-muted-foreground',
      },
    },
    defaultVariants: { variant: 'default' },
  }
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />
}

const STATUS_VARIANT: Record<string, BadgeProps['variant']> = {
  active:     'success',
  accepted:   'success',
  completed:  'success',
  pending:    'warning',
  running:    'warning',
  rejected:   'destructive',
  failed:     'destructive',
  archived:   'muted',
  superseded: 'muted',
}

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  return (
    <Badge variant={STATUS_VARIANT[status] ?? 'muted'} className={className}>
      {status}
    </Badge>
  )
}
