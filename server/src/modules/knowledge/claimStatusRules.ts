const CLAIM_CREATE_STATUSES = new Set(["active", "disputed", "rejected"]);

const CLAIM_STATUS_TRANSITIONS = new Map<string, ReadonlySet<string>>([
  ["active", new Set(["active", "disputed", "superseded", "archived"])],
  ["disputed", new Set(["disputed", "active", "superseded", "archived"])],
  ["superseded", new Set(["archived"])],
  ["rejected", new Set(["archived"])],
  ["archived", new Set()],
]);

const DISPUTED_RESOLUTION_STATES = new Set(["contradicted", "needs_source"]);

export const RELATION_CREATE_STATUSES = new Set(["candidate", "active"]);

export function claimCreateStatusError(status: string): string | null {
  if (CLAIM_CREATE_STATUSES.has(status)) return null;
  return `claim_create status must be active, disputed, or rejected: ${JSON.stringify(status)}`;
}

export function claimStatusTransitionError(currentStatus: string, nextStatus: string): string | null {
  const allowed = CLAIM_STATUS_TRANSITIONS.get(currentStatus);
  if (!allowed) return `invalid current claim status: ${JSON.stringify(currentStatus)}`;
  if (allowed.has(nextStatus)) return null;
  if (currentStatus === "archived") return "archived Claims are terminal";
  return `invalid Claim status transition: ${currentStatus} -> ${nextStatus}`;
}

export function claimResolutionStateError(status: string, resolutionState: string): string | null {
  if (status === "disputed" && !DISPUTED_RESOLUTION_STATES.has(resolutionState)) {
    return "disputed Claims require resolution_state contradicted or needs_source";
  }
  if (status === "active" && resolutionState === "contradicted") {
    return "active Claims cannot use resolution_state contradicted";
  }
  return null;
}
