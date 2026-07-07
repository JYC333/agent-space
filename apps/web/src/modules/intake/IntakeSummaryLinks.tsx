import { SpaceLink as Link } from '../../core/spaceNav'
import type { IntakeSummaryResult } from './intakePageModel'

export function IntakeSummaryLinks({ result }: { result: IntakeSummaryResult }) {
  return (
    <div className="mt-3 text-xs border-t border-border pt-2 space-y-0.5">
      <p className="text-muted-foreground line-clamp-2">{result.preview}</p>
      {result.artifact_id && (
        <Link to={`/artifacts/${result.artifact_id}`} className="text-accent-foreground hover:underline block">
          View summary artifact →
        </Link>
      )}
      <Link to={`/runs/${result.run_id}`} className="text-muted-foreground hover:underline block">
        View run →
      </Link>
      {result.proposal_ids.length > 0 && (
        <Link to="/proposals" className="text-muted-foreground hover:underline block">
          {result.proposal_ids.length} proposal{result.proposal_ids.length !== 1 ? 's' : ''} pending review →
        </Link>
      )}
    </div>
  )
}
