import type {
  BrainThinkDomain,
  BrainThinkGapSummary,
  BrainThinkProvenanceItem,
} from "@agent-space/protocol" with { "resolution-mode": "import" };
import type { Queryable } from "../routeUtils/common";
import { insertArtifactRow } from "../artifacts/reviewArtifactWriter";

export const BRAIN_THINK_SESSION_ARTIFACT_TYPE = "brain_think_session";

export interface BrainThinkSessionArtifactContext {
  spaceId: string;
  ownerUserId: string;
  query: string;
  requestedDomains: BrainThinkDomain[];
  /** Per-domain persisted brief artifact ids (only the domains that persisted). */
  briefArtifactRefs: Array<{ domain: BrainThinkDomain; artifact_id: string }>;
  gapSummary: BrainThinkGapSummary;
  provenance: BrainThinkProvenanceItem[];
  synthesized: boolean;
  combinedAnswer?: string | null;
}

/**
 * Persist an owner-private `brain_think_session` artifact that links the per-domain
 * brief artifacts the Think answer was built from. It is a durable, ref-only
 * record (no raw snippets/content beyond the already-private brief refs) so the
 * session can later seed a Claim Candidate Packet. Owner-private because the
 * answer can derive from the viewer's private/restricted readable scope.
 */
export async function persistBrainThinkSessionArtifact(
  db: Queryable,
  input: BrainThinkSessionArtifactContext,
): Promise<string> {
  const ownerUserId = input.ownerUserId.trim();
  if (!ownerUserId) {
    throw new Error("brain_think_session artifacts require owner_user_id");
  }
  const payload = {
    kind: BRAIN_THINK_SESSION_ARTIFACT_TYPE,
    visibility: "private",
    query: input.query,
    requested_domains: input.requestedDomains,
    brief_artifact_refs: input.briefArtifactRefs,
    gap_summary: input.gapSummary,
    provenance: input.provenance,
    synthesized: input.synthesized,
    combined_answer: input.combinedAnswer ?? null,
    space_id: input.spaceId,
    owner_user_id: ownerUserId,
  };
  return insertArtifactRow(db, {
    spaceId: input.spaceId,
    ownerUserId,
    artifactType: BRAIN_THINK_SESSION_ARTIFACT_TYPE,
    title: titleForSession(input.query),
    content: JSON.stringify(payload, null, 2),
    metadata: payload,
    canonicalFormat: "brain_think_session.v1",
    visibility: "private",
  });
}

function titleForSession(query: string): string {
  const trimmed = query.trim().replace(/\s+/g, " ");
  const short = trimmed.length > 120 ? `${trimmed.slice(0, 117)}...` : trimmed;
  return short ? `Ask Brain: ${short}` : "Ask Brain";
}
