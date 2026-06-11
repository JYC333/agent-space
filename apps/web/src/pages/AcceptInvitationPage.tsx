import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { CheckCircle, XCircle, Loader } from 'lucide-react'
import { spacesApi } from '../api/client'
import { useAuth } from '../contexts/AuthContext'
import { useSpace } from '../contexts/SpaceContext'
import { Button } from '../components/ui/button'
import { errMsg } from '../lib/utils'

type State = 'loading' | 'confirm' | 'accepting' | 'done' | 'error'

export default function AcceptInvitationPage() {
  const { token } = useParams<{ token: string }>()
  const navigate = useNavigate()
  const { currentUser, isLoading: authLoading } = useAuth()
  const { reloadSpaces } = useSpace()
  const [searchParams] = useSearchParams()
  const autoAccept = searchParams.get('auto') === '1'

  const [state, setState] = useState<State>('loading')
  const [result, setResult] = useState<{ space_id: string; space_name: string; role: string } | null>(null)
  const [errorText, setErrorText] = useState('')

  const handleAccept = useCallback(async () => {
    if (!token) return
    setState('accepting')
    try {
      const res = await spacesApi.acceptInvite(token)
      setResult(res)
      await reloadSpaces()
      setState('done')
    } catch (e) {
      setErrorText(errMsg(e))
      setState('error')
    }
  }, [token, reloadSpaces])

  useEffect(() => {
    if (!authLoading && !currentUser) {
      // Preserve the token and request auto-accept after login completes
      const dest = encodeURIComponent(`/invitations/${token}?auto=1`)
      navigate(`/login?redirect=${dest}`, { replace: true })
    } else if (!authLoading && currentUser) {
      if (autoAccept) {
        handleAccept()
      } else {
        setState('confirm')
      }
    }
  }, [authLoading, currentUser, token, navigate, autoAccept, handleAccept])

  function goToSpace() {
    if (result) {
      navigate(`/spaces/${result.space_id}/today`, { replace: true })
    }
  }

  if (state === 'loading') {
    return <PageFrame><Loader className="size-5 animate-spin text-muted-foreground" /></PageFrame>
  }

  if (state === 'confirm') {
    return (
      <PageFrame>
        <div className="flex flex-col items-center gap-5 text-center">
          <div className="w-12 h-12 rounded-full flex items-center justify-center"
            style={{ background: 'color-mix(in oklch, var(--primary) 12%, transparent)' }}>
            <CheckCircle className="size-6 text-accent-foreground" />
          </div>
          <div>
            <h1 className="text-lg font-semibold text-foreground">You've been invited</h1>
            <p className="text-sm text-muted-foreground mt-1">
              Accept this invitation to join a shared space.
            </p>
          </div>
          <div className="flex gap-2 w-full">
            <Button onClick={() => navigate('/')} variant="outline" className="flex-1">Cancel</Button>
            <Button onClick={handleAccept} className="flex-1">Accept invitation</Button>
          </div>
        </div>
      </PageFrame>
    )
  }

  if (state === 'accepting') {
    return (
      <PageFrame>
        <Loader className="size-5 animate-spin text-muted-foreground" />
        <p className="text-sm text-muted-foreground">Accepting invitation…</p>
      </PageFrame>
    )
  }

  if (state === 'done' && result) {
    return (
      <PageFrame>
        <div className="flex flex-col items-center gap-5 text-center">
          <div className="w-12 h-12 rounded-full flex items-center justify-center"
            style={{ background: 'color-mix(in oklch, var(--success) 12%, transparent)' }}>
            <CheckCircle className="size-6" style={{ color: 'var(--success)' }} />
          </div>
          <div>
            <h1 className="text-lg font-semibold text-foreground">Joined!</h1>
            <p className="text-sm text-muted-foreground mt-1">
              You joined <strong>{result.space_name}</strong> as <strong>{result.role}</strong>.
            </p>
          </div>
          <Button onClick={goToSpace} className="w-full">Go to space</Button>
        </div>
      </PageFrame>
    )
  }

  return (
    <PageFrame>
      <div className="flex flex-col items-center gap-5 text-center">
        <XCircle className="size-10" style={{ color: 'var(--destructive)' }} />
        <div>
          <h1 className="text-lg font-semibold text-foreground">Invitation failed</h1>
          <p className="text-sm text-muted-foreground mt-1">{errorText}</p>
        </div>
        <Button onClick={() => navigate('/')} variant="outline">Go home</Button>
      </div>
    </PageFrame>
  )
}

function PageFrame({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <div
        className="flex flex-col items-center gap-6 p-10 rounded-2xl border border-border"
        style={{ background: 'var(--card)', minWidth: 340, maxWidth: 400 }}
      >
        {children}
      </div>
    </div>
  )
}
