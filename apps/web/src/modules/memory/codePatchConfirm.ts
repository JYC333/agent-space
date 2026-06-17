import type { Proposal } from '../../types/api'

export function codePatchAcceptOptions(
  proposal: Proposal,
): { confirmIncompletePatch?: boolean } | null {
  if (proposal.proposal_type !== 'code_patch' || proposal.incomplete_patch !== true) return {}
  const skipped = proposal.skipped_count ?? proposal.skipped_changes?.length ?? 0
  const suffix = skipped > 0
    ? ` ${skipped} skipped change${skipped === 1 ? '' : 's'} will not be applied.`
    : ' Some agent changes will not be applied.'
  if (!confirm(`This code patch is incomplete.${suffix} Apply it anyway?`)) return null
  return { confirmIncompletePatch: true }
}
