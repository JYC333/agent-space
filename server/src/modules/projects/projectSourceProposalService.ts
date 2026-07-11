import type { ServerConfig } from "../../config";
import type { Queryable, SpaceUserIdentity } from "../routeUtils/common";
import { HttpError, objectValue, optionalString, requiredString, withQueryableTransaction } from "../routeUtils/common";
import { insertProposalRow } from "../proposals/reviewPackets";
import { PgProposalApplyService } from "../proposals/applyService";
import { SourceConnectionService } from "../sources/sourceConnectionService";
import { arxivConnectionDraft } from "../sources/sourcePresets/service";
import { SourceBackfillPlanningService } from "../sources/sourceBackfillService";
import { ProjectOperationService } from "./projectOperationService";
import { assertProjectWriter } from "./access";
import { advisoryLock, findIdempotentOperation, fingerprintOf } from "./projectOperationIdempotency";

interface BindProposalActor {
  agentId?: string | null;
  runId?: string | null;
  idempotencyKey?: string | null;
}

/**
 * Agent- and user-facing proposal flows for Project source consumption.
 * These always produce a pending proposal (or reuse the matching one for the
 * same run + idempotency key); durable mutation happens only through
 * `ProjectSourceProposalApplier` after acceptance.
 */
export class ProjectSourceProposalService {
  constructor(
    private readonly db: Queryable,
    private readonly config?: ServerConfig,
  ) {}

  async proposeBind(identity: SpaceUserIdentity, projectId: string, body: Record<string, unknown>, actor: BindProposalActor = {}) {
    requiredString(body.source_connection_id, "source_connection_id");
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);

    const reused = await this.reuseBindProposal(identity.spaceId, projectId, actor);
    if (reused) return reused;

    const payload = {
      ...body,
      project_id: projectId,
      proposal_type: "project_source_bind",
      action_id: "project.source.propose_bind",
      ...(actor.idempotencyKey ? { idempotency_key: actor.idempotencyKey } : {}),
    };
    let proposal;
    try {
      proposal = await insertProposalRow(this.db, {
        spaceId: identity.spaceId,
        proposalType: "project_source_bind",
        title: "Bind Source to Project",
        payload,
        rationale: "Create reviewed Project consumption configuration.",
        createdByUserId: actor.agentId ? null : identity.userId,
        createdByAgentId: actor.agentId ?? null,
        createdByRunId: actor.runId ?? null,
        actionIdempotencyKey: actor.idempotencyKey ?? null,
        visibility: "space_shared",
        projectId,
        riskLevel: "medium",
        requiredApproverRole: "owner",
      });
    } catch (error) {
      if (actor.runId && actor.idempotencyKey && (error as { code?: string }).code === "23505") {
        const reusedAfterConflict = await this.reuseBindProposal(identity.spaceId, projectId, actor);
        if (reusedAfterConflict) return reusedAfterConflict;
      }
      throw error;
    }

    if (!actor.agentId || !this.config) return { proposal, auto_applied: false };
    const accepted = await PgProposalApplyService.fromConfig(this.config).acceptAgentProposalIfGranted(proposal.id, {
      actionId: "project.source.propose_bind",
      projectId,
    });
    return { proposal: accepted?.proposal ?? proposal, auto_applied: Boolean(accepted) };
  }

  /**
   * Bundles a proposed Source connection draft with a dependent Project
   * binding proposal into one idempotent Project operation, so a single
   * "set up this source for my project" request either fully succeeds or
   * fully replays on retry.
   */
  async proposeSourceSetup(identity: SpaceUserIdentity, projectId: string, body: Record<string, unknown>) {
    if (!this.config) throw new Error("Project source setup requires server config");
    const key = requiredString(body.idempotency_key, "idempotency_key");
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);

    return withQueryableTransaction(this.db, async (db) => {
      const fingerprint = fingerprintOf(body);
      await advisoryLock(db, identity.spaceId, "source_setup", key);
      const existing = await findIdempotentOperation(db, identity.spaceId, projectId, "source_setup", key);
      if (existing) {
        if (existing.fingerprint !== fingerprint) {
          throw new HttpError(409, "idempotency_key is already used with different source setup parameters");
        }
        return loadSourceSetupBundle(db, identity, projectId, existing.id);
      }

      const operations = new ProjectOperationService(db);
      const operation = await operations.create(identity, projectId, {
        kind: "source_setup",
        title: optionalString(body.operation_title) ?? "Set up project source",
        intent_text: optionalString(body.intent_text),
        steps: [{ title: "Review source activation" }, { title: "Review project binding" }],
      });
      await db.query(
        `UPDATE project_operations SET progress_json=$4::jsonb WHERE id=$1 AND space_id=$2 AND project_id=$3`,
        [operation.id, identity.spaceId, projectId, JSON.stringify({ idempotency: { key, fingerprint } })],
      );

      const sourceBody = body.preset_id === "arxiv" ? arxivConnectionDraft(body) : objectValue(body.source);
      const connection = await new SourceConnectionService(db, this.config!).proposeCreate(identity, sourceBody, { projectId });
      const binding = await new ProjectSourceProposalService(db, this.config).proposeBind(identity, projectId, {
        ...objectValue(body.binding),
        source_connection_id: (connection.draft as Record<string, unknown>).id,
        depends_on_proposal_id: connection.proposal.id,
      });
      await operations.link(identity.spaceId, projectId, String(operation.id), "proposal", String(connection.proposal.id), "source_activation");
      await operations.link(identity.spaceId, projectId, String(operation.id), "proposal", String(binding.proposal.id), "source_binding");
      return { operation, connection_draft: connection.draft, source_proposal: connection.proposal, binding_proposal: binding.proposal };
    });
  }

  /**
   * Plans and proposes a bounded history import for an existing binding,
   * grouped under an idempotent Project operation.
   */
  async proposeBackfill(identity: SpaceUserIdentity, projectId: string, bindingId: string, body: Record<string, unknown>) {
    const key = requiredString(body.idempotency_key, "idempotency_key");
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);

    return withQueryableTransaction(this.db, async (db) => {
      await advisoryLock(db, identity.spaceId, "source_backfill", key);
      const binding = await db.query<{ source_connection_id: string }>(
        `SELECT source_connection_id FROM project_source_bindings WHERE id=$1 AND space_id=$2 AND project_id=$3 AND status='active' FOR UPDATE`,
        [bindingId, identity.spaceId, projectId],
      );
      if (!binding.rows[0]) throw new HttpError(404, "Project source binding not found");
      const connectionId = binding.rows[0].source_connection_id;

      const planner = new SourceBackfillPlanningService(db, this.config);
      const request = { strategy: objectValue(body.strategy), quota_policy: objectValue(body.quota_policy) };
      const preview = await planner.preview(identity, connectionId, request);
      const operationTitle = optionalString(body.title) ?? "Import source history";
      const fingerprint = fingerprintOf({
        binding_id: bindingId,
        source_connection_id: connectionId,
        title: operationTitle,
        strategy: preview.strategy,
        quota_policy: preview.quota_policy,
      });

      const reused = await this.reuseBackfillProposal(db, identity, projectId, bindingId, connectionId, key, fingerprint, planner);
      if (reused) return reused;

      const operation = await new ProjectOperationService(db).create(identity, projectId, {
        kind: "source_backfill",
        title: operationTitle,
        progress: { idempotency: { key, fingerprint } },
        steps: [{ title: "Review import plan" }, { title: "Import history" }],
      });
      const plan = await planner.create(identity, connectionId, {
        ...request,
        strategy: preview.strategy,
        quota_policy: preview.quota_policy,
        idempotency_key: key,
        project_source_binding_id: bindingId,
        project_operation_id: operation.id,
      });
      const proposed = await planner.proposeStart(identity, connectionId, requiredString(plan.id, "source_backfill_plan_id"), { projectId });
      await new ProjectOperationService(db).link(identity.spaceId, projectId, operation.id, "proposal", proposed.proposal.id, "backfill_approval");
      return { operation, plan, proposal: proposed.proposal };
    });
  }

  private async reuseBindProposal(spaceId: string, projectId: string, actor: BindProposalActor) {
    if (!actor.runId || !actor.idempotencyKey) return null;
    const existing = await this.db.query<{ id: string; status: string }>(
      `SELECT * FROM proposals WHERE space_id=$1 AND created_by_run_id=$2 AND proposal_type='project_source_bind' AND action_idempotency_key=$3`,
      [spaceId, actor.runId, actor.idempotencyKey],
    );
    if (!existing.rows[0]) return null;
    return { proposal: existing.rows[0], auto_applied: existing.rows[0].status === "accepted" };
  }

  private async reuseBackfillProposal(
    db: Queryable,
    identity: SpaceUserIdentity,
    projectId: string,
    bindingId: string,
    connectionId: string,
    key: string,
    fingerprint: string,
    planner: SourceBackfillPlanningService,
  ) {
    const existing = await db.query<{
      id: string;
      project_source_binding_id: string | null;
      project_operation_id: string | null;
      strategy_json: Record<string, unknown>;
      quota_policy_json: Record<string, unknown>;
      proposal_id: string | null;
    }>(
      `SELECT id, project_source_binding_id, project_operation_id, strategy_json, quota_policy_json, proposal_id
         FROM source_backfill_plans WHERE space_id=$1 AND idempotency_key=$2 FOR UPDATE`,
      [identity.spaceId, key],
    );
    const row = existing.rows[0];
    if (!row) return null;
    if (row.project_source_binding_id !== bindingId || !row.project_operation_id || !row.proposal_id) {
      throw new HttpError(409, "idempotency_key is already used with different backfill parameters or Project scope");
    }
    const priorOperation = await db.query<{ title: string }>(
      `SELECT title FROM project_operations WHERE id=$1 AND space_id=$2 AND project_id=$3`,
      [row.project_operation_id, identity.spaceId, projectId],
    );
    const priorFingerprint = priorOperation.rows[0]
      ? fingerprintOf({ binding_id: bindingId, source_connection_id: connectionId, title: priorOperation.rows[0].title, strategy: row.strategy_json, quota_policy: row.quota_policy_json })
      : null;
    if (!priorOperation.rows[0] || priorFingerprint !== fingerprint) {
      throw new HttpError(409, "idempotency_key is already used with different backfill parameters or Project scope");
    }
    const operation = await new ProjectOperationService(db).get(identity, projectId, row.project_operation_id);
    const plan = await planner.get(identity, connectionId, row.id);
    const proposal = await db.query(`SELECT * FROM proposals WHERE id=$1 AND space_id=$2 AND project_id=$3`, [row.proposal_id, identity.spaceId, projectId]);
    if (!proposal.rows[0]) throw new HttpError(409, "Existing backfill proposal is missing or belongs to another Project");
    await new ProjectOperationService(db).link(identity.spaceId, projectId, row.project_operation_id, "proposal", row.proposal_id, "backfill_approval");
    return { operation, plan, proposal: proposal.rows[0] };
  }
}

async function loadSourceSetupBundle(db: Queryable, identity: SpaceUserIdentity, projectId: string, operationId: string) {
  const links = await db.query<{ role: string; proposal_id: string; proposal_type: string; payload_json: Record<string, unknown> }>(
    `SELECT l.role, p.id AS proposal_id, p.proposal_type, p.payload_json
       FROM project_operation_links l JOIN proposals p ON p.id=l.target_id AND p.space_id=l.space_id
      WHERE l.operation_id=$1 AND l.space_id=$2 AND l.target_type='proposal' AND l.role IN ('source_activation','source_binding')`,
    [operationId, identity.spaceId],
  );
  const source = links.rows.find((row) => row.role === "source_activation");
  const binding = links.rows.find((row) => row.role === "source_binding");
  if (!source || !binding) throw new HttpError(409, "Existing source setup operation is incomplete");

  const proposalRows = await db.query(`SELECT * FROM proposals WHERE space_id=$1 AND id=ANY($2::text[])`, [identity.spaceId, [source.proposal_id, binding.proposal_id]]);
  const proposals = new Map(proposalRows.rows.map((row: Record<string, unknown>) => [row.id, row]));

  const connectionId = source.payload_json.source_connection_id;
  if (typeof connectionId !== "string") throw new HttpError(409, "Existing source setup operation has no source draft");
  const connection = await db.query(`SELECT * FROM source_connections WHERE id=$1 AND space_id=$2`, [connectionId, identity.spaceId]);
  if (!connection.rows[0]) throw new HttpError(409, "Existing source setup draft is missing");

  return {
    operation: await new ProjectOperationService(db).get(identity, projectId, operationId),
    connection_draft: connection.rows[0],
    source_proposal: proposals.get(source.proposal_id),
    binding_proposal: proposals.get(binding.proposal_id),
  };
}
