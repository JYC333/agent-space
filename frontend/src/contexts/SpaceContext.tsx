import { createContext, useContext, useState, useEffect, useCallback, useMemo, type ReactNode } from 'react'
import { setSpaceContext } from '../api/client'
import { authApi } from '../api/client'
import { useAuth } from './AuthContext'
import type { SpaceWithMembership } from '../types/api'

export type Perspective = 'personal' | 'space'

interface SpaceContextValue {
  perspective: Perspective
  spaceId: string | null
  userId: string
  spaces: SpaceWithMembership[]
  personalSpaceId: string | null
  activeWriteTargetSpaceId: string | null
  activeOperationalSpaceId: string | null
  activeOperationalSpaceName: string | null
  setPerspective: (perspective: Perspective, optionalSpaceId?: string) => void
  setSpace: (spaceId: string) => void
  setWriteTarget: (spaceId: string | null) => void
  reloadSpaces: () => Promise<void>
}

const SpaceContext = createContext<SpaceContextValue | null>(null)

const DEFAULT_USER_ID  = 'default_user'
const STORAGE_KEY = 'agent-space:space-context'

function readStored(): {
  perspective: Perspective
  spaceId: string | null
  userId: string
  activeWriteTargetSpaceId: string | null
} {
  try {
    const s = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '{}')
    const perspective: Perspective = s.perspective === 'space' ? 'space' : 'personal'
    return {
      perspective,
      spaceId: typeof s.spaceId === 'string' ? s.spaceId : null,
      userId: typeof s.userId === 'string' ? s.userId : DEFAULT_USER_ID,
      activeWriteTargetSpaceId: typeof s.activeWriteTargetSpaceId === 'string' ? s.activeWriteTargetSpaceId : null,
    }
  } catch {
    return { perspective: 'personal', spaceId: null, userId: DEFAULT_USER_ID, activeWriteTargetSpaceId: null }
  }
}

export function SpaceProvider({ children }: { children: ReactNode }) {
  const { currentUser } = useAuth()
  const stored = readStored()

  const [perspective, setPerspectiveState] = useState<Perspective>(stored.perspective)
  const [spaceId, setSpaceIdState] = useState<string | null>(stored.perspective === 'space' ? stored.spaceId : null)
  const [userId,  setUserIdState]  = useState(stored.userId)
  const [spaces,  setSpaces]       = useState<SpaceWithMembership[]>([])
  const [activeWriteTargetSpaceId, setWriteTargetState] = useState<string | null>(stored.activeWriteTargetSpaceId)
  const [ready,   setReady]         = useState(false)

  const personalSpaceId = useMemo(
    () => spaces.find(s => s.type === 'personal')?.id ?? null,
    [spaces],
  )
  const activeOperationalSpaceId = useMemo(
    () => perspective === 'space' ? spaceId : (activeWriteTargetSpaceId ?? personalSpaceId),
    [perspective, spaceId, activeWriteTargetSpaceId, personalSpaceId],
  )
  const activeOperationalSpaceName = useMemo(
    () => spaces.find(s => s.id === activeOperationalSpaceId)?.name ?? null,
    [spaces, activeOperationalSpaceId],
  )

  useEffect(() => {
    if (currentUser) {
      setUserIdState(currentUser.id)
    }
    setReady(true)
  }, [currentUser?.id])

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
    if (!currentUser || spaces.length === 0) return
    const hasStoredSpace = stored.spaceId && spaces.some(s => s.id === stored.spaceId)
    const hasCurrentSpace = spaceId && spaces.some(s => s.id === spaceId)
    const hasWriteTarget = activeWriteTargetSpaceId && spaces.some(s => s.id === activeWriteTargetSpaceId)

    if (perspective === 'space' && !hasCurrentSpace) {
      const fallback = (hasStoredSpace ? stored.spaceId : currentUser.default_space_id) ?? spaces.find(s => s.type !== 'personal')?.id ?? null
      if (fallback && spaces.some(s => s.id === fallback)) setSpaceIdState(fallback)
      else setPerspectiveState('personal')
    }

    if (!hasWriteTarget) {
      setWriteTargetState(perspective === 'personal' ? personalSpaceId : (spaceId ?? null))
    }
  }, [
    currentUser,
    spaces,
    perspective,
    spaceId,
    activeWriteTargetSpaceId,
    personalSpaceId,
    stored.spaceId,
  ])

  useEffect(() => {
    if (perspective === 'personal') {
      setSpaceIdState(null)
      setWriteTargetState(prev => prev ?? personalSpaceId)
    } else {
      setWriteTargetState(prev => prev ?? spaceId)
    }
  }, [perspective, personalSpaceId, spaceId])

  useEffect(() => {
    if (!ready) return
    if (activeOperationalSpaceId) setSpaceContext(activeOperationalSpaceId, userId)
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      perspective,
      spaceId: perspective === 'space' ? spaceId : null,
      userId,
      activeWriteTargetSpaceId,
    }))
  }, [perspective, spaceId, activeWriteTargetSpaceId, activeOperationalSpaceId, userId, ready])

  function setPerspective(nextPerspective: Perspective, optionalSpaceId?: string) {
    setPerspectiveState(nextPerspective)
    if (nextPerspective === 'personal') {
      setSpaceIdState(null)
      setWriteTargetState(personalSpaceId)
      if (personalSpaceId) setSpaceContext(personalSpaceId, userId)
      return
    }
    if (optionalSpaceId) setSpace(optionalSpaceId)
  }

  function setSpace(newSpaceId: string) {
    setPerspectiveState('space')
    setSpaceContext(newSpaceId, userId)
    setSpaceIdState(newSpaceId)
    setWriteTargetState(newSpaceId)
  }

  function setWriteTarget(newSpaceId: string | null) {
    const valid = newSpaceId && spaces.some(s => s.id === newSpaceId) ? newSpaceId : null
    setWriteTargetState(valid)
    if (valid && perspective === 'personal') setSpaceContext(valid, userId)
  }

  if (!ready) return null

  return (
    <SpaceContext.Provider value={{
      perspective,
      spaceId,
      userId,
      spaces,
      personalSpaceId,
      activeWriteTargetSpaceId,
      activeOperationalSpaceId,
      activeOperationalSpaceName,
      setPerspective,
      setSpace,
      setWriteTarget,
      reloadSpaces,
    }}>
      {children}
    </SpaceContext.Provider>
  )
}

export function useSpace(): SpaceContextValue {
  const ctx = useContext(SpaceContext)
  if (!ctx) throw new Error('useSpace must be used inside SpaceProvider')
  return ctx
}
