import type { CSSProperties, ElementType, ReactNode } from 'react'

export interface DairyEntry {
  id: string
  user_id: string
  entry_date: string
  content: string
  created_at: string
  updated_at: string
}

export interface DairyReflection {
  id: string
  entry_id: string
  reflection_date: string
  content: string
  ai_model: string | null
  created_at: string
}

export interface DairyApi {
  today(): Promise<{ date: string; entry: DairyEntry | null }>
  listEntries(params?: { limit?: number; before?: string }): Promise<{ entries: DairyEntry[] }>
  saveEntry(date: string, content: string): Promise<{ entry: DairyEntry }>
  deleteEntry(date: string): Promise<{ deleted: boolean }>
  onThisDay(date: string): Promise<{ date: string; entries: DairyEntry[] }>
  reflections(date: string): Promise<{ entry_date: string; reflections: DairyReflection[] }>
}

export interface DairyPluginState {
  loading: boolean
  enabled: boolean
}

export interface DairyHostLinkProps {
  to: string
  style?: CSSProperties
  children?: ReactNode
}

export interface DairyWebHost {
  api: DairyApi
  Link: ElementType<DairyHostLinkProps>
  usePluginState(pluginId: string): DairyPluginState
}
