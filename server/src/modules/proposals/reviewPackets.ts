import { randomUUID } from "node:crypto";
import type { ProposalAcceptResultType } from "@agent-space/protocol" with {
  "resolution-mode": "import",
};
import { assertCanReviewBrainOpsPacket } from "../brainOps/reviewPolicy";
import type { Queryable } from "../routeUtils/common";
import type { ProposalApplyContext, ProposalApplyResult } from "./applierRegistry";

/**
 * Shared plumbing for review/brain-layer proposal packets.
 *
 * Every packet writer (memory maintenance, claim candidate, claim contradiction,
 * relation discovery, retrieval maintenance) writes the same 24-column
 * `proposals` row and, on accept, runs the same skeleton: validate the operation,
 * gate review through `assertCanReviewBrainOpsPacket`, fan the packet into child
 * pending proposals, then mark the packet accepted with the generated child ids.
 * This module owns that one INSERT and that one accept-skeleton so the
 * positional-parameter ordering and the `canonical_write_performed` /
 * creator-only review invariants live in a single place. Each module keeps only
 * its own "payload → child drafts" mapping.
 */

export type ReviewScope = "private" | "space_ops";

export function reviewScopeValue(value: ReviewScope | undefined): ReviewScope {
  return value === "space_ops" ? "space_ops" : "private";
}

export function visibilityForReviewScope(value: ReviewScope | undefined): "private" | "space_shared" {
  return value === "space_ops" ? "space_shared" : "private";
}

export interface InsertProposalRowInput {
  id?: string;
  spaceId: string;
  proposalType: string;
  title: string;
  summary?: string | null;
  payload: unknown;
  rationale: string;
  createdByUserId: string | null;
  visibility: string;
  riskLevel?: string;
  urgency?: string;
  preview?: boolean;
  status?: string;
  createdByRunId?: string | null;
  workspaceId?: string | null;
  projectId?: string | null;
  createdAt?: string;
}

export async function insertProposalRow(db: Queryable, input: InsertProposalRowInput): Promise<string> {
  const id = input.id ?? randomUUID();
  const now = input.createdAt ?? new Date().toISOString();
  await db.query(
    `INSERT INTO proposals (
       id, space_id, created_by_run_id, proposal_type, status, risk_level,
       urgency, preview, title, summary, payload_json, review_deadline,
       expires_at, created_at, updated_at, reviewed_at, reviewed_by,
       workspace_id, rationale, created_by_agent_id, created_by_user_id,
       required_approver_role, visibility, project_id
     ) VALUES (
       $1, $2, $3, $4, $5, $6,
       $7, $8, $9, $10, $11::jsonb, NULL,
       NULL, $12, $12, NULL, NULL,
       $13, $14, NULL, $15,
       NULL, $16, $17
     )`,
    [
      id,
      input.spaceId,
      input.createdByRunId ?? null,
      input.proposalType,
      input.status ?? "pending",
      input.riskLevel ?? "medium",
      input.urgency ?? "normal",
      input.preview ?? false,
      input.title,
      input.summary ?? null,
      JSON.stringify(input.payload ?? {}),
      now,
      input.workspaceId ?? null,
      input.rationale,
      input.createdByUserId,
      input.visibility,
      input.projectId ?? null,
    ],
  );
  return id;
}

export interface ChildProposalDraft {
  id?: string;
  proposalType: string;
  title: string;
  summary?: string | null;
  payload: Record<string, unknown>;
  rationale: string;
  visibility?: string;
  workspaceId?: string | null;
  projectId?: string | null;
  riskLevel?: string;
}

/** Insert one child proposal generated from an accepted packet. */
export async function insertChildProposalRow(
  context: ProposalApplyContext,
  draft: ChildProposalDraft,
): Promise<string> {
  return insertProposalRow(context.db, {
    id: draft.id,
    spaceId: context.proposal.space_id,
    proposalType: draft.proposalType,
    title: draft.title,
    summary: draft.summary ?? null,
    payload: draft.payload,
    rationale: draft.rationale,
    createdByUserId: context.proposal.created_by_user_id ?? context.userId,
    visibility: draft.visibility ?? "private",
    riskLevel: draft.riskLevel ?? "medium",
    workspaceId: draft.workspaceId ?? null,
    projectId: draft.projectId ?? null,
  });
}

export interface AcceptReviewPacketBuild {
  children: ChildProposalDraft[];
  /** Optional per-candidate skip records (claim/relation packets track these). */
  skipped?: Record<string, unknown>[];
  /** Extra keys merged into the accepted packet's stored payload. */
  finalPayloadExtra?: Record<string, unknown>;
  /** Extra keys merged into the apply result. */
  resultExtra?: Record<string, unknown>;
}

export interface AcceptReviewPacketOptions {
  expectedOperation: string;
  resultType: ProposalAcceptResultType;
  privateMessage: string;
  invalidPayload: () => Error;
  build: (
    payload: Record<string, unknown>,
    context: ProposalApplyContext,
  ) => Promise<AcceptReviewPacketBuild> | AcceptReviewPacketBuild;
}

/**
 * Run the shared packet-accept skeleton: validate operation, enforce the
 * creator-only / `space_ops` review gate, create the child proposals the caller's
 * `build` produced, and mark the packet accepted. Never writes canonical rows.
 */
export async function acceptReviewPacket(
  context: ProposalApplyContext,
  options: AcceptReviewPacketOptions,
): Promise<ProposalApplyResult> {
  const payload = context.proposal.payload_json ?? {};
  if (payload.operation !== options.expectedOperation) throw options.invalidPayload();
  await assertCanReviewBrainOpsPacket(context.db, context.proposal, context.userId, options.privateMessage);

  const built = await options.build(payload, context);
  const childProposalIds: string[] = [];
  for (const child of built.children) {
    childProposalIds.push(await insertChildProposalRow(context, child));
  }

  const now = new Date().toISOString();
  const skipped = built.skipped;
  const finalPayload = {
    ...payload,
    generated_child_proposal_ids: childProposalIds,
    generated_child_proposal_count: childProposalIds.length,
    accepted_by_user_id: context.userId,
    accepted_at: now,
    ...(skipped
      ? { skipped_child_proposal_count: skipped.length, skipped_child_proposals: skipped }
      : {}),
    ...(built.finalPayloadExtra ?? {}),
  };
  await context.db.query(
    `UPDATE proposals
        SET status = 'accepted', reviewed_at = $1, reviewed_by = $2, payload_json = $3::jsonb
      WHERE id = $4 AND space_id = $5`,
    [now, context.userId, JSON.stringify(finalPayload), context.proposal.id, context.proposal.space_id],
  );

  return {
    result_type: options.resultType,
    result: {
      generated_child_proposal_ids: childProposalIds,
      generated_child_proposal_count: childProposalIds.length,
      ...(skipped ? { skipped_child_proposal_count: skipped.length } : {}),
      ...(built.resultExtra ?? {}),
    },
  };
}
