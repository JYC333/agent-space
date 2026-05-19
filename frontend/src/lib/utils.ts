import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}

export function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

export function isNotFoundError(e: unknown): boolean {
  if (!(e instanceof Error)) return false
  const m = e.message.toLowerCase()
  return m.includes('404') || m.includes('not found') || m.includes('not accessible')
}
