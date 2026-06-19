import { randomUUID } from "node:crypto";
import type { PoolClient } from "../../db/pool";
import type { ServerConfig } from "../../config";
import { getDbPool } from "../../db/pool";
import {
  enforceProposalApply,
  type EnforceResult,
} from "../policy/service";
import { ProposalRiskLevelError } from "../policy/gateway";
import {
  createDefaultProposalApplierRegistry,
  type ProposalApplierContributor,
  type ProposalApplierRegistry,
} from "./applierRegistry";
import {
  PgProposalRepository,
} from "./repository";
import type {
  ProposalAcceptOut,
  ProposalApprovalOut,
  ProposalOut,
} from "@agent-space/protocol" with { "resolution-mode": "import" };

export class ProposalApplyHttpError extends Error {
  constructor(
    readonly statusCode: number,
    readonly detail: unknown,
  ) {
    super(typeof detail === "string" ? detail : "proposal apply failed");
    this.name = "ProposalApplyHttpError";
  }
}

export interface ProposalAcceptOptions {
  confirmIncompletePatch?: boolean;
}

interface ApplyProposalRow {
  id: string;
  space_id: string;
  proposal_type: string;
  status: string;
  risk_level: string | null;
  preview: boolean;
  payload_json: Record<string, unknown> | null;
  workspace_id: string | null;
  created_by_user_id: string | null;
  created_by_run_id: string | null;
  title: string | null;
}

interface GrantRow {
  id: string;
  granting_user_id: string;
  target_space_id: string;
  target_run_id: string;
  status: string;
  egress_review_expires_at: unknown;
}

interface ApprovalRow {
  id: string;
  proposal_id: string;
  approval_type: string;
  approver_user_id: string;
  grant_id: string | null;
  target_space_id: string | null;
  status: string;
  metadata_json: Record<string, unknown> | null;
  created_at: unknown;
  revoked_at: unknown;
}

export class PgProposalApplyService {
  constructor(
    private readonly config: ServerConfig,
    private readonly registry: ProposalApplierRegistry = createDefaultProposalApplierRegistry(),
  ) {}

  static fromConfig(
    config: ServerConfig,
    contributor?: ProposalApplierContributor,
  ): PgProposalApplyService {
    return new PgProposalApplyService(config, createDefaultProposalApplierRegistry(contributor));
  }

  supportedProposalTypes(): ReadonlySet<string> {
    return this.registry.registeredTypes();
  }

  async accept(
    proposalId: string,
    identity: { spaceId: string; userId: string },
    options: ProposalAcceptOptions = {},
  ): Promise<ProposalAcceptOut | null> {
    const client = await this.connect();
    let rollbackOnFailure: (() => Promise<void>) | null = null;
    try {
      await client.query("BEGIN");
      const proposal = await this.getProposalForUpdate(client, proposalId);
      if (
        !proposal ||
        proposal.status !== "pending" ||
        proposal.preview ||
        proposal.space_id !== identity.spaceId
      ) {
        await client.query("ROLLBACK");
        return null;
      }

      assertIncompleteCodePatchConfirmation(
        proposal.proposal_type,
        proposal.payload_json,
        options.confirmIncompletePatch === true,
      );
      await this.enforceApplyPolicy(client, proposal, identity.userId);
      const result = await this.registry.apply({
        config: this.config,
        db: client,
        proposal: {
          id: proposal.id,
          space_id: proposal.space_id,
          proposal_type: proposal.proposal_type,
          title: proposal.title,
          payload_json: proposal.payload_json,
          workspace_id: proposal.workspace_id,
          created_by_user_id: proposal.created_by_user_id,
          created_by_run_id: proposal.created_by_run_id,
        },
        userId: identity.userId,
      });
      rollbackOnFailure = result.rollback ?? null;
      const publicResult = { result_type: result.result_type, result: result.result };
      const accepted = await new PgProposalRepository(client).getVisible(
        identity.spaceId,
        identity.userId,
        proposalId,
      );
      if (!accepted) throw new Error("accepted proposal is not visible after apply");
      await client.query("COMMIT");
      rollbackOnFailure = null;
      return { proposal: accepted, ...publicResult };
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      if (rollbackOnFailure) {
        await rollbackOnFailure();
      }
      if (error instanceof ProposalRiskLevelError) {
        throw new ProposalApplyHttpError(422, {
          code: "invalid_proposal_risk_level",
          risk_value: error.riskValue,
          message: error.message,
        });
      }
      if (error instanceof ProposalApplyHttpError) throw error;
      throw error;
    } finally {
      client.release();
    }
  }

  async reject(
    proposalId: string,
    identity: { spaceId: string; userId: string },
  ): Promise<ProposalOut | null> {
    const client = await this.connect();
    try {
      await client.query("BEGIN");
      const updated = await client.query(
        `UPDATE proposals
            SET status = 'rejected', reviewed_at = $3
          WHERE id = $1
            AND space_id = $2
            AND status = 'pending'
            AND created_by_user_id = $4`,
        [proposalId, identity.spaceId, new Date().toISOString(), identity.userId],
      );
      if ((updated.rowCount ?? 0) === 0) {
        await client.query("ROLLBACK");
        return null;
      }
      const out = await new PgProposalRepository(client).getVisible(
        identity.spaceId,
        identity.userId,
        proposalId,
      );
      await client.query("COMMIT");
      return out;
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  }

  async approveEgressGrantingUser(
    proposalId: string,
    identity: { spaceId: string; userId: string },
    grantIdInput: string | null,
  ): Promise<ProposalApprovalOut> {
    const client = await this.connect();
    try {
      await client.query("BEGIN");
      const proposal = await this.getProposalForUpdate(client, proposalId);
      if (!proposal || proposal.space_id !== identity.spaceId) {
        throw new ProposalApplyHttpError(404, "Proposal not found");
      }
      const grantId = grantIdInput ?? await this.inferGrantId(client, proposal);
      if (!grantId) throw new ProposalApplyHttpError(422, "grant_id is required");
      const grant = await this.getGrant(client, grantId);
      if (!grant) throw new ProposalApplyHttpError(403, "grant not found");
      this.validateGrantApproval(proposal, grant, identity.userId, grantId);

      const existing = await client.query<ApprovalRow>(
        `SELECT id, proposal_id, approval_type, approver_user_id, grant_id,
                target_space_id, status, metadata_json, created_at, revoked_at
           FROM proposal_approvals
          WHERE proposal_id = $1
            AND approval_type = 'egress_granting_user'
            AND approver_user_id = $2
            AND grant_id = $3
            AND status = 'approved'
            AND revoked_at IS NULL
          ORDER BY created_at DESC
          LIMIT 1`,
        [proposal.id, identity.userId, grantId],
      );
      let approval = existing.rows[0];
      if (!approval) {
        const metadata = {
          approval_type: "egress_granting_user",
          raw_private_memory_included: false,
          personal_summary_persisted: false,
        };
        const inserted = await client.query<ApprovalRow>(
          `INSERT INTO proposal_approvals
             (id, proposal_id, approval_type, approver_user_id, grant_id,
              target_space_id, status, metadata_json, created_at, revoked_at)
           VALUES ($1, $2, 'egress_granting_user', $3, $4, $5, 'approved',
                   $6::jsonb, $7, NULL)
           RETURNING id, proposal_id, approval_type, approver_user_id, grant_id,
                     target_space_id, status, metadata_json, created_at, revoked_at`,
          [
            randomUUID(),
            proposal.id,
            identity.userId,
            grantId,
            grant.target_space_id,
            JSON.stringify(metadata),
            new Date().toISOString(),
          ],
        );
        approval = inserted.rows[0]!;
      }
      await client.query("COMMIT");
      return approvalToOut(approval);
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  }

  private async connect(): Promise<PoolClient> {
    if (!this.config.databaseUrl) {
      throw new Error("Proposal apply requires SERVER_DATABASE_URL");
    }
    return getDbPool(this.config.databaseUrl).connect();
  }

  private async getProposalForUpdate(
    client: PoolClient,
    proposalId: string,
  ): Promise<ApplyProposalRow | null> {
    const result = await client.query<ApplyProposalRow>(
      `SELECT id, space_id, proposal_type, status, risk_level, preview,
              payload_json, workspace_id, created_by_user_id, created_by_run_id,
              title
         FROM proposals
        WHERE id = $1
        FOR UPDATE`,
      [proposalId],
    );
    return result.rows[0] ?? null;
  }

  private async enforceApplyPolicy(
    client: PoolClient,
    proposal: ApplyProposalRow,
    userId: string,
  ): Promise<void> {
    const role = await getMembershipRole(client, userId, proposal.space_id);
    const result = await enforceProposalApply(
      this.config,
      {
        user_id: userId,
        space_id: proposal.space_id,
        proposal_id: proposal.id,
        proposal_type: proposal.proposal_type,
        declared_risk: proposal.risk_level,
        proposal_payload: proposal.payload_json,
        metadata_json: { server_apply: true },
      },
      role,
      this.registry.registeredTypes(),
    );
    if (result.status !== "allow") {
      throw policyResultToHttpError(result);
    }
  }

  private async inferGrantId(
    client: PoolClient,
    proposal: ApplyProposalRow,
  ): Promise<string | null> {
    const payload = proposal.payload_json ?? {};
    const grantId = stringValue(payload.grant_id);
    if (grantId) return grantId;
    const grantIds = payload.personal_memory_grant_ids;
    if (Array.isArray(grantIds) && grantIds.length === 1 && typeof grantIds[0] === "string") {
      return grantIds[0];
    }
    const sourceRunId = stringValue(payload.source_run_id) ?? proposal.created_by_run_id;
    if (!sourceRunId) return null;
    const run = await client.query<{ grant_id: string | null }>(
      `SELECT personal_grant_context_json->>'grant_id' AS grant_id
         FROM runs
        WHERE id = $1`,
      [sourceRunId],
    );
    return run.rows[0]?.grant_id ?? null;
  }

  private async getGrant(client: PoolClient, grantId: string): Promise<GrantRow | null> {
    const result = await client.query<GrantRow>(
      `SELECT id, granting_user_id, target_space_id, target_run_id, status,
              egress_review_expires_at
         FROM personal_memory_grants
        WHERE id = $1`,
      [grantId],
    );
    return result.rows[0] ?? null;
  }

  private validateGrantApproval(
    proposal: ApplyProposalRow,
    grant: GrantRow,
    userId: string,
    grantId: string,
  ): void {
    const payload = proposal.payload_json ?? {};
    if (grant.granting_user_id !== userId) {
      throw new ProposalApplyHttpError(
        403,
        "only granting_user_id can approve grant-derived egress",
      );
    }
    if (grant.status === "revoked" || grant.status === "expired" || grant.status === "failed") {
      throw new ProposalApplyHttpError(403, `grant status ${JSON.stringify(grant.status)} cannot approve egress`);
    }
    const payloadGrantId = stringValue(payload.grant_id);
    if (payloadGrantId && payloadGrantId !== grantId) {
      throw new ProposalApplyHttpError(403, "proposal grant_id does not match approval grant_id");
    }
    const payloadGrantIds = payload.personal_memory_grant_ids;
    if (Array.isArray(payloadGrantIds) && !payloadGrantIds.map(String).includes(grantId)) {
      throw new ProposalApplyHttpError(
        403,
        "proposal personal_memory_grant_ids does not include approval grant_id",
      );
    }
    if (stringValue(payload.target_space_id) && payload.target_space_id !== grant.target_space_id) {
      throw new ProposalApplyHttpError(403, "proposal target_space_id does not match grant target_space_id");
    }
    if (proposal.space_id !== grant.target_space_id) {
      throw new ProposalApplyHttpError(403, "proposal space_id does not match grant target_space_id");
    }
    const sourceRunId = stringValue(payload.source_run_id) ?? proposal.created_by_run_id;
    if (!sourceRunId) {
      throw new ProposalApplyHttpError(403, "grant-derived proposal is missing source_run_id");
    }
    if (sourceRunId !== grant.target_run_id) {
      throw new ProposalApplyHttpError(403, "proposal source_run_id does not match grant target_run_id");
    }
    const deadline = dateFrom(grant.egress_review_expires_at);
    if (deadline && deadline.getTime() <= Date.now()) {
      throw new ProposalApplyHttpError(403, "egress review deadline has passed");
    }
  }
}

export function assertIncompleteCodePatchConfirmation(
  proposalType: string,
  payloadJson: Record<string, unknown> | null,
  confirmed: boolean,
): void {
  if (proposalType !== "code_patch") return;
  const payload = recordValue(payloadJson);
  if (payload.incomplete_patch !== true || confirmed) return;
  throw new ProposalApplyHttpError(422, {
    code: "incomplete_patch_requires_confirmation",
    message: (
      "This code_patch proposal has incomplete_patch=true: some agent file changes were skipped " +
      "and the patch is partial. Pass confirm_incomplete_patch=true to apply it anyway."
    ),
    skipped_changes: skippedChangesForDetail(payload),
  });
}

function skippedChangesForDetail(payload: Record<string, unknown>): unknown[] {
  if (Array.isArray(payload.skipped_changes)) return payload.skipped_changes;
  if (Array.isArray(payload.skipped)) return payload.skipped;
  return [];
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

async function getMembershipRole(
  client: PoolClient,
  userId: string,
  spaceId: string,
): Promise<string | null> {
  const result = await client.query<{ role: string }>(
    `SELECT role
       FROM space_memberships
      WHERE space_id = $1 AND user_id = $2 AND status = 'active'
      LIMIT 1`,
    [spaceId, userId],
  );
  return result.rows[0]?.role ?? null;
}

function policyResultToHttpError(result: EnforceResult): ProposalApplyHttpError {
  if (result.status === "error") {
    return new ProposalApplyHttpError(500, result.message ?? result.error_code ?? "Policy audit failed");
  }
  return new ProposalApplyHttpError(403, result.message ?? result.error_code ?? "Policy denied proposal apply");
}

function approvalToOut(row: ApprovalRow): ProposalApprovalOut {
  return {
    id: row.id,
    proposal_id: row.proposal_id,
    approval_type: row.approval_type,
    approver_user_id: row.approver_user_id,
    grant_id: row.grant_id,
    target_space_id: row.target_space_id,
    status: row.status,
    metadata_json: row.metadata_json,
    created_at: dateValue(row.created_at) ?? new Date(0).toISOString(),
    revoked_at: dateValue(row.revoked_at),
  };
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function dateValue(value: unknown): string | null {
  const date = dateFrom(value);
  return date ? date.toISOString() : null;
}

function dateFrom(value: unknown): Date | null {
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value;
  if (typeof value === "string" && value.trim()) {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
  }
  return null;
}
