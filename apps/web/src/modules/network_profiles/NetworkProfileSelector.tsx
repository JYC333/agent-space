import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { networkProfilesApi } from '../../api/client'
import type { NetworkProfileOut } from '../../types/api'

export default function NetworkProfileSelector({
  value,
  onChange,
  disabled = false,
  className = '',
}: {
  value: string | null | undefined
  onChange: (value: string | null) => void
  disabled?: boolean
  className?: string
}) {
  const [profiles, setProfiles] = useState<NetworkProfileOut[]>([])
  const [loading, setLoading] = useState(false)

  async function load() {
    setLoading(true)
    try {
      setProfiles(await networkProfilesApi.list())
    } catch {
      setProfiles([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <select
        value={value ?? ''}
        onChange={e => onChange(e.target.value || null)}
        disabled={disabled || loading}
        className="flex h-9 min-w-0 flex-1 rounded-md border border-border bg-input px-3 text-sm"
      >
        <option value="">Direct</option>
        {profiles.map(profile => (
          <option key={profile.id} value={profile.id} disabled={!profile.enabled}>
            {profile.name}{profile.enabled ? '' : ' (disabled)'}
          </option>
        ))}
      </select>
      <button
        type="button"
        className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-border text-muted-foreground hover:text-foreground disabled:opacity-50"
        onClick={load}
        disabled={disabled || loading}
        title="Refresh network profiles"
      >
        <RefreshCw className={`size-3.5 ${loading ? 'animate-spin' : ''}`} />
      </button>
    </div>
  )
}
