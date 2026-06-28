import type { BrainOpsReviewMode, BrainOpsScanMode } from "@agent-space/protocol" with { "resolution-mode": "import" };
import type { Queryable } from "../routeUtils/common";
import { readSpaceRetrievalSettings } from "../retrieval/settings";
import {
  isKnownSpaceRole,
  isSpaceOwnerOrAdmin,
  type SpaceRole,
} from "../access/roles";

export type { SpaceRole } from "../access/roles";

export interface BrainOpsPacketReviewProposal {
  space_id: string;
  visibility?: string | null;
  created_by_user_id?: string | null;
  payload_json?: Record<string, unknown> | null;
}

export class BrainOpsPacketReviewError extends Error {
  constructor(message: string, readonly statusCode = 403) {
    super(message);
    this.name = "BrainOpsPacketReviewError";
  }
}

export async function assertCanReviewBrainOpsPacket(
  db: Queryable,
  proposal: BrainOpsPacketReviewProposal,
  userId: string,
  privateMessage: string,
): Promise<void> {
  if (isSpaceOpsPacket(proposal)) {
    const allowed = await canReviewSpaceOpsPackets(db, proposal.space_id, userId);
    if (!allowed) {
      throw new BrainOpsPacketReviewError("space-wide Brain Ops packet review is not enabled for this reviewer");
    }
    return;
  }

  if (proposal.created_by_user_id && proposal.created_by_user_id !== userId) {
    throw new BrainOpsPacketReviewError(privateMessage);
  }
}

export async function canReviewSpaceOpsPackets(
  db: Queryable,
  spaceId: string,
  userId: string,
): Promise<boolean> {
  const settings = await readSpaceRetrievalSettings(db, spaceId);
  if (settings.brainOpsReviewMode === "private_only") return false;
  const role = await readSpaceRole(db, spaceId, userId);
  return roleCanReviewSpaceOps(role, settings.brainOpsReviewMode);
}

export async function canInitiateBrainOpsScan(
  db: Queryable,
  spaceId: string,
  userId: string,
): Promise<boolean> {
  const settings = await readSpaceRetrievalSettings(db, spaceId);
  const role = await readSpaceRole(db, spaceId, userId);
  return roleCanInitiateBrainOpsScan(role, settings.brainOpsScanMode);
}

export async function readSpaceRole(
  db: Queryable,
  spaceId: string,
  userId: string,
): Promise<SpaceRole | null> {
  const result = await db.query<{ role: string }>(
    `SELECT role
       FROM space_memberships
      WHERE space_id = $1
        AND user_id = $2
        AND status = 'active'
      LIMIT 1`,
    [spaceId, userId],
  );
  const role = result.rows[0]?.role;
  return isKnownSpaceRole(role) ? role : null;
}

export function roleCanReviewSpaceOps(
  role: SpaceRole | null,
  mode: BrainOpsReviewMode,
): boolean {
  if (!role || mode === "private_only") return false;
  if (isSpaceOwnerOrAdmin(role)) return mode === "admins" || mode === "members";
  if (mode !== "members") return false;
  return role === "reviewer" || role === "member";
}

export function roleCanInitiateBrainOpsScan(
  role: SpaceRole | null,
  mode: BrainOpsScanMode,
): boolean {
  if (!role) return false;
  if (isSpaceOwnerOrAdmin(role)) return true;
  if (mode !== "members") return false;
  return role === "reviewer" || role === "member";
}

export function isSpaceOpsPacket(proposal: BrainOpsPacketReviewProposal): boolean {
  const payload = proposal.payload_json ?? {};
  return proposal.visibility === "space_shared" && payload.review_scope === "space_ops";
}
