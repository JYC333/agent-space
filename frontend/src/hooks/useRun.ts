import { useState, useEffect } from 'react'
import { agentsApi } from '../api/client'
import { errMsg } from '../lib/utils'
import type { AgentRun } from '../types/api'

const TERMINAL = new Set<string>(['completed', 'failed', 'cancelled'])
const POLL_INTERVAL_MS = 2000

interface UseRunResult {
  run: AgentRun | null
  loading: boolean
  error: string | null
}

export function useRun(runId: string | null): UseRunResult {
  const [run,     setRun]     = useState<AgentRun | null>(null)
  const [loading, setLoading] = useState(!!runId)
  const [error,   setError]   = useState<string | null>(null)

  useEffect(() => {
    if (!runId) return
    const id = runId  // narrow to string for closure

    let active = true
    let intervalId: ReturnType<typeof setInterval>

    async function poll() {
      try {
        const data = await agentsApi.getRun(id)
        if (!active) return
        setRun(data)
        setLoading(false)
        if (TERMINAL.has(data.status)) clearInterval(intervalId)
      } catch (e) {
        if (!active) return
        setError(errMsg(e))
        setLoading(false)
        clearInterval(intervalId)
      }
    }

    poll()
    intervalId = setInterval(poll, POLL_INTERVAL_MS)

    return () => { active = false; clearInterval(intervalId) }
  }, [runId])

  return { run, loading, error }
}
