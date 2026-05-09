import { cn } from '../../lib/utils'

export function Input({ className, ...props }: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        'flex h-9 w-full rounded-md border border-border bg-input px-3 py-1 text-sm text-foreground',
        'placeholder:text-muted-foreground',
        'focus:outline-none focus:ring-1 focus:ring-ring focus:border-ring',
        'disabled:opacity-40 disabled:cursor-not-allowed',
        'transition-colors',
        className
      )}
      {...props}
    />
  )
}
