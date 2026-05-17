import { useNavigate } from 'react-router-dom'
import { ArrowRight, Info, UserRound } from 'lucide-react'
import { useSpace } from '../contexts/SpaceContext'
import { Button } from './ui/button'
import { Badge } from './ui/badge'

export function PerspectiveGuardBanner({ isSpaceScopedPage }: { isSpaceScopedPage: boolean }) {
  const navigate = useNavigate()
  const { perspective, setSpace, activeOperationalSpaceId, activeOperationalSpaceName } = useSpace()

  if (perspective !== 'personal' || !isSpaceScopedPage) return null

  const hasOperationalSpace = Boolean(activeOperationalSpaceId)
  const operationalName = activeOperationalSpaceName ?? activeOperationalSpaceId ?? 'No operational space selected'

  function switchToOperationalSpace() {
    if (!activeOperationalSpaceId) return
    setSpace(activeOperationalSpaceId)
  }

  return (
    <div className="border-b border-warning/30 bg-warning/10 px-4 py-3">
      <div className="mx-auto flex max-w-[1440px] flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 gap-3">
          <Info className="mt-0.5 size-4 shrink-0 text-warning" />
          <div className="min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-sm font-medium text-foreground">
                You are in Personal perspective, but this page operates in a specific space.
              </p>
              <Badge variant={hasOperationalSpace ? 'warning' : 'destructive'}>
                Current operational space: {operationalName}
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground">
              Personal shows your cross-space ledger. This page still reads or writes space-scoped data.
            </p>
          </div>
        </div>

        <div className="flex shrink-0 flex-wrap gap-2">
          <Button
            type="button"
            size="sm"
            variant="secondary"
            disabled={!hasOperationalSpace}
            onClick={switchToOperationalSpace}
          >
            Switch to {operationalName}
            <ArrowRight className="ml-1.5 size-3.5" />
          </Button>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => navigate('/personal')}
          >
            <UserRound className="mr-1.5 size-3.5" />
            Go to Personal View
          </Button>
        </div>
      </div>
    </div>
  )
}
