import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react'
import { setSpaceContext } from '../api/client'
import { authApi } from '../api/client'
import { useAuth } from './AuthContext'
import type { SpaceWithMembership } from '../types/api'

interface SpaceContextValue {
  spaceId: string
  userId: string
  spaces: SpaceWithMembership[]
  setSpace: (spaceId: string, userId?: string) => void
  reloadSpaces: () => Promise<void>
}

const SpaceContext = createContext<SpaceContextValue | null>(null)

const DEFAULT_SPACE_ID = 'personal'
const DEFAULT_USER_ID  = 'default_user'
const STORAGE_KEY = 'agent-space:space-context'

function readStored(): { spaceId: string; userId: string } {
  try {
    const s = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '{}')
    return { spaceId: s.spaceId ?? DEFAULT_SPACE_ID, userId: s.userId ?? DEFAULT_USER_ID }
  } catch {
    return { spaceId: DEFAULT_SPACE_ID, userId: DEFAULT_USER_ID }
  }
}

export function SpaceProvider({ children }: { children: ReactNode }) {
  const { currentUser } = useAuth()
  const stored = readStored()

  const [spaceId, setSpaceIdState] = useState(stored.spaceId)
  const [userId,  setUserIdState]  = useState(stored.userId)
  const [spaces,  setSpaces]       = useState<SpaceWithMembership[]>([])
  const [ready,   setReady]         = useState(false)

  // When a real user logs in, adopt their identity and default space
  useEffect(() => {
    if (currentUser) {
      setUserIdState(currentUser.id)
      const activeSpace = currentUser.default_space_id ?? stored.spaceId
      setSpaceIdState(activeSpace)
    }
    setReady(true)
  }, [currentUser?.id, stored.spaceId]) // eslint-disable-line react-hooks/exhaustive-deps

  const reloadSpaces = useCallback(async () => {
    if (!currentUser) { setSpaces([]); return }
    try {
      const list = await authApi.mySpaces()
      setSpaces(list)
    } catch {
      setSpaces([])
    }
  }, [currentUser?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { reloadSpaces() }, [reloadSpaces])

  useEffect(() => {
    if (!ready) return
    setSpaceContext(spaceId, userId)
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ spaceId, userId }))
  }, [spaceId, userId, ready])

  function setSpace(newSpaceId: string, newUserId?: string) {
    const effectiveUserId = newUserId ?? userId
    // Update the API client synchronously so child effects that fire in the same
    // React commit (before the parent context effect) use the new space ID.
    setSpaceContext(newSpaceId, effectiveUserId)
    setSpaceIdState(newSpaceId)
    if (newUserId) setUserIdState(newUserId)
  }

  if (!ready) return null

  return (
    <SpaceContext.Provider value={{ spaceId, userId, spaces, setSpace, reloadSpaces }}>
      {children}
    </SpaceContext.Provider>
  )
}

export function useSpace(): SpaceContextValue {
  const ctx = useContext(SpaceContext)
  if (!ctx) throw new Error('useSpace must be used inside SpaceProvider')
  return ctx
}
