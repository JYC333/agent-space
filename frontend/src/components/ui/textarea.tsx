import { cn } from '../../lib/utils'

export function Textarea({ className, ...props }: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={cn(
        'flex min-h-[80px] w-full rounded-md border border-border bg-input px-3 py-2 text-sm text-foreground',
        'placeholder:text-muted-foreground',
        'focus:outline-none focus:ring-1 focus:ring-ring focus:border-ring',
        'disabled:opacity-40 disabled:cursor-not-allowed',
        'resize-y transition-colors',
        className
      )}
      {...props}
    />
  )
}
